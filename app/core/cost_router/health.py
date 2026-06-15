"""Provider health tracking.

We don't want to route a request to a provider that is currently
timing out, returning 5xx, or hanging.  This module keeps a sliding
window of health probes for each provider and exposes a simple
``healthy_providers()`` query.

Design notes:
- Probes are explicit (``record_success`` / ``record_failure``) — the
  router calls them after every call.  We could also schedule
  background health checks but that adds complexity and the explicit
  signal is sufficient for v1.
- The window is a small ring buffer of recent outcomes; a provider
  with >50% failure rate over the last 5 probes is considered unhealthy.
- The interface is sync to keep call sites simple.  Concurrency safety
  is not required: health is racy by nature (a probe result may be
  stale by the time we read it) and that's fine.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class HealthSnapshot:
    """Result of a single probe."""

    provider: str
    success: bool
    latency_ms: int
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


class ProviderHealth:
    """Tracks recent health for a set of providers.

    Health is "unhealthy" when the failure rate over the rolling
    ``window`` exceeds ``max_failure_rate``.  A provider with no
    recorded outcomes is assumed healthy (we don't block on cold start).
    """

    def __init__(self, *, window: int = 5, max_failure_rate: float = 0.5) -> None:
        self._window = window
        self._max_failure_rate = max_failure_rate
        self._probes: dict[str, deque[HealthSnapshot]] = {}

    def record(self, snapshot: HealthSnapshot) -> None:
        dq = self._probes.setdefault(snapshot.provider, deque(maxlen=self._window))
        dq.append(snapshot)
        if not snapshot.success:
            logger.debug(
                "provider %s probe failed (%.0fms): %s",
                snapshot.provider,
                snapshot.latency_ms,
                snapshot.error or "unknown",
            )

    def record_success(self, provider: str, *, latency_ms: int) -> None:
        self.record(
            HealthSnapshot(provider=provider, success=True, latency_ms=latency_ms)
        )

    def record_failure(
        self, provider: str, *, latency_ms: int = 0, error: str | None = None
    ) -> None:
        self.record(
            HealthSnapshot(
                provider=provider,
                success=False,
                latency_ms=latency_ms,
                error=error,
            )
        )

    def is_healthy(self, provider: str) -> bool:
        dq = self._probes.get(provider)
        if not dq:
            return True  # unknown — assume healthy
        failures = sum(1 for p in dq if not p.success)
        return (failures / len(dq)) <= self._max_failure_rate

    def healthy_providers(self, providers: Iterable[str]) -> list[str]:
        return [p for p in providers if self.is_healthy(p)]

    def snapshot(self, provider: str) -> list[HealthSnapshot]:
        return list(self._probes.get(provider, ()))

    def reset(self, provider: str | None = None) -> None:
        if provider is None:
            self._probes.clear()
        else:
            self._probes.pop(provider, None)


__all__ = ["ProviderHealth", "HealthSnapshot"]
