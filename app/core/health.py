# app/core/health.py
"""Dependency Health Monitor — graceful degradation for SARAS.

Periodically checks all external dependencies and reports status.
When a dependency goes down, SARAS can:
  - Route around it (use a fallback)
  - Inform the user proactively
  - Log to the self-improvement tracker
  - Show status on the dashboard

Checked services:
  - Redis (sentinel bridge, caching)
  - Ollama / local LLM (System 1 fast path)
  - Home Assistant (smart home control)
  - SMTP (email sending)
  - Google Calendar API
  - External APIs (weather, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_check: str = ""
    latency_ms: float = 0
    error: str = ""
    consecutive_failures: int = 0
    last_healthy: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "consecutive_failures": self.consecutive_failures,
            "last_healthy": self.last_healthy,
        }


class HealthMonitor:
    """Monitors all external dependencies and provides graceful degradation."""

    def __init__(self) -> None:
        self._services: Dict[str, ServiceHealth] = {}
        self._checks: Dict[str, Callable] = {}
        self._register_default_checks()

    # ── Check Registration ─────────────────────────────────────────────

    def _register_default_checks(self) -> None:
        """Register health check functions for known services."""
        self._register("redis", self._check_redis)
        self._register("ollama", self._check_ollama)
        self._register("home_assistant", self._check_home_assistant)
        self._register("smtp", self._check_smtp)
        self._register("google_calendar", self._check_google_calendar)

    def _register(self, name: str, check_fn: Callable) -> None:
        self._services[name] = ServiceHealth(name=name)
        self._checks[name] = check_fn

    # ── Run All Checks ─────────────────────────────────────────────────

    async def check_all(self) -> Dict[str, ServiceHealth]:
        """Run all health checks concurrently."""
        tasks = [self._run_check(name) for name in self._checks]
        await asyncio.gather(*tasks, return_exceptions=True)
        return self._services

    async def _run_check(self, name: str) -> None:
        """Run a single health check with timing."""
        check_fn = self._checks.get(name)
        if not check_fn:
            return

        service = self._services[name]
        start = time.time()
        now_str = datetime.now(timezone.utc).isoformat()

        try:
            if asyncio.iscoroutinefunction(check_fn):
                await check_fn()
            else:
                await asyncio.get_event_loop().run_in_executor(None, check_fn)

            elapsed = (time.time() - start) * 1000
            service.status = ServiceStatus.HEALTHY if elapsed < 5000 else ServiceStatus.DEGRADED
            service.latency_ms = elapsed
            service.error = ""
            service.consecutive_failures = 0
            service.last_healthy = now_str

        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            service.status = ServiceStatus.DOWN
            service.latency_ms = elapsed
            service.error = str(exc)[:200]
            service.consecutive_failures += 1

        service.last_check = now_str

    # ── Query ──────────────────────────────────────────────────────────

    def get_status(self, name: str) -> ServiceStatus:
        """Get the cached status of a service."""
        service = self._services.get(name)
        return service.status if service else ServiceStatus.UNKNOWN

    def is_available(self, name: str) -> bool:
        """Check if a service is healthy or degraded (usable)."""
        status = self.get_status(name)
        return status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)

    def get_all_statuses(self) -> List[Dict[str, Any]]:
        """Get all service statuses as dicts (for API/dashboard)."""
        return [s.to_dict() for s in self._services.values()]

    def get_summary(self) -> Dict[str, Any]:
        """High-level summary of system health."""
        total = len(self._services)
        healthy = sum(1 for s in self._services.values() if s.status == ServiceStatus.HEALTHY)
        degraded = sum(1 for s in self._services.values() if s.status == ServiceStatus.DEGRADED)
        down = sum(1 for s in self._services.values() if s.status == ServiceStatus.DOWN)

        if down > 0:
            overall = "degraded"
        elif degraded > 0:
            overall = "mostly_healthy"
        elif healthy == total:
            overall = "all_healthy"
        else:
            overall = "unknown"

        return {
            "overall": overall,
            "total": total,
            "healthy": healthy,
            "degraded": degraded,
            "down": down,
            "down_services": [
                s.name for s in self._services.values()
                if s.status == ServiceStatus.DOWN
            ],
        }

    # ── Individual Health Checks ───────────────────────────────────────

    async def _check_redis(self) -> None:
        """Check Redis connectivity."""
        from app.settings.config import Config
        import redis.asyncio as aioredis

        r = aioredis.from_url(Config.REDIS_URL, socket_connect_timeout=3)
        try:
            await r.ping()
        finally:
            await r.close()

    def _check_ollama(self) -> None:
        """Check Ollama local LLM availability."""
        from app.settings.config import Config
        import urllib.request

        url = f"{Config.OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Ollama returned {resp.status}")

    def _check_home_assistant(self) -> None:
        """Check Home Assistant API."""
        from app.settings.config import Config

        if not Config.HOME_ASSISTANT_TOKEN:
            raise ValueError("HOME_ASSISTANT_TOKEN not configured")

        import urllib.request

        url = f"{Config.HOME_ASSISTANT_URL}/api/"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {Config.HOME_ASSISTANT_TOKEN}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise ConnectionError(f"HA returned {resp.status}")

    def _check_smtp(self) -> None:
        """Check SMTP server connectivity."""
        from app.settings.config import Config
        import smtplib

        if not Config.SMTP_HOST:
            raise ValueError("SMTP_HOST not configured")

        smtp = smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=5)
        smtp.ehlo()
        smtp.quit()

    async def _check_google_calendar(self) -> None:
        """Check if Google Calendar credentials exist and are valid."""
        from app.settings.config import Config
        from pathlib import Path

        creds_path = Path(Config.GOOGLE_CALENDAR_CREDENTIALS_PATH)
        token_path = Path(Config.GOOGLE_CALENDAR_TOKEN_PATH)

        if not creds_path.exists():
            raise FileNotFoundError("Google Calendar credentials not found")

        if not token_path.exists():
            raise FileNotFoundError("Google Calendar token not found (auth needed)")


# ── Module singleton ───────────────────────────────────────────────────

_MONITOR: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = HealthMonitor()
    return _MONITOR
