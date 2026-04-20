"""Background routine to periodically run the MiroFish-style ForecastEngine."""

import logging
from apscheduler.triggers.interval import IntervalTrigger

from app.core.forecast import ForecastEngine

logger = logging.getLogger(__name__)


def register_forecast_routine(scheduler, user_id: str, interval_hours: int = 4) -> None:
    """Register the periodic forecast generation for a user."""

    async def _fire():
        try:
            engine = ForecastEngine()
            await engine.run_cycle(user_id)
        except Exception as e:
            logger.error(f"Error in background forecast routine: {e}")

    job_id = f"forecast_engine_{user_id}"

    scheduler._scheduler.add_job(
        _fire,
        trigger=IntervalTrigger(hours=interval_hours),
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "Forecast routine registered for user %s every %d hours",
        user_id,
        interval_hours,
    )
