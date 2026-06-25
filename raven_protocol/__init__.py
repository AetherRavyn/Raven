"""Raven Protocol — A2A-inspired module communication protocol.

Pure module system where modules communicate via standardized
messages without direct imports.

Usage:
    from raven_protocol import AgentCard, Message, ModuleServer, ModuleClient

    # Define a module
    card = AgentCard(name="iot", description="IoT control", skills=[
        Skill(name="turn_on", description="Turn on a device", tags=["light", "switch"])
    ])
    server = ModuleServer(card)
    server.register_method("iot.turn_on", my_handler)
    server.start()

    # Call from another module
    client = ModuleClient()
    result = await client.call("iot", "iot.turn_on", {"entity_id": "light.living_room"})

    # Serve over HTTP
    from raven_protocol.http_transport import create_module_routes
    app = create_module_routes()
"""

from raven_protocol.agent_card import AgentCard, Skill
from raven_protocol.message import Message, MessageType, TaskState
from raven_protocol.registry import ModuleRegistry, get_registry
from raven_protocol.server import ModuleServer, ModuleClient
from raven_protocol.auth import AuthProvider, AuthMiddleware, get_auth_provider, get_auth_middleware
from raven_protocol.streaming import StreamManager, get_stream_manager
from raven_protocol.websocket_transport import WebSocketManager, get_ws_manager

__all__ = [
    "AgentCard", "Skill",
    "Message", "MessageType", "TaskState",
    "ModuleRegistry", "get_registry",
    "ModuleServer", "ModuleClient",
    "AuthProvider", "AuthMiddleware", "get_auth_provider", "get_auth_middleware",
    "StreamManager", "get_stream_manager",
    "WebSocketManager", "get_ws_manager",
]
