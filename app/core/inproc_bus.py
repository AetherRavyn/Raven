"""In-process bus — Phase 2.5.

A tiny pub/sub bus for high-frequency events (tool traces, metrics,
audit writes) that should NOT pay the cost of serialising through
the signed envelope layer.

Design constraints:
- **No third-party deps.**
- **No shared mutable state across instances** — every component
  instantiates its own bus.
- **Sub-millisecond publish.**
- **Synchronous delivery** to handlers in the current event loop.
  Use ``await bus.publish(...)`` to yield once.
- **Silent drop on subscriber failure** — never break the publisher.

This is the *hot path* bus. The signed envelope bus (Phase 2 main)
handles boundary crossings (sidecar ↔ orchestrator).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# A handler may be sync or async; we always wrap in async.
Handler = Callable[[Any], "Awaitable[None] | None"]


class InProcBus:
    """A minimal in-process pub/sub."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a handler for ``topic``.

        Duplicate (topic, handler) pairs are ignored — subscribing
        twice with the same callable does not deliver twice.
        """
        handlers = self._handlers[topic]
        if handler in handlers:
            return
        handlers.append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        try:
            self._handlers[topic].remove(handler)
        except ValueError:
            pass

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish ``payload`` to every handler subscribed to ``topic``.

        Handler exceptions are caught and logged; the bus never
        propagates them.
        """
        for handler in list(self._handlers.get(topic, [])):
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.debug(
                    "InProcBus handler for %s raised: %s", topic, exc
                )

    def topic_count(self, topic: str) -> int:
        return len(self._handlers.get(topic, []))


# ── Module singleton ────────────────────────────────────────────────

_BUS: InProcBus | None = None


def get_inproc_bus() -> InProcBus:
    """Return a process-wide bus instance."""
    global _BUS
    if _BUS is None:
        _BUS = InProcBus()
    return _BUS


__all__ = ["InProcBus", "get_inproc_bus", "Handler"]