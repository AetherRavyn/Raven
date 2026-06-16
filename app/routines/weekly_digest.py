"""Weekly digest routine — fires once per week per user (default Sunday 19:00).

Composes a "week ahead" preview: open task count, commitments
due this week, anomalies observed in the last 7 days, and the
top 3 predicted habits for the week.  Routes through the
proactive engine when registered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.proactive import ProactiveDigest, send_proactive_digest
from app.core.task_ledger import TaskLedger

logger = logging.getLogger(__name__)


async def compose_weekly_digest(
    user_id: str,
    *,
    now: datetime | None = None,
    task_ledger_factory: Callable[[], TaskLedger] | None = None,
    commitment_tracker: Any = None,
    anomaly_detector: Any = None,
    anticipation_engine: Any = None,
) -> str:
    """Build the text for the weekly digest.

    All optional inputs default to "no data" so the routine
    still works in a fresh process.  Tests pass mocks for the
    ones they want to exercise.
    """
    moment = now or datetime.now(timezone.utc)
    week_end = moment + timedelta(days=7)

    lines: list[str] = []
    week_label = moment.strftime("%A, %B %d")
    lines.append(f"Week ahead — starting {week_label}.")

    # 1) Open tasks
    try:
        ledger = task_ledger_factory() if task_ledger_factory else TaskLedger()
        open_count = sum(
            1
            for t in ledger.list_tasks(status="open")
            if t.get("task_type") in {"task", "runtime"}
        )
        lines.append(f"Open tasks: {open_count}.")
    except Exception as exc:  # noqa: BLE001
        logger.debug("weekly_digest: ledger failed: %s", exc)

    # 2) Commitments due this week
    if commitment_tracker is not None:
        try:
            due = [
                c
                for c in commitment_tracker.list_pending(user_id)
                if c.due_at is not None and c.due_at <= week_end
            ]
            if due:
                lines.append(f"{len(due)} commitment(s) due by next {week_end.strftime('%A')}.")
            else:
                lines.append("No commitments due this week.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("weekly_digest: commitment lookup failed: %s", exc)

    # 3) Anomalies in the last 7 days
    if anomaly_detector is not None:
        try:
            from app.core.proactive_core import ObservationKind

            anomalies: list[Any] = []
            for kind in (
                ObservationKind.WORK_HOURS,
                ObservationKind.SPENDING_USD,
            ):
                anomalies.extend(
                    anomaly_detector.detect_all(user_id, kind, window=timedelta(days=7), now=moment)
                )
            if anomalies:
                lines.append(
                    f"{len(anomalies)} pattern shift(s) this week — see the morning briefing for details."
                )
            else:
                lines.append("No pattern shifts this week.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("weekly_digest: anomaly check failed: %s", exc)

    # 4) Predicted habits for the week
    if anticipation_engine is not None:
        try:
            preds = anticipation_engine.predict_for_user(user_id, moment)
            if preds:
                names = ", ".join(p.habit.name for p in preds[:3])
                lines.append(f"Predicted habits this week: {names}.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("weekly_digest: anticipation failed: %s", exc)

    return "\n".join(lines)


async def _send_via_engine(
    user_id: str, platform: str, chat_id: str
) -> bool:
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
        get_context,
    )

    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False
    text = await compose_weekly_digest(user_id)
    signal = ProactiveSignal(
        id=f"weekly_digest:{user_id}:{datetime.now(timezone.utc).date().isoformat()}",
        user_id=user_id,
        kind=SignalKind.ROUTINE,
        title="Weekly digest",
        body=text,
        urgency=Urgency.LOW,
        value=0.9,
        confidence=0.95,
        interruption_cost=0.1,
        source="weekly_digest",
        metadata={"target_id": f"weekly_digest:{user_id}"},
    )
    decision = await ctx.adapter.dispatch(signal)
    logger.info(
        "weekly_digest: user=%s verdict=%s stage=%s",
        user_id,
        decision.verdict.value,
        decision.stage,
    )
    return True


def register_weekly_digest(
    scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    *,
    cron_day_of_week: str = "sun",
    cron_hour: int = 19,
    cron_minute: int = 0,
) -> None:
    """Register the weekly digest cron job for a user.

    ``cron_day_of_week`` uses APScheduler's 3-letter codes
    (``mon``, ``tue``, ``wed``, ``thu``, ``fri``, ``sat``,
    ``sun``).  Default is Sunday evening.

    On a v2 :class:`Scheduler` the same DOW codes are
    supported by the new cron parser, so we pass them
    through unchanged.
    """
    from app.core.scheduling import (
        Scheduler,
    )

    if isinstance(scheduler, Scheduler):
        register_weekly_digest_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            cron_day_of_week=cron_day_of_week,
            cron_hour=cron_hour,
            cron_minute=cron_minute,
        )
        return

    from app.core.models import ReplyTarget

    async def _fire():
        if await _send_via_engine(user_id, platform, chat_id):
            return
        text = await compose_weekly_digest(user_id)
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        digest = ProactiveDigest(title=text, items=[], source="weekly_digest")
        await send_proactive_digest(target, digest)

    reminder_id = f"weekly_digest_{user_id}"
    scheduler._scheduler.add_job(
        _fire,
        trigger="cron",
        id=reminder_id,
        day_of_week=cron_day_of_week,
        hour=cron_hour,
        minute=cron_minute,
        replace_existing=True,
    )
    logger.info(
        "Weekly digest registered for user %s at %s %02d:%02d UTC",
        user_id,
        cron_day_of_week,
        cron_hour,
        cron_minute,
    )


def register_weekly_digest_v2(
    scheduler: "Scheduler",  # noqa: F821 (forward ref under __future__ annotations)
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    cron_day_of_week: str = "sun",
    cron_hour: int = 19,
    cron_minute: int = 0,
    schedule_id: str | None = None,
) -> str:
    """Register the weekly digest on a v2 :class:`Scheduler`."""
    from app.core.scheduling import CronTrigger
    from app.core.models import ReplyTarget

    async def _fire(user_id_arg: str, *, triggered_at, **_: object) -> None:
        if await _send_via_engine(user_id_arg, platform, chat_id):
            return
        text = await compose_weekly_digest(user_id_arg)
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        digest = ProactiveDigest(title=text, items=[], source="weekly_digest")
        await send_proactive_digest(target, digest)

    routine_id = f"weekly_digest::{user_id}"
    scheduler.routine_registry.register_fn(
        routine_id,
        _fire,
        name=f"Weekly digest for {user_id}",
        kind="weekly_digest",
    )
    sched = scheduler.add(
        routine_id,
        CronTrigger(
            expression=f"{cron_minute} {cron_hour} * * {cron_day_of_week}",
        ),
        user_id=user_id,
        schedule_id=schedule_id or f"weekly_digest_{user_id}",
        metadata={"platform": platform, "chat_id": chat_id},
    )
    logger.info(
        "weekly_digest v2 registered: user=%s at %s %02d:%02d schedule_id=%s",
        user_id,
        cron_day_of_week,
        cron_hour,
        cron_minute,
        sched.id,
    )
    return sched.id
