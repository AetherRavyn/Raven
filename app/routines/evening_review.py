"""Evening review routine — fires once per day per user at a configured hour.

Composes a short end-of-day summary: tasks completed, tasks
still open, follow-up commitments due tomorrow, and one
forward-looking line ("tomorrow you have N pending items").
Routes through the proactive engine when registered, falls
back to direct send otherwise.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.proactive import ProactiveDigest, send_proactive_digest
from app.core.task_ledger import TaskLedger

logger = logging.getLogger(__name__)


DigestBuilder = Callable[[str, datetime], Awaitable[str]]


async def compose_evening_review(
    user_id: str,
    *,
    now: datetime | None = None,
    task_ledger_factory: Callable[[], TaskLedger] | None = None,
) -> str:
    """Build the text for the evening review.

    The composition is deliberately local — no LLM by default.
    The morning-briefing LLM path is opt-in via
    ``set_evening_llm_renderer``.
    """
    moment = now or datetime.now(timezone.utc)
    tomorrow = (moment + timedelta(days=1)).date()

    def _ledger() -> TaskLedger:
        return task_ledger_factory() if task_ledger_factory else TaskLedger()

    open_tasks: list[dict[str, Any]] = []
    try:
        ledger = _ledger()
        # We don't track "completed today" yet; show open and
        # count by type.
        all_open = ledger.list_tasks(status="open")
        open_tasks = all_open
    except Exception as exc:  # noqa: BLE001
        logger.debug("Evening review: ledger read failed: %s", exc)

    pending_count = sum(1 for t in open_tasks if t.get("task_type") in {"task", "runtime"})
    approval_count = sum(1 for t in open_tasks if t.get("task_type") == "approval")

    date_str = moment.strftime("%A, %B %d")
    lines = [
        f"End-of-day check-in for {date_str}.",
        f"You have {pending_count} open task(s) and {approval_count} pending approval(s).",
    ]
    # Don't fabricate calendar data; surface commitments that
    # are due tomorrow.
    try:
        from app.core.proactive_core import FollowUpTracker

        # Use the shared in-memory tracker if one is registered;
        # otherwise we just skip the commitment line.
        tracker: FollowUpTracker | None = None
        try:
            from app.core.proactive_core import get_context

            ctx = get_context(user_id)
            if ctx is not None and hasattr(ctx.engine, "_follow_up"):
                # Engine doesn't currently own a tracker; this is
                # a future seam.  For now: skip.
                tracker = None
        except Exception:  # noqa: BLE001
            tracker = None
        if tracker is None:
            tracker = FollowUpTracker()
        due_today = [
            c
            for c in tracker.list_pending(user_id)
            if c.due_at is not None
            and c.due_at.astimezone(timezone.utc).date() <= tomorrow
        ]
        if due_today:
            lines.append(
                f"{len(due_today)} commitment(s) are due by tomorrow."
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Evening review: commitment lookup failed: %s", exc)

    return "\n".join(lines)


async def _send_via_engine(
    user_id: str, platform: str, chat_id: str
) -> bool:
    """Send the evening review through the proactive engine."""
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
        get_context,
    )

    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False
    text = await compose_evening_review(user_id)
    signal = ProactiveSignal(
        id=f"evening_review:{user_id}:{datetime.now(timezone.utc).date().isoformat()}",
        user_id=user_id,
        kind=SignalKind.ROUTINE,
        title="Evening review",
        body=text,
        urgency=Urgency.LOW,
        value=0.95,
        confidence=0.95,
        interruption_cost=0.1,
        source="evening_review",
        metadata={"target_id": f"evening_review:{user_id}"},
    )
    decision = await ctx.adapter.dispatch(signal)
    logger.info(
        "evening_review: user=%s verdict=%s stage=%s",
        user_id,
        decision.verdict.value,
        decision.stage,
    )
    return True


def register_evening_review(
    scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    *,
    cron_hour: int = 21,
    cron_minute: int = 0,
) -> None:
    """Register the evening review cron job for a user."""
    from app.core.models import ReplyTarget

    async def _fire():
        if await _send_via_engine(user_id, platform, chat_id):
            return
        # Legacy fallback.
        text = await compose_evening_review(user_id)
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        digest = ProactiveDigest(title=text, items=[], source="evening_review")
        await send_proactive_digest(target, digest)

    reminder_id = f"evening_review_{user_id}"
    scheduler._scheduler.add_job(
        _fire,
        trigger="cron",
        id=reminder_id,
        hour=cron_hour,
        minute=cron_minute,
        replace_existing=True,
    )
    logger.info(
        "Evening review registered for user %s at %02d:%02d UTC",
        user_id,
        cron_hour,
        cron_minute,
    )
