"""Resilient Recovery — FRIDAY-style graceful degradation.

When external services fail, Raven degrades gracefully:
- Falls back to cached data
- Switches to alternative providers
- Reduces feature complexity
- Maintains core functionality
- Reports degradation status

Unlike hard failures, degraded mode keeps Raven operational
at reduced capacity rather than stopping completely.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ServiceHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ServiceStatus:
    """Status of an external service."""
    name: str
    health: ServiceHealth = ServiceHealth.UNKNOWN
    last_check: float = 0.0
    error_count: int = 0
    last_error: str = ""
    fallback_available: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ResilienceManager:
    """FRIDAY-style resilient recovery.

    Monitors service health and provides fallbacks when
    services fail. Core functionality always works, even
    when external services are down.
    """

    def __init__(self) -> None:
        self._services: dict[str, ServiceStatus] = {}
        self._fallbacks: dict[str, Callable] = {}
        self._degraded_features: set[str] = set()

    def register_service(self, name: str, fallback: Callable | None = None) -> None:
        """Register a service with optional fallback."""
        self._services[name] = ServiceStatus(
            name=name,
            fallback_available=fallback is not None,
        )
        if fallback:
            self._fallbacks[name] = fallback

    def report_healthy(self, name: str) -> None:
        """Report a service as healthy."""
        if name in self._services:
            self._services[name].health = ServiceHealth.HEALTHY
            self._services[name].error_count = 0
            self._services[name].last_check = time.time()
            self._degraded_features.discard(name)

    def report_degraded(self, name: str, error: str = "") -> None:
        """Report a service as degraded."""
        if name in self._services:
            self._services[name].health = ServiceHealth.DEGRADED
            self._services[name].error_count += 1
            self._services[name].last_error = error
            self._services[name].last_check = time.time()
            self._degraded_features.add(name)

    def report_down(self, name: str, error: str = "") -> None:
        """Report a service as down."""
        if name in self._services:
            self._services[name].health = ServiceHealth.DOWN
            self._services[name].error_count += 1
            self._services[name].last_error = error
            self._services[name].last_check = time.time()
            self._degraded_features.add(name)

    def is_healthy(self, name: str) -> bool:
        """Check if a service is healthy."""
        status = self._services.get(name)
        return status is not None and status.health == ServiceHealth.HEALTHY

    def is_degraded(self, name: str) -> bool:
        """Check if a service is degraded or down."""
        status = self._services.get(name)
        return status is not None and status.health in (ServiceHealth.DEGRADED, ServiceHealth.DOWN)

    def get_fallback(self, name: str) -> Callable | None:
        """Get the fallback function for a service."""
        return self._fallbacks.get(name)

    async def try_with_fallback(
        self,
        service_name: str,
        primary_fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Try a primary function, fall back if it fails."""
        try:
            result = await primary_fn(*args, **kwargs)
            self.report_healthy(service_name)
            return result
        except Exception as exc:
            self.report_degraded(service_name, str(exc))
            fallback = self.get_fallback(service_name)
            if fallback:
                logger.warning("Service %s degraded, using fallback: %s", service_name, exc)
                try:
                    return await fallback(*args, **kwargs) if callable(fallback) else fallback
                except Exception as fb_exc:
                    self.report_down(service_name, str(fb_exc))
                    raise
            raise

    def get_degraded_features(self) -> list[str]:
        """Get list of features currently in degraded mode."""
        return list(self._degraded_features)

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of all service statuses."""
        return {
            name: {
                "health": status.health.value,
                "error_count": status.error_count,
                "last_error": status.last_error,
                "fallback_available": status.fallback_available,
            }
            for name, status in self._services.items()
        }

    def get_degradation_report(self) -> str:
        """Get a human-readable degradation report."""
        degraded = self.get_degraded_features()
        if not degraded:
            return "All systems operational."

        lines = ["## System Status\n"]
        for name, status in self._services.items():
            icon = {"healthy": "🟢", "degraded": "🟡", "down": "🔴", "unknown": "⚪"}
            lines.append(f"- {icon.get(status.health.value, '⚪')} {name}: {status.health.value}")
            if status.last_error:
                lines.append(f"  Error: {status.last_error[:100]}")

        return "\n".join(lines)


# Singleton
_resilience: ResilienceManager | None = None


def get_resilience_manager() -> ResilienceManager:
    global _resilience
    if _resilience is None:
        _resilience = ResilienceManager()
    return _resilience
