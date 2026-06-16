"""Day 21 — Default routine registration on the v2 scheduler.

Aggregates every built-in routine so the runtime can wire
them up in one call:

    from app.core.scheduling import get_default_scheduler
    from app.routines.registry import register_default_routines

    scheduler = get_default_scheduler()
    register_default_routines(scheduler, user_id, platform, chat_id)

Each routine is registered with a v2 :class:`Trigger` (cron,
time-of-day, interval, event, or one-shot).  The trigger is
exposed via :attr:`Routine.metadata` and via the
:class:`Scheduler.explain` snapshot, so a dashboard can show
*what* is scheduled and *when* it next fires.

Day 22 adds :func:`register_default_signals` which wires
the three watcher routines (``calendar_watcher``,
``internet_watcher``, ``autonomy_worker``) using their v2
``register_*_v2`` entry points.  These run on
:class:`IntervalTrigger` schedules and produce
:class:`~app.core.scheduling.Signal` objects that the
scheduler publishes through its
:class:`~app.core.scheduling.SignalRouter`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.scheduling import Scheduler

from app.routines.anomaly_digest import register_anomaly_digest_v2
from app.routines.autonomy_worker import register_autonomy_worker_v2
from app.routines.calendar_watcher import register_calendar_watcher_v2
from app.routines.evening_review import register_evening_review_v2
from app.routines.internet_watcher import register_internet_watcher_v2
from app.routines.morning_briefing import register_morning_briefing_v2
from app.routines.weekly_digest import register_weekly_digest_v2

logger = logging.getLogger(__name__)


def register_default_routines(
    scheduler: Scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    *,
    morning_hour: int = 8,
    morning_minute: int = 0,
    evening_hour: int = 21,
    evening_minute: int = 0,
    weekly_day: str = "sun",
    weekly_hour: int = 19,
    weekly_minute: int = 0,
    anomaly_hour: int = 9,
    anomaly_minute: int = 30,
) -> dict[str, str]:
    """Register every built-in routine for one user.

    Returns a dict of ``kind -> schedule_id`` for diagnostics.
    """
    schedule_ids: dict[str, str] = {}

    schedule_ids["morning_briefing"] = register_morning_briefing_v2(
        scheduler,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        cron_hour=morning_hour,
        cron_minute=morning_minute,
    )
    schedule_ids["evening_review"] = register_evening_review_v2(
        scheduler,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        cron_hour=evening_hour,
        cron_minute=evening_minute,
    )
    schedule_ids["weekly_digest"] = register_weekly_digest_v2(
        scheduler,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        cron_day_of_week=weekly_day,
        cron_hour=weekly_hour,
        cron_minute=weekly_minute,
    )
    schedule_ids["anomaly_digest"] = register_anomaly_digest_v2(
        scheduler,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        cron_hour=anomaly_hour,
        cron_minute=anomaly_minute,
    )

    logger.info(
        "default routines registered: user=%s count=%d",
        user_id,
        len(schedule_ids),
    )
    return schedule_ids


def register_default_signals(
    scheduler: Scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    *,
    calendar_interval_minutes: int = 5,
    internet_interval_hours: int = 6,
    autonomy_interval_minutes: int = 15,
    signal_router: Any = None,
) -> dict[str, str]:
    """Register the three v2 watcher routines for one user.

    These run on :class:`IntervalTrigger` schedules and emit
    :class:`~app.core.scheduling.Signal` objects through the
    supplied ``signal_router`` (falling back to the
    scheduler's own router, or the process-wide default).

    Returns ``kind -> schedule_id`` for diagnostics.  Skips
    any routine whose registration fails — watchdogs must
    not block boot.
    """
    schedule_ids: dict[str, str] = {}

    for kind, fn, kwargs in (
        (
            "calendar_watcher",
            register_calendar_watcher_v2,
            {"interval_minutes": calendar_interval_minutes},
        ),
        (
            "internet_watcher",
            register_internet_watcher_v2,
            {"interval_hours": internet_interval_hours},
        ),
        (
            "autonomy_worker",
            register_autonomy_worker_v2,
            {"interval_minutes": autonomy_interval_minutes},
        ),
    ):
        try:
            schedule_ids[kind] = fn(
                scheduler,
                user_id=user_id,
                platform=platform,
                chat_id=chat_id,
                signal_router=signal_router,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "register_default_signals: %s failed for user %s: %s",
                kind,
                user_id,
                exc,
            )
            schedule_ids[kind] = ""

    registered = sum(1 for v in schedule_ids.values() if v)
    logger.info(
        "default signals registered: user=%s count=%d/%d",
        user_id,
        registered,
        len(schedule_ids),
    )
    return schedule_ids


__all__ = ["register_default_routines", "register_default_signals"]
