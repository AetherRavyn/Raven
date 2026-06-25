"""Registry — module discovery and routing (A2A-inspired).

Central registry that:
1. Stores Agent Cards for all registered modules
2. Routes messages to the right module based on skill matching
3. Discovers modules by capability tags
4. Manages module lifecycle (register, deregister, health)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from raven_protocol.agent_card import AgentCard, Skill
from raven_protocol.message import Message, MessageType

logger = logging.getLogger(__name__)


class ModuleHandle:
    """Handle to a registered module for message delivery."""

    def __init__(self, card: AgentCard, handler: Callable) -> None:
        self.card = card
        self.handler = handler  # async callable: (Message) -> Message


class ModuleRegistry:
    """Central registry for module discovery and routing.

    A2A-inspired: modules register their Agent Cards, and the
    registry routes messages to the right module.
    """

    def __init__(self) -> None:
        self._modules: dict[str, ModuleHandle] = {}

    def register(self, card: AgentCard, handler: Callable) -> None:
        """Register a module with its Agent Card and message handler."""
        self._modules[card.name] = ModuleHandle(card=card, handler=handler)
        logger.info("Module registered: %s (%d skills)", card.name, len(card.skills))

    def deregister(self, name: str) -> bool:
        """Remove a module from the registry."""
        if name in self._modules:
            del self._modules[name]
            logger.info("Module deregistered: %s", name)
            return True
        return False

    def get_card(self, name: str) -> AgentCard | None:
        """Get an Agent Card by module name."""
        handle = self._modules.get(name)
        return handle.card if handle else None

    def get_handler(self, name: str) -> Callable | None:
        """Get a module's message handler."""
        handle = self._modules.get(name)
        return handle.handler if handle else None

    def list_modules(self) -> list[AgentCard]:
        """List all registered Agent Cards."""
        return [handle.card for handle in self._modules.values()]

    def find_modules_by_skill(self, tags: list[str]) -> list[AgentCard]:
        """Find modules that have a skill matching the given tags."""
        results = []
        for handle in self._modules.values():
            if handle.card.find_skill(tags):
                results.append(handle.card)
        return results

    def find_modules_by_tag(self, tag: str) -> list[AgentCard]:
        """Find modules with a specific tag in any of their skills."""
        return self.find_modules_by_skill([tag])

    async def route_message(self, message: Message) -> Message:
        """Route a message to the appropriate module.

        If message.target is set, route directly.
        Otherwise, find the best module by skill matching.
        """
        target = message.target

        # Direct routing
        if target and target in self._modules:
            handler = self._modules[target].handler
            return await handler(message)

        # Skill-based routing
        if message.method:
            # Extract skill tags from method name
            # e.g. "smart_home.turn_on" → tags ["smart_home", "turn_on"]
            parts = message.method.split(".")
            cards = self.find_modules_by_skill(parts)
            if cards:
                handler = self.get_handler(cards[0].name)
                if handler:
                    return await handler(message)

        # No handler found
        return Message.make_error(
            message.id,
            f"No module found for method '{message.method}' or target '{target}'",
            source="registry",
        )

    def get_registry_summary(self) -> dict[str, Any]:
        """Get a summary of all registered modules."""
        return {
            "total_modules": len(self._modules),
            "modules": [
                {
                    "name": card.name,
                    "description": card.description,
                    "skills": [s.name for s in card.skills],
                    "transport": card.transport,
                }
                for card in self.list_modules()
            ],
        }


# Singleton
_registry: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry
