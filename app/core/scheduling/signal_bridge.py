"""Signal-to-ProactiveSignal bridge (Day 24).

Closes the loop with the proactive engine (Phase C1).

* :mod:`app.core.scheduling.signal` — typed reactive events from
  v2 watchers (D22).
* :mod:`app.core.scheduling.signal_delivery` — direct delivery
  to ``botsignal`` (D23).
* :mod:`app.core.scheduling.signal_bridge` — this module;
  converts :class:`Signal` to :class:`ProactiveSignal` and
  routes through the proactive engine's
  four-stage pipeline (DND -> value gate -> silence ->
  dispatch).

Why both?  The direct adapter (D23) is a *dumb* path — it
bypasses the proactive engine.  The bridge is a *smart* path
— it goes through the engine so DND windows, value-gate
thresholds, and per-kind channel preferences apply.  A
production deployment wires the bridge; the direct adapter
stays for tests and for signals that should always reach the
user (e.g. CRITICAL alerts that should bypass DND — the
engine already does this for ``Urgency.CRITICAL``).

The kind/severity mapping is the single source of truth
for translating between the two ``SignalKind`` enums and
the ``Urgency`` / ``value`` scales.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from app.core.models import SignalPayload
from app.core.scheduling.signal import (
    Signal,
    SignalKind,
    SignalRouter,
    SignalSeverity,
)

logger = logging.getLogger(__name__)


# -- mapping tables (single source of truth) --------------------------------

#: Maps a :class:`SignalKind` (scheduling) to a
#: :class:`app.core.proactive_core.types.SignalKind` (proactive).
#: Unmapped kinds fall back to ``ROUTINE`` so the engine still
#: sees a valid category.
SIGNAL_KIND_TO_PROACTIVE: dict[SignalKind, str] = {
    SignalKind.CALENDAR: "calendar_prep",
    SignalKind.INTERNET: "forecast",
    SignalKind.AUTONOMY: "routine",
    SignalKind.ANOMALY: "anomaly",
    SignalKind.FOLLOW_UP: "follow_up",
    SignalKind.SYSTEM: "routine",
    SignalKind.MEMORY: "routine",
    SignalKind.CONTINUITY: "routine",
}

#: Maps a :class:`SignalSeverity` to a proactive ``Urgency``
#: (LOW / NORMAL / HIGH / CRITICAL).  CRITICAL maps to CRITICAL
#: so the engine's ``allow_critical`` DND bypass kicks in.
SIGNAL_SEVERITY_TO_URGENCY: dict[SignalSeverity, str] = {
    SignalSeverity.INFO: "low",
    SignalSeverity.NOTICE: "normal",
    SignalSeverity.WARNING: "high",
    SignalSeverity.CRITICAL: "critical",
}

#: Maps a :class:`SignalSeverity` to a proactive ``value`` in
#: [0.0, 1.0].  Higher severity = higher utility score.
SIGNAL_SEVERITY_TO_VALUE: dict[SignalSeverity, float] = {
    SignalSeverity.INFO: 0.5,
    SignalSeverity.NOTICE: 0.6,
    SignalSeverity.WARNING: 0.8,
    SignalSeverity.CRITICAL: 0.95,
}

#: Default ``confidence`` for converted signals.  Matches the
#: proactive default so consumers see consistent numbers.
DEFAULT_CONFIDENCE: float = 0.7

#: Default ``interruption_cost`` for converted signals.  The
#: engine's value gate multiplies by this; lower means
#: "less intrusive" (voice at 0.1) vs higher (push at 0.4).
DEFAULT_INTERRUPTION_COST: float = 0.3


# -- pure converter ---------------------------------------------------------


def signal_to_proactive(signal: Signal) -> Any:
    """Convert a :class:`Signal` to a :class:`ProactiveSignal`.

    Pure function — no I/O, no scheduler state.  Maps the
    producer-side categories (``SignalKind`` /
    ``SignalSeverity``) onto the engine's contract
    (``Urgency`` / ``value`` / ``kind``) using the
    module-level tables.

    The returned ``ProactiveSignal`` has:
    * ``id`` = signal id (so audit logs correlate)
    * ``user_id`` = signal user id
    * ``kind`` = mapped proactive kind
    * ``title`` = signal title
    * ``body`` = signal body or title (fallback)
    * ``urgency`` = mapped urgency
    * ``value`` = mapped utility score
    * ``confidence`` = :data:`DEFAULT_CONFIDENCE`
    * ``interruption_cost`` = :data:`DEFAULT_INTERRUPTION_COST`
    * ``source`` = signal source (e.g. ``"calendar_watcher"``)
    * ``payload`` = :class:`SignalPayload` with body text
    * ``metadata`` = signal payload dict (entity ids, refs)
    * ``created_at`` = signal created_at
    """
    from app.core.proactive_core.types import ProactiveSignal, SignalKind as ProactiveSignalKind, Urgency

    proactive_kind = SIGNAL_KIND_TO_PROACTIVE.get(signal.kind, "routine")
    urgency_value = SIGNAL_SEVERITY_TO_URGENCY.get(
        signal.severity, "normal"
    )
    value = SIGNAL_SEVERITY_TO_VALUE.get(signal.severity, 0.5)

    return ProactiveSignal(
        id=signal.id,
        user_id=signal.user_id,
        kind=ProactiveSignalKind(proactive_kind),
        title=signal.title,
        body=signal.body or signal.title,
        urgency=Urgency(urgency_value),
        value=value,
        confidence=DEFAULT_CONFIDENCE,
        interruption_cost=DEFAULT_INTERRUPTION_COST,
        source=signal.source,
        payload=SignalPayload(
            text=signal.body or signal.title,
            source_kind=f"signal_{signal.kind.value}",
        ),
        metadata=dict(signal.payload),
        created_at=signal.created_at,
    )


# -- bridge ------------------------------------------------------------------


class ProactiveSignalBridge:
    """Subscribe to a router and route through the proactive engine.

    For each :class:`Signal` that matches the configured
    :class:`SignalKind` set, the bridge:

    1. converts it to a :class:`ProactiveSignal`
       (:func:`signal_to_proactive`)
    2. calls ``delivery_adapter.dispatch(...)`` which runs
       the four-stage pipeline (DND, value gate, silence,
       dispatch)
    3. lets the engine decide whether to deliver

    The bridge does not perform delivery itself — it only
    feeds the engine.  This keeps all policy decisions in
    one place.

    Parameters
    ----------
    router:
        The :class:`SignalRouter` to subscribe to.  Usually
        the process-wide default.
    delivery_adapter:
        A :class:`app.core.proactive_core.delivery.DeliveryAdapter`
        instance.  Any object with an ``async dispatch(signal)``
        method works (duck-typed for tests).
    kinds:
        Which :class:`SignalKind` values to bridge.  Defaults
        to the four most useful reactive kinds; a no-op for
        unmapped kinds.
    user_id_resolver:
        Optional callable that maps a signal to a user_id.
        Defaults to ``signal.user_id``.
    """

    def __init__(
        self,
        router: SignalRouter,
        delivery_adapter: Any,
        *,
        kinds: Sequence[SignalKind] = (
            SignalKind.CALENDAR,
            SignalKind.INTERNET,
            SignalKind.AUTONOMY,
            SignalKind.ANOMALY,
            SignalKind.FOLLOW_UP,
        ),
    ) -> None:
        self.router = router
        self.delivery_adapter = delivery_adapter
        self.kinds: frozenset[SignalKind] = frozenset(kinds)
        self._unsubscribe: Callable[[], None] | None = None
        # Diagnostic counters
        self.dispatched_count = 0
        self.skipped_kind_count = 0
        self.error_count = 0

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._unsubscribe is not None:
            return
        self._unsubscribe = self.router.subscribe(
            self._handle,
            name=f"proactive_signal_bridge_{id(self)}",
            predicate=self._filter,
        )
        logger.debug(
            "ProactiveSignalBridge started: kinds=%s",
            sorted(k.value for k in self.kinds),
        )

    def stop(self) -> None:
        if self._unsubscribe is None:
            return
        self._unsubscribe()
        self._unsubscribe = None
        logger.debug("ProactiveSignalBridge stopped")

    @property
    def is_running(self) -> bool:
        return self._unsubscribe is not None

    # -- filter + handler -------------------------------------------------

    def _filter(self, signal: Signal) -> bool:
        return signal.kind in self.kinds

    async def _handle(self, signal: Signal) -> None:
        try:
            proactive = signal_to_proactive(signal)
        except Exception as exc:  # noqa: BLE001
            self.error_count += 1
            logger.warning(
                "ProactiveSignalBridge: conversion failed for %s: %s",
                signal.id,
                exc,
            )
            return
        try:
            await self.delivery_adapter.dispatch(proactive)
        except Exception as exc:  # noqa: BLE001
            self.error_count += 1
            logger.warning(
                "ProactiveSignalBridge: dispatch failed for %s: %s",
                signal.id,
                exc,
            )
            return
        self.dispatched_count += 1

    # -- diagnostics ------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "dispatched": self.dispatched_count,
            "errors": self.error_count,
            "kinds": len(self.kinds),
        }


# -- module-level singleton --------------------------------------------------

_bridge: ProactiveSignalBridge | None = None


def get_default_proactive_signal_bridge() -> ProactiveSignalBridge | None:
    """Return the process-wide bridge, or ``None`` if not wired."""
    return _bridge


def set_default_proactive_signal_bridge(bridge: ProactiveSignalBridge | None) -> None:
    """Set or clear the process-wide bridge (mainly for tests)."""
    global _bridge
    _bridge = bridge


def reset_default_proactive_signal_bridge() -> None:
    set_default_proactive_signal_bridge(None)


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_INTERRUPTION_COST",
    "ProactiveSignalBridge",
    "SIGNAL_KIND_TO_PROACTIVE",
    "SIGNAL_SEVERITY_TO_URGENCY",
    "SIGNAL_SEVERITY_TO_VALUE",
    "get_default_proactive_signal_bridge",
    "reset_default_proactive_signal_bridge",
    "set_default_proactive_signal_bridge",
    "signal_to_proactive",
]
