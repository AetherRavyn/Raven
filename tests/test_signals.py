"""Tests for the signal module (Day 22)."""

from __future__ import annotations

import asyncio


from app.core.scheduling import (
    DedupeCache,
    Signal,
    SignalKind,
    SignalRouter,
    SignalSeverity,
    generate_signals,
    get_default_signal_router,
    reset_default_signal_router,
    set_default_signal_router,
)
from app.core.scheduling.signal import _Queue


# --------------------------------------------------------------------------- #
# SignalKind / SignalSeverity                                                  #
# --------------------------------------------------------------------------- #


class TestSignalEnums:
    def test_kinds_are_strings(self) -> None:
        # Enum members are string-coercible so producers can use literals.
        assert SignalKind.CALENDAR == "calendar"
        assert SignalKind.INTERNET == "internet"
        assert SignalKind.AUTONOMY == "autonomy"
        assert SignalKind.ANOMALY == "anomaly"
        assert SignalKind.FOLLOW_UP == "follow_up"
        assert SignalKind.SYSTEM == "system"
        assert SignalKind.MEMORY == "memory"
        assert SignalKind.CONTINUITY == "continuity"

    def test_severities_are_strings(self) -> None:
        assert SignalSeverity.INFO == "info"
        assert SignalSeverity.NOTICE == "notice"
        assert SignalSeverity.WARNING == "warning"
        assert SignalSeverity.CRITICAL == "critical"

    def test_kind_round_trip(self) -> None:
        assert SignalKind("calendar") is SignalKind.CALENDAR
        assert SignalSeverity("critical") is SignalSeverity.CRITICAL


# --------------------------------------------------------------------------- #
# Signal                                                                      #
# --------------------------------------------------------------------------- #


class TestSignal:
    def test_make_generates_id(self) -> None:
        s = Signal.make(
            kind="calendar",
            source="test",
            user_id="u1",
            title="Test",
        )
        assert s.id.startswith("sig_")
        assert len(s.id) == 4 + 12
        assert s.kind is SignalKind.CALENDAR
        assert s.severity is SignalSeverity.INFO
        assert s.user_id == "u1"
        assert s.title == "Test"
        assert s.body is None
        assert s.payload == {}
        assert s.dedupe_key is None

    def test_make_accepts_enum_or_string(self) -> None:
        a = Signal.make(SignalKind.CALENDAR, "s", "u1", "t")
        b = Signal.make("calendar", "s", "u1", "t")
        assert a.kind is b.kind
        a2 = Signal.make("calendar", "s", "u1", "t", severity=SignalSeverity.WARNING)
        b2 = Signal.make("calendar", "s", "u1", "t", severity="warning")
        assert a2.severity is b2.severity

    def test_make_with_payload_and_dedupe(self) -> None:
        s = Signal.make(
            "calendar",
            "calendar_watcher",
            "u1",
            "Meeting",
            severity="notice",
            body="In 15 minutes",
            payload={"event_id": "evt_1"},
            dedupe_key="evt_1:15min",
        )
        assert s.severity is SignalSeverity.NOTICE
        assert s.body == "In 15 minutes"
        assert s.payload == {"event_id": "evt_1"}
        assert s.dedupe_key == "evt_1:15min"

    def test_payload_default_isolation(self) -> None:
        # Each Signal gets its own dict (no shared mutable default).
        a = Signal.make("calendar", "s", "u1", "t")
        b = Signal.make("calendar", "s", "u1", "t")
        a.payload["k"] = "v"
        assert "k" not in b.payload

    def test_to_dict_is_json_safe(self) -> None:
        s = Signal.make(
            "calendar",
            "calendar_watcher",
            "u1",
            "Meeting",
            body="body text",
            payload={"id": "evt_1", "n": 5},
        )
        d = s.to_dict()
        assert d["kind"] == "calendar"
        assert d["severity"] == "info"
        assert d["payload"] == {"id": "evt_1", "n": 5}
        assert "T" in d["created_at"]  # ISO timestamp

    def test_repr_is_compact(self) -> None:
        s = Signal.make("calendar", "cal", "u1", "x")
        r = repr(s)
        assert "calendar" in r
        assert "u1" in r


# --------------------------------------------------------------------------- #
# _Queue                                                                      #
# --------------------------------------------------------------------------- #


class TestQueue:
    def test_push_and_peek(self) -> None:
        q = _Queue(user_id="u1")
        s1 = Signal.make("calendar", "s", "u1", "t1")
        s2 = Signal.make("calendar", "s", "u1", "t2")
        q.push(s1)
        q.push(s2)
        assert q.peek() == [s1, s2]
        assert q.peek(n=1) == [s2]

    def test_drain_clears(self) -> None:
        q = _Queue(user_id="u1")
        q.push(Signal.make("calendar", "s", "u1", "t"))
        assert len(q.drain()) == 1
        assert q.peek() == []

    def test_overflow_drops_oldest(self) -> None:
        q = _Queue(user_id="u1", maxlen=2)
        s1 = Signal.make("calendar", "s", "u1", "t1")
        s2 = Signal.make("calendar", "s", "u1", "t2")
        s3 = Signal.make("calendar", "s", "u1", "t3")
        q.push(s1)
        q.push(s2)
        q.push(s3)
        assert q.peek() == [s2, s3]


# --------------------------------------------------------------------------- #
# SignalRouter                                                                #
# --------------------------------------------------------------------------- #


class TestSignalRouter:
    def test_empty_router(self) -> None:
        r = SignalRouter()
        assert r.handler_count == 0
        stats = r.stats()
        assert stats["handlers"] == 0
        assert stats["users_with_queues"] == 0
        assert stats["total_queued"] == 0

    async def test_publish_to_queue(self) -> None:
        r = SignalRouter()
        s = Signal.make("calendar", "s", "u1", "t")
        delivered = await r.publish(s)
        assert delivered == 0  # no handlers
        assert r.queue_size("u1") == 1
        assert r.peek("u1") == [s]

    async def test_subscribe_and_publish(self) -> None:
        r = SignalRouter()
        received: list[Signal] = []

        async def handler(sig: Signal) -> None:
            received.append(sig)

        unsub = r.subscribe(handler)
        s = Signal.make("calendar", "s", "u1", "t")
        n = await r.publish(s)
        assert n == 1
        assert received == [s]
        unsub()
        assert r.handler_count == 0

    async def test_unsubscribe_handler(self) -> None:
        r = SignalRouter()

        async def h(_: Signal) -> None:
            pass

        r.subscribe(h)
        assert r.handler_count == 1
        r.unsubscribe_handler(h)
        assert r.handler_count == 0

    async def test_predicate_filters(self) -> None:
        r = SignalRouter()
        received: list[Signal] = []

        async def handler(sig: Signal) -> None:
            received.append(sig)

        r.subscribe(handler, predicate=lambda s: s.severity is SignalSeverity.CRITICAL)
        a = Signal.make("calendar", "s", "u1", "a", severity="info")
        b = Signal.make("calendar", "s", "u1", "b", severity="critical")
        await r.publish(a)
        await r.publish(b)
        assert len(received) == 1
        assert received[0] is b

    async def test_handler_error_does_not_block_fanout(self) -> None:
        r = SignalRouter()
        received: list[Signal] = []

        async def bad(_: Signal) -> None:
            raise RuntimeError("boom")

        async def good(sig: Signal) -> None:
            received.append(sig)

        r.subscribe(bad, name="bad")
        r.subscribe(good, name="good")
        s = Signal.make("calendar", "s", "u1", "t")
        n = await r.publish(s)
        # bad raises -> counted as not delivered; good counts.
        assert n == 1
        assert received == [s]

    async def test_publish_many(self) -> None:
        r = SignalRouter()
        received: list[Signal] = []

        async def handler(sig: Signal) -> None:
            received.append(sig)

        r.subscribe(handler)
        s1 = Signal.make("calendar", "s", "u1", "t1")
        s2 = Signal.make("calendar", "s", "u1", "t2")
        result = await r.publish_many([s1, s2])
        assert result == {s1.id: 1, s2.id: 1}
        assert received == [s1, s2]

    async def test_drain_user(self) -> None:
        r = SignalRouter()
        s1 = Signal.make("calendar", "s", "u1", "t1")
        s2 = Signal.make("calendar", "s", "u1", "t2")
        await r.publish(s1)
        await r.publish(s2)
        assert r.queue_size("u1") == 2
        drained = r.drain("u1")
        assert drained == [s1, s2]
        assert r.queue_size("u1") == 0

    async def test_queue_overflow(self) -> None:
        r = SignalRouter(queue_maxlen=2)
        for i in range(5):
            await r.publish(
                Signal.make("calendar", "s", "u1", f"t{i}")
            )
        assert r.queue_size("u1") == 2

    def test_subscribe_returns_unsubscribe_callable(self) -> None:
        r = SignalRouter()

        async def h(_: Signal) -> None:
            pass

        unsub = r.subscribe(h)
        assert r.handler_count == 1
        unsub()
        assert r.handler_count == 0

    def test_handler_name_falls_back(self) -> None:
        r = SignalRouter()
        handler = lambda s: asyncio.sleep(0)  # noqa: E731
        r.subscribe(handler)  # type: ignore[arg-type]
        assert r.handler_count == 1


# --------------------------------------------------------------------------- #
# DedupeCache                                                                 #
# --------------------------------------------------------------------------- #


class TestDedupeCache:
    def test_fresh_key_returns_false(self) -> None:
        d = DedupeCache()
        fresh = d.check_and_record("u1", SignalKind.CALENDAR, "evt_1:15min")
        assert fresh is False

    def test_duplicate_returns_true(self) -> None:
        d = DedupeCache()
        d.check_and_record("u1", SignalKind.CALENDAR, "evt_1:15min")
        fresh = d.check_and_record("u1", SignalKind.CALENDAR, "evt_1:15min")
        assert fresh is True

    def test_none_key_always_fresh(self) -> None:
        d = DedupeCache()
        assert d.check_and_record("u1", SignalKind.CALENDAR, None) is False
        assert d.check_and_record("u1", SignalKind.CALENDAR, None) is False

    def test_per_user_isolation(self) -> None:
        d = DedupeCache()
        d.check_and_record("u1", SignalKind.CALENDAR, "k")
        assert d.check_and_record("u2", SignalKind.CALENDAR, "k") is False

    def test_per_kind_isolation(self) -> None:
        d = DedupeCache()
        d.check_and_record("u1", SignalKind.CALENDAR, "k")
        assert d.check_and_record("u1", SignalKind.INTERNET, "k") is False

    def test_ttl_expiry(self) -> None:
        d = DedupeCache(ttl_seconds=1.0)
        d.check_and_record("u1", SignalKind.CALENDAR, "k", now=1000.0)
        assert d.check_and_record("u1", SignalKind.CALENDAR, "k", now=1000.5) is True
        # After TTL, key is forgotten
        assert d.check_and_record("u1", SignalKind.CALENDAR, "k", now=1002.0) is False

    def test_maxlen_eviction(self) -> None:
        d = DedupeCache(maxlen=3)
        for i in range(5):
            d.check_and_record("u1", SignalKind.CALENDAR, f"k{i}")
        # Newer keys are still tracked
        assert d.check_and_record("u1", SignalKind.CALENDAR, "k4") is True
        # Oldest evicted
        assert d.check_and_record("u1", SignalKind.CALENDAR, "k0") is False

    def test_clear(self) -> None:
        d = DedupeCache()
        d.check_and_record("u1", SignalKind.CALENDAR, "k")
        d.clear()
        assert d.check_and_record("u1", SignalKind.CALENDAR, "k") is False


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestDefaultRouter:
    def test_singleton(self) -> None:
        reset_default_signal_router()
        a = get_default_signal_router()
        b = get_default_signal_router()
        assert a is b

    def test_reset_creates_new(self) -> None:
        a = get_default_signal_router()
        reset_default_signal_router()
        b = get_default_signal_router()
        assert a is not b

    def test_set_default(self) -> None:
        custom = SignalRouter()
        set_default_signal_router(custom)
        try:
            assert get_default_signal_router() is custom
        finally:
            reset_default_signal_router()


# --------------------------------------------------------------------------- #
# generate_signals                                                            #
# --------------------------------------------------------------------------- #


class TestGenerateSignals:
    async def test_aggregates_producers(self) -> None:
        async def p1() -> list[Signal]:
            return [Signal.make("calendar", "s", "u1", "a")]

        async def p2() -> list[Signal]:
            return [Signal.make("internet", "s", "u1", "b")]

        out = await generate_signals(p1, p2)
        assert len(out) == 2
        assert out[0].kind is SignalKind.CALENDAR
        assert out[1].kind is SignalKind.INTERNET

    async def test_producer_error_swallowed(self) -> None:
        async def bad() -> list[Signal]:
            raise RuntimeError("nope")

        async def good() -> list[Signal]:
            return [Signal.make("calendar", "s", "u1", "x")]

        out = await generate_signals(bad, good)
        assert len(out) == 1
        assert out[0].title == "x"

    async def test_no_producers(self) -> None:
        out = await generate_signals()
        assert out == []


# --------------------------------------------------------------------------- #
# End-to-end                                                                  #
# --------------------------------------------------------------------------- #


class TestEndToEnd:
    async def test_producer_to_subscribers(self) -> None:
        router = SignalRouter()
        delivered: list[Signal] = []
        warned: list[Signal] = []

        async def all_signals(sig: Signal) -> None:
            delivered.append(sig)

        async def only_critical(sig: Signal) -> None:
            if sig.severity is SignalSeverity.CRITICAL:
                warned.append(sig)

        router.subscribe(all_signals, name="all")
        router.subscribe(only_critical, name="crit")

        # Simulate watcher producing a critical signal
        sig = Signal.make(
            "calendar",
            "calendar_watcher",
            "u1",
            "Meeting starting now",
            severity="critical",
            body="Standup with team",
            dedupe_key="evt_99:start",
        )
        n = await router.publish(sig)

        assert n == 2
        assert delivered == [sig]
        assert warned == [sig]
        # Queue retains the signal for replay
        assert router.peek("u1") == [sig]
