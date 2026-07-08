from __future__ import annotations

import logging
from typing import Any

from app.core.blueprint_manager import BlueprintManager
from app.core.blueprint_runner import BlueprintRunner
from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.tools.__init__ import tool_error, tool_success

logger = logging.getLogger(__name__)


class BlueprintTool(BaseTool):
    def get_name(self) -> str:
        return "blueprint"

    def get_description(self) -> str:
        return "Automation blueprint catalog — install, run, and manage automation workflows"

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform",
                    required=True,
                    enum=[
                        "list",
                        "install",
                        "uninstall",
                        "enable",
                        "disable",
                        "run",
                        "get",
                        "history",
                    ],
                ),
                ToolParameter(
                    name="blueprint_id",
                    type="string",
                    description="Blueprint identifier",
                    required=False,
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Blueprint name (for install)",
                    required=False,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="YAML blueprint content (for install)",
                    required=False,
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    description="Filter by status (for list)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = str(kwargs.get("action", "")).strip()
        manager = BlueprintManager()

        if action == "list":
            blueprints = manager.list_blueprints()
            return tool_success(
                action=action,
                count=len(blueprints),
                blueprints=[
                    {
                        "id": b.name,
                        "name": b.name,
                        "version": b.version,
                        "enabled": b.enabled,
                        "category": "",
                        "author": b.author,
                    }
                    for b in blueprints
                ],
            )

        if action == "install":
            name_hint = kwargs.get("name", "").strip()
            content = kwargs.get("content", "").strip()
            if not name_hint or not content:
                return tool_error(
                    "name and content are required for install", action=action
                )
            try:
                import yaml

                data = yaml.safe_load(content)
                if not isinstance(data, dict):
                    return tool_error("Invalid YAML content", action=action)
                bp_name = manager.install(data)
                bp = manager.get_blueprint(bp_name)
                if bp is None:
                    return tool_error(
                        f"Blueprint {bp_name} installed but not found",
                        action=action,
                    )
                return tool_success(
                    action=action,
                    blueprint_id=bp.name,
                    name=bp.name,
                    version=bp.version,
                )
            except Exception as e:
                return tool_error(f"Failed to install blueprint: {e}", action=action)

        if action == "uninstall":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error(
                    "blueprint_id is required for uninstall", action=action
                )
            result = manager.uninstall(bp_id)
            return tool_success(
                action=action, success=result, blueprint_id=bp_id
            )

        if action == "enable":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error(
                    "blueprint_id is required for enable", action=action
                )
            result = manager.enable(bp_id)
            return tool_success(
                action=action, success=result, blueprint_id=bp_id
            )

        if action == "disable":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error(
                    "blueprint_id is required for disable", action=action
                )
            result = manager.disable(bp_id)
            return tool_success(
                action=action, success=result, blueprint_id=bp_id
            )

        if action == "get":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error("blueprint_id is required for get", action=action)
            bp = manager.get_blueprint(bp_id)
            if bp is None:
                return tool_error(f"Blueprint {bp_id} not found", action=action)
            return tool_success(
                action=action,
                id=bp.name,
                name=bp.name,
                version=bp.version,
                description=bp.description,
                category="",
                author=bp.author,
                enabled=True,
                steps=len(bp.steps),
            )

        if action == "history":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error(
                    "blueprint_id is required for history", action=action
                )
            history = manager.get_run_history(bp_id)
            return tool_success(
                action=action,
                count=len(history),
                history=[
                    {
                        "id": h["id"],
                        "status": h["status"],
                        "started_at": h["started_at"],
                        "completed_at": h.get("finished_at"),
                        "result": h.get("error"),
                    }
                    for h in history[-20:]
                ],
            )

        if action == "run":
            bp_id = kwargs.get("blueprint_id", "").strip()
            if not bp_id:
                return tool_error("blueprint_id is required for run", action=action)
            try:
                bp = manager.get_blueprint(bp_id)
                if bp is None:
                    return tool_error(f"Blueprint {bp_id} not found", action=action)
                runner = BlueprintRunner(manager=manager)
                result = runner.run(bp_id)
                return tool_success(
                    action=action,
                    success=result.get("status") == "success",
                    steps_completed=result.get("steps_completed", 0),
                    steps_total=len(bp.steps),
                    duration_ms=int(result.get("duration", 0) * 1000),
                    error=result.get("error"),
                )
            except Exception as e:
                return tool_error(f"Blueprint run failed: {e}", action=action)

        return tool_error(f"Unknown action: {action}", action=action)
