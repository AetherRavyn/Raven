"""Anomaly digest routine — fires periodically to surface pattern shifts.

Runs the configured :class:`AnomalyDetector` against the user's
recent observations and surfaces any hits through the proactive
engine.  Silently does nothing if no anomalies are found or no
detector is wired up.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.proactive import ProactiveDigest, send_proactive_digest
from app.core.proactive_core import (
    ObservationKind,
    anomaly_to_signal,
    generate_signals,
    get_context,
)

logger = logging.getLogger(__name__)


async def compose_anomaly_digest(
    user_id: str,
    *,
    detector: Any = None,
    now: datetime | None = None,
    window: timedelta | None = None,
    kinds: Iterable[ObservationKind] | None = None,
) -> tuple[str, list[Any]]:
    """Return ``(text, anomalies)``.

    ``text`` is the user-facing summary; ``anomalies`` is the
    raw list for callers that want to route signals themselves.
    """
    moment = now or datetime.now(timezone.utc)
    win = window or timedelta(days=1)

    if detector is None:
        return "No anomaly detector wired up.", []

    check_kinds = list(
        kinds
        or (
            ObservationKind.WORK_HOURS,
            ObservationKind.SPENDING_USD,
            ObservationKind.EMAIL_REPLY_LATENCY_S,
        )
    )

    anomalies: list[Any] = []
    for kind in check_kinds:
        try:
            anomalies.extend(
                detector.detect_all(user_id, kind, window=win, now=moment)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("anomaly_digest: detect %s failed: %s", kind, exc)

    if not anomalies:
        return "No anomalies in the last period.", []

    lines = [f"{len(anomalies)} pattern shift(s) detected:"]
    for a in anomalies[:5]:
        lines.append(f"  - {a.message}")
    return "\n".join(lines), anomalies


async def _send_via_engine(
    user_id: str, platform: str, chat_id: str
) -> bool:
    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False

    detector = getattr(ctx.engine, "anomaly_detector", None)
    text, anomalies = await compose_anomaly_digest(user_id, detector=detector)
    if not anomalies:
        return True  # nothing to do, but the engine was reachable

    # Build signals from anomalies and dispatch each.
    from app.core.proactive_core import ProactiveSignal

    signals: list[ProactiveSignal] = [anomaly_to_signal(a) for a in anomalies]
    for sig in signals:
        decision = await ctx.adapter.dispatch(sig)
        logger.info(
            "anomaly_digest: user=%s sig_id=%s verdict=%s",
            user_id,
            sig.id,
            decision.verdict.value,
        )
    return True


def register_anomaly_digest(
    scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    *,
    cron_hour: int = 9,
    cron_minute: int = 30,
) -> None:
    """Register the anomaly-digest cron job for a user (default 09:30 daily)."""
    from app.core.scheduling import (
        CronTrigger,
        Scheduler,
    )

    if isinstance(scheduler, Scheduler):
        register_anomaly_digest_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            cron_hour=cron_hour,
            cron_minute=cron_minute,
        )
        return

    from app.core.models import ReplyTarget

    async def _fire():
        if await _send_via_engine(user_id, platform, chat_id):
            return
        # Legacy fallback: detect + send text.
        from app.core.proactive_core import AnomalyDetector

        text, _ = await compose_anomaly_digest(
            user_id, detector=AnomalyDetector()
        )
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        digest = ProactiveDigest(title=text, items=[], source="anomaly_digest")
        await send_proactive_digest(target, digest)

    reminder_id = f"anomaly_digest_{user_id}"
    scheduler._scheduler.add_job(
        _fire,
        trigger="cron",
        id=reminder_id,
        hour=cron_hour,
        minute=cron_minute,
        replace_existing=True,
    )
    logger.info(
        "Anomaly digest registered for user %s at %02d:%02d UTC",
        user_id,
        cron_hour,
        cron_minute,
    )


def register_anomaly_digest_v2(
    scheduler: "Scheduler",
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    cron_hour: int = 9,
    cron_minute: int = 30,
    schedule_id: str | None = None,
) -> str:
    """Register the anomaly digest on a v2 :class:`Scheduler`."""
    from app.core.scheduling import CronTrigger
    from app.core.models import ReplyTarget

    async def _fire(user_id_arg: str, *, triggered_at, **_: object) -> None:
        if await _send_via_engine(user_id_arg, platform, chat_id):
            return
        from app.core.proactive_core import AnomalyDetector

        text, _ = await compose_anomaly_digest(
            user_id_arg, detector=AnomalyDetector()
        )
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        digest = ProactiveDigest(title=text, items=[], source="anomaly_digest")
        await send_proactive_digest(target, digest)

    routine_id = f"anomaly_digest::{user_id}"
    scheduler.routine_registry.register_fn(
        routine_id,
        _fire,
        name=f"Anomaly digest for {user_id}",
        kind="anomaly_digest",
    )
    sched = scheduler.add(
        routine_id,
        CronTrigger(expression=f"{cron_minute} {cron_hour} * * *"),
        user_id=user_id,
        schedule_id=schedule_id or f"anomaly_digest_{user_id}",
        metadata={"platform": platform, "chat_id": chat_id},
    )
    logger.info(
        "anomaly_digest v2 registered: user=%s at %02d:%02d schedule_id=%s",
        user_id,
        cron_hour,
        cron_minute,
        sched.id,
    )
    return sched.id


# ---------------------------------------------------------------------------
# generate_signals helper (re-export) so callers can use the
# full multi-source path if they have a tracker and an
# anticipation engine wired up.
# ---------------------------------------------------------------------------

__all__ = [
    "compose_anomaly_digest",
    "register_anomaly_digest",
    "generate_signals",
]
