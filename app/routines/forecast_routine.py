"""Background routine to periodically run the MiroFish-style ForecastEngine
and the new PredictionOrchestrator for comprehensive predictive intelligence."""

import logging
from apscheduler.triggers.interval import IntervalTrigger

from app.core.forecast import ForecastEngine

logger = logging.getLogger(__name__)


def register_forecast_routine(scheduler, user_id: str, interval_hours: int = 4) -> None:
    """Register the periodic forecast generation for a user."""

    async def _fire():
        # Legacy ForecastEngine cycle
        try:
            engine = ForecastEngine()
            await engine.run_cycle(user_id)
        except Exception as e:
            logger.error(f"Error in background forecast routine: {e}")

        # New PredictionOrchestrator — comprehensive forecasting
        try:
            from app.core.prediction.orchestrator import get_prediction_orchestrator

            orchestrator = get_prediction_orchestrator()
            result = await orchestrator.comprehensive_forecast(horizon_hours=24)
            if result and result.get("status") == "success":
                components = result.get("components", {})
                n_components = sum(1 for v in components.values() if v)
                logger.info(
                    "PredictionOrchestrator: %d forecast components generated for user %s",
                    n_components,
                    user_id,
                )
                # Run scenario analysis for key events
                scenario_result = await orchestrator.run_scenario_analysis(
                    event=f"User {user_id} schedule for next 24 hours"
                )
                if scenario_result and scenario_result.get("status") == "success":
                    scenarios = scenario_result.get("scenarios", [])
                    logger.info(
                        "PredictionOrchestrator: %d scenarios analyzed",
                        len(scenarios),
                    )
        except Exception as e:
            logger.debug(f"PredictionOrchestrator cycle skipped: {e}")

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
