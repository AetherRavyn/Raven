# app/tools/remindertool.py
"""ReminderTool — lets the LLM set, list, and cancel reminders."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class ReminderTool(BaseTool):
    def get_name(self) -> str:
        return "manage_reminder"

    def get_description(self) -> str:
        return (
            "Set, list, or cancel reminders and alarms. "
            "action=set: schedule a one-time or recurring reminder. "
            "action=list: show all pending reminders. "
            "action=cancel: cancel a reminder by id."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="set | list | cancel",
                    required=True,
                    enum=["set", "list", "cancel"],
                ),
                ToolParameter(
                    name="message",
                    type="string",
                    description="Reminder message text (required for action=set).",
                    required=False,
                ),
                ToolParameter(
                    name="when",
                    type="string",
                    description=(
                        "ISO 8601 datetime string for one-shot reminders, e.g. '2026-03-02T09:00:00Z'. "
                        "Or a cron expression for recurring (5 fields): '0 8 * * *' = 8am daily."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="reminder_id",
                    type="string",
                    description="Reminder ID to cancel (required for action=cancel).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict:
        from app.core.scheduler import get_scheduler

        action = kwargs.get("action")
        message = kwargs.get("message", "")
        when = kwargs.get("when", "")
        reminder_id = kwargs.get("reminder_id", "")
        request = kwargs.get("_request")  # IncomingRequest from AgentRuntime

        scheduler = get_scheduler()

        if action == "list":
            jobs = scheduler.list_reminders()
            if not jobs:
                return {
                    "success": True,
                    "reminders": [],
                    "message": "No pending reminders.",
                }
            return {"success": True, "reminders": jobs}

        if action == "cancel":
            if not reminder_id:
                return {"success": False, "error": "reminder_id required for cancel"}
            ok = scheduler.cancel_reminder(reminder_id)
            return {
                "success": ok,
                "message": "Cancelled." if ok else "Reminder not found.",
            }

        if action == "set":
            if not message:
                return {"success": False, "error": "message required for set"}
            if not when:
                return {"success": False, "error": "when required for set"}

            platform = request.platform if request else "telegram"
            chat_id = request.reply_target.chat_id if request else ""
            user_id = request.user_id if request else "unknown"
            new_id = f"reminder_{user_id}_{uuid.uuid4().hex[:8]}"

            # Determine if cron or datetime
            parts = when.split()
            if len(parts) == 5 and all(
                p.replace("*", "")
                .replace("/", "")
                .replace("-", "")
                .replace(",", "")
                .isdigit()
                or p == "*"
                for p in parts
            ):
                # Looks like a cron expression
                scheduler.add_reminder(
                    reminder_id=new_id,
                    user_id=user_id,
                    platform=platform,
                    chat_id=chat_id,
                    message=message,
                    run_at=None,
                    repeat_cron=when,
                )
            else:
                try:
                    run_at = datetime.fromisoformat(when.replace("Z", "+00:00"))
                except ValueError:
                    return {
                        "success": False,
                        "error": f"Cannot parse 'when': {when}. Use ISO 8601 or cron.",
                    }
                scheduler.add_reminder(
                    reminder_id=new_id,
                    user_id=user_id,
                    platform=platform,
                    chat_id=chat_id,
                    message=message,
                    run_at=run_at,
                )

            return {
                "success": True,
                "reminder_id": new_id,
                "message": f"Reminder set: '{message}' at {when}",
            }

        return {"success": False, "error": f"Unknown action: {action}"}
