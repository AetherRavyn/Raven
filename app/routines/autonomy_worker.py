"""Autonomy worker — periodic background autonomy cycle.

Day 22: Adds :class:`AutonomyWorker.generate_signals` and a
:func:`register_autonomy_worker_v2` entry point that wires
the worker to a v2 :class:`Scheduler`.  The legacy
``APScheduler`` path is preserved for backward compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from app.core.autonomy_engine import AutonomyEngine

logger = logging.getLogger(__name__)


class AutonomyWorker:
    """Wraps the :class:`AutonomyEngine` for v2 signal emission.

    The engine itself is unchanged; this class adds a
    :meth:`generate_signals` adapter that runs one cycle and
    packages the outcome as a ``Signal`` so the v2
    scheduler can publish it through the
    :class:`SignalRouter`.  The legacy ``register_*``
    functions call ``engine.execute_cycle`` directly.
    """

    def __init__(self) -> None:
        self.engine = AutonomyEngine()

    async def generate_signals(
        self,
        *,
        user_id: str,
        platform: str,
        chat_id: str,
    ) -> list:
        """Run one autonomy cycle and return :class:`Signal` objects.

        Currently emits a single ``AUTONOMY`` signal that
        summarises the cycle outcome.  Future work can split
        the outcome into per-action signals (e.g. one signal
        per task completed, per suggestion raised, per
        follow-up created).
        """
        from app.core.scheduling import Signal, SignalKind, SignalSeverity

        try:
            outcome = await self.engine.execute_cycle(user_id, platform, chat_id)
        except Exception as exc:
            logger.error("AutonomyWorker cycle failed: %s", exc)
            return [
                Signal.make(
                    kind=SignalKind.AUTONOMY,
                    source="autonomy_worker",
                    user_id=user_id,
                    title="Autonomy cycle failed",
                    severity=SignalSeverity.WARNING,
                    body=str(exc),
                    payload={
                        "kind": "error",
                        "platform": platform,
                        "chat_id": chat_id,
                        "error": str(exc),
                    },
                )
            ]

        actions = 0
        suggestions: list[str] = []
        if isinstance(outcome, dict):
            actions = int(outcome.get("actions", 0) or 0)
            suggestions = list(outcome.get("suggestions", []) or [])

        if actions == 0 and not suggestions:
            return []

        severity = (
            SignalSeverity.NOTICE if actions else SignalSeverity.INFO
        )
        title = (
            f"Autonomy cycle: {actions} action(s)"
            if actions
            else "Autonomy cycle: suggestions"
        )
        body_lines = [f"• {s}" for s in suggestions[:10]] if suggestions else []
        return [
            Signal.make(
                kind=SignalKind.AUTONOMY,
                source="autonomy_worker",
                user_id=user_id,
                title=title,
                severity=severity,
                body="\n".join(body_lines) or None,
                payload={
                    "kind": "cycle_outcome",
                    "actions": actions,
                    "suggestions": suggestions,
                    "platform": platform,
                    "chat_id": chat_id,
                },
            )
        ]


def register_autonomy_worker(
    scheduler, user_id: str, platform: str, chat_id: str, interval_minutes: int = 15
) -> str | None:
    """Register the continuous background autonomy loop.

    Returns the schedule id when registered on a v2
    :class:`~app.core.scheduling.Scheduler`, or ``None`` when
    the legacy APScheduler path is used.
    """
    from app.core.scheduling import Scheduler

    if isinstance(scheduler, Scheduler):
        return register_autonomy_worker_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            interval_minutes=interval_minutes,
        )

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
    return None


def register_autonomy_worker_v2(
    scheduler,
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    interval_minutes: int = 15,
    signal_router: Any = None,
    schedule_id: str | None = None,
) -> str:
    """Register the autonomy worker on a v2 :class:`Scheduler`."""
    from app.core.scheduling import (
        IntervalTrigger,
        Scheduler,
        get_default_signal_router,
    )

    if not isinstance(scheduler, Scheduler):
        raise TypeError(
            "register_autonomy_worker_v2 requires a v2 Scheduler; "
            f"got {type(scheduler).__name__}"
        )

    routine_id = f"autonomy_worker::{user_id}"
    worker = AutonomyWorker()
    router = signal_router or getattr(scheduler, "signal_router", None) or get_default_signal_router()

    async def _fire(uid: str, *args: Any, triggered_at: datetime | None = None, **kwargs: Any) -> list:
        signals = await worker.generate_signals(
            user_id=uid,
            platform=platform,
            chat_id=chat_id,
        )
        for sig in signals:
            await router.publish(sig)
        return signals

    if scheduler.routine_registry.get(routine_id) is None:
        scheduler.routine_registry.register_fn(
            routine_id,
            _fire,
            name="autonomy_worker",
            kind="watcher",
            metadata={
                "user_id": user_id,
                "platform": platform,
                "chat_id": chat_id,
                "interval_minutes": interval_minutes,
            },
        )

    sid = schedule_id or f"autonomy_engine_{user_id}"
    scheduler.add(
        routine_id=routine_id,
        trigger=IntervalTrigger(every=timedelta(minutes=interval_minutes)),
        user_id=user_id,
        schedule_id=sid,
    )
    logger.info(
        "AutonomyWorker v2 registered for user %s every %d minutes (schedule=%s)",
        user_id,
        interval_minutes,
        sid,
    )
    return sid
