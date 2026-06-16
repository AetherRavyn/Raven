"""Phase F — Flexible scheduling (Day 21).

A scheduler that supports multiple trigger types:

* :class:`TimeOfDayTrigger` — daily at HH:MM, optional weekdays
* :class:`IntervalTrigger` — every N seconds/minutes/hours
* :class:`CronTrigger` — full 5-field cron expression
* :class:`EventTrigger` — fires on explicit events
* :class:`OneShotTrigger` — fire once at a specific datetime

The :class:`Scheduler` ties triggers + routines together:

    from app.core.scheduling import (
        Scheduler, RoutineRegistry, ScheduleRegistry,
        TimeOfDayTrigger, IntervalTrigger, CronTrigger,
        EventTrigger, OneShotTrigger,
    )

    sched = Scheduler()
    sched.routine_registry.register_fn("morning", morning_briefing)
    sched.add(
        "morning",
        TimeOfDayTrigger(hour=8, minute=0),
        user_id="u1",
    )

    # Pure evaluation (great for tests):
    fired = sched.tick(now=datetime.now(timezone.utc))

    # Or the async loop:
    asyncio.run(sched.run_forever(poll_interval=1.0))
"""

from __future__ import annotations

from app.core.scheduling.registry import (
    Schedule,
    ScheduleRegistry,
    make_schedule_id,
)
from app.core.scheduling.routine import Routine, RoutineFn, RoutineRegistry
from app.core.scheduling.scheduler import (
    ClockFn,
    FiredSchedule,
    FireCallback,
    Scheduler,
    get_default_scheduler,
    reset_default_scheduler,
    set_default_scheduler,
)
from app.core.scheduling.trigger import (
    CronTrigger,
    EventTrigger,
    IntervalTrigger,
    OneShotTrigger,
    TimeOfDayTrigger,
    Trigger,
)

__all__ = [
    "ClockFn",
    "CronTrigger",
    "EventTrigger",
    "FiredSchedule",
    "FireCallback",
    "IntervalTrigger",
    "OneShotTrigger",
    "Routine",
    "RoutineFn",
    "RoutineRegistry",
    "Schedule",
    "ScheduleRegistry",
    "Scheduler",
    "TimeOfDayTrigger",
    "Trigger",
    "get_default_scheduler",
    "make_schedule_id",
    "reset_default_scheduler",
    "set_default_scheduler",
]
