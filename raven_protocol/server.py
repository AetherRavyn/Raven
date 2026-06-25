"""Module Server — wraps a Python module as an A2A-compatible server.

Any module can be exposed as an A2A server by:
1. Defining an Agent Card
2. Implementing a message handler
3. Registering with the ModuleServer

The server handles:
- Message routing
- Error handling
- Health checks
- Capability advertisement
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from raven_protocol.agent_card import AgentCard
from raven_protocol.message import Message, MessageType
from raven_protocol.registry import get_registry

logger = logging.getLogger(__name__)


class ModuleServer:
    """A2A-compatible module server.

    Wraps any Python callable as an A2A module that can be
    discovered and called by other modules.
    """

    def __init__(self, card: AgentCard) -> None:
        self.card = card
        self._handlers: dict[str, Callable] = {}
        self._registry = get_registry()

    def register_method(self, method: str, handler: Callable) -> None:
        """Register a handler for a specific method.

        Method names follow the pattern: "module.action"
        e.g. "smart_home.turn_on", "camera.snapshot"
        """
        self._handlers[method] = handler

    def start(self) -> None:
        """Register this server with the central registry."""
        self._registry.register(self.card, self._handle_message)
        logger.info("ModuleServer started: %s", self.card.name)

    def stop(self) -> None:
        """Unregister from the central registry."""
        self._registry.deregister(self.card.name)
        logger.info("ModuleServer stopped: %s", self.card.name)

    async def _handle_message(self, message: Message) -> Message:
        """Route an incoming message to the appropriate handler."""
        method = message.method

        # Find matching handler
        handler = self._handlers.get(method)
        if not handler:
            # Try prefix matching
            for registered_method, h in self._handlers.items():
                if method.startswith(registered_method):
                    handler = h
                    break

        if not handler:
            return Message.make_error(
                message.id,
                f"Unknown method '{method}' for module '{self.card.name}'",
                source=self.card.name,
            )

        try:
            result = await handler(message.params)
            return Message.response(message.id, result, source=self.card.name)
        except Exception as exc:
            logger.error("Module %s handler error: %s", self.card.name, exc)
            return Message.make_error(message.id, str(exc), source=self.card.name)

    def get_card(self) -> AgentCard:
        return self.card


class ModuleClient:
    """Client for calling other modules via the registry."""

    def __init__(self) -> None:
        self._registry = get_registry()

    async def call(self, target: str, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a module's method and return the result."""
        message = Message.request(method, params or {}, target=target)
        response = await self._registry.route_message(message)

        if response.type == MessageType.ERROR:
            raise RuntimeError(response.error or "Module call failed")

        return response.result

    async def call_any(self, tags: list[str], method: str, params: dict[str, Any] | None = None) -> Any:
        """Call any module that has a matching skill."""
        message = Message.request(method, params or {})
        response = await self._registry.route_message(message)

        if response.type == MessageType.ERROR:
            raise RuntimeError(response.error or "No matching module found")

        return response.result

    def discover(self, tags: list[str]) -> list[AgentCard]:
        """Discover modules by skill tags."""
        return self._registry.find_modules_by_skill(tags)

    def list_all(self) -> list[AgentCard]:
        """List all registered modules."""
        return self._registry.list_modules()
