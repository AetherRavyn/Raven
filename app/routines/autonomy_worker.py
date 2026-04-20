import logging
import asyncio
from apscheduler.triggers.interval import IntervalTrigger

from app.core.autonomy_engine import AutonomyEngine

logger = logging.getLogger(__name__)

def register_autonomy_worker(
    scheduler, user_id: str, platform: str, chat_id: str, interval_minutes: int = 15
) -> None:
    """Register the continuous background autonomy loop."""

    async def _fire():
        try:
            engine = AutonomyEngine()
            await engine.execute_cycle(user_id, platform, chat_id)
        except Exception as e:
            logger.error(f"Error in autonomy engine routine: {e}")

    job_id = f"autonomy_engine_{user_id}"

    scheduler._scheduler.add_job(
        _fire,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "Autonomy engine registered for user %s every %d minutes",
        user_id,
        interval_minutes,
    )
