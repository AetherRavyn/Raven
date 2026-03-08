import json
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class WriteTodosTool(BaseTool):
    def __init__(self):
        self.valid_statuses = {"pending", "in_progress", "completed", "cancelled"}

    def get_name(self) -> str:
        return "write_todos"

    def get_description(self) -> str:
        return (
            "Overwrite the current todo list with a new list of tasks. "
            "Use this to track progress, add tasks, or mark them as done."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="todos",
                    type="array",
                    description=(
                        "A list of todo objects. Each object MUST have: "
                        "1. 'description' (string): The task details. "
                        "2. 'status' (string): One of ['pending', 'in_progress', 'completed', 'cancelled']. "
                        "IMPORTANT: Only one task can be 'in_progress' at a time."
                    ),
                    required=True,
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        raw_todos = kwargs.get("todos")

        if raw_todos is None:
            return self._error("Missing required parameter: 'todos'")

        # 1. Parsing: Handle both List and JSON String formats (LLM robustness)
        todos = []
        try:
            if isinstance(raw_todos, str):
                todos = json.loads(raw_todos)
            elif isinstance(raw_todos, list):
                todos = raw_todos
            else:
                return self._error("'todos' must be a list or a valid JSON string.")
        except json.JSONDecodeError:
            return self._error("Failed to parse 'todos' JSON string.")

        # 2. Validation: Check structure and business rules
        error_msg = self._validate_todos(todos)
        if error_msg:
            return self._error(error_msg)

        # 3. Execution: Format the output for the LLM
        # (In a real app, you would save `todos` to a database or file here)

        if not todos:
            return {
                "llmContent": "Successfully cleared the todo list.",
                "returnDisplay": {"todos": []},
            }

        todo_list_string = "\n".join(
            [
                f"{i + 1}. [{t['status']}] {t['description']}"
                for i, t in enumerate(todos)
            ]
        )

        return {
            "llmContent": f"Successfully updated the todo list. The current list is now:\n{todo_list_string}",
            "returnDisplay": {"todos": todos},
        }

    def _validate_todos(self, todos: List[Any]) -> Optional[str]:
        """
        Validates the schema of the todo objects and business rules.
        """
        if not isinstance(todos, list):
            return "'todos' parameter must be an array."

        in_progress_count = 0

        for i, item in enumerate(todos):
            # Type check
            if not isinstance(item, dict):
                return f"Item at index {i} is not a valid object."

            # Required fields check
            description = item.get("description")
            status = item.get("status")

            if (
                not description
                or not isinstance(description, str)
                or not description.strip()
            ):
                return f"Item at index {i} is missing a valid 'description'."

            if status not in self.valid_statuses:
                return f"Item at index {i} has invalid status '{status}'. Allowed: {', '.join(self.valid_statuses)}"

            # Logic check
            if status == "in_progress":
                in_progress_count += 1

        if in_progress_count > 1:
            return "Invalid parameters: Only one task can be 'in_progress' at a time."

        return None

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "output": f"Error: {msg}"}
