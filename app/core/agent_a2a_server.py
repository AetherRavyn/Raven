"""Agent Module — A2A-compliant agent orchestration module.

Exposes agent capabilities via the Raven Protocol.
Any module can discover and delegate to agents without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_list_agents(params: dict[str, Any]) -> dict[str, Any]:
    """List all available agents."""
    from app.core.orchestrator import MessageOrchestrator
    from app.core.botsignal import get_botsignal

    # Get the swarm manager's registered agents
    try:
        orch = MessageOrchestrator(get_botsignal())
        agents = [
            {"name": name, "description": agent.role_prompt[:100]}
            for name, agent in orch._swarm_manager.available_agents.items()
        ]
        return {"agents": agents, "count": len(agents)}
    except Exception as exc:
        logger.warning("Could not list agents: %s", exc)
        return {"agents": [], "count": 0}


async def handle_spawn_agent(params: dict[str, Any]) -> dict[str, Any]:
    """Dynamically spawn an agent for a task."""
    from app.core.orchestrator import MessageOrchestrator
    from app.core.botsignal import get_botsignal
    from app.core.models import IncomingRequest, ReplyTarget

    name = params.get("name", "dynamic_agent")
    role = params.get("role", "General task executor")
    task = params.get("task", "")

    try:
        orch = MessageOrchestrator(get_botsignal())
        # Create a minimal request for the agent
        request = IncomingRequest(
            platform="internal",
            user_id="system",
            text=task,
            reply_target=ReplyTarget(platform="internal", chat_id="system"),
        )
        result = await orch._swarm_manager.spawn_and_execute(
            name=name,
            role_description=role,
            task=task,
            request=request,
        )
        return {"success": True, "agent": name, "result": result[:2000]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def handle_delegate_task(params: dict[str, Any]) -> dict[str, Any]:
    """Delegate a task to a specific agent."""
    from app.core.orchestrator import MessageOrchestrator
    from app.core.botsignal import get_botsignal
    from app.core.models import IncomingRequest, ReplyTarget

    agent_name = params.get("agent_name", "")
    task = params.get("task", "")

    try:
        orch = MessageOrchestrator(get_botsignal())
        agent = orch._swarm_manager.available_agents.get(agent_name)
        if not agent:
            return {"success": False, "error": f"Agent '{agent_name}' not found"}

        from app.core.agency import WorkerAgent
        worker = WorkerAgent(
            name=agent.name,
            role_prompt=agent.role_prompt,
            tools=agent.tools,
            system_prompt=agent.get_enhanced_prompt(),
        )
        request = IncomingRequest(
            platform="internal",
            user_id="system",
            text=task,
            reply_target=ReplyTarget(platform="internal", chat_id="system"),
        )
        result = await worker.execute_task(task, request)
        return {"success": True, "agent": agent_name, "result": result[:2000]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def create_agent_server() -> ModuleServer:
    """Create and configure the Agent module server."""
    card = AgentCard(
        name="agents",
        description="Agent orchestration: discovery, delegation, dynamic spawning",
        version="1.0.0",
        skills=[
            Skill(name="list_agents", description="List available agents", tags=["discover", "list"]),
            Skill(name="spawn_agent", description="Spawn dynamic agent", tags=["spawn", "create"]),
            Skill(name="delegate_task", description="Delegate to specific agent", tags=["delegate", "task"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("agents.list", handle_list_agents)
    server.register_method("agents.spawn", handle_spawn_agent)
    server.register_method("agents.delegate", handle_delegate_task)

    return server
