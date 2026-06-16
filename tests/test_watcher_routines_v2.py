"""Tests for the v2 watcher routines (Day 22).

Exercises the ``generate_signals`` contract and the
``register_*_v2`` entry points for:

* :mod:`app.routines.calendar_watcher`
* :mod:`app.routines.internet_watcher`
* :mod:`app.routines.autonomy_worker`

These tests use a fake Google Calendar tool and a fake
Agent Reach so the watchers can run end-to-end without
external services.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.scheduling import (
    DedupeCache,
    IntervalTrigger,
    Scheduler,
    Signal,
    SignalKind,
    SignalRouter,
    SignalSeverity,
    reset_default_signal_router,
    reset_default_scheduler,
)
from app.routines.autonomy_worker import (
    AutonomyWorker,
    register_autonomy_worker,
    register_autonomy_worker_v2,
)
from app.routines.calendar_watcher import (
    CalendarWatcher,
    register_calendar_watcher,
    register_calendar_watcher_v2,
)
from app.routines.internet_watcher import (
    InternetWatcher,
    register_internet_watcher,
    register_internet_watcher_v2,
)
from app.routines.registry import register_default_signals


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class FakeCalendarTool:
    """Stub :class:`GoogleCalendarTool` that returns canned events."""

    def __init__(self, events: list[dict]) -> None:
        self._events = events
        self.last_call: dict | None = None

    async def execute(self, *, operation: str, **kwargs: object) -> dict:
        self.last_call = {"operation": operation, **kwargs}
        if operation == "list_events":
            return {"success": True, "events": list(self._events)}
        return {"success": False, "error": "unknown operation"}


class FakeReach:
    """Stub :class:`AgentReach` that returns canned discovery results."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results
        self.calls: list[str] = []

    def discover(
        self, *, query: str, limit: int = 3, sources: str = "all"
    ) -> dict:
        self.calls.append(query)
        if not self._results:
            return {"success": False, "error": "no sources"}
        return {"success": True, "summary": "Test summary", "results": self._results}


class FakeAutonomyEngine:
    """Stub :class:`AutonomyEngine` that returns a canned outcome."""

    def __init__(self, outcome: dict | Exception) -> None:
        self._outcome = outcome
        self.calls: list[tuple[str, str, str]] = []

    async def execute_cycle(
        self, user_id: str, platform: str, chat_id: str
    ) -> dict:
        self.calls.append((user_id, platform, chat_id))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    import app.routines.calendar_watcher as cw
    cw._notified_events = set()
    cw._daily_summary_date = ""
    reset_default_scheduler()
    reset_default_signal_router()
    yield
    cw._notified_events = set()
    cw._daily_summary_date = ""
    reset_default_scheduler()
    reset_default_signal_router()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# CalendarWatcher                                                             #
# --------------------------------------------------------------------------- #


def _event(event_id: str, summary: str, minutes_from_now: int) -> dict:
    """Build a fake Google Calendar event dict."""
    start = (_now_utc() + timedelta(minutes=minutes_from_now)).isoformat()
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "location": "Conf Room A",
        "attendees": [{"displayName": "Alice"}, {"email": "bob@x.com"}],
    }


class TestCalendarWatcherV2:
    async def test_generate_signals_15_min_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear the global "first check of day" flag so the test
        # only sees the 15-minute warning.
        import app.routines.calendar_watcher as cw
        cw._daily_summary_date = _now_utc().strftime("%Y-%m-%d")
        w = CalendarWatcher()
        monkeypatch.setattr(w, "_get_calendar_tool", lambda: FakeCalendarTool([_event("e1", "Standup", 12)]))
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        s = sigs[0]
        assert s.kind is SignalKind.CALENDAR
        assert s.severity is SignalSeverity.NOTICE
        assert "Standup" in (s.body or "")
        assert s.payload["event_id"] == "e1"
        assert s.dedupe_key == "e1:15min"

    async def test_generate_signals_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.routines.calendar_watcher as cw
        cw._daily_summary_date = _now_utc().strftime("%Y-%m-%d")
        w = CalendarWatcher()
        monkeypatch.setattr(w, "_get_calendar_tool", lambda: FakeCalendarTool([_event("e1", "Standup", -2)]))
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        s = sigs[0]
        assert s.severity is SignalSeverity.WARNING
        assert "started" in (s.body or "").lower()
        assert s.payload["kind"] == "started"

    async def test_generate_signals_no_tool(self) -> None:
        w = CalendarWatcher()
        w._get_calendar_tool = lambda: None  # type: ignore[assignment]
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert sigs == []

    async def test_generate_signals_dedupes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.routines.calendar_watcher as cw
        cw._daily_summary_date = _now_utc().strftime("%Y-%m-%d")
        w = CalendarWatcher()
        monkeypatch.setattr(w, "_get_calendar_tool", lambda: FakeCalendarTool([_event("e1", "Standup", 12)]))
        cache = DedupeCache()
        first = await w.generate_signals(
            user_id="u1", platform="telegram", chat_id="c1", dedupe_cache=cache,
        )
        second = await w.generate_signals(
            user_id="u1", platform="telegram", chat_id="c1", dedupe_cache=cache,
        )
        assert len(first) == 1
        assert second == []  # dedupe suppressed

    async def test_v2_registration_returns_schedule_id(self) -> None:
        s = Scheduler()
        router = SignalRouter()
        sid = register_calendar_watcher_v2(
            s, user_id="u1", platform="telegram", chat_id="c1",
            signal_router=router,
        )
        assert sid == "calendar_watcher_u1"
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.kind == "interval"
        # Routine is registered
        assert s.routine_registry.get("calendar_watcher::u1") is not None

    async def test_v2_registration_rejects_legacy_scheduler(self) -> None:
        with pytest.raises(TypeError):
            register_calendar_watcher_v2(
                "not a scheduler",  # type: ignore[arg-type]
                user_id="u1", platform="telegram", chat_id="c1",
            )

    async def test_v2_end_to_end_fires_signals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.routines.calendar_watcher as cw
        cw._daily_summary_date = _now_utc().strftime("%Y-%m-%d")
        sched = Scheduler()
        router = SignalRouter()
        received: list[Signal] = []

        async def collect(sig: Signal) -> None:
            received.append(sig)

        router.subscribe(collect)
        register_calendar_watcher_v2(
            sched,
            user_id="u1",
            platform="telegram",
            chat_id="c1",
            signal_router=router,
        )
        # Replace the watcher inside the routine closure so the
        # fake tool is used.  The simpler way is to re-register
        # the routine with our own watcher and our own closure.
        sched.routine_registry.unregister("calendar_watcher::u1")
        watcher = CalendarWatcher()
        monkeypatch.setattr(
            watcher, "_get_calendar_tool", lambda: FakeCalendarTool([_event("e1", "Standup", 12)])
        )
        cache = DedupeCache()

        async def _fire(uid: str, *args: object, triggered_at: datetime | None = None, **kwargs: object) -> list[Signal]:
            sigs = await watcher.generate_signals(
                user_id=uid, platform="telegram", chat_id="c1", dedupe_cache=cache,
            )
            for sig in sigs:
                await router.publish(sig)
            return sigs

        sched.routine_registry.register_fn("calendar_watcher::u1", _fire, name="calendar_watcher", kind="watcher")
        # Force the trigger to fire on the first tick by anchoring
        # it well before the default 5-minute interval.
        sid = sched.schedule_registry.for_user("u1")[0].id
        sched.schedule_registry.get(sid).trigger.anchor = _now_utc() - timedelta(minutes=10)
        fired = sched.tick(now=_now_utc())
        assert len(fired) == 1
        await sched.fire(fired[0].schedule, _now_utc())
        assert len(received) == 1
        assert received[0].kind is SignalKind.CALENDAR

    def test_legacy_register_falls_through_to_v2(self) -> None:
        s = Scheduler()
        result = register_calendar_watcher(s, "u1", "telegram", "c1")
        assert result == "calendar_watcher_u1"
        assert s.schedule_registry.get("calendar_watcher_u1") is not None


# --------------------------------------------------------------------------- #
# InternetWatcher                                                             #
# --------------------------------------------------------------------------- #


class TestInternetWatcherV2:
    async def test_generate_signals_no_topics(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        w = InternetWatcher(workspace_dir=str(tmp_path))
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert sigs == []

    async def test_generate_signals_with_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        w = InternetWatcher(workspace_dir=str(tmp_path))
        # Inject topics via watchlists.json
        (tmp_path / "watchlists.json").write_text(json.dumps({"topics": ["xAI"]}))
        w.reach = FakeReach([{"url": "https://example.com/1"}, {"url": "https://example.com/2"}])
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        s = sigs[0]
        assert s.kind is SignalKind.INTERNET
        assert s.payload["topic"] == "xAI"
        assert s.payload["source_url"] == "https://example.com/1"
        assert s.severity is SignalSeverity.INFO
        # Evidence was appended
        evidence = (tmp_path / "evidence.jsonl").read_text().strip().splitlines()
        assert len(evidence) == 1
        rec = json.loads(evidence[0])
        assert rec["topic_id"] == "xAI"
        assert rec["sentiment"] == "neutral"

    async def test_sentiment_classification(self, tmp_path: Path) -> None:
        w = InternetWatcher(workspace_dir=str(tmp_path))
        (tmp_path / "watchlists.json").write_text(json.dumps({"topics": ["t"]}))
        w.reach = FakeReach([{"url": "u"}])
        w.reach.discover = lambda **kw: {  # type: ignore[assignment]
            "success": True,
            "summary": "Crisis level decline in the market",
            "results": [{"url": "u"}],
        }
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        assert sigs[0].severity is SignalSeverity.WARNING
        assert sigs[0].payload["sentiment"] == "negative"

    async def test_reach_failure_continues(self, tmp_path: Path) -> None:
        w = InternetWatcher(workspace_dir=str(tmp_path))
        (tmp_path / "watchlists.json").write_text(json.dumps({"topics": ["t1", "t2"]}))
        w.reach = FakeReach([])
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert sigs == []

    async def test_v2_registration(self) -> None:
        s = Scheduler()
        router = SignalRouter()
        sid = register_internet_watcher_v2(
            s, user_id="u1", platform="telegram", chat_id="c1",
            signal_router=router, interval_hours=2,
        )
        assert sid == "internet_watcher_u1"
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.kind == "interval"

    def test_legacy_register_falls_through_to_v2(self) -> None:
        s = Scheduler()
        result = register_internet_watcher(s, "u1", "telegram", "c1")
        assert result == "internet_watcher_u1"


# --------------------------------------------------------------------------- #
# AutonomyWorker                                                              #
# --------------------------------------------------------------------------- #


class TestAutonomyWorkerV2:
    async def test_generate_signals_with_actions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = AutonomyWorker()
        monkeypatch.setattr(
            w, "engine", FakeAutonomyEngine(
                {"actions": 2, "suggestions": ["Follow up on task A"]}
            )
        )
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        s = sigs[0]
        assert s.kind is SignalKind.AUTONOMY
        assert s.payload["actions"] == 2
        assert "Follow up" in (s.body or "")

    async def test_generate_signals_no_activity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = AutonomyWorker()
        monkeypatch.setattr(w, "engine", FakeAutonomyEngine({}))
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert sigs == []

    async def test_generate_signals_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = AutonomyWorker()
        monkeypatch.setattr(w, "engine", FakeAutonomyEngine(RuntimeError("boom")))
        sigs = await w.generate_signals(user_id="u1", platform="telegram", chat_id="c1")
        assert len(sigs) == 1
        assert sigs[0].severity is SignalSeverity.WARNING
        assert sigs[0].payload["kind"] == "error"

    async def test_v2_registration(self) -> None:
        s = Scheduler()
        router = SignalRouter()
        sid = register_autonomy_worker_v2(
            s, user_id="u1", platform="telegram", chat_id="c1",
            signal_router=router, interval_minutes=10,
        )
        assert sid == "autonomy_engine_u1"
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.kind == "interval"

    def test_legacy_register_falls_through_to_v2(self) -> None:
        s = Scheduler()
        result = register_autonomy_worker(s, "u1", "telegram", "c1")
        assert result == "autonomy_engine_u1"


# --------------------------------------------------------------------------- #
# register_default_signals                                                    #
# --------------------------------------------------------------------------- #


class TestRegisterDefaultSignals:
    def test_registers_three_schedules(self) -> None:
        s = Scheduler()
        ids = register_default_signals(s, "u1", "telegram", "c1")
        assert set(ids.keys()) == {
            "calendar_watcher", "internet_watcher", "autonomy_worker",
        }
        for kind, sid in ids.items():
            assert sid, f"{kind} not registered"

    def test_per_user_isolation(self) -> None:
        s = Scheduler()
        a = register_default_signals(s, "u1", "telegram", "c1")
        b = register_default_signals(s, "u2", "telegram", "c2")
        assert a["calendar_watcher"] != b["calendar_watcher"]

    def test_custom_intervals(self) -> None:
        s = Scheduler()
        ids = register_default_signals(
            s, "u1", "telegram", "c1",
            calendar_interval_minutes=1,
            internet_interval_hours=1,
            autonomy_interval_minutes=1,
        )
        cal = s.schedule_registry.get(ids["calendar_watcher"])
        assert cal is not None
        assert isinstance(cal.trigger, IntervalTrigger)
        # Trigger fires every 1 minute
        assert cal.trigger.every == timedelta(minutes=1)


# --------------------------------------------------------------------------- #
# Scheduler <-> Signal integration                                            #
# --------------------------------------------------------------------------- #


class TestSchedulerSignalIntegration:
    async def test_fire_publishes_returned_signals(self) -> None:
        sched = Scheduler()
        router = SignalRouter()
        sched.signal_router = router
        received: list[Signal] = []
        router.subscribe(lambda s: asyncio.sleep(0))  # no-op subscriber

        async def collect(sig: Signal) -> None:
            received.append(sig)

        router.subscribe(collect)

        async def producer(uid: str, *args: object, triggered_at: datetime | None = None, **kwargs: object) -> list[Signal]:
            return [Signal.make("calendar", "t", uid, "x")]

        sched.routine_registry.register_fn("r1", producer, name="r1", kind="test")
        # Anchor in the past so the trigger fires on the first tick.
        anchor = _now_utc() - timedelta(minutes=2)
        sched.add(
            "r1",
            IntervalTrigger(every=timedelta(minutes=1), anchor=anchor),
            user_id="u1",
            schedule_id="s1",
        )
        fired = sched.tick(now=_now_utc())
        assert len(fired) == 1
        await sched.fire(fired[0].schedule, _now_utc())
        assert len(received) == 1
        assert received[0].kind is SignalKind.CALENDAR

    async def test_fire_ignores_non_signal_return(self) -> None:
        sched = Scheduler()
        router = SignalRouter()
        sched.signal_router = router

        async def producer(uid: str, *args: object, triggered_at: datetime | None = None, **kwargs: object) -> None:
            return None

        sched.routine_registry.register_fn("r1", producer, name="r1", kind="test")
        anchor = _now_utc() - timedelta(minutes=2)
        sched.add(
            "r1",
            IntervalTrigger(every=timedelta(minutes=1), anchor=anchor),
            user_id="u1",
            schedule_id="s1",
        )
        fired = sched.tick(now=_now_utc())
        assert len(fired) == 1
        # Should not raise
        await sched.fire(fired[0].schedule, _now_utc())
        assert router.queue_size("u1") == 0
