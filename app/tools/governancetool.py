"""GovernanceTool — allow user-facing LLMs to approve or reject pending tasks."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.core.task_ledger import TaskLedger

logger = logging.getLogger(__name__)


class GovernanceTool(BaseTool):
    """Approve or reject pending tool calls that require user confirmation."""

    def get_name(self) -> str:
        return "governance"

    def get_description(self) -> str:
        return (
            "Approve or reject pending tasks/tool calls that require user confirmation. "
            "Use this when the user explicitly says 'Approve', 'Yes', 'Deny', or 'No' "
            "to a previously paused tool call."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=["approve", "reject"],
                ),
                ToolParameter(
                    name="task_id",
                    type="string",
                    description="The ID of the pending task to approve or reject.",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation")
        task_id = kwargs.get("task_id")
        request = kwargs.get("_request")

        if not operation or not task_id:
            return {"success": False, "error": "operation and task_id are required"}

        # Prevent automated/system background processes from approving
        if request:
            user_id = getattr(request, "user_id", "")
            platform = getattr(request, "platform", "")
            if user_id.lower() == "system" or platform.lower() == "system":
                return {
                    "success": False,
                    "error": "Automated system processes cannot approve tasks.",
                }

        try:
            from app.settings.config import Config
            from pathlib import Path

            workspace_dir = str(Path(Config.STATE_DB_PATH).parent)
            ledger = TaskLedger(workspace_dir)

            tasks = ledger.list_tasks()
            target_task = next((t for t in tasks if t.get("task_id") == task_id), None)

            if not target_task:
                return {"success": False, "error": f"Task {task_id} not found."}

            if target_task.get("status") not in ["pending_approval", "open"]:
                return {
                    "success": False,
                    "error": f"Task {task_id} is already in state '{target_task.get('status')}'.",
                }

            if operation == "approve":
                ledger.update_status(task_id, "approved")
                return {
                    "success": True,
                    "message": f"Task {task_id} approved. You may now call the original tool again with the same arguments.",
                    "metadata": target_task.get("metadata", {}),
                }
            elif operation == "reject":
                ledger.update_status(task_id, "rejected")
                return {"success": True, "message": f"Task {task_id} rejected."}
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.exception("GovernanceTool error")
            return {"success": False, "error": str(exc)}
