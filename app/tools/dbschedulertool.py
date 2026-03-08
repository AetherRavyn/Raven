from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class DatabaseQueryTool(BaseTool):
    """Execute read-only SQL queries on PostgreSQL or Supabase.
    Returns results as JSON. Use with caution - intended for data exploration."""

    def __init__(self, **cfg: Any):
        self._connection_string = cfg.get("connection_string") or os.environ.get(
            "DATABASE_URL"
        )

    def get_name(self) -> str:
        return "db_query"

    def get_description(self) -> str:
        return (
            "Execute read-only SQL queries on PostgreSQL/Supabase. "
            "Only SELECT queries are allowed for safety. "
            "Returns results as JSON array. Use for data exploration."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="SQL SELECT query to execute",
                    required=True,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max rows to return (default 100)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        query = kwargs.get("query", "").strip()
        if not query:
            return self._error("query parameter is required")

        limit = int(kwargs.get("limit", 100))

        # Security: only allow SELECT
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            return self._error("Only SELECT queries are allowed for safety")

        # Add LIMIT if not present
        if "LIMIT" not in query_upper:
            query = f"{query} LIMIT {limit}"

        try:
            result = await self._execute_query(query)
            return result
        except Exception as e:
            return self._error(f"Query failed: {e}")

    async def _execute_query(self, query: str) -> Dict[str, Any]:
        import asyncpg

        if not self._connection_string:
            return self._error("DATABASE_URL not configured")

        try:
            conn = await asyncpg.connect(self._connection_string)
            try:
                rows = await conn.fetch(query)
                # Convert to dicts
                results = [dict(r) for r in rows]
                return {
                    "success": True,
                    "query": query,
                    "row_count": len(results),
                    "results": results,
                }
            finally:
                await conn.close()
        except ImportError:
            return self._error("asyncpg not installed")
        except Exception as e:
            return self._error(f"Database error: {e}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class SchedulerTool(BaseTool):
    """Schedule one-time or recurring tasks. List, add, or remove scheduled jobs.
    Jobs are stored in workspace/scheduled_tasks.json."""

    def __init__(self, **cfg: Any):
        self._tasks_file = Path("workspace/scheduled_tasks.json")

    def get_name(self) -> str:
        return "scheduler_ops"

    def get_description(self) -> str:
        return (
            "Manage scheduled tasks: list all, add a new task, or remove a task. "
            "Supports one-time and recurring schedules. "
            "Tasks are stored locally and executed via the scheduler."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: list, add, or remove",
                    required=True,
                    enum=["list", "add", "remove"],
                ),
                ToolParameter(
                    name="task_id",
                    type="string",
                    description="Unique task ID (for remove operation)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Task description (for add operation)",
                    required=False,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Command to execute (for add operation)",
                    required=False,
                ),
                ToolParameter(
                    name="schedule",
                    type="string",
                    description="Cron expression or 'once' + datetime (for add)",
                    required=False,
                ),
            ],
        )

    def _load_tasks(self) -> List[Dict[str, Any]]:
        if not self._tasks_file.exists():
            return []
        try:
            return json.loads(self._tasks_file.read_text())
        except Exception:
            return []

    def _save_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self._tasks_file.write_text(json.dumps(tasks, indent=2))

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "list")

        try:
            if operation == "list":
                return await self._list_tasks()
            elif operation == "add":
                return await self._add_task(kwargs)
            elif operation == "remove":
                return await self._remove_task(kwargs.get("task_id", ""))
            else:
                return self._error(f"Unknown operation: {operation}")
        except Exception as e:
            return self._error(f"Scheduler error: {e}")

    async def _list_tasks(self) -> Dict[str, Any]:
        tasks = self._load_tasks()
        return {
            "success": True,
            "operation": "list",
            "count": len(tasks),
            "tasks": tasks,
        }

    async def _add_task(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        task_id = kwargs.get("task_id", "").strip()
        description = kwargs.get("description", "").strip()
        command = kwargs.get("command", "").strip()
        schedule = kwargs.get("schedule", "").strip()

        if not task_id or not command or not schedule:
            return self._error(
                "task_id, command, and schedule are required for add operation"
            )

        tasks = self._load_tasks()

        # Check for duplicate
        if any(t.get("task_id") == task_id for t in tasks):
            return self._error(f"Task ID '{task_id}' already exists")

        new_task = {
            "task_id": task_id,
            "description": description,
            "command": command,
            "schedule": schedule,
            "enabled": True,
            "created_at": str(Path("workspace/scheduled_tasks.json").stat().st_mtime),
        }

        tasks.append(new_task)
        self._save_tasks(tasks)

        return {
            "success": True,
            "operation": "add",
            "task": new_task,
            "message": f"Task '{task_id}' added successfully",
        }

    async def _remove_task(self, task_id: str) -> Dict[str, Any]:
        if not task_id:
            return self._error("task_id is required for remove operation")

        tasks = self._load_tasks()
        original_count = len(tasks)
        tasks = [t for t in tasks if t.get("task_id") != task_id]

        if len(tasks) == original_count:
            return self._error(f"Task '{task_id}' not found")

        self._save_tasks(tasks)
        return {
            "success": True,
            "operation": "remove",
            "task_id": task_id,
            "message": f"Task '{task_id}' removed successfully",
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}
