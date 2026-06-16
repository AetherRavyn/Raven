"""Tests for :class:`ProactiveSignalBridge` and the Signal->ProactiveSignal converter (Day 24)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from app.core.proactive_core.types import (
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    Urgency,
)
from app.core.scheduling import (
    Signal,
    SignalKind,
    SignalRouter,
    SignalSeverity,
    reset_default_proactive_signal_bridge,
    reset_default_signal_router,
)
from app.core.scheduling.signal_bridge import (
    DEFAULT_CONFIDENCE,
    DEFAULT_INTERRUPTION_COST,
    ProactiveSignalBridge,
    SIGNAL_KIND_TO_PROACTIVE,
    SIGNAL_SEVERITY_TO_URGENCY,
    SIGNAL_SEVERITY_TO_VALUE,
    signal_to_proactive,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class FakeDeliveryAdapter:
    """Records every dispatch; configurable per-call outcome."""

    dispatched: list[ProactiveSignal] = field(default_factory=list)
    raises: Exception | None = None
    verdict: DecisionVerdict = DecisionVerdict.SPEAK

    async def dispatch(self, signal: ProactiveSignal) -> ProactiveDecision:
        if self.raises is not None:
            raise self.raises
        self.dispatched.append(signal)
        return ProactiveDecision(signal=signal, verdict=self.verdict, stage="dispatch")


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    reset_default_signal_router()
    reset_default_proactive_signal_bridge()
    yield
    reset_default_signal_router()
    reset_default_proactive_signal_bridge()


def _signal(
    kind: SignalKind,
    *,
    severity: SignalSeverity = SignalSeverity.INFO,
    user_id: str = "u1",
    title: str = "Test",
    body: str | None = None,
    source: str = "test_source",
    payload: dict | None = None,
) -> Signal:
    return Signal.make(
        kind,
        source,
        user_id,
        title,
        severity=severity,
        body=body,
        payload=payload or {},
    )


# --------------------------------------------------------------------------- #
# Mapping tables (single source of truth)                                     #
# --------------------------------------------------------------------------- #


class TestMappingTables:
    def test_kind_covers_all_scheduler_kinds(self) -> None:
        # Every SignalKind value must have a mapping (even if it's ROUTINE).
        for k in SignalKind:
            assert k in SIGNAL_KIND_TO_PROACTIVE

    def test_urgency_covers_all_severities(self) -> None:
        for s in SignalSeverity:
            assert s in SIGNAL_SEVERITY_TO_URGENCY

    def test_value_covers_all_severities(self) -> None:
        for s in SignalSeverity:
            assert s in SIGNAL_SEVERITY_TO_VALUE

    def test_critical_maps_to_critical(self) -> None:
        assert SIGNAL_SEVERITY_TO_URGENCY[SignalSeverity.CRITICAL] == Urgency.CRITICAL.value

    def test_info_maps_to_low(self) -> None:
        assert SIGNAL_SEVERITY_TO_URGENCY[SignalSeverity.INFO] == Urgency.LOW.value

    def test_calendar_maps_to_calendar_prep(self) -> None:
        assert SIGNAL_KIND_TO_PROACTIVE[SignalKind.CALENDAR] == "calendar_prep"

    def test_anomaly_maps_to_anomaly(self) -> None:
        assert SIGNAL_KIND_TO_PROACTIVE[SignalKind.ANOMALY] == "anomaly"


# --------------------------------------------------------------------------- #
# signal_to_proactive converter                                              #
# --------------------------------------------------------------------------- #


class TestSignalToProactive:
    def test_basic_fields(self) -> None:
        s = _signal(
            SignalKind.CALENDAR,
            severity=SignalSeverity.NOTICE,
            title="Meeting in 15 min",
            body="Standup",
        )
        p = signal_to_proactive(s)
        assert isinstance(p, ProactiveSignal)
        assert p.id == s.id
        assert p.user_id == "u1"
        assert p.title == "Meeting in 15 min"
        assert p.body == "Standup"
        assert p.source == "test_source"
        assert p.metadata == {}

    def test_kind_mapping(self) -> None:
        p = signal_to_proactive(_signal(SignalKind.CALENDAR))
        assert p.kind == "calendar_prep"
        p = signal_to_proactive(_signal(SignalKind.INTERNET))
        assert p.kind == "forecast"
        p = signal_to_proactive(_signal(SignalKind.AUTONOMY))
        assert p.kind == "routine"
        p = signal_to_proactive(_signal(SignalKind.ANOMALY))
        assert p.kind == "anomaly"
        p = signal_to_proactive(_signal(SignalKind.FOLLOW_UP))
        assert p.kind == "follow_up"

    def test_urgency_mapping(self) -> None:
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.INFO)).urgency == Urgency.LOW
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.NOTICE)).urgency == Urgency.NORMAL
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.WARNING)).urgency == Urgency.HIGH
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.CRITICAL)).urgency == Urgency.CRITICAL

    def test_value_mapping(self) -> None:
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.INFO)).value == 0.5
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.WARNING)).value == 0.8
        assert signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.CRITICAL)).value == 0.95

    def test_confidence_and_interruption_cost_defaults(self) -> None:
        p = signal_to_proactive(_signal(SignalKind.CALENDAR))
        assert p.confidence == DEFAULT_CONFIDENCE
        assert p.interruption_cost == DEFAULT_INTERRUPTION_COST

    def test_payload_carries_body(self) -> None:
        p = signal_to_proactive(
            _signal(SignalKind.CALENDAR, body="long body text")
        )
        assert p.payload is not None
        assert p.payload.text == "long body text"
        assert p.payload.source_kind == "signal_calendar"

    def test_body_fallback_to_title(self) -> None:
        p = signal_to_proactive(_signal(SignalKind.CALENDAR, title="title-only"))
        assert p.body == "title-only"

    def test_metadata_carries_signal_payload(self) -> None:
        s = _signal(
            SignalKind.CALENDAR,
            payload={"event_id": "e1", "platform": "telegram", "chat_id": "c1"},
        )
        p = signal_to_proactive(s)
        assert p.metadata["event_id"] == "e1"
        assert p.metadata["platform"] == "telegram"
        assert p.metadata["chat_id"] == "c1"

    def test_metadata_default_empty(self) -> None:
        p = signal_to_proactive(_signal(SignalKind.CALENDAR, payload={}))
        assert p.metadata == {}

    def test_created_at_preserved(self) -> None:
        s = _signal(SignalKind.CALENDAR)
        p = signal_to_proactive(s)
        assert p.created_at == s.created_at

    def test_final_value_calculation(self) -> None:
        p = signal_to_proactive(_signal(SignalKind.CALENDAR, severity=SignalSeverity.WARNING))
        # value=0.8, confidence=0.7 -> final = 0.56
        assert abs(p.final_value() - 0.56) < 1e-9


# --------------------------------------------------------------------------- #
# ProactiveSignalBridge lifecycle                                             #
# --------------------------------------------------------------------------- #


class TestLifecycle:
    def test_start_subscribes(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)
        assert not bridge.is_running
        bridge.start()
        assert bridge.is_running
        assert router.handler_count == 1

    def test_start_idempotent(self) -> None:
        router = SignalRouter()
        bridge = ProactiveSignalBridge(router, FakeDeliveryAdapter())
        bridge.start()
        bridge.start()
        assert router.handler_count == 1

    def test_stop_unsubscribes(self) -> None:
        router = SignalRouter()
        bridge = ProactiveSignalBridge(router, FakeDeliveryAdapter())
        bridge.start()
        bridge.stop()
        assert not bridge.is_running
        assert router.handler_count == 0

    def test_stop_idempotent(self) -> None:
        router = SignalRouter()
        bridge = ProactiveSignalBridge(router, FakeDeliveryAdapter())
        bridge.stop()  # not running — no-op
        assert not bridge.is_running


# --------------------------------------------------------------------------- #
# Filter + dispatch                                                          #
# --------------------------------------------------------------------------- #


class TestFilterAndDispatch:
    async def test_dispatches_selected_kinds(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(
            router,
            adapter,
            kinds=[SignalKind.CALENDAR, SignalKind.INTERNET],
        )
        bridge.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="meeting"))
        await router.publish(_signal(SignalKind.INTERNET, title="intel"))
        await router.publish(_signal(SignalKind.AUTONOMY, title="cycle"))
        assert len(adapter.dispatched) == 2
        titles = [d.title for d in adapter.dispatched]
        assert "meeting" in titles
        assert "intel" in titles

    async def test_default_kinds(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)  # default kinds
        bridge.start()
        for kind in (
            SignalKind.CALENDAR,
            SignalKind.INTERNET,
            SignalKind.AUTONOMY,
            SignalKind.ANOMALY,
            SignalKind.FOLLOW_UP,
        ):
            await router.publish(_signal(kind, title=kind.value))
        assert len(adapter.dispatched) == 5

    async def test_continuity_kind_filtered_out(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)  # no CONTINUITY
        bridge.start()
        await router.publish(_signal(SignalKind.CONTINUITY, title="handoff"))
        assert adapter.dispatched == []

    async def test_engine_can_silence(self) -> None:
        """DND / value-gate / silence stages return SILENCE; no send."""
        router = SignalRouter()
        adapter = FakeDeliveryAdapter(verdict=DecisionVerdict.SILENCE)
        bridge = ProactiveSignalBridge(router, adapter)
        bridge.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        # The engine still saw the signal, but produced SILENCE.
        assert len(adapter.dispatched) == 1
        # Bridge's counter only tracks dispatch attempts, not verdicts.
        assert bridge.dispatched_count == 1

    async def test_error_does_not_propagate(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter(raises=RuntimeError("dispatch failed"))
        bridge = ProactiveSignalBridge(router, adapter)
        bridge.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        assert bridge.error_count == 1
        assert bridge.dispatched_count == 0

    async def test_stop_then_publish_noop(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)
        bridge.start()
        bridge.stop()
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        assert adapter.dispatched == []


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


class TestStats:
    async def test_counts(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(
            router, adapter, kinds=[SignalKind.CALENDAR]
        )
        bridge.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="ok"))
        await router.publish(_signal(SignalKind.INTERNET, title="filtered"))
        s = bridge.stats()
        assert s["dispatched"] == 1
        assert s["errors"] == 0
        assert s["kinds"] == 1


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_set_and_get(self) -> None:
        router = SignalRouter()
        bridge = ProactiveSignalBridge(router, FakeDeliveryAdapter())
        from app.core.scheduling import (
            set_default_proactive_signal_bridge,
        )

        set_default_proactive_signal_bridge(bridge)
        try:
            from app.core.scheduling import (
                get_default_proactive_signal_bridge,
            )

            assert get_default_proactive_signal_bridge() is bridge
        finally:
            reset_default_proactive_signal_bridge()

    def test_reset_clears(self) -> None:
        from app.core.scheduling import (
            get_default_proactive_signal_bridge,
        )

        reset_default_proactive_signal_bridge()
        assert get_default_proactive_signal_bridge() is None


# --------------------------------------------------------------------------- #
# End-to-end: full v2 signal -> proactive engine -> SILENCE/SPEAK verdict     #
# --------------------------------------------------------------------------- #


class TestEndToEnd:
    async def test_critical_signal_routes_through_engine(self) -> None:
        """A CRITICAL signal becomes a CRITICAL ProactiveSignal.

        The engine's ``Urgency.CRITICAL`` DND bypass kicks in
        (handled by the engine itself, not the bridge).
        """
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)
        bridge.start()

        sig = _signal(
            SignalKind.CALENDAR,
            severity=SignalSeverity.CRITICAL,
            title="Meeting started 5 min ago",
            body="Standup with team",
            payload={"event_id": "e1", "platform": "telegram", "chat_id": "c1"},
        )
        await router.publish(sig)
        assert len(adapter.dispatched) == 1
        p = adapter.dispatched[0]
        assert p.urgency == Urgency.CRITICAL
        assert p.value == 0.95
        assert p.kind == "calendar_prep"
        assert p.metadata["event_id"] == "e1"
        assert p.metadata["chat_id"] == "c1"

    async def test_info_signal_has_low_urgency(self) -> None:
        router = SignalRouter()
        adapter = FakeDeliveryAdapter()
        bridge = ProactiveSignalBridge(router, adapter)
        bridge.start()
        await router.publish(
            _signal(SignalKind.INTERNET, severity=SignalSeverity.INFO, title="intel")
        )
        p = adapter.dispatched[0]
        assert p.urgency == Urgency.LOW
        assert p.value == 0.5
        assert p.kind == "forecast"
