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
from app.core.scheduling.signal import (
    DedupeCache,
    Signal,
    SignalHandler,
    SignalKind,
    SignalPredicate,
    SignalRouter,
    SignalSeverity,
    generate_signals,
    get_default_signal_router,
    reset_default_signal_router,
    set_default_signal_router,
)
from app.core.scheduling.signal_bridge import (
    ProactiveSignalBridge,
    get_default_proactive_signal_bridge,
    reset_default_proactive_signal_bridge,
    set_default_proactive_signal_bridge,
    signal_to_proactive,
)
from app.core.scheduling.signal_delivery import (
    CHAT_ID_KEY,
    PLATFORM_KEY,
    SignalDeliveryAdapter,
    get_default_signal_delivery_adapter,
    reset_default_signal_delivery_adapter,
    set_default_signal_delivery_adapter,
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
    "CHAT_ID_KEY",
    "ClockFn",
    "CronTrigger",
    "DedupeCache",
    "EventTrigger",
    "FiredSchedule",
    "FireCallback",
    "IntervalTrigger",
    "OneShotTrigger",
    "PLATFORM_KEY",
    "ProactiveSignalBridge",
    "Routine",
    "RoutineFn",
    "RoutineRegistry",
    "Schedule",
    "ScheduleRegistry",
    "Scheduler",
    "Signal",
    "SignalDeliveryAdapter",
    "SignalHandler",
    "SignalKind",
    "SignalPredicate",
    "SignalRouter",
    "SignalSeverity",
    "TimeOfDayTrigger",
    "Trigger",
    "generate_signals",
    "get_default_proactive_signal_bridge",
    "get_default_scheduler",
    "get_default_signal_delivery_adapter",
    "get_default_signal_router",
    "make_schedule_id",
    "reset_default_proactive_signal_bridge",
    "reset_default_scheduler",
    "reset_default_signal_delivery_adapter",
    "reset_default_signal_router",
    "set_default_scheduler",
    "set_default_signal_delivery_adapter",
    "set_default_proactive_signal_bridge",
    "set_default_signal_router",
    "signal_to_proactive",
]
