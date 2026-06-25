import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.settings.config import Config
from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class AutonomyTool(BaseTool):
    """
    Exposes the background Autonomy Engine (and its TaskPlanner) to the main LLM.
    Allows the AI to securely spawn a background goal when a user requests multiple
    distinct workflows or complex actions that should be planned and executed asynchronously.
    """

    group = "automation"

    def get_name(self) -> str:
        return "spawn_autonomous_goal"

    def get_description(self) -> str:
        return (
            "Spawns a background autonomous goal for complex, multi-step requests. "
            "Use this STRICTLY when the user asks for multiple distinct tasks at once, "
            "or a long-running project that requires a deliberate work plan. "
            "The system will automatically design a work plan and execute it autonomously "
            "using Swarm agents in a background thread."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="title",
                    type="string",
                    description="A short, descriptive title for the overall goal (e.g., 'Daily System Review').",
                    required=True,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Detailed description of everything that needs to be done. Please include all user requirements and constraints.",
                    required=True,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["automation"],
            risk_level="low",
            cost_tier="low",
            confirmation_policy="none",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        title = kwargs.get("title")
        description = kwargs.get("description")

        if not title or not description:
            return {"success": False, "error": "Both 'title' and 'description' are required."}

        goal_id = str(uuid.uuid4())
        goal = {
            "id": goal_id,
            "title": title,
            "description": description,
            "status": "Active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "blockers": []
        }

        workspace_dir = Path(Config.MEMORY_ROOT)  # Usually just reads "workspace"
        goals_file = workspace_dir / "goals.jsonl"

        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
            with open(goals_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(goal) + "\n")
        except Exception as e:
            logger.error("Failed to spawn autonomous goal: %s", e)
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "message": (
                f"Autonomous goal '{title}' has been successfully spawned. The Autonomy Engine "
                "will formulate a plan and execute it in the background."
            ),
            "goal_id": goal_id,
        }
