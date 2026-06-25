"""API Gateway Module — A2A-compliant external API access module.

Exposes the universal API gateway via the Raven Protocol.
Any module can call external APIs through this module.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_call_api(params: dict[str, Any]) -> dict[str, Any]:
    """Call an external API endpoint."""
    from app.core.api_gateway import get_api_gateway
    gateway = get_api_gateway()
    result = await gateway.call(
        api_name=params.get("api", ""),
        endpoint=params.get("endpoint", ""),
        params=params.get("params"),
        use_cache=params.get("use_cache", True),
    )
    return {
        "success": result.success,
        "status_code": result.status_code,
        "data": result.data,
        "error": result.error,
        "cached": result.cached,
        "latency_ms": result.latency_ms,
    }


async def handle_list_apis(params: dict[str, Any]) -> dict[str, Any]:
    """List all registered APIs."""
    from app.core.api_gateway import get_api_gateway
    gateway = get_api_gateway()
    return {"apis": gateway.list_apis(), "count": len(gateway.list_apis())}


async def handle_get_usage(params: dict[str, Any]) -> dict[str, Any]:
    """Get API usage statistics."""
    from app.core.api_gateway import get_api_gateway
    gateway = get_api_gateway()
    return gateway.get_usage_stats()


async def handle_register_api(params: dict[str, Any]) -> dict[str, Any]:
    """Register a new API."""
    from app.core.api_gateway import get_api_gateway, APIDefinition
    gateway = get_api_gateway()
    api = APIDefinition(
        name=params.get("name", ""),
        base_url=params.get("base_url", ""),
        auth_type=params.get("auth_type", "none"),
        auth_config=params.get("auth_config", {}),
    )
    gateway.register(api.name, api)
    return {"success": True, "api": api.name}


def create_api_gateway_server() -> ModuleServer:
    """Create and configure the API Gateway module server."""
    card = AgentCard(
        name="api_gateway",
        description="Universal API gateway — access any public API",
        version="1.0.0",
        skills=[
            Skill(name="call_api", description="Call an external API", tags=["api", "http", "external"]),
            Skill(name="list_apis", description="List registered APIs", tags=["api", "list"]),
            Skill(name="get_usage", description="Get API usage stats", tags=["api", "stats"]),
            Skill(name="register_api", description="Register a new API", tags=["api", "register"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("api_gateway.call", handle_call_api)
    server.register_method("api_gateway.list", handle_list_apis)
    server.register_method("api_gateway.usage", handle_get_usage)
    server.register_method("api_gateway.register", handle_register_api)

    return server
