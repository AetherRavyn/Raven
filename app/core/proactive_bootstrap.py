from __future__ import annotations

import logging

from app.core.scheduler import SarasScheduler
from app.routines.morning_briefing import register_morning_briefing
from app.routines.forecast_routine import register_forecast_routine
from app.routines.internet_watcher import register_internet_watcher
from app.routines.autonomy_worker import register_autonomy_worker
from app.routines.memory_consolidation import register_memory_consolidator
from app.routines.calendar_watcher import register_calendar_watcher
from app.settings.config import Config

logger = logging.getLogger(__name__)


def register_proactive_routines(scheduler: SarasScheduler) -> None:
    if not Config.MORNING_BRIEFING_USERS:
        logger.debug("No MORNING_BRIEFING_USERS configured; proactive routines skipped")
        return

    # Phase C1: wire the proactive core so routines can route their
    # output through the should-I-speak decision engine.  This is
    # best-effort — if registration fails (missing dependencies,
    # mis-config), the routines still register and fall back to the
    # legacy direct-send path.
    try:
        from app.core.proactive_core import register_proactive_core

        register_proactive_core(botsignal=scheduler._botsignal)
    except Exception as exc:  # noqa: BLE001
        logger.info("Proactive core bootstrap skipped: %s", exc)

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
            # Register background prediction engine
            register_forecast_routine(scheduler, uid, interval_hours=4)
            # Register internet watcher
            register_internet_watcher(scheduler, uid, platform, cid, interval_hours=6)
            # Register True Autonomy Engine
            register_autonomy_worker(scheduler, uid, platform, cid, interval_minutes=15)
            # Register Memory Consolidator
            register_memory_consolidator(scheduler, uid, interval_hours=12)
            # Register Calendar Watcher (proactive meeting alerts)
            register_calendar_watcher(scheduler, uid, platform, cid, interval_minutes=5)

    # ── Start Sentinel Bridge (HomeSentinel → SARAS) ───────────────
    _start_sentinel_bridge(scheduler)


def _start_sentinel_bridge(scheduler: SarasScheduler) -> None:
    """Initialize the HomeSentinel event bridge if Redis is available."""
    try:
        from app.core.sentinel_bridge import get_sentinel_bridge

        bridge = get_sentinel_bridge()
        bridge._botsignal = scheduler._botsignal

        # Register notification targets from MORNING_BRIEFING_USERS
        if Config.MORNING_BRIEFING_USERS:
            for entry in Config.MORNING_BRIEFING_USERS.split(","):
                parts = entry.strip().split(":")
                if len(parts) == 3:
                    platform, uid, cid = parts
                    bridge.add_notify_target(platform, cid)

        # Try to connect to Redis for live event streaming
        bridge.start(redis_url=Config.REDIS_URL)

        # Register periodic digest flush
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler._scheduler.add_job(
            bridge.flush_digest,
            trigger=IntervalTrigger(minutes=5),
            id="sentinel_digest",
            replace_existing=True,
        )
        logger.info("SentinelBridge registered with periodic digest every 5 minutes")

    except Exception as exc:
        logger.info("SentinelBridge skipped — %s", exc)
