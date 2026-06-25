"""Live Status tile for the companion.

The tile is a small JSON document the renderer polls (or receives via
WebSocket push).  It exposes:

  * CPU + RAM percentages (sampled cheaply via ``psutil`` if
    available, otherwise a stub).
  * Queue depth — number of pending events / commands waiting for
    the orchestrator.
  * Last action — most recent tool call (success or failure).
  * Last error — most recent error message.

The collector never raises.  If a metric source is unavailable it
records a sentinel value (``None``) and the renderer displays
"unknown".  The contract is JSON-stable so the Tauri/Capacitor
renderers can map it 1:1.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# A small adapter so the status tile can ask "what mode are we in?"
# without importing app.runtime.mode at module load.  Callers wire
# this up at app start.
ModeProvider = Callable[[], Optional[str]]


@dataclass(slots=True)
class StatusSnapshot:
    """One frame of the Live Status tile."""

    cpu_pct: Optional[float] = None
    ram_pct: Optional[float] = None
    queue_depth: int = 0
    last_action: str = ""
    last_error: str = ""
    uptime_s: int = 0
    timestamp_ms: int = 0
    # Phase 10 — operating mode: "online" | "degraded" | "offline" |
    # None when no mode provider is wired.  The companion renders an
    # explicit "unknown" pill when this is None so the user is never
    # misled about the system's reachability.
    mode: Optional[str] = None
    # True when the mode was set by an operator override rather than
    # auto-detection.  Renderers may show a small "manual" badge.
    mode_overridden: bool = False
    # Counter for queued outbound actions (Phase 10 outbox).  Zero
    # in healthy states; > 0 means the system is buffering for later.
    outbox_pending: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_pct": self.cpu_pct,
            "ram_pct": self.ram_pct,
            "queue_depth": self.queue_depth,
            "last_action": self.last_action,
            "last_error": self.last_error,
            "uptime_s": self.uptime_s,
            "timestamp_ms": self.timestamp_ms,
            "mode": self.mode,
            "mode_overridden": self.mode_overridden,
            "outbox_pending": self.outbox_pending,
        }


def _read_cpu_pct() -> Optional[float]:
    """Best-effort CPU%.  Returns ``None`` if ``psutil`` is missing."""
    try:
        import psutil  # type: ignore[import-not-found]
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


def _read_ram_pct() -> Optional[float]:
    try:
        import psutil  # type: ignore[import-not-found]
        return float(psutil.virtual_memory().percent)
    except Exception:
        return None


class StatusCollector:
    """Build StatusSnapshots on demand.

    The collector is stateless across calls except for:
      * ``_process_started_at`` — used to compute uptime.
      * ``_last_action`` / ``_last_error`` — updated via
        :meth:`record_action` and :meth:`record_error`.
      * ``_queue_depth`` — incremented/decremented via
        :meth:`enqueue` and :meth:`dequeue`.
      * ``_mode_provider`` / ``_outbox_provider`` — optional
        Phase 10 hooks.  When wired (typically by the supervisor at
        app start) the snapshot includes ``mode`` and
        ``outbox_pending``.

    The collector is intentionally lightweight — no background loop.
    Callers (the WebSocket dispatcher, the renderer, the test suite)
    decide when to sample.
    """

    def __init__(
        self,
        *,
        mode_provider: ModeProvider | None = None,
        outbox_provider: Callable[[], int] | None = None,
    ) -> None:
        self._process_started_at: float = time.time()
        self._last_action: str = ""
        self._last_error: str = ""
        self._queue_depth: int = 0
        self._max_queue_depth: int = 0
        self._mode_provider: ModeProvider | None = mode_provider
        self._outbox_provider: Callable[[], int] | None = outbox_provider

    def set_mode_provider(self, provider: ModeProvider | None) -> None:
        """Hot-swap the mode provider (used at app start)."""
        self._mode_provider = provider

    def set_outbox_provider(
        self, provider: Callable[[], int] | None
    ) -> None:
        """Hot-swap the outbox counter (used at app start)."""
        self._outbox_provider = provider

    # ── mutators ──────────────────────────────────────────────────

    def record_action(self, action: str) -> None:
        self._last_action = action

    def record_error(self, error: str) -> None:
        self._last_error = error

    def enqueue(self, n: int = 1) -> None:
        self._queue_depth += max(0, n)
        self._max_queue_depth = max(self._max_queue_depth, self._queue_depth)

    def dequeue(self, n: int = 1) -> None:
        self._queue_depth = max(0, self._queue_depth - max(0, n))

    def reset(self) -> None:
        """Reset transient counters (used in tests)."""
        self._last_action = ""
        self._last_error = ""
        self._queue_depth = 0
        self._max_queue_depth = 0
        self._process_started_at = time.time()

    # ── accessors ─────────────────────────────────────────────────

    @property
    def queue_depth(self) -> int:
        return self._queue_depth

    @property
    def max_queue_depth(self) -> int:
        return self._max_queue_depth

    def sample(self) -> StatusSnapshot:
        mode: Optional[str] = None
        overridden = False
        if self._mode_provider is not None:
            try:
                mode = self._mode_provider()
            except Exception:
                mode = None
        outbox_pending = 0
        if self._outbox_provider is not None:
            try:
                outbox_pending = max(0, int(self._outbox_provider()))
            except Exception:
                outbox_pending = 0
        return StatusSnapshot(
            cpu_pct=_read_cpu_pct(),
            ram_pct=_read_ram_pct(),
            queue_depth=self._queue_depth,
            last_action=self._last_action,
            last_error=self._last_error,
            uptime_s=int(time.time() - self._process_started_at),
            timestamp_ms=int(time.time() * 1000),
            mode=mode,
            mode_overridden=overridden,
            outbox_pending=outbox_pending,
        )


__all__ = ["ModeProvider", "StatusCollector", "StatusSnapshot"]