from __future__ import annotations

import logging

from app.core.scheduler import SarasScheduler
from app.routines.morning_briefing import register_morning_briefing
from app.settings.config import Config

logger = logging.getLogger(__name__)


def register_proactive_routines(scheduler: SarasScheduler) -> None:
    if not Config.MORNING_BRIEFING_USERS:
        logger.debug("No MORNING_BRIEFING_USERS configured; proactive routines skipped")
        return

    for entry in Config.MORNING_BRIEFING_USERS.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            platform, uid, cid = parts
            register_morning_briefing(
                scheduler,
                uid,
                platform,
                cid,
                cron_hour=Config.MORNING_BRIEFING_HOUR,
                cron_minute=Config.MORNING_BRIEFING_MINUTE,
            )
