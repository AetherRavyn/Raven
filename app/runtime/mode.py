"""System mode — online / degraded / offline.

The system has three operating modes:

  * ``online``    — every subsystem is reachable. Cloud models work,
                     real-time channels deliver, and the cost router
                     can use the full ladder (tiny → small → medium →
                     large).
  * ``degraded``  — cloud is unreachable but local resources (the
                     ``tiny`` model, the local memory store, the
                     on-disk caches) are still up.  The router only
                     uses ``tiny`` and cache hits; outbound actions
                     still go through (we are partially up).
  * ``offline``   — we cannot reach the network at all, or all
                     models are down.  Outbound actions are queued in
                     :mod:`app.runtime.outbox` for later.  Canned
                     answers are returned for common intents.

The mode is auto-detected by a tiny periodic probe.  A mode change
never drops a request — it only changes the *answer*.  That is the
fragility contract from the plan.

Design:

  * No third-party deps.  The probe is a single ``socket.create_connection``
    to a 1.1.1.1-class host with a short timeout.  Cost is ≤ 1 kbps.
  * The detector runs as a single coroutine.  It does not own a thread.
  * State is a tiny dataclass; transitions are recorded to a small
    ring buffer so callers can ask "when did we last go offline?".
  * External callers can register a callback to be notified of mode
    changes.  Used by the cost router, the companion status tile, the
    CLI, and the outbox drainer.

The detector can be overridden by an external writer (the CLI, a
config file, an operator) — overrides expire after a TTL so a stale
override does not pin the system forever.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────

#: Hosts tried in order for the connectivity probe.  These are well-known
#: anycast resolvers / time servers; we never send data to them.
DEFAULT_PROBE_HOSTS: tuple[tuple[str, int], ...] = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
)

#: How long to wait for a TCP handshake before declaring failure.
PROBE_TIMEOUT_S: float = 2.0

#: How often the detector probes.  Plan budget: ≤ 1 kbps.
PROBE_INTERVAL_S: float = 10.0

#: How many consecutive failures before we drop from ``online`` to
#: ``degraded`` and from ``degraded`` to ``offline``.
FAIL_TO_DEGRADED = 2
FAIL_TO_OFFLINE = 5

#: How many consecutive successes before we climb back up.
PASS_TO_DEGRADED = 1
PASS_TO_ONLINE = 3

#: How long an external override (from the CLI) is honoured before
#: the auto-detector resumes control.
OVERRIDE_TTL_S: float = 300.0


# ── Public types ────────────────────────────────────────────────────


class Mode(str, Enum):
    """Operating mode of the system."""

    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass(slots=True)
class ModeTransition:
    """A change in operating mode."""

    at: float
    from_mode: Mode
    to_mode: Mode
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "from": self.from_mode.value,
            "to": self.to_mode.value,
            "reason": self.reason,
        }


@dataclass
class ModeState:
    """Snapshot of the detector's view of the world."""

    mode: Mode = Mode.ONLINE
    last_probe_ok: bool = True
    last_probe_at: float = 0.0
    consecutive_passes: int = 0
    consecutive_fails: int = 0
    last_error: str = ""
    override: Optional[Mode] = None
    override_expires_at: float = 0.0
    history: deque[ModeTransition] = field(default_factory=lambda: deque(maxlen=64))

    def effective_mode(self) -> Mode:
        """The mode the rest of the system should respect.

        An unexpired override wins over the auto-detected mode.
        """
        now = time.time()
        if self.override is not None and now < self.override_expires_at:
            return self.override
        return self.mode

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.effective_mode().value,
            "auto": self.mode.value,
            "override": self.override.value if self.override else None,
            "override_expires_at": self.override_expires_at,
            "last_probe_ok": self.last_probe_ok,
            "last_probe_at": self.last_probe_at,
            "consecutive_passes": self.consecutive_passes,
            "consecutive_fails": self.consecutive_fails,
            "last_error": self.last_error,
            "history": [h.to_dict() for h in self.history],
        }


# ── Probe ───────────────────────────────────────────────────────────


def probe_connectivity(
    hosts: tuple[tuple[str, int], ...] = DEFAULT_PROBE_HOSTS,
    timeout_s: float = PROBE_TIMEOUT_S,
) -> tuple[bool, str]:
    """Synchronous one-shot probe.  Returns (ok, error_message).

    Tries each host in order; first success wins.  On failure the
    error message is the last host's error (informative, not fatal).
    """
    last_err = "no hosts"
    for host, port in hosts:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True, ""
        except OSError as exc:
            last_err = f"{host}:{port} {exc.__class__.__name__}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_err = f"{host}:{port} {exc.__class__.__name__}: {exc}"
            continue
    return False, last_err


# ── Detector ────────────────────────────────────────────────────────


ModeCallback = Callable[[Mode, Mode], Awaitable[None]]


class ModeDetector:
    """Single-coroutine mode detector.

    Use:

        det = ModeDetector()
        det.on_change(my_async_cb)   # optional
        await det.start()            # spawns the probe loop
        ...
        await det.stop()

    The detector is safe to use without ``start()`` — callers can
    invoke :meth:`set_override` to force a mode for testing.
    """

    def __init__(
        self,
        *,
        probe_hosts: tuple[tuple[str, int], ...] = DEFAULT_PROBE_HOSTS,
        probe_interval_s: float = PROBE_INTERVAL_S,
        state_path: str | Path | None = None,
    ) -> None:
        self.state = ModeState()
        self._probe_hosts = probe_hosts
        self._probe_interval = probe_interval_s
        self._callbacks: list[ModeCallback] = []
        self._pending_callbacks: list[asyncio.Task[None]] = []
        self._task: Optional[asyncio.Task[None]] = None
        self._stopped = False
        self._state_path: Optional[Path] = Path(state_path) if state_path else None
        if self._state_path is not None and self._state_path.is_file():
            try:
                self._load_state()
            except Exception as exc:  # noqa: BLE001
                logger.debug("mode state load failed: %s", exc)

    # ── Subscriptions ────────────────────────────────────────────

    def on_change(self, cb: ModeCallback) -> None:
        """Register an async callback fired on every mode change.

        The callback is invoked *after* the state is updated.  It
        receives (old_mode, new_mode).
        """
        self._callbacks.append(cb)

    async def drain_callbacks(self) -> None:
        """Wait for any scheduled on_change callbacks to finish.

        Tests use this to deterministically observe transitions
        without spinning the event loop.  Production does not need
        to call this — the loop drains the tasks naturally.
        """
        if not self._pending_callbacks:
            return
        tasks = self._pending_callbacks
        self._pending_callbacks = []
        # Wait, but don't propagate exceptions — callbacks are best-effort.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.debug("mode callback raised: %s", r)

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run(), name="mode-detector")
        logger.info(
            "ModeDetector started (interval=%.1fs, hosts=%d)",
            self._probe_interval,
            len(self._probe_hosts),
        )

    async def stop(self) -> None:
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        self._save_state()
        logger.info("ModeDetector stopped")

    # ── Public query ─────────────────────────────────────────────

    def current(self) -> Mode:
        return self.state.effective_mode()

    # ── External override ────────────────────────────────────────

    def set_override(
        self, mode: Mode | None, *, ttl_s: float = OVERRIDE_TTL_S
    ) -> None:
        """Set an operator override.

        ``None`` clears the override.  ``ttl_s=0`` clears it as well.
        """
        if mode is None or ttl_s <= 0:
            self.state.override = None
            self.state.override_expires_at = 0.0
            logger.info("Mode override cleared")
        else:
            self.state.override = mode
            self.state.override_expires_at = time.time() + ttl_s
            logger.info(
                "Mode override set: %s (ttl=%.0fs)", mode.value, ttl_s
            )
        self._notify_change()
        self._save_state()

    # ── Internal ─────────────────────────────────────────────────

    async def _run(self) -> None:
        # First tick happens immediately so callers don't have to wait.
        await self._tick_once()
        while not self._stopped:
            try:
                await asyncio.sleep(self._probe_interval)
                await self._tick_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("ModeDetector tick error: %s", exc)

    async def _tick_once(self) -> None:
        # Run the blocking probe in a thread so we never stall the loop.
        ok, err = await asyncio.get_event_loop().run_in_executor(
            None, probe_connectivity, self._probe_hosts, PROBE_TIMEOUT_S
        )
        self._absorb_probe(ok, err)
        self._save_state()

    def _absorb_probe(self, ok: bool, err: str) -> None:
        prev_effective = self.state.effective_mode()
        self.state.last_probe_at = time.time()
        self.state.last_probe_ok = ok
        self.state.last_error = err
        if ok:
            self.state.consecutive_passes += 1
            self.state.consecutive_fails = 0
        else:
            self.state.consecutive_fails += 1
            self.state.consecutive_passes = 0

        # Auto-mode transitions.
        new_auto = self.state.mode
        if self.state.consecutive_fails >= FAIL_TO_OFFLINE:
            new_auto = Mode.OFFLINE
        elif self.state.consecutive_fails >= FAIL_TO_DEGRADED:
            new_auto = Mode.DEGRADED
        elif (
            self.state.consecutive_passes >= PASS_TO_ONLINE
            and self.state.mode != Mode.ONLINE
        ):
            new_auto = Mode.ONLINE
        elif (
            self.state.consecutive_passes >= PASS_TO_DEGRADED
            and self.state.mode == Mode.OFFLINE
        ):
            new_auto = Mode.DEGRADED

        if new_auto != self.state.mode:
            self._record_transition(
                self.state.mode, new_auto,
                f"probe {'ok' if ok else 'fail'} ({err})"
            )
            self.state.mode = new_auto

        # Notify if effective mode actually changed.
        if self.state.effective_mode() != prev_effective:
            self._notify_change()

    def _record_transition(
        self, frm: Mode, to: Mode, reason: str = ""
    ) -> None:
        self.state.history.append(
            ModeTransition(at=time.time(), from_mode=frm, to_mode=to, reason=reason)
        )
        logger.info(
            "Mode change: %s → %s (%s)",
            frm.value,
            to.value,
            reason or "no reason",
        )

    def _notify_change(self) -> None:
        if not self._callbacks:
            return
        # Schedule callbacks on the loop without awaiting them.
        new = self.state.effective_mode()
        old = self.state.history[-1].from_mode if self.state.history else new
        # If we just transitioned, history has it.  Otherwise look
        # for the most recent transition.
        for cb in list(self._callbacks):
            try:
                self._pending_callbacks.append(
                    asyncio.create_task(cb(old, new))
                )
            except RuntimeError:
                # No running loop — drop.  The CLI is fine because it
                # does not depend on callbacks.
                pass

    # ── Built-in observers ───────────────────────────────────────

    def register_outbox_drain(self) -> None:
        """Drain the durable outbox on every offline→online recovery.

        When the system comes back online (or moves to a
        degraded-online state from a fully-offline state) we want
        to clear any messages that were enqueued while the channel
        was unreachable.  This is a one-line callback: register
        it on the detector and the integration is complete.

        Safe to call multiple times — the second call just adds a
        second identical observer.  In practice the wiring layer
        (e.g. ``app/runtime/wiring.py``) calls this exactly once
        at startup.
        """

        async def _drain_on_recovery(old: Mode, new: Mode) -> None:
            if old in (Mode.OFFLINE, Mode.DEGRADED) and new in (
                Mode.ONLINE,
                Mode.DEGRADED,
            ):
                # Lazy import: the outbox module pulls in only stdlib,
                # but we still don't want a hard dependency at
                # import-time of mode.py.
                from app.runtime.outbox import get_outbox

                try:
                    report = await get_outbox().drain_until_drained()
                    logger.info(
                        "post-recovery outbox drain: %s", report
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "outbox drain on recovery failed"
                    )

        self.on_change(_drain_on_recovery)

    # ── Persistence ──────────────────────────────────────────────

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            # history is a deque; serialise to a list of dicts.
            d = self.state.to_dict()
            self._state_path.write_text(json.dumps(d, indent=2))
        except OSError as exc:
            logger.debug("mode state save failed: %s", exc)

    def _load_state(self) -> None:
        data = json.loads(self._state_path.read_text())
        # We restore a few fields only — not the entire detector.
        # Override is honoured but expires naturally.
        if "override" in data and data["override"]:
            self.state.override = Mode(data["override"])
            self.state.override_expires_at = float(
                data.get("override_expires_at", 0.0)
            )
        # History is informational; we load it for the CLI.
        hist = data.get("history") or []
        self.state.history = deque(
            (
                ModeTransition(
                    at=float(h["at"]),
                    from_mode=Mode(h["from"]),
                    to_mode=Mode(h["to"]),
                    reason=str(h.get("reason", "")),
                )
                for h in hist[-32:]
            ),
            maxlen=64,
        )


# ── Module singleton ───────────────────────────────────────────────

_DETECTOR: Optional[ModeDetector] = None


def get_mode_detector() -> ModeDetector:
    """Return the module-level detector, creating it on first use."""
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = ModeDetector()
    return _DETECTOR


__all__ = [
    "DEFAULT_PROBE_HOSTS",
    "FAIL_TO_DEGRADED",
    "FAIL_TO_OFFLINE",
    "Mode",
    "ModeCallback",
    "ModeDetector",
    "ModeState",
    "ModeTransition",
    "OFFLINE",
    "ONLINE",
    "OVERRIDE_TTL_S",
    "PASS_TO_DEGRADED",
    "PASS_TO_ONLINE",
    "PROBE_INTERVAL_S",
    "PROBE_TIMEOUT_S",
    "get_mode_detector",
    "probe_connectivity",
]


# Convenience aliases (Mode.<X> already gives access, but tests
# sometimes import the bare constants).
ONLINE = Mode.ONLINE
OFFLINE = Mode.OFFLINE
