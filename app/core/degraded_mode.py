"""Degraded-mode detector — Phase 3.7.

The cognition ladder prefers the tiny local model.  When that model is
unreachable for more than ``tiny_down_threshold_s`` (default 30 s),
RAVEN enters **degraded mode** and:

1. **Local-only mode** (cloud providers also unhealthy): every request
   gets a canned response from :data:`REBOOT_BANNER` so the user
   knows RAVEN is alive but rebooting.
2. **Cloud-only mode** (local down, cloud healthy): the ladder skips
   the tiny step and routes straight to ``small``.
3. **Fully-down mode** (all providers down): every request returns the
   last cached answer for the same intent hash, if any, else the
   reboot banner.

The detector is purely advisory — it produces a
:class:`DegradationStatus` that callers (the ladder, the orchestrator)
read to decide behaviour.  It never raises.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.core.cost_router.health import ProviderHealth

logger = logging.getLogger(__name__)


REBOOT_BANNER = (
    "I'm rebooting my brain — give me 30 s and try again."
)


@dataclass(slots=True)
class DegradationStatus:
    """Snapshot of which providers are usable right now."""

    local_healthy: bool
    cloud_healthy: bool
    # Set when local has been down for > tiny_down_threshold_s.
    local_down_long: bool
    # A canned user-facing banner to surface in fully-down mode.
    banner: str = ""
    # When local went down (epoch seconds).  None if currently up.
    local_down_since: float | None = None

    @property
    def fully_down(self) -> bool:
        return (not self.local_healthy) and (not self.cloud_healthy)

    @property
    def cloud_only(self) -> bool:
        return (not self.local_healthy) and self.cloud_healthy

    def to_dict(self) -> dict:
        return {
            "local_healthy": self.local_healthy,
            "cloud_healthy": self.cloud_healthy,
            "local_down_long": self.local_down_long,
            "fully_down": self.fully_down,
            "cloud_only": self.cloud_only,
            "banner": self.banner,
            "local_down_since": self.local_down_since,
        }


class DegradationDetector:
    """Track provider health and emit a :class:`DegradationStatus`.

    Parameters
    ----------
    health
        Shared :class:`ProviderHealth` instance (so the ladder and the
        detector see the same probe results).
    local_providers
        Names treated as "local" — typically ``{"ollama"}``.
    cloud_providers
        Names treated as "cloud" — ``{"anthropic", "openai", ...}``.
    tiny_down_threshold_s
        Seconds the local provider must be continuously unhealthy
        before we declare "local down long".
    """

    def __init__(
        self,
        *,
        health: ProviderHealth | None = None,
        local_providers: tuple[str, ...] = ("ollama",),
        cloud_providers: tuple[str, ...] = (
            "anthropic",
            "openai",
            "google",
            "groq",
            "openrouter",
        ),
        tiny_down_threshold_s: float = 30.0,
    ) -> None:
        self._health = health or ProviderHealth()
        self._local = tuple(local_providers)
        self._cloud = tuple(cloud_providers)
        self._threshold = float(tiny_down_threshold_s)
        self._local_down_since: float | None = None

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def _any_healthy(self, names: tuple[str, ...]) -> bool:
        if not names:
            return False
        for p in names:
            if self._health.is_healthy(p):
                return True
        return False

    def status(self) -> DegradationStatus:
        """Return the current degradation status."""
        local_ok = self._any_healthy(self._local)
        cloud_ok = self._any_healthy(self._cloud)

        now = time.time()
        if local_ok:
            self._local_down_since = None
        else:
            if self._local_down_since is None:
                self._local_down_since = now

        down_long = (
            self._local_down_since is not None
            and (now - self._local_down_since) >= self._threshold
        )

        banner = ""
        if not local_ok and not cloud_ok:
            banner = REBOOT_BANNER

        return DegradationStatus(
            local_healthy=local_ok,
            cloud_healthy=cloud_ok,
            local_down_long=down_long,
            banner=banner,
            local_down_since=self._local_down_since,
        )

    def force_local_down(self, since: float | None = None) -> None:
        """Test helper: pretend local has been down since ``since``."""
        self._local_down_since = since if since is not None else time.time()

    def reset(self) -> None:
        self._local_down_since = None


__all__ = [
    "DegradationStatus",
    "DegradationDetector",
    "REBOOT_BANNER",
]
