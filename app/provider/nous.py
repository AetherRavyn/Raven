from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NOUS_API_URL = os.getenv("NOUS_API_URL", "https://portal.nous.ai/api/v1")
NOUS_API_KEY = os.getenv("NOUS_API_KEY", "")
APP_VERSION = os.getenv("RAVEN_VERSION", "1.0.0")
BATCH_LIMIT = 100
BUFFER_MAX = 1000
RETRY_ATTEMPTS = 3


@dataclass
class NousSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    device_id: str = ""
    platform: str = ""
    app_version: str = ""
    started_at: str = ""
    last_heartbeat: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class NousEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    event_type: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: str = ""
    severity: str = "info"


@dataclass
class NousReport:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    report_type: str = ""
    data: dict = field(default_factory=dict)
    created_at: str = ""


@dataclass
class NousFeedback:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    rating: int = 5
    category: str = ""
    message: str = ""
    created_at: str = ""


class NousClient:
    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        auto_flush: bool = True,
        flush_interval: int = 60,
    ) -> None:
        self._api_url = (api_url or NOUS_API_URL).rstrip("/")
        self._api_key = api_key or NOUS_API_KEY
        self._auto_flush = auto_flush
        self._flush_interval = flush_interval
        self._buffer: deque[NousEvent] = deque(maxlen=BUFFER_MAX)
        self._http = httpx.AsyncClient(
            base_url=self._api_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"Raven-Nous/{APP_VERSION}",
            },
            timeout=httpx.Timeout(15.0),
        )
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

    # ── Session lifecycle ──────────────────────────────────────────────

    async def register_session(
        self,
        user_id: str,
        device_id: str,
        platform: str,
        app_version: str,
    ) -> NousSession:
        session = NousSession(
            user_id=user_id,
            device_id=device_id,
            platform=platform,
            app_version=app_version,
        )
        payload = {
            "id": session.id,
            "user_id": user_id,
            "device_id": device_id,
            "platform": platform,
            "app_version": app_version,
        }
        await self._request("POST", "/sessions", json=payload)
        return session

    async def end_session(self, session_id: str) -> bool:
        result = await self._request("DELETE", f"/sessions/{session_id}")
        return result is not None

    # ── Events ─────────────────────────────────────────────────────────

    async def send_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict | None = None,
        severity: str = "info",
    ) -> bool:
        event = NousEvent(
            session_id=session_id,
            event_type=event_type,
            payload=payload or {},
            severity=severity,
        )
        if self._auto_flush:
            self._buffer.append(event)
            return True
        result = await self._request(
            "POST",
            "/events",
            json={
                "id": event.id,
                "session_id": session_id,
                "event_type": event_type,
                "payload": payload or {},
                "severity": severity,
            },
        )
        return result is not None

    # ── Reports ────────────────────────────────────────────────────────

    async def send_crash_report(
        self,
        session_id: str,
        error: str,
        stacktrace: str,
        context: dict | None = None,
    ) -> bool:
        result = await self._request(
            "POST",
            "/reports",
            json={
                "session_id": session_id,
                "report_type": "crash",
                "data": {
                    "error": error,
                    "stacktrace": stacktrace,
                    "context": context or {},
                },
            },
        )
        return result is not None

    async def send_performance_report(self, session_id: str, metrics: dict) -> bool:
        result = await self._request(
            "POST",
            "/reports",
            json={
                "session_id": session_id,
                "report_type": "performance",
                "data": metrics,
            },
        )
        return result is not None

    # ── Feedback ───────────────────────────────────────────────────────

    async def send_feedback(
        self,
        user_id: str,
        rating: int,
        category: str,
        message: str,
    ) -> bool:
        result = await self._request(
            "POST",
            "/feedback",
            json={
                "user_id": user_id,
                "rating": max(1, min(5, rating)),
                "category": category,
                "message": message,
            },
        )
        return result is not None

    # ── Health ─────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        result = await self._request("GET", "/health")
        return result is not None

    # ── Flush loop ─────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._auto_flush:
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        batch: list[NousEvent] = []
        while self._buffer and len(batch) < BATCH_LIMIT:
            batch.append(self._buffer.popleft())
        if batch:
            await self._request(
                "POST",
                "/events/batch",
                json=[
                    {
                        "id": e.id,
                        "session_id": e.session_id,
                        "event_type": e.event_type,
                        "payload": e.payload,
                        "severity": e.severity,
                    }
                    for e in batch
                ],
            )

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("Nous flush loop error")

    # ── HTTP helpers ───────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        last_exc: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                resp = await self._http.request(method, path, **kwargs)
                resp.raise_for_status()
                if resp.content:
                    return resp.json()
                return {}
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Nous HTTP %s %s -> %s (attempt %d/%d)",
                    method,
                    path,
                    exc.response.status_code,
                    attempt + 1,
                    RETRY_ATTEMPTS,
                )
                last_exc = exc
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Nous request failed %s %s (attempt %d/%d): %s",
                    method,
                    path,
                    attempt + 1,
                    RETRY_ATTEMPTS,
                    exc,
                )
                last_exc = exc
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(2**attempt)
        logger.error("Nous request exhausted retries %s %s: %s", method, path, last_exc)
        return None

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()
