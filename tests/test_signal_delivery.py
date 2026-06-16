"""Tests for :class:`SignalDeliveryAdapter` (Day 23)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from app.core.models import ReplyTarget, SignalPayload
from app.core.scheduling import (
    Signal,
    SignalKind,
    SignalRouter,
    SignalSeverity,
    reset_default_signal_delivery_adapter,
    reset_default_signal_router,
    set_default_signal_delivery_adapter,
)
from app.core.scheduling.signal_delivery import (
    CHAT_ID_KEY,
    PLATFORM_KEY,
    SignalDeliveryAdapter,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class FakeBotSignal:
    """Records every ``send`` call; can be made to raise."""

    sent: list[tuple[ReplyTarget, SignalPayload]] = field(default_factory=list)
    raises: Exception | None = None

    async def send(self, target: ReplyTarget, payload: SignalPayload) -> None:
        if self.raises is not None:
            raise self.raises
        self.sent.append((target, payload))


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    reset_default_signal_router()
    reset_default_signal_delivery_adapter()
    yield
    reset_default_signal_router()
    reset_default_signal_delivery_adapter()


def _signal(
    kind: SignalKind,
    user_id: str = "u1",
    *,
    platform: str | None = "telegram",
    chat_id: str | None = "c1",
    title: str = "Test signal",
    body: str | None = None,
) -> Signal:
    payload: dict = {}
    if platform is not None:
        payload["platform"] = platform
    if chat_id is not None:
        payload["chat_id"] = chat_id
    return Signal.make(
        kind,
        "test",
        user_id,
        title,
        body=body,
        payload=payload,
    )


# --------------------------------------------------------------------------- #
# Lifecycle                                                                   #
# --------------------------------------------------------------------------- #


class TestLifecycle:
    def test_start_subscribes(self) -> None:
        router = SignalRouter()
        adapter = SignalDeliveryAdapter(router, FakeBotSignal())
        assert not adapter.is_running
        adapter.start()
        assert adapter.is_running
        assert router.handler_count == 1

    def test_start_is_idempotent(self) -> None:
        router = SignalRouter()
        adapter = SignalDeliveryAdapter(router, FakeBotSignal())
        adapter.start()
        adapter.start()  # no-op
        assert router.handler_count == 1

    def test_stop_unsubscribes(self) -> None:
        router = SignalRouter()
        adapter = SignalDeliveryAdapter(router, FakeBotSignal())
        adapter.start()
        adapter.stop()
        assert not adapter.is_running
        assert router.handler_count == 0

    def test_stop_is_idempotent(self) -> None:
        router = SignalRouter()
        adapter = SignalDeliveryAdapter(router, FakeBotSignal())
        adapter.stop()  # not running — no-op
        assert not adapter.is_running


# --------------------------------------------------------------------------- #
# Filter + delivery                                                           #
# --------------------------------------------------------------------------- #


class TestFilterAndDeliver:
    async def test_delivers_selected_kinds(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(
            router, bot, kinds=[SignalKind.CALENDAR, SignalKind.INTERNET]
        )
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="meeting"))
        await router.publish(_signal(SignalKind.INTERNET, title="intel"))
        # AUTONOMY is not in kinds
        await router.publish(_signal(SignalKind.AUTONOMY, title="cycle"))
        assert len(bot.sent) == 2
        titles = [p.text for _, p in bot.sent]
        assert "meeting" in titles
        assert "intel" in titles

    async def test_default_kinds_include_watchers(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)  # default kinds
        adapter.start()
        for kind in (SignalKind.CALENDAR, SignalKind.INTERNET, SignalKind.AUTONOMY):
            await router.publish(_signal(kind, title=kind.value))
        assert len(bot.sent) == 3

    async def test_body_used_when_present(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="t", body="long body"))
        assert bot.sent[0][1].text == "long body"

    async def test_title_used_when_no_body(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="title-only"))
        assert bot.sent[0][1].text == "title-only"

    async def test_source_kind_is_signal_scoped(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        assert bot.sent[0][1].source_kind == "signal_calendar"

    async def test_target_platform_and_chat_id(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, platform="slack", chat_id="C42"))
        target, _ = bot.sent[0]
        assert target.platform == "slack"
        assert target.chat_id == "C42"


# --------------------------------------------------------------------------- #
# Edge cases                                                                  #
# --------------------------------------------------------------------------- #


class TestEdgeCases:
    async def test_skips_signal_without_platform(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, platform=None))
        assert bot.sent == []
        assert adapter.skipped_count == 1

    async def test_skips_signal_without_chat_id(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, chat_id=None))
        assert bot.sent == []
        assert adapter.skipped_count == 1

    async def test_botsignal_error_does_not_propagate(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal(raises=RuntimeError("network"))
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        # Must not raise — handler errors are caught by the router
        # AND counted by the adapter.
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        assert adapter.error_count == 1
        assert adapter.delivered_count == 0

    async def test_after_stop_publishes_do_nothing(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()
        adapter.stop()
        await router.publish(_signal(SignalKind.CALENDAR, title="x"))
        assert bot.sent == []


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


class TestStats:
    async def test_counts(self) -> None:
        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot, kinds=[SignalKind.CALENDAR])
        adapter.start()
        await router.publish(_signal(SignalKind.CALENDAR, title="ok"))
        await router.publish(_signal(SignalKind.CALENDAR, platform=None))  # skipped
        await router.publish(_signal(SignalKind.INTERNET, title="filtered"))  # kind filter
        s = adapter.stats()
        assert s["delivered"] == 1
        assert s["skipped"] == 1
        assert s["errors"] == 0
        assert s["kinds"] == 1


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_set_and_get(self) -> None:
        router = SignalRouter()
        adapter = SignalDeliveryAdapter(router, FakeBotSignal())
        set_default_signal_delivery_adapter(adapter)
        try:
            from app.core.scheduling import get_default_signal_delivery_adapter

            assert get_default_signal_delivery_adapter() is adapter
        finally:
            reset_default_signal_delivery_adapter()

    def test_reset_clears(self) -> None:
        from app.core.scheduling import get_default_signal_delivery_adapter

        reset_default_signal_delivery_adapter()
        assert get_default_signal_delivery_adapter() is None


# --------------------------------------------------------------------------- #
# Integration with watcher-routine signals                                    #
# --------------------------------------------------------------------------- #


class TestEndToEnd:
    async def test_calendar_signal_flows_through(self) -> None:
        """Simulates the full v2 watcher path:
        CalendarWatcher.generate_signals() → SignalRouter.publish() →
        SignalDeliveryAdapter → botsignal.send()
        """

        router = SignalRouter()
        bot = FakeBotSignal()
        adapter = SignalDeliveryAdapter(router, bot)
        adapter.start()

        sig = Signal.make(
            kind=SignalKind.CALENDAR,
            source="calendar_watcher",
            user_id="u1",
            title="Meeting in 15 min",
            severity=SignalSeverity.NOTICE,
            body="📅 **Meeting in 15 minutes**: Standup",
            payload={"event_id": "e1", "platform": "telegram", "chat_id": "c1"},
            dedupe_key="e1:15min",
        )
        await router.publish(sig)
        assert len(bot.sent) == 1
        target, payload = bot.sent[0]
        assert target.platform == "telegram"
        assert target.chat_id == "c1"
        assert "Standup" in (payload.text or "")
        assert payload.source_kind == "signal_calendar"
        # Queue retains the signal for replay
        assert router.queue_size("u1") == 1
        # _Queue is private; we use the router's stats instead
        assert router.stats()["total_queued"] == 1


# --------------------------------------------------------------------------- #
# Module exports                                                              #
# --------------------------------------------------------------------------- #


class TestModuleExports:
    def test_keys_exposed(self) -> None:
        assert PLATFORM_KEY == "platform"
        assert CHAT_ID_KEY == "chat_id"
