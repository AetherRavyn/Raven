"""Tests for the flexible scheduler (Day 21)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.scheduling import (
    CronTrigger,
    EventTrigger,
    FiredSchedule,
    IntervalTrigger,
    OneShotTrigger,
    Routine,
    RoutineRegistry,
    Schedule,
    ScheduleRegistry,
    Scheduler,
    TimeOfDayTrigger,
)
from app.core.scheduling.trigger import _DOW_NAMES, _parse_cron_field


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, user_id: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(
            {
                "user_id": user_id,
                "args": args,
                "triggered_at": kwargs.get("triggered_at"),
                "kwargs": kwargs,
            }
        )


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


async def _noop() -> None:
    pass


# -------------------------------------------------------------------
# TimeOfDayTrigger
# -------------------------------------------------------------------


class TestTimeOfDayTrigger:
    def test_fires_at_time(self) -> None:
        t = TimeOfDayTrigger(hour=8, minute=0)
        assert t.should_fire(utc(2026, 6, 15, 8, 0), None)

    def test_does_not_fire_other_time(self) -> None:
        t = TimeOfDayTrigger(hour=8, minute=0)
        assert not t.should_fire(utc(2026, 6, 15, 8, 1), None)
        assert not t.should_fire(utc(2026, 6, 15, 7, 59), None)

    def test_idempotent_within_minute(self) -> None:
        t = TimeOfDayTrigger(hour=8, minute=0)
        ts = utc(2026, 6, 15, 8, 0)
        assert t.should_fire(ts, None)
        assert not t.should_fire(ts, ts)

    def test_weekday_filter(self) -> None:
        # Python weekday: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        # Schedule: Tue / Thu / Sat
        t = TimeOfDayTrigger(hour=8, minute=0, weekdays=(1, 3, 5))
        assert not t.should_fire(utc(2026, 6, 15, 8, 0), None)  # Mon
        assert t.should_fire(utc(2026, 6, 16, 8, 0), None)  # Tue
        assert not t.should_fire(utc(2026, 6, 17, 8, 0), None)  # Wed
        assert t.should_fire(utc(2026, 6, 18, 8, 0), None)  # Thu
        assert not t.should_fire(utc(2026, 6, 19, 8, 0), None)  # Fri
        assert t.should_fire(utc(2026, 6, 20, 8, 0), None)  # Sat
        assert not t.should_fire(utc(2026, 6, 21, 8, 0), None)  # Sun

    def test_invalid_hour(self) -> None:
        with pytest.raises(ValueError):
            TimeOfDayTrigger(hour=24)

    def test_invalid_minute(self) -> None:
        with pytest.raises(ValueError):
            TimeOfDayTrigger(minute=60)

    def test_invalid_weekday(self) -> None:
        with pytest.raises(ValueError):
            TimeOfDayTrigger(weekdays=(7,))

    def test_next_fire_after(self) -> None:
        t = TimeOfDayTrigger(hour=8, minute=0)
        assert t.next_fire_after(utc(2026, 6, 15, 8, 0)) == utc(2026, 6, 16, 8, 0)
        assert t.next_fire_after(utc(2026, 6, 15, 8, 1)) == utc(2026, 6, 16, 8, 0)
        assert t.next_fire_after(utc(2026, 6, 15, 7, 59)) == utc(2026, 6, 15, 8, 0)

    def test_to_dict(self) -> None:
        t = TimeOfDayTrigger(hour=8, minute=30, weekdays=(0, 2, 4))
        d = t.to_dict()
        assert d["kind"] == "time_of_day"
        assert d["hour"] == 8
        assert d["weekdays"] == (0, 2, 4)


# -------------------------------------------------------------------
# IntervalTrigger
# -------------------------------------------------------------------


class TestIntervalTrigger:
    def test_fires_after_one_interval_with_anchor(self) -> None:
        anchor = utc(2026, 6, 15, 8, 0)
        t = IntervalTrigger(every=timedelta(hours=1), anchor=anchor)
        assert not t.should_fire(anchor, None)
        assert t.should_fire(anchor + timedelta(hours=1), None)
        assert t.should_fire(anchor + timedelta(hours=2), None)

    def test_no_anchor_never_fires(self) -> None:
        t = IntervalTrigger(every=timedelta(minutes=5))
        assert not t.should_fire(utc(2026, 6, 15, 8, 0), None)

    def test_catch_up(self) -> None:
        anchor = utc(2026, 6, 15, 8, 0)
        t = IntervalTrigger(
            every=timedelta(hours=1), anchor=anchor, catch_up=True
        )
        first = anchor + timedelta(hours=1)
        assert t.should_fire(first + timedelta(hours=5), first)

    def test_invalid_every(self) -> None:
        with pytest.raises(ValueError):
            IntervalTrigger(every=timedelta(seconds=0))
        with pytest.raises(ValueError):
            IntervalTrigger(every=timedelta(seconds=-1))

    def test_next_fire_after(self) -> None:
        t = IntervalTrigger(every=timedelta(hours=1))
        assert t.next_fire_after(utc(2026, 6, 15, 8, 0)) == utc(2026, 6, 15, 9, 0)
        anchor = utc(2026, 6, 15, 8, 0)
        t2 = IntervalTrigger(every=timedelta(hours=1), anchor=anchor)
        assert t2.next_fire_after(utc(2026, 6, 15, 8, 30)) == utc(2026, 6, 15, 9, 0)


# -------------------------------------------------------------------
# CronTrigger
# -------------------------------------------------------------------


class TestCronTrigger:
    def test_daily_9am(self) -> None:
        t = CronTrigger(expression="0 9 * * *")
        assert t.should_fire(utc(2026, 6, 15, 9, 0), None)
        assert not t.should_fire(utc(2026, 6, 15, 9, 1), None)
        assert not t.should_fire(utc(2026, 6, 15, 8, 0), None)

    def test_weekly_sun_19(self) -> None:
        t = CronTrigger(expression="0 19 * * sun")
        assert t.should_fire(utc(2026, 6, 14, 19, 0), None)
        assert not t.should_fire(utc(2026, 6, 15, 19, 0), None)

    def test_weekday_range(self) -> None:
        t = CronTrigger(expression="0 9 * * mon-fri")
        assert t.should_fire(utc(2026, 6, 15, 9, 0), None)
        assert not t.should_fire(utc(2026, 6, 14, 9, 0), None)

    def test_step(self) -> None:
        t = CronTrigger(expression="*/15 * * * *")
        for m in (0, 15, 30, 45):
            assert t.should_fire(utc(2026, 6, 15, 9, m), None)
        assert not t.should_fire(utc(2026, 6, 15, 9, 7), None)

    def test_list(self) -> None:
        t = CronTrigger(expression="0 9,17 * * *")
        assert t.should_fire(utc(2026, 6, 15, 9, 0), None)
        assert t.should_fire(utc(2026, 6, 15, 17, 0), None)
        assert not t.should_fire(utc(2026, 6, 15, 12, 0), None)

    def test_dow_name(self) -> None:
        t = CronTrigger(expression="0 9 * * wednesday")
        assert t.should_fire(utc(2026, 6, 17, 9, 0), None)
        assert not t.should_fire(utc(2026, 6, 16, 9, 0), None)

    def test_idempotent(self) -> None:
        t = CronTrigger(expression="0 9 * * *")
        ts = utc(2026, 6, 15, 9, 0)
        assert t.should_fire(ts, None)
        assert not t.should_fire(ts, ts)

    def test_invalid_expression(self) -> None:
        with pytest.raises(ValueError):
            CronTrigger(expression="0 9 * *")
        with pytest.raises(ValueError):
            CronTrigger(expression="a b c d e")

    def test_next_fire_after(self) -> None:
        t = CronTrigger(expression="0 9 * * *")
        assert t.next_fire_after(utc(2026, 6, 15, 9, 0)) == utc(2026, 6, 16, 9, 0)

    def test_next_fire_after_weekly(self) -> None:
        t = CronTrigger(expression="0 19 * * sun")
        nxt = t.next_fire_after(utc(2026, 6, 15, 19, 0))
        assert nxt == utc(2026, 6, 21, 19, 0)
        assert nxt is not None
        assert nxt.weekday() == 6

    def test_next_fire_after_no_match(self) -> None:
        # Feb 30 doesn't exist — expression can never fire.
        t = CronTrigger(expression="0 0 30 2 *")
        # next_fire_after returns None within its bound.
        nxt = t.next_fire_after(utc(2026, 1, 1, 0, 0))
        assert nxt is None


# -------------------------------------------------------------------
# Parse cron field
# -------------------------------------------------------------------


class TestParseCronField:
    def test_wildcard(self) -> None:
        assert _parse_cron_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}

    def test_exact(self) -> None:
        assert _parse_cron_field("3", 0, 5) == {3}

    def test_range(self) -> None:
        assert _parse_cron_field("1-3", 0, 5) == {1, 2, 3}

    def test_step(self) -> None:
        assert _parse_cron_field("*/2", 0, 5) == {0, 2, 4}

    def test_list(self) -> None:
        assert _parse_cron_field("1,3,5", 0, 5) == {1, 3, 5}

    def test_dow_name(self) -> None:
        assert _parse_cron_field("mon", 0, 6) == {_DOW_NAMES["mon"]}
        assert _parse_cron_field("sun", 0, 6) == {_DOW_NAMES["sun"]}

    def test_combined(self) -> None:
        assert _parse_cron_field("1-3,5", 0, 5) == {1, 2, 3, 5}


# -------------------------------------------------------------------
# EventTrigger
# -------------------------------------------------------------------


class TestEventTrigger:
    def test_matches(self) -> None:
        t = EventTrigger(event_name="calendar_updated")
        assert t.matches("calendar_updated", {})
        assert not t.matches("email_arrived", {})

    def test_payload_filter(self) -> None:
        t = EventTrigger(
            event_name="calendar_updated",
            payload_filter={"user": "u1"},
        )
        assert t.matches("calendar_updated", {"user": "u1", "extra": "x"})
        assert not t.matches("calendar_updated", {"user": "u2"})

    def test_should_fire_is_noop(self) -> None:
        t = EventTrigger(event_name="x")
        assert t.should_fire(utc(2026, 6, 15, 9, 0), None) is False

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            EventTrigger(event_name="")

    def test_next_fire_after_is_none(self) -> None:
        t = EventTrigger(event_name="x")
        assert t.next_fire_after(utc(2026, 6, 15)) is None


# -------------------------------------------------------------------
# OneShotTrigger
# -------------------------------------------------------------------


class TestOneShotTrigger:
    def test_does_not_fire_before(self) -> None:
        t = OneShotTrigger(run_at=utc(2026, 6, 15, 9, 0))
        assert not t.should_fire(utc(2026, 6, 15, 8, 59), None)

    def test_fires_at_run_at(self) -> None:
        t = OneShotTrigger(run_at=utc(2026, 6, 15, 9, 0))
        assert t.should_fire(utc(2026, 6, 15, 9, 0), None)

    def test_does_not_re_fire(self) -> None:
        t = OneShotTrigger(run_at=utc(2026, 6, 15, 9, 0))
        ts = utc(2026, 6, 15, 9, 0)
        assert t.should_fire(ts, None)
        assert not t.should_fire(ts + timedelta(minutes=5), ts)

    def test_naive_datetime_promoted_to_utc(self) -> None:
        t = OneShotTrigger(run_at=datetime(2026, 6, 15, 9, 0))
        assert t.run_at.tzinfo is not None

    def test_next_fire_after(self) -> None:
        t = OneShotTrigger(run_at=utc(2026, 6, 15, 9, 0))
        assert t.next_fire_after(utc(2026, 6, 15, 8, 0)) == utc(2026, 6, 15, 9, 0)
        assert t.next_fire_after(utc(2026, 6, 15, 9, 0)) is None
        assert t.next_fire_after(utc(2026, 6, 15, 10, 0)) is None


# -------------------------------------------------------------------
# Trigger serialisation
# -------------------------------------------------------------------


class TestTriggerSerialize:
    def test_round_trip(self) -> None:
        for t in [
            TimeOfDayTrigger(hour=8, minute=0, weekdays=(0, 2)),
            IntervalTrigger(every=timedelta(hours=1), anchor=utc(2026, 1, 1)),
            CronTrigger(expression="*/15 * * * *"),
            EventTrigger(event_name="x"),
            OneShotTrigger(run_at=utc(2026, 1, 1)),
        ]:
            d = t.to_dict()
            assert d["kind"] == t.kind


# -------------------------------------------------------------------
# ScheduleRegistry
# -------------------------------------------------------------------


class TestScheduleRegistry:
    def test_add_and_get(self) -> None:
        r = ScheduleRegistry()
        sched = Schedule(
            id="s1",
            user_id="u1",
            routine_id="r1",
            trigger=TimeOfDayTrigger(hour=8, minute=0),
        )
        r.add(sched)
        assert r.get("s1") is sched
        assert r.count() == 1

    def test_duplicate_id_rejected(self) -> None:
        r = ScheduleRegistry()
        r.add(Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger()))
        with pytest.raises(ValueError):
            r.add(Schedule(id="s1", user_id="u2", routine_id="r2", trigger=TimeOfDayTrigger()))

    def test_remove(self) -> None:
        r = ScheduleRegistry()
        r.add(Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger()))
        assert r.remove("s1") is True
        assert r.remove("s1") is False

    def test_for_routine(self) -> None:
        r = ScheduleRegistry()
        r.add(Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger()))
        r.add(Schedule(id="s2", user_id="u2", routine_id="r1", trigger=TimeOfDayTrigger()))
        r.add(Schedule(id="s3", user_id="u1", routine_id="r2", trigger=TimeOfDayTrigger()))
        assert len(r.for_routine("r1")) == 2
        assert len(r.for_routine("r2")) == 1
        assert len(r.for_routine("r3")) == 0

    def test_for_user_global(self) -> None:
        r = ScheduleRegistry()
        r.add(Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger()))
        r.add(Schedule(id="s2", user_id="u1", routine_id="r2", trigger=TimeOfDayTrigger()))
        r.add(Schedule(id="s3", user_id="u2", routine_id="r1", trigger=TimeOfDayTrigger()))
        r.add(Schedule(id="s4", user_id="", routine_id="r3", trigger=TimeOfDayTrigger()))
        assert len(r.for_user("u1")) == 3
        assert len(r.for_user("u2")) == 2
        assert len(r.for_user("u3")) == 1

    def test_enabled_filter(self) -> None:
        r = ScheduleRegistry()
        s1 = Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger())
        s2 = Schedule(
            id="s2",
            user_id="u1",
            routine_id="r1",
            trigger=TimeOfDayTrigger(),
            enabled=False,
        )
        r.add(s1)
        r.add(s2)
        assert len(r.enabled()) == 1
        assert r.set_enabled("s2", True) is True
        assert len(r.enabled()) == 2
        assert r.set_enabled("nonexistent", True) is False

    def test_clear(self) -> None:
        r = ScheduleRegistry()
        r.add(Schedule(id="s1", user_id="u1", routine_id="r1", trigger=TimeOfDayTrigger()))
        r.clear()
        assert r.count() == 0

    def test_to_dict_round_trip(self) -> None:
        s = Schedule(
            id="s1",
            user_id="u1",
            routine_id="r1",
            trigger=TimeOfDayTrigger(hour=8, minute=0),
            args=(1, 2),
            kwargs={"k": "v"},
        )
        d = s.to_dict()
        assert d["id"] == "s1"
        assert d["args"] == [1, 2]
        assert d["kwargs"] == {"k": "v"}
        assert d["trigger"]["kind"] == "time_of_day"
        assert d["trigger"]["hour"] == 8

    def test_matches_user(self) -> None:
        global_s = Schedule(id="g", user_id="", routine_id="r", trigger=TimeOfDayTrigger())
        scoped_s = Schedule(id="s", user_id="u1", routine_id="r", trigger=TimeOfDayTrigger())
        assert global_s.matches_user("anyone")
        assert global_s.matches_user(None)
        assert scoped_s.matches_user("u1")
        assert not scoped_s.matches_user("u2")
        assert not scoped_s.matches_user(None)


# -------------------------------------------------------------------
# RoutineRegistry
# -------------------------------------------------------------------


class TestRoutineRegistry:
    def test_register(self) -> None:
        r = RoutineRegistry()
        r.register(Routine(id="r1", name="Routine 1", fn=_noop, kind="general"))
        assert r.get("r1") is not None
        assert r.count() == 1

    def test_register_fn(self) -> None:
        r = RoutineRegistry()
        routine = r.register_fn("r1", _noop, name="X", kind="morning")
        assert routine.id == "r1"
        assert routine.kind == "morning"

    def test_duplicate_rejected(self) -> None:
        r = RoutineRegistry()
        r.register(Routine(id="r1", name="X", fn=_noop))
        with pytest.raises(ValueError):
            r.register(Routine(id="r1", name="Y", fn=_noop))

    def test_unregister(self) -> None:
        r = RoutineRegistry()
        r.register(Routine(id="r1", name="X", fn=_noop))
        assert r.unregister("r1") is True
        assert r.unregister("r1") is False

    def test_clear(self) -> None:
        r = RoutineRegistry()
        r.register(Routine(id="r1", name="X", fn=_noop))
        r.clear()
        assert r.count() == 0


# -------------------------------------------------------------------
# Scheduler.tick
# -------------------------------------------------------------------


class TestSchedulerTick:
    def test_add_and_remove(self) -> None:
        s = Scheduler()
        sched = s.add("r1", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        assert s.schedule_registry.count() == 1
        assert s.remove(sched.id) is True
        assert s.schedule_registry.count() == 0

    def test_tick_fires_time_of_day(self) -> None:
        s = Scheduler()
        s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        fired = s.tick(now=utc(2026, 6, 15, 8, 0))
        assert len(fired) == 1
        assert fired[0].routine_id == "morning"

    def test_tick_no_fire(self) -> None:
        s = Scheduler()
        s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        assert s.tick(now=utc(2026, 6, 15, 7, 59)) == []

    def test_tick_idempotent(self) -> None:
        s = Scheduler()
        s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        assert len(s.tick(now=utc(2026, 6, 15, 8, 0))) == 1
        assert s.tick(now=utc(2026, 6, 15, 8, 0)) == []

    def test_tick_interval(self) -> None:
        s = Scheduler()
        anchor = utc(2026, 6, 15, 8, 0)
        s.add("poll", IntervalTrigger(every=timedelta(hours=1), anchor=anchor), user_id="u1")
        assert s.tick(now=anchor) == []
        assert len(s.tick(now=anchor + timedelta(hours=1))) == 1
        assert len(s.tick(now=anchor + timedelta(hours=2))) == 1

    def test_tick_cron(self) -> None:
        s = Scheduler()
        s.add("weekly", CronTrigger(expression="0 19 * * sun"), user_id="u1")
        assert len(s.tick(now=utc(2026, 6, 14, 19, 0))) == 1
        assert s.tick(now=utc(2026, 6, 15, 19, 0)) == []

    def test_tick_event(self) -> None:
        s = Scheduler()
        s.add("on_cal", EventTrigger(event_name="calendar_updated"), user_id="u1")
        assert s.tick(now=utc(2026, 6, 15, 9, 0)) == []
        s.fire_event("calendar_updated", {"user": "u1"})
        fired = s.tick(now=utc(2026, 6, 15, 9, 0))
        assert len(fired) == 1
        assert s.tick(now=utc(2026, 6, 15, 9, 0)) == []

    def test_tick_event_with_filter(self) -> None:
        s = Scheduler()
        s.add(
            "on_cal",
            EventTrigger(event_name="calendar_updated", payload_filter={"user": "u1"}),
            user_id="u1",
        )
        s.fire_event("calendar_updated", {"user": "u2"})
        assert s.tick(now=utc(2026, 6, 15, 9, 0)) == []
        s.fire_event("calendar_updated", {"user": "u1"})
        assert len(s.tick(now=utc(2026, 6, 15, 9, 0))) == 1

    def test_tick_one_shot_disables_after_fire(self) -> None:
        s = Scheduler()
        sched = s.add("remind", OneShotTrigger(run_at=utc(2026, 6, 15, 9, 0)), user_id="u1")
        assert sched.enabled
        assert len(s.tick(now=utc(2026, 6, 15, 8, 59))) == 0
        assert len(s.tick(now=utc(2026, 6, 15, 9, 0))) == 1
        assert sched.enabled is False
        assert s.tick(now=utc(2026, 6, 15, 9, 0)) == []

    def test_tick_updates_fire_count(self) -> None:
        s = Scheduler()
        anchor = utc(2026, 6, 15, 8, 0)
        sched = s.add("poll", IntervalTrigger(every=timedelta(hours=1), anchor=anchor), user_id="u1")
        s.tick(now=anchor + timedelta(hours=1))
        s.tick(now=anchor + timedelta(hours=2))
        s.tick(now=anchor + timedelta(hours=3))
        assert sched.fire_count == 3

    def test_tick_disabled_skipped(self) -> None:
        s = Scheduler()
        sched = s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        s.disable(sched.id)
        assert s.tick(now=utc(2026, 6, 15, 8, 0)) == []

    def test_tick_multiple_schedules(self) -> None:
        s = Scheduler()
        s.add("a", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        s.add("b", TimeOfDayTrigger(hour=8, minute=0), user_id="u2")
        s.add("c", TimeOfDayTrigger(hour=9, minute=0), user_id="u1")
        fired = s.tick(now=utc(2026, 6, 15, 8, 0))
        assert len(fired) == 2
        assert {f.routine_id for f in fired} == {"a", "b"}

    def test_tick_naive_datetime_promoted(self) -> None:
        s = Scheduler()
        s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        fired = s.tick(now=datetime(2026, 6, 15, 8, 0))
        assert len(fired) == 1

    def test_tick_uses_clock(self) -> None:
        s = Scheduler()
        called: list[bool] = []

        def clock() -> datetime:
            called.append(True)
            return utc(2026, 6, 15, 8, 0)

        s.clock = clock
        s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        fired = s.tick()
        assert called
        assert len(fired) == 1

    def test_enable_disable(self) -> None:
        s = Scheduler()
        sched = s.add("morning", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        s.disable(sched.id)
        got = s.schedule_registry.get(sched.id)
        assert got is not None
        assert got.enabled is False
        s.enable(sched.id)
        got2 = s.schedule_registry.get(sched.id)
        assert got2 is not None
        assert got2.enabled is True


# -------------------------------------------------------------------
# Scheduler.fire
# -------------------------------------------------------------------


class TestSchedulerFire:
    def test_fire_invokes_routine(self) -> None:
        s = Scheduler()
        rec = Recorder()
        s.routine_registry.register_fn("r1", rec, kind="test")
        sched = s.add("r1", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        asyncio.run(s.fire(sched, utc(2026, 6, 15, 8, 0)))
        assert len(rec.calls) == 1
        assert rec.calls[0]["user_id"] == "u1"
        assert rec.calls[0]["kwargs"]["triggered_at"] == utc(2026, 6, 15, 8, 0)

    def test_fire_unknown_routine_no_op(self) -> None:
        s = Scheduler()
        sched = s.add("nonexistent", TimeOfDayTrigger(hour=8, minute=0))
        asyncio.run(s.fire(sched, utc(2026, 6, 15, 8, 0)))

    def test_fire_routine_raises_logged(self) -> None:
        s = Scheduler()

        async def bad(user_id: str, **kwargs: Any) -> None:
            raise RuntimeError("boom")

        s.routine_registry.register_fn("bad", bad)
        sched = s.add("bad", TimeOfDayTrigger(hour=8, minute=0))
        asyncio.run(s.fire(sched, utc(2026, 6, 15, 8, 0)))


# -------------------------------------------------------------------
# Scheduler.run_forever
# -------------------------------------------------------------------


class TestSchedulerRunForever:
    def test_loop_fires_callbacks(self) -> None:
        s = Scheduler()
        # Use IntervalTrigger so the loop fires repeatedly
        # without idempotency interfering.
        now_box = [utc(2026, 6, 15, 8, 0)]
        s.clock = lambda: now_box[0]
        s.routine_registry.register_fn("r1", Recorder())
        s.add(
            "r1",
            IntervalTrigger(
                every=timedelta(milliseconds=10),
                anchor=utc(2026, 6, 15, 8, 0),
            ),
            user_id="u1",
        )

        fired_log: list[FiredSchedule] = []

        async def cb(sched: Schedule, ts: datetime) -> None:
            fired_log.append(FiredSchedule(schedule=sched, triggered_at=ts))

        s.fire_callback = cb

        async def main() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(s.run_forever(poll_interval=0.01, stop=stop))
            # Advance the clock in the background.
            for _ in range(3):
                await asyncio.sleep(0.02)
                now_box[0] = now_box[0] + timedelta(milliseconds=20)
            stop.set()
            await task

        asyncio.run(main())
        assert len(fired_log) >= 1

    def test_loop_handles_callback_exception(self) -> None:
        s = Scheduler()
        now_box = [utc(2026, 6, 15, 8, 0)]
        s.clock = lambda: now_box[0]
        s.routine_registry.register_fn("r1", Recorder())
        s.add("r1", TimeOfDayTrigger(hour=8, minute=0))

        async def bad_cb(sched: Schedule, ts: datetime) -> None:
            raise RuntimeError("boom")

        s.fire_callback = bad_cb

        async def main() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(s.run_forever(poll_interval=0.01, stop=stop))
            await asyncio.sleep(0.05)
            stop.set()
            await task

        asyncio.run(main())


# -------------------------------------------------------------------
# Scheduler.explain
# -------------------------------------------------------------------


class TestSchedulerExplain:
    def test_explain(self) -> None:
        s = Scheduler()
        s.routine_registry.register_fn("r1", Recorder(), kind="morning")
        s.add("r1", TimeOfDayTrigger(hour=8, minute=0), user_id="u1")
        s.fire_event("test_event", {"k": "v"})
        out = s.explain()
        assert len(out["schedules"]) == 1
        assert out["schedules"][0]["trigger"]["kind"] == "time_of_day"
        assert len(out["routines"]) == 1
        assert out["routines"][0]["kind"] == "morning"
        assert out["pending_events"] == [("test_event", {"k": "v"})]


# -------------------------------------------------------------------
# Event queue
# -------------------------------------------------------------------


class TestEventQueue:
    def test_fire_event_returns_count(self) -> None:
        s = Scheduler()
        assert s.fire_event("x") == 1
        assert s.fire_event("y") == 2

    def test_drain_events(self) -> None:
        s = Scheduler()
        s.fire_event("a", {"k": 1})
        s.fire_event("b", {"k": 2})
        events = s.drain_events()
        assert events == [("a", {"k": 1}), ("b", {"k": 2})]
        assert s.pending_events == []
