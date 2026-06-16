"""Tests for the continuity-aware target resolver and DeliveryAdapter
integration (Day 16, Phase C4 follow-up)."""

from __future__ import annotations

from typing import Any

import pytest


def _stub_bs() -> Any:
    class _StubBS:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str, str]] = []

        async def send(self, target: Any, payload: Any) -> None:
            self.sent.append((target.platform, target.chat_id, payload.text))

    return _StubBS()


def _make_signal(
    user_id: str = "u1",
    kind: Any = None,
    urgency: Any = None,
    value: float = 0.95,
    confidence: float = 0.95,
    cost: float = 0.1,
) -> Any:
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
    )

    return ProactiveSignal(
        id=f"sig_{user_id}",
        user_id=user_id,
        kind=kind or SignalKind.ROUTINE,
        title="Test",
        body="Hello",
        urgency=urgency or Urgency.NORMAL,
        value=value,
        confidence=confidence,
        interruption_cost=cost,
        source="test",
    )


# -------------------------------------------------------------------
# DefaultTargetResolver
# -------------------------------------------------------------------


class TestDefaultTargetResolver:
    def test_returns_configured_pair(self) -> None:
        from app.core.continuity import DefaultTargetResolver

        r = DefaultTargetResolver(platform="telegram", chat_id="100")
        assert r.resolve("anyone") == ("telegram", "100")

    def test_empty_chat_id_returns_none(self) -> None:
        from app.core.continuity import DefaultTargetResolver

        r = DefaultTargetResolver(platform="telegram", chat_id="")
        assert r.resolve("anyone") is None


# -------------------------------------------------------------------
# ContinuityTargetResolver
# -------------------------------------------------------------------


class TestContinuityTargetResolver:
    def setup_method(self) -> None:
        from app.core.continuity import reset_continuity

        reset_continuity()

    def test_no_continuity_returns_none(self) -> None:
        from app.core.continuity import ContinuityTargetResolver

        r = ContinuityTargetResolver()
        assert r.resolve("nobody") is None

    def test_primary_session_wins(self) -> None:
        from app.core.continuity import ContinuityTargetResolver, continuity

        c = continuity()
        c.ensure_handle("telegram", "100", "alice")
        c.ensure_handle("voice", "desk", "alice", device_kind="voice_assistant")
        c.get_or_create_session("alice", "voice:desk")
        r = ContinuityTargetResolver()
        assert r.resolve("alice") == ("voice", "desk")

    def test_falls_back_to_any_bound_channel(self) -> None:
        from app.core.continuity import ContinuityTargetResolver, continuity

        c = continuity()
        c.ensure_handle("telegram", "100", "alice")
        # No active session — resolver falls back to bound channels.
        r = ContinuityTargetResolver()
        result = r.resolve("alice")
        assert result == ("telegram", "100")

    def test_unknown_user_returns_none(self) -> None:
        from app.core.continuity import ContinuityTargetResolver, continuity

        c = continuity()
        c.ensure_handle("telegram", "100", "alice")
        r = ContinuityTargetResolver()
        assert r.resolve("eve") is None

    def test_split_handles_no_colon(self) -> None:
        from app.core.continuity.integration import ContinuityTargetResolver

        assert ContinuityTargetResolver._split("nocolon") is None
        assert ContinuityTargetResolver._split(":empty_platform") is None
        assert ContinuityTargetResolver._split("empty_chat:") is None
        assert ContinuityTargetResolver._split("ok:value") == ("ok", "value")


# -------------------------------------------------------------------
# CompositeTargetResolver
# -------------------------------------------------------------------


class TestCompositeTargetResolver:
    def test_first_non_none_wins(self) -> None:
        from app.core.continuity import (
            CompositeTargetResolver,
            DefaultTargetResolver,
        )

        r1 = DefaultTargetResolver(platform="x", chat_id="")
        r2 = DefaultTargetResolver(platform="y", chat_id="200")
        composite = CompositeTargetResolver(resolvers=(r1, r2))
        assert composite.resolve("u1") == ("y", "200")

    def test_empty_chain_returns_none(self) -> None:
        from app.core.continuity import CompositeTargetResolver

        composite = CompositeTargetResolver()
        assert composite.resolve("u1") is None

    def test_child_exception_skipped(self) -> None:
        from app.core.continuity import (
            CompositeTargetResolver,
            DefaultTargetResolver,
        )

        class _Boom:
            def resolve(self, user_id: str) -> tuple[str, str] | None:
                raise RuntimeError("explode")

        composite = CompositeTargetResolver(
            resolvers=(
                _Boom(),  # type: ignore[arg-type]
                DefaultTargetResolver(platform="y", chat_id="200"),
            )
        )
        assert composite.resolve("u1") == ("y", "200")


# -------------------------------------------------------------------
# build_default_resolver
# -------------------------------------------------------------------


class TestBuildDefaultResolver:
    def test_continuity_off(self) -> None:
        from app.core.continuity import DefaultTargetResolver, build_default_resolver

        r = build_default_resolver(platform="telegram", chat_id="100", use_continuity=False)
        assert isinstance(r, DefaultTargetResolver)

    def test_continuity_on(self) -> None:
        from app.core.continuity import CompositeTargetResolver, build_default_resolver

        r = build_default_resolver(platform="telegram", chat_id="100", use_continuity=True)
        assert isinstance(r, CompositeTargetResolver)
        assert len(r.resolvers) == 2


# -------------------------------------------------------------------
# DeliveryAdapter target resolution
# -------------------------------------------------------------------


class TestDeliveryAdapterWithResolver:
    def setup_method(self) -> None:
        from app.core.continuity import reset_continuity
        from app.core.proactive_core.bootstrap import reset_registry

        reset_continuity()
        reset_registry()

    def _engine_for(
        self,
        user_id: str,
        *,
        chat_id: str = "",
        channel: str = "telegram",
    ) -> Any:
        from app.core.proactive_core import configure_default_engine

        return configure_default_engine(user_id, chat_id=chat_id, channel=channel)

    @pytest.mark.asyncio
    async def test_resolver_fills_in_missing_target(self) -> None:
        from app.core.continuity import (
            build_default_resolver,
        )
        from app.core.continuity import continuity
        from app.core.proactive_core.delivery import DeliveryAdapter

        c = continuity()
        c.ensure_handle("voice", "desk", "alice", device_kind="voice_assistant")
        c.get_or_create_session("alice", "voice:desk")

        engine = self._engine_for("alice")  # no chat_id
        resolver = build_default_resolver(platform="telegram", chat_id="", use_continuity=True)
        bs = _stub_bs()
        adapter = DeliveryAdapter(engine, botsignal=bs, target_resolver=resolver)

        sig = _make_signal(user_id="alice")
        decision = await adapter.dispatch(sig)
        assert decision.target is not None
        assert decision.target.platform == "voice"
        assert decision.target.chat_id == "desk"
        assert decision.verdict.value == "speak"
        assert bs.sent == [("voice", "desk", "Test\nHello")]

    @pytest.mark.asyncio
    async def test_no_target_no_resolver_silences(self) -> None:
        from app.core.proactive_core import DecisionVerdict
        from app.core.proactive_core.delivery import DeliveryAdapter

        engine = self._engine_for("u1")  # no chat_id, no continuity
        bs = _stub_bs()
        adapter = DeliveryAdapter(engine, botsignal=bs)  # no resolver

        sig = _make_signal(user_id="u1")
        decision = await adapter.dispatch(sig)
        assert decision.verdict == DecisionVerdict.SILENCE
        assert decision.reason == "no_target_resolved"
        assert bs.sent == []

    @pytest.mark.asyncio
    async def test_dispatcher_target_takes_precedence(self) -> None:
        from app.core.continuity import (
            DefaultTargetResolver,
            continuity,
        )
        from app.core.proactive_core.delivery import DeliveryAdapter

        # Engine registered for telegram, but continuity has
        # voice active.  Dispatcher wins (telegram:111).
        c = continuity()
        c.ensure_handle("voice", "desk", "alice", device_kind="voice_assistant")
        c.get_or_create_session("alice", "voice:desk")

        engine = self._engine_for("alice", chat_id="111", channel="telegram")
        resolver = DefaultTargetResolver(platform="telegram", chat_id="111")
        bs = _stub_bs()
        adapter = DeliveryAdapter(engine, botsignal=bs, target_resolver=resolver)

        sig = _make_signal(user_id="alice")
        decision = await adapter.dispatch(sig)
        assert decision.target is not None
        assert decision.target.platform == "telegram"
        assert decision.target.chat_id == "111"

    @pytest.mark.asyncio
    async def test_resolver_exception_falls_through(self) -> None:
        from app.core.proactive_core import DecisionVerdict
        from app.core.proactive_core.delivery import DeliveryAdapter

        class _Boom:
            def resolve(self, user_id: str) -> tuple[str, str] | None:
                raise RuntimeError("explode")

        engine = self._engine_for("u1")
        bs = _stub_bs()
        adapter = DeliveryAdapter(engine, botsignal=bs, target_resolver=_Boom())  # type: ignore[arg-type]

        sig = _make_signal(user_id="u1")
        decision = await adapter.dispatch(sig)
        assert decision.verdict == DecisionVerdict.SILENCE
        assert decision.reason == "no_target_resolved"

    @pytest.mark.asyncio
    async def test_default_resolver_built_when_none_given(self) -> None:
        """build_default_adapter fills in a default resolver when not given."""
        from app.core.proactive_core.delivery import build_default_adapter

        adapter = build_default_adapter(
            "u1", chat_id="100", channel="telegram", botsignal=_stub_bs()
        )
        assert adapter._target_resolver is not None
        assert adapter._target_resolver.resolve("u1") == ("telegram", "100")


# -------------------------------------------------------------------
# Bootstrap integration
# -------------------------------------------------------------------


class TestBootstrapWiring:
    def setup_method(self) -> None:
        from app.core.continuity import reset_continuity
        from app.core.proactive_core.bootstrap import reset_registry

        reset_continuity()
        reset_registry()

    def test_resolver_attached_to_context(self) -> None:
        from app.core.continuity import CompositeTargetResolver
        from app.core.proactive_core.bootstrap import register_proactive_core

        ctxs = register_proactive_core(raw_users="telegram:alice:111")
        assert len(ctxs) == 1
        assert isinstance(ctxs[0].target_resolver, CompositeTargetResolver)

    def test_use_continuity_false_skips_resolver(self) -> None:
        from app.core.continuity import DefaultTargetResolver
        from app.core.proactive_core import (
            ProactiveBootstrapConfig,
        )
        from app.core.proactive_core.bootstrap import register_proactive_core

        ctxs = register_proactive_core(
            raw_users="telegram:alice:111",
            config=ProactiveBootstrapConfig(use_continuity=False),
        )
        assert isinstance(ctxs[0].target_resolver, DefaultTargetResolver)

    def test_malformed_entry_skipped(self) -> None:
        from app.core.proactive_core.bootstrap import register_proactive_core

        ctxs = register_proactive_core(raw_users="bad,also_bad,good:alice:111")
        assert len(ctxs) == 1
        assert ctxs[0].user_id == "alice"

    def test_empty_users_returns_empty_list(self) -> None:
        from app.core.proactive_core.bootstrap import register_proactive_core

        ctxs = register_proactive_core(raw_users="")
        assert ctxs == []


# -------------------------------------------------------------------
# End-to-end: bootstrap + continuity follow
# -------------------------------------------------------------------


class TestEndToEndFollowTheUser:
    def setup_method(self) -> None:
        from app.core.continuity import reset_continuity
        from app.core.proactive_core.bootstrap import reset_registry

        reset_continuity()
        reset_registry()

    @pytest.mark.asyncio
    async def test_proactive_signal_follows_active_channel(self) -> None:
        from app.core.continuity import continuity
        from app.core.proactive_core import (
            ProactiveSignal,
            SignalKind,
            Urgency,
        )
        from app.core.proactive_core.bootstrap import (
            register_proactive_core,
        )

        # Bootstrap: alice is registered for telegram:111.
        # But she's now active on voice (just opened a session there).
        register_proactive_core(raw_users="telegram:alice:111")
        c = continuity()
        c.ensure_handle("voice", "desk", "alice", device_kind="voice_assistant")
        c.get_or_create_session("alice", "voice:desk")

        # Build a separate adapter with continuity-aware resolver
        # and no engine chat_id — the resolver must fill it in.
        from app.core.continuity import build_default_resolver
        from app.core.proactive_core import configure_default_engine
        from app.core.proactive_core.delivery import DeliveryAdapter

        engine = configure_default_engine("alice")
        bs = _stub_bs()
        adapter = DeliveryAdapter(
            engine,
            botsignal=bs,
            target_resolver=build_default_resolver(
                platform="telegram", chat_id="111", use_continuity=True
            ),
        )

        sig = ProactiveSignal(
            id="s1",
            user_id="alice",
            kind=SignalKind.ROUTINE,
            title="Heads up",
            body="morning briefing",
            urgency=Urgency.NORMAL,
            value=0.95,
            confidence=0.95,
            interruption_cost=0.1,
            source="test",
        )
        decision = await adapter.dispatch(sig)
        assert decision.target is not None
        assert decision.target.platform == "voice"
        assert decision.target.chat_id == "desk"
        assert bs.sent == [("voice", "desk", "Heads up\nmorning briefing")]
