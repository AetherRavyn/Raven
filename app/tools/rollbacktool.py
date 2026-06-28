"""Rollback Tool — List checkpoints and restore files from snapshots.

Agents use this to safely undo file operations by restoring from
auto-created checkpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class RollbackTool(BaseTool):
    """List checkpoints and restore files from auto-snapshots.

    Every file mutation (write, edit, delete) creates a checkpoint
    automatically. This tool lets agents inspect and restore from
    those checkpoints.
    """

    group = "system"

    def get_name(self) -> str:
        return "rollback"

    def get_description(self) -> str:
        return (
            "Manages file checkpoints and rollbacks. "
            "Actions: 'list' (show checkpoints, optional filter by filepath), "
            "'rollback' (restore file from a specific checkpoint ID), "
            "'undo' (restore most recent checkpoint for a file). "
            "Every file mutation creates an automatic checkpoint."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: list, rollback, undo",
                    required=True,
                    enum=["list", "rollback", "undo"],
                ),
                ToolParameter(
                    name="filepath",
                    type="string",
                    description="File path filter (for list, undo). Required for undo.",
                    required=False,
                ),
                ToolParameter(
                    name="checkpoint_id",
                    type="string",
                    description="Checkpoint ID to restore from (required for rollback)",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Max checkpoints to list (default 20)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        filepath = kwargs.get("filepath", "").strip()
        checkpoint_id = kwargs.get("checkpoint_id", "").strip()
        max_results = int(kwargs.get("max_results", 20))

        try:
            from app.core.checkpoints import get_checkpoint_manager

            mgr = get_checkpoint_manager()

            if action == "list":
                checkpoints = mgr.list_checkpoints(filepath if filepath else None)
                result_count = len(checkpoints)
                if max_results and result_count > max_results:
                    checkpoints = checkpoints[-max_results:]
                return {
                    "success": True,
                    "total_checkpoints": result_count,
                    "checkpoints": [
                        {
                            "id": cp["id"],
                            "file": cp.get("original_path", ""),
                            "size": cp.get("size", 0),
                            "reason": cp.get("reason", ""),
                            "created_at": cp.get("created_at", 0),
                        }
                        for cp in checkpoints
                    ],
                }

            elif action == "rollback":
                if not checkpoint_id:
                    return {"success": False, "error": "checkpoint_id is required"}
                result = mgr.rollback(checkpoint_id)
                if "error" in result:
                    return {"success": False, "error": result["error"]}
                return {"success": True, **result}

            elif action == "undo":
                if not filepath:
                    return {"success": False, "error": "filepath is required"}
                checkpoints = mgr.list_checkpoints(filepath)
                if not checkpoints:
                    return {"success": False, "error": f"No checkpoints found for {filepath}"}
                latest = checkpoints[-1]
                result = mgr.rollback(latest["id"])
                if "error" in result:
                    return {"success": False, "error": result["error"]}
                return {"success": True, **result}

            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            logger.exception("Rollback failed")
            return {"success": False, "error": str(e)}
