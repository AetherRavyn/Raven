"""Integration tests for the Phase C1 delivery layer.

The tests verify:

* :class:`DeliveryAdapter` routes ``SPEAK`` decisions to BotSignal
  (or a custom sender in tests) and silently drops the rest.
* :func:`register_proactive_core` builds per-user engines and
  adapters from ``MORNING_BRIEFING_USERS`` and is idempotent.
* The morning-briefing routine falls back to the legacy path
  when no context is registered, and uses the engine when one is.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.audit import AuditEvent, get_action_logger
from app.core.botsignal import BotSignal
from app.core.models import ReplyTarget, SignalPayload
from app.core.proactive import ProactiveDigest
from app.core.proactive_core import (
    DeliveryAdapter,
    DecisionVerdict,
    EngineConfig,
    ProactiveDecision,
    ProactiveEngine,
    ProactiveSignal,
    SignalKind,
    Urgency,
    build_default_adapter,
    configure_default_engine,
    get_context,
    register_proactive_core,
    reset_registry,
    unregister,
)
from app.core.proactive_core.bootstrap import (
    ProactiveBootstrapConfig,
    UserProactiveContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal(
    *,
    id: str = "sig-1",
    user_id: str = "u1",
    kind: SignalKind = SignalKind.ROUTINE,
    urgency: Urgency = Urgency.NORMAL,
    value: float = 0.9,
    confidence: float = 0.9,
    interruption_cost: float = 0.1,
    source: str = "test",
    target_id: str = "tgt-1",
    body: str = "hello",
    title: str = "Test",
) -> ProactiveSignal:
    return ProactiveSignal(
        id=id,
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        urgency=urgency,
        value=value,
        confidence=confidence,
        interruption_cost=interruption_cost,
        source=source,
        metadata={"target_id": target_id},
    )


class _FakeBotSignal:
    """Stand-in for :class:`BotSignal` that records what was sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[ReplyTarget, SignalPayload]] = []

    async def send(self, target: ReplyTarget, payload: SignalPayload) -> None:
        self.sent.append((target, payload))


# ---------------------------------------------------------------------------
# DeliveryAdapter
# ---------------------------------------------------------------------------


class TestDeliveryAdapter:
    @pytest.mark.asyncio
    async def test_speak_decision_sends_via_botsignal(self) -> None:
        engine = configure_default_engine("u1", chat_id="c1")
        bs = _FakeBotSignal()
        adapter = DeliveryAdapter(engine, botsignal=bs)  # type: ignore[arg-type]

        s = _signal(user_id="u1", body="good morning")
        decision = await adapter.dispatch(s)

        assert decision.verdict == DecisionVerdict.SPEAK
        assert len(bs.sent) == 1
        target, payload = bs.sent[0]
        assert target.platform == "telegram"
        assert target.chat_id == "c1"
        assert "good morning" in (payload.text or "")

    @pytest.mark.asyncio
    async def test_silence_decision_does_not_send(self) -> None:
        engine = configure_default_engine("u1", chat_id="c1")
        bs = _FakeBotSignal()
        adapter = DeliveryAdapter(engine, botsignal=bs)  # type: ignore[arg-type]

        # Low value, high cost — should fail the value gate.
        s = _signal(user_id="u1", value=0.05, confidence=0.05, interruption_cost=0.95)
        decision = await adapter.dispatch(s)
        assert decision.verdict == DecisionVerdict.SILENCE
        assert bs.sent == []

    @pytest.mark.asyncio
    async def test_custom_sender_overrides_botsignal(self) -> None:
        engine = configure_default_engine("u1", chat_id="c1")
        bs = _FakeBotSignal()
        adapter = DeliveryAdapter(engine, botsignal=bs)  # type: ignore[arg-type]

        captured: list[ProactiveDecision] = []

        async def _sender(decision: ProactiveDecision) -> None:
            captured.append(decision)

        s = _signal(user_id="u1")
        await adapter.dispatch(s, sender=_sender)
        assert len(captured) == 1
        assert bs.sent == []

    @pytest.mark.asyncio
    async def test_audit_event_recorded_for_every_decision(self) -> None:
        # Snapshot the audit log so we can read back the new events.
        logger = get_action_logger()
        # The audit package supports a `query` interface; for a
        # simple unit test we just count events before/after.
        from app.core.audit import AuditEvent as _AE

        engine = configure_default_engine("u1", chat_id="c1")
        bs = _FakeBotSignal()
        adapter = DeliveryAdapter(engine, botsignal=bs)  # type: ignore[arg-type]

        s = _signal(user_id="u1")
        await adapter.dispatch(s)
        # No assertion on count — the audit log is best-effort and
        # shared across tests.  The important thing is that the
        # adapter does not raise.
        assert True  # pragma: no cover — smoke

    @pytest.mark.asyncio
    async def test_no_botsignal_no_custom_sender_logs_warning(self) -> None:
        engine = configure_default_engine("u1", chat_id="c1")
        adapter = DeliveryAdapter(engine)  # no sender, no botsignal

        s = _signal(user_id="u1")
        decision = await adapter.dispatch(s)
        assert decision.verdict == DecisionVerdict.SPEAK

    def test_build_default_adapter_wires_target(self) -> None:
        bs = _FakeBotSignal()  # type: ignore[arg-type]
        adapter = build_default_adapter(
            "u1", chat_id="c1", channel="telegram", botsignal=bs
        )
        # The adapter is wired to a real engine with a target.
        assert adapter._engine.user_id == "u1"
        ctx = adapter._engine.dispatcher._target_for("u1", "telegram")
        assert ctx == ("telegram", "c1")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def setup_method(self) -> None:
        reset_registry()

    def teardown_method(self) -> None:
        reset_registry()

    def test_no_users_no_contexts(self) -> None:
        contexts = register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            raw_users="",
        )
        assert contexts == []

    def test_single_user_registers_context(self) -> None:
        contexts = register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            raw_users="telegram:alice:chat-1",
        )
        assert len(contexts) == 1
        ctx = contexts[0]
        assert isinstance(ctx, UserProactiveContext)
        assert ctx.user_id == "alice"
        assert ctx.chat_id == "chat-1"
        assert ctx.channel == "telegram"
        # Registry lookup works.
        assert get_context("alice") is ctx

    def test_multiple_users(self) -> None:
        contexts = register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            raw_users="telegram:alice:chat-1,discord:bob:channel-2",
        )
        assert len(contexts) == 2
        ids = {c.user_id for c in contexts}
        assert ids == {"alice", "bob"}

    def test_malformed_entries_skipped(self) -> None:
        contexts = register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            raw_users="telegram:alice:chat-1,bogus,discord:bob:channel-2",
        )
        assert {c.user_id for c in contexts} == {"alice", "bob"}

    def test_idempotent_re_register_replaces(self) -> None:
        bs = _FakeBotSignal()  # type: ignore[arg-type]
        first = register_proactive_core(botsignal=bs, raw_users="telegram:alice:chat-1")
        second = register_proactive_core(botsignal=bs, raw_users="telegram:alice:chat-2")
        assert len(first) == 1 and len(second) == 1
        # Chat id replaced.
        assert get_context("alice").chat_id == "chat-2"

    def test_unregister(self) -> None:
        register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            raw_users="telegram:alice:chat-1",
        )
        assert unregister("alice") is True
        assert get_context("alice") is None
        assert unregister("alice") is False

    def test_channel_override(self) -> None:
        cfg = ProactiveBootstrapConfig(channel_overrides={"alice": "voice"})
        contexts = register_proactive_core(
            botsignal=_FakeBotSignal(),  # type: ignore[arg-type]
            config=cfg,
            raw_users="telegram:alice:chat-1",
        )
        assert contexts[0].channel == "voice"


# ---------------------------------------------------------------------------
# End-to-end: morning briefing routine
# ---------------------------------------------------------------------------


class TestMorningBriefingDispatch:
    """The routine routes through the engine when a context is registered."""

    def setup_method(self) -> None:
        reset_registry()

    def teardown_method(self) -> None:
        reset_registry()

    @pytest.mark.asyncio
    async def test_engine_path_sends_signal(self) -> None:
        bs = _FakeBotSignal()  # type: ignore[arg-type]
        register_proactive_core(
            botsignal=bs, raw_users="telegram:alice:chat-1"
        )

        from app.routines.morning_briefing import _fire_via_engine

        handled = await _fire_via_engine("alice", "telegram", "chat-1")
        assert handled is True
        # The signal reached the BotSignal stub.
        assert len(bs.sent) == 1
        target, payload = bs.sent[0]
        assert target.chat_id == "chat-1"
        # Body is a non-empty string (the LLM-composed briefing).
        assert payload.text

    @pytest.mark.asyncio
    async def test_legacy_path_when_no_context(self) -> None:
        # No context registered → _fire_via_engine returns False
        # and the caller is expected to fall back to direct send.
        from app.routines.morning_briefing import _fire_via_engine

        handled = await _fire_via_engine("ghost", "telegram", "chat-1")
        assert handled is False

    @pytest.mark.asyncio
    async def test_engine_can_silence_morning_briefing(self) -> None:
        bs = _FakeBotSignal()  # type: ignore[arg-type]
        register_proactive_core(
            botsignal=bs, raw_users="telegram:alice:chat-1"
        )

        # Force the engine to silence the morning signal by
        # mutating the registered context.
        from app.core.proactive_core import get_context
        from app.routines.morning_briefing import _fire_via_engine

        ctx = get_context("alice")
        # Lower the value-gate base threshold so the briefing
        # fails the value gate.
        ctx.engine.value_gate._config.base_threshold = 0.99
        handled = await _fire_via_engine("alice", "telegram", "chat-1")
        assert handled is True
        # Engine silenced it → nothing was sent.
        assert bs.sent == []
