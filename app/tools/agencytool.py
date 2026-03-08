import asyncio
import logging
from typing import Any, Dict, List

from app.core.agency import SwarmManager
from app.core.models import IncomingRequest
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class AgencyDelegationTool(BaseTool):
    """
    Allows the primary AgentRuntime to delegate a complex "Case Study"
    to the Asynchronous Corporate Swarm (System 2).
    """

    def __init__(self, swarm_manager: SwarmManager):
        self.swarm_manager = swarm_manager

    def get_name(self) -> str:
        return "delegate_case_study"

    def get_description(self) -> str:
        agent_names = sorted(self.swarm_manager.available_agents.keys())
        agent_list = (
            ", ".join(f"'{a}'" for a in agent_names)
            if agent_names
            else "(none registered yet)"
        )
        return (
            "Delegates a highly complex, multi-step 'Case Study' or deep research task "
            "to a background swarm of specialized AI agents. Use this ONLY when a task requires "
            "deep investigation, massive parallel research, or will take a long time. "
            "This runs asynchronously in the background and will notify the user upon completion. "
            f"Available agents: {agent_list}."
        )

    def get_schema(self) -> ToolSchema:
        agent_names = sorted(self.swarm_manager.available_agents.keys())
        agent_list = (
            ", ".join(f"'{a}'" for a in agent_names) if agent_names else "(none)"
        )
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="tasks",
                    type="array",
                    description=(
                        "A list of tasks to execute in parallel. Each task is a JSON object containing: "
                        f"'agent_name' (must be one of: {agent_list}), "
                        "and 'task' (the specific instruction for the worker)."
                    ),
                    required=True,
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        tasks = kwargs.get("tasks", [])
        request: IncomingRequest = kwargs.get("_request")

        if not request:
            return {
                "success": False,
                "error": "Internal Error: No request context passed to Agency Tool.",
            }
        if not tasks or not isinstance(tasks, list):
            return {
                "success": False,
                "error": "You must provide a valid list of tasks.",
            }

        # Validate task structures
        valid_tasks = []
        for t in tasks:
            if isinstance(t, dict) and "agent_name" in t and "task" in t:
                valid_tasks.append(t)

        if not valid_tasks:
            return {"success": False, "error": "Tasks array contained invalid objects."}

        # Fire and forget: We spawn the swarm manager as a background task.
        # This prevents the main AgentRuntime ReAct loop from blocking for 10 minutes.
        logger.info(f"Spawning background SwarmManager for {len(valid_tasks)} tasks.")
        asyncio.create_task(self.swarm_manager.execute_case_study(request, valid_tasks))

        return {
            "success": True,
            "status": "System 2 Asynchronous Swarm has been successfully spawned in the background.",
            "action_required": "Tell the user that you have deployed background agents to investigate the matter and they will receive a report shortly.",
        }
