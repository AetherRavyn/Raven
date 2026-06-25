"""Memory Module — A2A-compliant memory system module.

Exposes memory capabilities via the Raven Protocol.
Any module can query/store memories without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_remember(params: dict[str, Any]) -> dict[str, Any]:
    """Store a memory."""
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    memory_id = facade.remember(
        content=params.get("content", ""),
        user_id=params.get("user_id"),
        category=params.get("category", "FACT"),
    )
    return {"success": True, "memory_id": memory_id}


async def handle_recall(params: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant memories."""
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    results = facade.recall(
        query=params.get("query", ""),
        user_id=params.get("user_id"),
        top_k=params.get("top_k", 5),
    )
    return {
        "memories": [
            {"content": r.content, "source": r.source, "confidence": r.confidence}
            for r in results
        ],
        "count": len(results),
    }


async def handle_query_kg(params: dict[str, Any]) -> dict[str, Any]:
    """Query the knowledge graph."""
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    result = facade.graph_query(params.get("entity", ""))
    return result


async def handle_get_profile(params: dict[str, Any]) -> dict[str, Any]:
    """Get user profile."""
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    return facade.profile(params.get("user_id", "default"))


async def handle_build_memory_context(params: dict[str, Any]) -> dict[str, Any]:
    """Build memory context for LLM prompt."""
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    context = facade.build_context(
        user_id=params.get("user_id", "default"),
        current_topic=params.get("current_topic", ""),
    )
    return {"memory_context": context}


def create_memory_server() -> ModuleServer:
    """Create and configure the Memory module server."""
    card = AgentCard(
        name="memory",
        description="Memory system: semantic search, knowledge graph, user profiles",
        version="1.0.0",
        skills=[
            Skill(name="remember", description="Store a memory", tags=["store", "save", "memory"]),
            Skill(name="recall", description="Retrieve memories", tags=["search", "query", "recall"]),
            Skill(name="query_kg", description="Query knowledge graph", tags=["kg", "graph", "knowledge"]),
            Skill(name="get_profile", description="Get user profile", tags=["profile", "user"]),
            Skill(name="build_memory_context", description="Build memory context for prompts", tags=["context", "prompt"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("memory.remember", handle_remember)
    server.register_method("memory.recall", handle_recall)
    server.register_method("memory.query_kg", handle_query_kg)
    server.register_method("memory.get_profile", handle_get_profile)
    server.register_method("memory.build_context", handle_build_memory_context)

    return server
