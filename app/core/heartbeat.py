from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.botsignal import get_botsignal
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.core.scheduler import get_scheduler
from app.core.models import ReplyTarget, SignalPayload

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HeartbeatPlan:
    user_id: str
    platform: str
    chat_id: str
    interval_minutes: int = 30
    enabled: bool = True


class HeartbeatRunner:
    """Periodic main-session check that batches inbox, reminders, and follow-ups."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.inbox = TaskInboxStore(workspace_dir)
        self.ledger = TaskLedger(workspace_dir)

    async def run_once(
        self, user_id: str, platform: str, chat_id: str
    ) -> dict[str, Any]:
        botsignal = get_botsignal()
        scheduler = get_scheduler()
        open_items = self.inbox.list_items(user_id=user_id)
        pending_tasks = self.ledger.list_tasks(status="open")
        reminders = scheduler.list_reminders()

        lines = ["Heartbeat check:"]
        lines.append(f"- inbox items: {len(open_items)}")
        lines.append(f"- open tasks: {len(pending_tasks)}")
        lines.append(f"- reminders: {len(reminders)}")

        target = ReplyTarget(platform=platform, chat_id=chat_id)
        await botsignal.send(
            target, SignalPayload(text="\n".join(lines), source_kind="heartbeat")
        )

        return {
            "inbox_items": len(open_items),
            "open_tasks": len(pending_tasks),
            "reminders": len(reminders),
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }

    def schedule(self, plan: HeartbeatPlan) -> str:
        scheduler = get_scheduler()
        job_id = f"heartbeat_{plan.platform}_{plan.user_id}"

        async def _fire() -> None:
            await self.run_once(plan.user_id, plan.platform, plan.chat_id)

        from apscheduler.triggers.interval import IntervalTrigger

        scheduler._scheduler.add_job(
            _fire,
            trigger=IntervalTrigger(minutes=plan.interval_minutes),
            id=job_id,
            replace_existing=True,
        )
        logger.info(
            "Heartbeat scheduled: %s every %s minutes", job_id, plan.interval_minutes
        )
        return job_id
