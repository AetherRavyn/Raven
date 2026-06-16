from __future__ import annotations

import logging

from app.core.scheduler import SarasScheduler
from app.routines.anomaly_digest import register_anomaly_digest
from app.routines.evening_review import register_evening_review
from app.routines.forecast_routine import register_forecast_routine
from app.routines.internet_watcher import register_internet_watcher
from app.routines.autonomy_worker import register_autonomy_worker
from app.routines.memory_consolidation import register_memory_consolidator
from app.routines.calendar_watcher import register_calendar_watcher
from app.routines.morning_briefing import register_morning_briefing
from app.routines.registry import register_default_routines
from app.routines.weekly_digest import register_weekly_digest
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

    # Day 21: build a v2 :class:`Scheduler` (one per process) and
    # use it for the new flexible trigger model.  The legacy
    # ``SarasScheduler`` is kept running so the original cron
    # jobs continue to fire even before every routine has been
    # migrated to the v2 path.  When a routine detects the v2
    # scheduler, it takes the v2 path; otherwise it falls back.
    v2_scheduler = _ensure_v2_scheduler(scheduler)

    for entry in Config.MORNING_BRIEFING_USERS.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            platform, uid, cid = parts
            # v2 registration — every built-in routine in one call.
            try:
                register_default_routines(
                    v2_scheduler,
                    uid,
                    platform,
                    cid,
                    morning_hour=Config.MORNING_BRIEFING_HOUR,
                    morning_minute=Config.MORNING_BRIEFING_MINUTE,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("v2 default routines skipped: %s", exc)

            # Legacy registrations (still useful for routines that
            # haven't been ported yet — forecast, internet watcher,
            # autonomy worker, memory consolidator, calendar watcher).
            register_morning_briefing(
                scheduler,
                uid,
                platform,
                cid,
                cron_hour=Config.MORNING_BRIEFING_HOUR,
                cron_minute=Config.MORNING_BRIEFING_MINUTE,
            )
            register_forecast_routine(scheduler, uid, interval_hours=4)
            register_internet_watcher(scheduler, uid, platform, cid, interval_hours=6)
            register_autonomy_worker(scheduler, uid, platform, cid, interval_minutes=15)
            register_memory_consolidator(scheduler, uid, interval_hours=12)
            register_calendar_watcher(scheduler, uid, platform, cid, interval_minutes=5)
            # Phase C3: end-of-day review (default 21:00 UTC)
            try:
                register_evening_review(
                    scheduler, uid, platform, cid, cron_hour=21, cron_minute=0
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("evening_review skipped: %s", exc)
            # Phase C3: weekly digest (Sunday 19:00 UTC)
            try:
                register_weekly_digest(
                    scheduler,
                    uid,
                    platform,
                    cid,
                    cron_day_of_week="sun",
                    cron_hour=19,
                    cron_minute=0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("weekly_digest skipped: %s", exc)
            # Phase C3: anomaly digest (default 09:30 UTC)
            try:
                register_anomaly_digest(
                    scheduler, uid, platform, cid, cron_hour=9, cron_minute=30
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("anomaly_digest skipped: %s", exc)

    # ── Start Sentinel Bridge (HomeSentinel → SARAS) ───────────────
    _start_sentinel_bridge(scheduler)


def _ensure_v2_scheduler(legacy: SarasScheduler) -> Any:
    """Return the v2 :class:`Scheduler` singleton, wiring in the
    legacy ``botsignal`` if available.

    The default fire callback falls back to the legacy
    scheduler's ``botsignal`` so routines that still need
    direct-send get a path.  A no-op callback is used when no
    signal is available.
    """
    from app.core.scheduling import Scheduler, get_default_scheduler

    sched = get_default_scheduler()
    if sched.fire_callback is None:
        # Default fire callback: ask the scheduler's own
        # :meth:`fire` method to call the registered routine.
        sched.fire_callback = sched.fire
    if legacy is not None and getattr(legacy, "_botsignal", None) is not None:
        sched.metadata.setdefault("botsignal", legacy._botsignal)
    return sched


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
