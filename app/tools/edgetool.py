from typing import Any, Dict
import os
import json
import uuid
import logging
from app.tools.base import BaseTool, ToolSchema, ToolParameter
from app.core.task_ledger import TaskLedger
from app.settings.config import Config

logger = logging.getLogger(__name__)


class EdgeDeviceTool(BaseTool):
    """
    Manages edge devices, dispatches tasks, and checks results.
    """

    def get_name(self) -> str:
        return "edge_device"

    def get_description(self) -> str:
        return "Manage edge devices: list devices, dispatch tasks to them, and check task results."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The operation to perform: 'list_devices', 'dispatch_task', or 'check_task'",
                    required=True,
                    enum=["list_devices", "dispatch_task", "check_task"],
                ),
                ToolParameter(
                    name="target_node",
                    type="string",
                    description="The specific node_id to dispatch the task to (optional)",
                    required=False,
                ),
                ToolParameter(
                    name="required_capability",
                    type="string",
                    description="The capability required by the task, e.g., 'python' or 'local_llm' (optional)",
                    required=False,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="The command or payload to run on the edge device (for 'dispatch_task')",
                    required=False,
                ),
                ToolParameter(
                    name="task_id",
                    type="string",
                    description="The task ID to check (for 'check_task')",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation")

        if operation == "list_devices":
            devices_path = os.path.join(Config.MEMORY_ROOT, "state", "devices.json")
            if not os.path.exists(devices_path):
                return {"devices": {}}
            try:
                with open(devices_path, "r") as f:
                    return {"devices": json.load(f)}
            except Exception as e:
                return {"error": f"Failed to read devices.json: {e}"}

        elif operation == "dispatch_task":
            target_node = kwargs.get("target_node")
            required_capability = kwargs.get("required_capability")
            command = kwargs.get("command", "")

            ledger = TaskLedger(Config.MEMORY_ROOT)
            task_id = f"edge_{uuid.uuid4().hex[:8]}"
            
            metadata = {"payload": command}
            if target_node:
                metadata["target_node"] = target_node
            if required_capability:
                metadata["required_capability"] = required_capability

            ledger.add_task(
                task_id=task_id,
                task_type="edge_task",
                title=f"Edge Task: {required_capability or 'general'}",
                user_id="system",
                metadata=metadata,
            )

            ledger.update_status(task_id, "queued_for_edge")
            return {"status": "dispatched", "task_id": task_id}

        elif operation == "check_task":
            task_id = kwargs.get("task_id")
            if not task_id:
                return {"error": "task_id is required for check_task"}

            res_path = os.path.join(Config.MEMORY_ROOT, f"edge_result_{task_id}.json")
            if os.path.exists(res_path):
                try:
                    with open(res_path, "r") as f:
                        data = json.load(f)
                    return {"task_id": task_id, "status": "completed", "result": data}
                except Exception as e:
                    return {"error": f"Failed to read result: {e}"}
            else:
                return {"task_id": task_id, "status": "pending"}

        return {"error": f"Unknown operation: {operation}"}
