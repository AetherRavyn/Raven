from __future__ import annotations

import logging
import os
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.botsignal import get_botsignal
from app.core.models import ReplyTarget, SignalPayload
from app.core.scheduler import get_scheduler
from app.settings.config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProactiveDigest:
    title: str
    items: list[str] = field(default_factory=list)
    source: str = "system"

    def render(self) -> str:
        if not self.items:
            return self.title
        return self.title + "\n" + "\n".join(f"- {item}" for item in self.items)


def build_cross_platform_targets() -> list[ReplyTarget]:
    targets: list[ReplyTarget] = []
    raw = os.getenv("MORNING_BRIEFING_USERS", Config.MORNING_BRIEFING_USERS)
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) == 3:
            platform, _user_id, chat_id = parts
            targets.append(ReplyTarget(platform=platform, chat_id=chat_id))
    return targets


def build_follow_up_message(question: str, age_hours: int = 24) -> str:
    return (
        f"Follow-up: you asked about '{question}'. "
        f"I have not seen a confirmation in the last {age_hours} hours."
    )


async def send_proactive_digest(target: ReplyTarget, digest: ProactiveDigest) -> None:
    botsignal = get_botsignal()
    await botsignal.send(
        target,
        SignalPayload(
            text=digest.render(),
            source_kind="proactive",
        ),
    )


def next_daily_run(hour: int, minute: int) -> datetime:
    now = datetime.now(timezone.utc)
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        scheduled += timedelta(days=1)
    return scheduled


def schedule_follow_up(
    *,
    platform: str,
    user_id: str,
    chat_id: str,
    question: str,
    hours: int = 24,
) -> str:
    scheduler = get_scheduler()
    run_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    reminder_id = f"follow_up_{platform}_{user_id}_{digest}"
    scheduler.add_reminder(
        reminder_id=reminder_id,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        message=build_follow_up_message(question, age_hours=hours),
        run_at=run_at,
    )
    return reminder_id
