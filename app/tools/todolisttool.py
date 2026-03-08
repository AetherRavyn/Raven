# app/tools/todolisttool.py
"""TodoListTool — manage Todoist tasks."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

TODOIST_API = "https://api.todoist.com/rest/v2"


class TodoListTool(BaseTool):
    """Manage Todoist tasks: create, complete, list, update, delete tasks."""

    def get_name(self) -> str:
        return "todoist"

    def get_description(self) -> str:
        return (
            "Manage Todoist tasks: create tasks, complete tasks, list tasks, "
            "update task content, delete tasks, and manage projects. "
            "Requires Todoist API token from Todoist > Settings > Integrations."
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
                    enum=[
                        "add_task",
                        "complete_task",
                        "list_tasks",
                        "list_projects",
                        "delete_task",
                        "update_task",
                    ],
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Task content/title",
                    required=False,
                ),
                ToolParameter(
                    name="task_id",
                    type="string",
                    description="Task ID (for complete, delete, update)",
                    required=False,
                ),
                ToolParameter(
                    name="project_id",
                    type="string",
                    description="Project ID (optional, defaults to Inbox)",
                    required=False,
                ),
                ToolParameter(
                    name="due_string",
                    type="string",
                    description="Due date string (e.g., 'today', 'tomorrow', 'next monday')",
                    required=False,
                ),
                ToolParameter(
                    name="priority",
                    type="integer",
                    description="Priority (1=normal, 2=high, 3=urgent)",
                    required=False,
                ),
            ],
        )

    def _get_token(self) -> str:
        return getattr(Config, "TODOIST_API_TOKEN", None) or ""

    def _headers(self) -> Dict[str, str]:
        token = self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        token = self._get_token()
        if not token:
            return {
                "success": False,
                "error": "TODOIST_API_TOKEN not configured. Get from Todoist > Settings > Integrations",
            }

        operation = kwargs.get("operation", "list_tasks")
        content = kwargs.get("content", "")
        task_id = kwargs.get("task_id", "")
        project_id = kwargs.get("project_id", "")
        due_string = kwargs.get("due_string", "")
        priority = kwargs.get("priority", 1)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if operation == "add_task":
                    if not content:
                        return {"success": False, "error": "content required"}

                    payload: Dict[str, Any] = {"content": content}
                    if project_id:
                        payload["project_id"] = project_id
                    if due_string:
                        payload["due_string"] = due_string
                    if priority > 1:
                        payload["priority"] = priority

                    resp = await client.post(
                        f"{TODOIST_API}/tasks",
                        headers=self._headers(),
                        json=payload,
                    )
                    resp.raise_for_status()
                    task = resp.json()
                    return {
                        "success": True,
                        "task_id": task.get("id"),
                        "content": task.get("content"),
                        "due": task.get("due", {}).get("string"),
                        "message": "Task added to Todoist",
                    }

                if operation == "complete_task":
                    if not task_id:
                        return {"success": False, "error": "task_id required"}

                    resp = await client.post(
                        f"{TODOIST_API}/tasks/{task_id}/close",
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "message": "Task completed",
                        "task_id": task_id,
                    }

                if operation == "list_tasks":
                    url = f"{TODOIST_API}/tasks"
                    if project_id:
                        url = f"{TODOIST_API}/projects/{project_id}/tasks"

                    resp = await client.get(url, headers=self._headers())
                    resp.raise_for_status()
                    tasks = resp.json()

                    return {
                        "success": True,
                        "tasks": [
                            {
                                "id": t.get("id"),
                                "content": t.get("content"),
                                "due": t.get("due", {}).get("string"),
                                "priority": t.get("priority"),
                                "project_id": t.get("project_id"),
                            }
                            for t in tasks[:20]
                        ],
                        "count": len(tasks),
                    }

                if operation == "list_projects":
                    resp = await client.get(
                        f"{TODOIST_API}/projects",
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    projects = resp.json()

                    return {
                        "success": True,
                        "projects": [
                            {
                                "id": p.get("id"),
                                "name": p.get("name"),
                            }
                            for p in projects
                        ],
                    }

                if operation == "delete_task":
                    if not task_id:
                        return {"success": False, "error": "task_id required"}

                    resp = await client.delete(
                        f"{TODOIST_API}/tasks/{task_id}",
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "message": "Task deleted",
                        "task_id": task_id,
                    }

                if operation == "update_task":
                    if not task_id:
                        return {"success": False, "error": "task_id required"}

                    payload: Dict[str, Any] = {}
                    if content:
                        payload["content"] = content
                    if due_string:
                        payload["due_string"] = due_string
                    if priority > 1:
                        payload["priority"] = priority

                    resp = await client.post(
                        f"{TODOIST_API}/tasks/{task_id}",
                        headers=self._headers(),
                        json=payload,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "message": "Task updated",
                        "task_id": task_id,
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"Todoist API error: {exc.response.status_code}",
            }
        except Exception as exc:
            logger.exception("TodoListTool error")
            return {"success": False, "error": str(exc)}
