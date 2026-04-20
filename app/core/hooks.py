from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

HookHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(slots=True)
class HookEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class HookDispatcher:
    """Event-driven hook system for lifecycle and tool events."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {}

    def register(self, event_name: str, handler: HookHandler) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    async def dispatch(
        self, event_name: str, payload: dict[str, Any] | None = None
    ) -> None:
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return
        event_payload = payload or {}
        for handler in handlers:
            try:
                result = handler(event_payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.debug("Hook handler failed for %s: %s", event_name, exc)
