"""Tests for the v2 routine registry (Day 21)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

from app.core.scheduling import Scheduler, get_default_scheduler, reset_default_scheduler
from app.routines.anomaly_digest import register_anomaly_digest_v2
from app.routines.evening_review import register_evening_review_v2
from app.routines.morning_briefing import register_morning_briefing_v2
from app.routines.registry import register_default_routines
from app.routines.weekly_digest import register_weekly_digest_v2


def utc(y: int, m: int, d: int, h: int = 0, mn: int = 0) -> datetime:
    return datetime(y, m, d, h, mn, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_scheduler_singleton() -> Iterator[None]:
    reset_default_scheduler()
    yield
    reset_default_scheduler()


class TestV2RoutineRegistration:
    def test_morning_briefing_v2(self) -> None:
        s = Scheduler()
        sid = register_morning_briefing_v2(
            s, user_id="u1", platform="telegram", chat_id="c1"
        )
        assert sid == "morning_briefing_u1"
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.routine_id == "morning_briefing::u1"
        assert sched.trigger.kind == "cron"
        assert sched.trigger.to_dict()["expression"] == "0 8 * * *"
        # Routine is registered
        assert s.routine_registry.get("morning_briefing::u1") is not None

    def test_evening_review_v2(self) -> None:
        s = Scheduler()
        sid = register_evening_review_v2(
            s, user_id="u1", platform="telegram", chat_id="c1"
        )
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.to_dict()["expression"] == "0 21 * * *"

    def test_weekly_digest_v2(self) -> None:
        s = Scheduler()
        sid = register_weekly_digest_v2(
            s, user_id="u1", platform="telegram", chat_id="c1"
        )
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.to_dict()["expression"] == "0 19 * * sun"

    def test_anomaly_digest_v2(self) -> None:
        s = Scheduler()
        sid = register_anomaly_digest_v2(
            s, user_id="u1", platform="telegram", chat_id="c1"
        )
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.to_dict()["expression"] == "30 9 * * *"

    def test_custom_time(self) -> None:
        s = Scheduler()
        sid = register_morning_briefing_v2(
            s,
            user_id="u1",
            platform="telegram",
            chat_id="c1",
            cron_hour=7,
            cron_minute=30,
        )
        sched = s.schedule_registry.get(sid)
        assert sched is not None
        assert sched.trigger.to_dict()["expression"] == "30 7 * * *"

    def test_custom_schedule_id(self) -> None:
        s = Scheduler()
        sid = register_morning_briefing_v2(
            s,
            user_id="u1",
            platform="telegram",
            chat_id="c1",
            schedule_id="custom_id",
        )
        assert sid == "custom_id"

    def test_metadata_carried(self) -> None:
        s = Scheduler()
        register_morning_briefing_v2(
            s, user_id="u1", platform="telegram", chat_id="c1"
        )
        sched = s.schedule_registry.get("morning_briefing_u1")
        assert sched is not None
        assert sched.metadata["platform"] == "telegram"
        assert sched.metadata["chat_id"] == "c1"


class TestDefaultRoutines:
    def test_register_all_four(self) -> None:
        s = Scheduler()
        ids = register_default_routines(s, "u1", "telegram", "c1")
        assert set(ids.keys()) == {
            "morning_briefing",
            "evening_review",
            "weekly_digest",
            "anomaly_digest",
        }
        assert s.schedule_registry.count() == 4
        assert s.routine_registry.count() == 4

    def test_custom_times(self) -> None:
        s = Scheduler()
        ids = register_default_routines(
            s, "u1", "telegram", "c1",
            morning_hour=6, evening_hour=22, anomaly_hour=8, anomaly_minute=15,
        )
        morning = s.schedule_registry.get(ids["morning_briefing"])
        assert morning is not None
        assert morning.trigger.to_dict()["expression"] == "0 6 * * *"
        evening = s.schedule_registry.get(ids["evening_review"])
        assert evening is not None
        assert evening.trigger.to_dict()["expression"] == "0 22 * * *"
        anomaly = s.schedule_registry.get(ids["anomaly_digest"])
        assert anomaly is not None
        assert anomaly.trigger.to_dict()["expression"] == "15 8 * * *"

    def test_per_user_isolation(self) -> None:
        s = Scheduler()
        register_default_routines(s, "u1", "telegram", "c1")
        register_default_routines(s, "u2", "telegram", "c2")
        assert s.schedule_registry.count() == 8
        u1 = s.schedule_registry.for_user("u1")
        u2 = s.schedule_registry.for_user("u2")
        assert len(u1) == 4
        assert len(u2) == 4


class TestSingleton:
    def test_default_scheduler_singleton(self) -> None:
        a = get_default_scheduler()
        b = get_default_scheduler()
        assert a is b

    def test_reset_clears(self) -> None:
        a = get_default_scheduler()
        reset_default_scheduler()
        b = get_default_scheduler()
        assert a is not b


class TestRoutineFireDispatch:
    """Verify that a registered v2 routine is called when the
    scheduler fires its schedule.  Uses a fake routine to avoid
    the heavy LLM / proactive-core dependency chain."""

    def test_fire_calls_routine(self) -> None:
        from app.core.scheduling import CronTrigger

        s = Scheduler()
        calls: list[tuple[str, datetime]] = []

        async def my_routine(user_id: str, *, triggered_at, **_: object) -> None:
            calls.append((user_id, triggered_at))

        s.routine_registry.register_fn("test_routine", my_routine, kind="test")
        s.add(
            "test_routine",
            CronTrigger(expression="0 9 * * *"),
            user_id="u1",
        )

        # Use the default fire callback to dispatch.
        s.fire_callback = s.fire
        fired = s.tick(now=utc(2026, 6, 15, 9, 0))
        assert len(fired) == 1

        # Drive the fire callback manually.
        import asyncio

        asyncio.run(s.fire(fired[0].schedule, fired[0].triggered_at))
        assert len(calls) == 1
        assert calls[0][0] == "u1"
        assert calls[0][1] == utc(2026, 6, 15, 9, 0)

    def test_explain_snapshot(self) -> None:
        from app.core.scheduling import CronTrigger

        s = Scheduler()

        async def dummy(user_id: str, **_: object) -> None:
            pass

        s.routine_registry.register_fn("r1", dummy)
        s.add("r1", CronTrigger(expression="*/15 * * * *"))
        out = s.explain()
        assert len(out["schedules"]) == 1
        assert out["schedules"][0]["trigger"]["kind"] == "cron"
        assert out["schedules"][0]["trigger"]["expression"] == "*/15 * * * *"
