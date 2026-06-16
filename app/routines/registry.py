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
"""

from __future__ import annotations

import logging

from app.core.scheduling import Scheduler

from app.routines.anomaly_digest import register_anomaly_digest_v2
from app.routines.evening_review import register_evening_review_v2
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


__all__ = ["register_default_routines"]
