"""IoT Module — A2A-compliant smart home module.

Exposes IoT capabilities via the Raven Protocol.
Any module can call IoT methods without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer, Message

logger = logging.getLogger(__name__)


async def handle_turn_on(params: dict[str, Any]) -> dict[str, Any]:
    """Turn on a smart home device."""
    from raven_iot.tools.smart_home import SmartHomeTool
    tool = SmartHomeTool()
    return await tool.execute(operation="turn_on", entity_id=params.get("entity_id"))


async def handle_turn_off(params: dict[str, Any]) -> dict[str, Any]:
    """Turn off a smart home device."""
    from raven_iot.tools.smart_home import SmartHomeTool
    tool = SmartHomeTool()
    return await tool.execute(operation="turn_off", entity_id=params.get("entity_id"))


async def handle_list_entities(params: dict[str, Any]) -> dict[str, Any]:
    """List all smart home entities."""
    from raven_iot.tools.smart_home import SmartHomeTool
    tool = SmartHomeTool()
    return await tool.execute(operation="list_entities", domain_filter=params.get("domain_filter"))


async def handle_get_state(params: dict[str, Any]) -> dict[str, Any]:
    """Get state of a smart home entity."""
    from raven_iot.tools.smart_home import SmartHomeTool
    tool = SmartHomeTool()
    return await tool.execute(operation="get_state", entity_id=params.get("entity_id"))


def create_iot_server() -> ModuleServer:
    """Create and configure the IoT module server."""
    card = AgentCard(
        name="iot",
        description="Smart home control via Home Assistant",
        version="1.0.0",
        skills=[
            Skill(name="turn_on", description="Turn on a device", tags=["light", "switch", "device"]),
            Skill(name="turn_off", description="Turn off a device", tags=["light", "switch", "device"]),
            Skill(name="list_entities", description="List all devices", tags=["list", "discover"]),
            Skill(name="get_state", description="Get device state", tags=["state", "query"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("iot.turn_on", handle_turn_on)
    server.register_method("iot.turn_off", handle_turn_off)
    server.register_method("iot.list_entities", handle_list_entities)
    server.register_method("iot.get_state", handle_get_state)

    return server
