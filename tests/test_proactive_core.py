"""Tests for the Phase C1 Proactive Core.

No I/O required — every component is a pure function or a pure
class.  The tests are organised one class per pipeline stage:

* :class:`TestTypes` — dataclass / enum smoke
* :class:`TestQuietHours` — DND / focus mode / learned windows
* :class:`TestValueGate` — score and threshold
* :class:`TestSilence` — rate limit, dedup, annoyance
* :class:`TestDispatcher` — channel selection
* :class:`TestEngine` — end-to-end pipeline
* :class:`TestAnnoyanceFeedback` — user feedback loop
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from app.core.proactive_core import (
    AnnoyanceTracker,
    ChannelDispatcher,
    ChannelPreference,
    DecisionVerdict,
    DispatcherConfig,
    EngineConfig,
    GateConfig,
    InMemoryRateLimitStore,
    ProactiveDecision,
    ProactiveEngine,
    ProactiveSignal,
    QuietHoursResolver,
    QuietWindow,
    SignalKind,
    SilenceConfig,
    SilenceEngine,
    Urgency,
    ValueGate,
    configure_default_engine,
)
from app.core.proactive_core.silence import fingerprint
from app.core.proactive_core.value_gate import GateConfig as _GateConfig
from app.core.models import ReplyTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal(
    *,
    id: str = "sig-1",
    user_id: str = "u1",
    kind: SignalKind = SignalKind.ROUTINE,
    urgency: Urgency = Urgency.NORMAL,
    value: float = 0.5,
    confidence: float = 0.7,
    interruption_cost: float = 0.3,
    source: str = "test",
    target_id: str = "tgt-1",
) -> ProactiveSignal:
    return ProactiveSignal(
        id=id,
        user_id=user_id,
        kind=kind,
        title="t",
        body="b",
        urgency=urgency,
        value=value,
        confidence=confidence,
        interruption_cost=interruption_cost,
        source=source,
        metadata={"target_id": target_id},
    )


class _StaticCalendar:
    """Always reports the user is busy."""

    def is_user_busy(self, user_id: str, at: datetime) -> bool:
        return True


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestTypes:
    def test_signal_final_value_clipped(self) -> None:
        s = _signal(value=2.0, confidence=2.0)
        assert s.final_value() == 1.0
        s = _signal(value=-1.0, confidence=0.5)
        assert s.final_value() == 0.0

    def test_proactive_decision_to_dict(self) -> None:
        s = _signal()
        d = ProactiveDecision(
            signal=s,
            verdict=DecisionVerdict.SPEAK,
            stage="accepted",
            score=0.5,
            channel="telegram",
            target=ReplyTarget(platform="telegram", chat_id="42"),
        )
        out = d.to_dict()
        assert out["signal_id"] == "sig-1"
        assert out["verdict"] == "speak"
        assert out["channel"] == "telegram"
        assert out["target"] == {"platform": "telegram", "chat_id": "42"}


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


class TestQuietHours:
    def test_user_window_blocks(self) -> None:
        window = QuietWindow(start_hour=22, start_minute=0, end_hour=7, end_minute=0, label="night")
        r = QuietHoursResolver(user_windows=[window])
        now = datetime(2024, 6, 12, 23, 0, tzinfo=timezone.utc)
        in_quiet, label = r.is_in_quiet_window(now)
        assert in_quiet and label == "user:night"

    def test_wrap_midnight_window(self) -> None:
        window = QuietWindow(22, 0, 7, 0, "night")
        r = QuietHoursResolver(user_windows=[window])
        # 3am should still be in the window
        now = datetime(2024, 6, 12, 3, 0, tzinfo=timezone.utc)
        in_quiet, _ = r.is_in_quiet_window(now)
        assert in_quiet
        # 9am should not
        now = datetime(2024, 6, 12, 9, 0, tzinfo=timezone.utc)
        in_quiet, _ = r.is_in_quiet_window(now)
        assert not in_quiet

    def test_focus_mode_blocks(self) -> None:
        r = QuietHoursResolver(focus_mode=True)
        in_quiet, label = r.is_in_quiet_window(datetime(2024, 6, 12, 12, 0, tzinfo=timezone.utc))
        assert in_quiet and label == "focus_mode"

    def test_learned_window(self) -> None:
        window = QuietWindow(13, 0, 14, 0, "lunch")
        r = QuietHoursResolver(learned_windows=[window])
        in_quiet, label = r.is_in_quiet_window(datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc))
        assert in_quiet and label == "learned:lunch"

    def test_critical_signal_passes_quiet_hours(self) -> None:
        window = QuietWindow(22, 0, 7, 0, "night")
        r = QuietHoursResolver(user_windows=[window])
        s = _signal(urgency=Urgency.CRITICAL)
        now = datetime(2024, 6, 12, 23, 0, tzinfo=timezone.utc)
        assert r.evaluate(s, now=now) is None

    def test_normal_signal_is_deferred(self) -> None:
        window = QuietWindow(22, 0, 7, 0, "night")
        r = QuietHoursResolver(user_windows=[window])
        s = _signal(urgency=Urgency.NORMAL)
        now = datetime(2024, 6, 12, 23, 0, tzinfo=timezone.utc)
        d = r.evaluate(s, now=now)
        assert d is not None
        assert d.verdict == DecisionVerdict.DEFER
        assert d.defer_until is not None
        assert d.defer_until > now

    def test_calendar_provider_mutes(self) -> None:
        r = QuietHoursResolver()
        s = _signal()
        now = datetime(2024, 6, 12, 12, 0, tzinfo=timezone.utc)
        d = r.evaluate(s, now=now, calendar=_StaticCalendar())
        assert d is not None
        assert "calendar:busy" in d.reason

    def test_critical_can_be_blocked_when_every_window_disallows(self) -> None:
        # When every window sets allow_critical=False, even CRITICAL
        # is blocked.
        windows = [
            QuietWindow(0, 0, 23, 59, "always", allow_critical=False),
        ]
        r = QuietHoursResolver(user_windows=windows)
        s = _signal(urgency=Urgency.CRITICAL)
        d = r.evaluate(s, now=datetime(2024, 6, 12, 12, 0, tzinfo=timezone.utc))
        assert d is not None
        assert d.verdict == DecisionVerdict.DEFER


# ---------------------------------------------------------------------------
# Value gate
# ---------------------------------------------------------------------------


class TestValueGate:
    def test_score_utility_minus_cost(self) -> None:
        gate = ValueGate()
        s = _signal(value=0.8, confidence=0.9, interruption_cost=0.2)
        # 0.72 - 0.2 = 0.52
        assert gate.score(s) == pytest.approx(0.52)

    def test_score_clipped(self) -> None:
        gate = ValueGate()
        s = _signal(value=2.0, confidence=2.0, interruption_cost=-0.5)
        assert gate.score(s) == 1.0

    def test_critical_lowers_threshold(self) -> None:
        gate = ValueGate()
        s_low = _signal(value=0.1, confidence=0.1, urgency=Urgency.LOW)
        s_crit = _signal(value=0.1, confidence=0.1, urgency=Urgency.CRITICAL)
        _, _ = gate.evaluate(s_low)
        _, _ = gate.evaluate(s_crit)
        assert gate.config.threshold_for(s_crit) < gate.config.threshold_for(s_low)

    def test_below_threshold_silences(self) -> None:
        gate = ValueGate(config=GateConfig(base_threshold=0.9))
        s = _signal(value=0.3, confidence=0.3, interruption_cost=0.5)
        d, score = gate.evaluate(s)
        assert d is not None
        assert d.verdict == DecisionVerdict.SILENCE
        assert d.stage == "value"
        assert score < 0.9

    def test_above_threshold_passes(self) -> None:
        gate = ValueGate(config=GateConfig(base_threshold=0.1))
        s = _signal(value=0.9, confidence=0.9)
        d, score = gate.evaluate(s)
        assert d is None
        assert score > 0.1

    def test_explain_returns_components(self) -> None:
        gate = ValueGate()
        s = _signal()
        info = gate.explain(s)
        assert "value" in info
        assert "score" in info
        assert "threshold" in info


# ---------------------------------------------------------------------------
# Silence
# ---------------------------------------------------------------------------


class TestSilence:
    def test_first_signal_passes(self) -> None:
        engine = SilenceEngine()
        s = _signal()
        assert engine.evaluate(s) is None

    def test_rate_limit_kicks_in(self) -> None:
        config = SilenceConfig(max_per_hour=2, critical_exempt=False)
        engine = SilenceEngine(config=config)
        for i in range(2):
            s = _signal(id=f"sig-{i}", target_id=f"t-{i}")
            assert engine.evaluate(s) is None
            engine.commit(s)
        s3 = _signal(id="sig-3", target_id="t-3")
        d = engine.evaluate(s3)
        assert d is not None
        assert d.verdict == DecisionVerdict.SILENCE
        assert "rate_limit" in d.reason

    def test_critical_exempt(self) -> None:
        config = SilenceConfig(max_per_hour=1, critical_exempt=True)
        engine = SilenceEngine(config=config)
        for i in range(5):
            s = _signal(id=f"c-{i}", target_id=f"t-{i}", urgency=Urgency.CRITICAL)
            assert engine.evaluate(s) is None
            engine.commit(s)

    def test_dedup(self) -> None:
        engine = SilenceEngine()
        s = _signal()
        assert engine.evaluate(s) is None
        engine.commit(s)
        # Same fingerprint within window → silence.
        s2 = _signal(id="sig-2")
        d = engine.evaluate(s2)
        assert d is not None
        assert "dedup" in d.reason

    def test_dedup_different_target_id_passes(self) -> None:
        engine = SilenceEngine()
        s = _signal()
        assert engine.evaluate(s) is None
        engine.commit(s)
        s2 = _signal(id="sig-2", target_id="tgt-2")
        assert engine.evaluate(s2) is None

    def test_fingerprint_stable(self) -> None:
        a = _signal(kind=SignalKind.ANOMALY, source="anomaly_detector")
        b = _signal(kind=SignalKind.ANOMALY, source="anomaly_detector", id="other")
        assert fingerprint(a) == fingerprint(b)

    def test_in_memory_store_record_and_seen(self) -> None:
        store = InMemoryRateLimitStore()
        store.record("u1", time.time())
        assert store.last_delivered("u1")
        store.mark_seen("u1", "fp", time.time())
        assert store.seen("u1", "fp", 60.0)
        assert not store.seen("u1", "missing", 60.0)


# ---------------------------------------------------------------------------
# Annoyance
# ---------------------------------------------------------------------------


class TestAnnoyanceFeedback:
    def test_annoying_kind_is_silenced(self) -> None:
        config = SilenceConfig(annoyance_threshold=1, annoyance_cooldown_s=3600)
        store = InMemoryRateLimitStore()
        tracker = AnnoyanceTracker(store, config)
        engine = SilenceEngine(store=store, config=config)
        s = _signal()
        tracker.report("u1", s)
        d = engine.evaluate(s)
        assert d is not None
        assert "annoyance" in d.reason

    def test_cool_down_expires(self) -> None:
        # Two reports, but cool-down already expired → not annoying.
        config = SilenceConfig(annoyance_threshold=1, annoyance_cooldown_s=0.0)
        store = InMemoryRateLimitStore()
        tracker = AnnoyanceTracker(store, config)
        engine = SilenceEngine(store=store, config=config)
        s = _signal()
        tracker.report("u1", s)
        # Cool-down is 0, so by the time we evaluate it's over.
        time.sleep(0.01)
        # Re-report so the timestamp is fresh
        tracker.report("u1", s)
        # With cooldown=0, the next call to is_annoying returns False.
        assert engine.annoyance.is_annoying("u1", s) is False


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_preference_routed_to_preferred_channel(self) -> None:
        pref = ChannelPreference(kind=SignalKind.ANOMALY, channel="discord")
        d = ChannelDispatcher(
            preferences=[pref],
            config=DispatcherConfig(user_channels={"u1": {"discord": "D1"}}),
        )
        s = _signal(kind=SignalKind.ANOMALY)
        decision = d.evaluate(s)
        assert decision is not None
        assert decision.verdict == DecisionVerdict.SPEAK
        assert decision.channel == "discord"
        assert decision.target is not None
        assert decision.target.chat_id == "D1"

    def test_urgency_override(self) -> None:
        config = DispatcherConfig(
            user_channels={"u1": {"voice": "VOICE1"}},
            channel_by_urgency={Urgency.CRITICAL: "voice"},
        )
        d = ChannelDispatcher(config=config)
        s = _signal(urgency=Urgency.CRITICAL)
        decision = d.evaluate(s)
        assert decision is not None
        assert decision.channel == "voice"

    def test_no_target_returns_speak_without_target(self) -> None:
        # The dispatcher no longer decides SILENCE on a missing
        # target.  It returns SPEAK with target=None so the
        # delivery adapter (with its continuity resolver) can
        # fill in a real target — or downgrade to SILENCE.
        d = ChannelDispatcher(config=DispatcherConfig())
        s = _signal()
        decision = d.evaluate(s)
        assert decision is not None
        assert decision.verdict == DecisionVerdict.SPEAK
        assert decision.target is None
        assert "no_target" in decision.reason

    def test_fallback_to_default(self) -> None:
        pref = ChannelPreference(kind=SignalKind.ANOMALY, channel="discord")
        config = DispatcherConfig(user_channels={"u1": {"telegram": "T1"}})
        d = ChannelDispatcher(preferences=[pref], config=config)
        s = _signal(kind=SignalKind.ANOMALY)
        decision = d.evaluate(s)
        assert decision is not None
        assert decision.channel == "telegram"
        assert decision.target is not None
        assert decision.target.chat_id == "T1"


# ---------------------------------------------------------------------------
# Engine (end-to-end)
# ---------------------------------------------------------------------------


class TestEngine:
    def _engine(self, user_id: str = "u1") -> ProactiveEngine:
        config = EngineConfig(
            focus_mode=False,
        )
        engine = ProactiveEngine.for_user(user_id, config=config)
        engine.register_target("telegram", "chat-1")
        return engine

    @pytest.mark.asyncio
    async def test_happy_path_speaks(self) -> None:
        engine = self._engine()
        s = _signal(value=0.9, confidence=0.9, urgency=Urgency.NORMAL)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.SPEAK
        assert d.channel == "telegram"
        assert d.target is not None
        assert d.target.chat_id == "chat-1"

    @pytest.mark.asyncio
    async def test_dnd_defers(self) -> None:
        engine = self._engine()
        engine.add_quiet_window(QuietWindow(0, 0, 23, 59, "all-day"))
        s = _signal(urgency=Urgency.HIGH)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.DEFER
        assert d.stage == "dnd"

    @pytest.mark.asyncio
    async def test_focus_mode_defers(self) -> None:
        engine = self._engine()
        engine.set_focus_mode(True)
        s = _signal(urgency=Urgency.HIGH)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.DEFER

    @pytest.mark.asyncio
    async def test_low_value_silenced(self) -> None:
        engine = self._engine()
        # Low value, normal urgency, default gate won't let it through.
        s = _signal(value=0.05, confidence=0.1, interruption_cost=0.9)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.SILENCE
        assert d.stage == "value"

    @pytest.mark.asyncio
    async def test_dedup_silences_repeat(self) -> None:
        engine = self._engine()
        s = _signal(value=0.9, confidence=0.9)
        d1 = await engine.evaluate(s)
        assert d1.verdict == DecisionVerdict.SPEAK
        d2 = await engine.evaluate(s)
        assert d2.verdict == DecisionVerdict.SILENCE
        assert d2.stage == "silence"
        assert "dedup" in d2.reason

    @pytest.mark.asyncio
    async def test_rate_limit_silences(self) -> None:
        engine = self._engine()
        # Override silence config for a small window.
        engine.silence = SilenceEngine(config=SilenceConfig(max_per_hour=2, critical_exempt=False))
        # High value signals that clear the value gate.
        for i in range(2):
            s = _signal(id=f"x{i}", target_id=f"t{i}", value=0.9, confidence=0.9)
            d = await engine.evaluate(s)
            assert d.verdict == DecisionVerdict.SPEAK
        s3 = _signal(id="x3", target_id="t3", value=0.9, confidence=0.9)
        d = await engine.evaluate(s3)
        assert d.verdict == DecisionVerdict.SILENCE
        assert "rate_limit" in d.reason

    @pytest.mark.asyncio
    async def test_wrong_user_drops(self) -> None:
        engine = self._engine(user_id="alice")
        s = _signal(user_id="bob")
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.DROP

    @pytest.mark.asyncio
    async def test_critical_signal_breaks_through(self) -> None:
        engine = self._engine()
        engine.add_quiet_window(QuietWindow(0, 0, 23, 59, "all-day"))
        s = _signal(urgency=Urgency.CRITICAL, value=0.9, confidence=0.9)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.SPEAK

    @pytest.mark.asyncio
    async def test_no_target_returns_speak_with_none_target(self) -> None:
        # Engine propagates the dispatcher's "no target" decision
        # as SPEAK with target=None (then "accepted" stage after
        # silence-engine bookkeeping).  The delivery adapter is
        # responsible for resolving a real target (or downgrading
        # to SILENCE if no resolver is configured).
        engine = ProactiveEngine.for_user("u1")
        s = _signal(value=0.9, confidence=0.9)
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.SPEAK
        assert d.target is None
        # The engine re-stages SPEAK as "accepted" after
        # silence-engine bookkeeping.  The original dispatch
        # stage reason is preserved on the signal flow, but
        # the final stage here is "accepted".
        assert d.stage in ("dispatch", "accepted")

    @pytest.mark.asyncio
    async def test_user_feedback_silences_subsequent(self) -> None:
        engine = self._engine()
        # Lower the annoyance threshold so one complaint is enough.
        engine.silence = SilenceEngine(
            config=SilenceConfig(
                max_per_hour=5,
                critical_exempt=False,
                annoyance_threshold=1,
                annoyance_cooldown_s=3600,
            )
        )
        # First, deliver a signal normally.
        s = _signal(value=0.9, confidence=0.9, target_id="evt-1")
        d = await engine.evaluate(s)
        assert d.verdict == DecisionVerdict.SPEAK
        # User complains.
        engine.report_user_feedback(s)
        # New signal of the same kind/source should be silenced.
        s2 = _signal(id="sig-2", value=0.9, confidence=0.9, target_id="evt-2")
        d2 = await engine.evaluate(s2)
        assert d2.verdict == DecisionVerdict.SILENCE
        assert "annoyance" in d2.reason


# ---------------------------------------------------------------------------
# Helper / explain
# ---------------------------------------------------------------------------


class TestExplain:
    def test_engine_explain(self) -> None:
        engine = ProactiveEngine.for_user("u1")
        info = engine.explain()
        assert info["user_id"] == "u1"
        assert "value_gate" in info
        assert "silence" in info
        assert "dispatcher" in info

    def test_configure_default_engine_registers_target(self) -> None:
        e = configure_default_engine("u1", chat_id="chat-X")
        assert e.user_id == "u1"
        # The dispatcher should now have a registered target.
        d = e.dispatcher._target_for("u1", "telegram")
        assert d == ("telegram", "chat-X")


# ---------------------------------------------------------------------------
# GateConfig import-name check
# ---------------------------------------------------------------------------


def test_gate_config_alias() -> None:
    """The value_gate module exports GateConfig as both name and alias."""
    from app.core.proactive_core import value_gate

    assert value_gate.GateConfig is _GateConfig
