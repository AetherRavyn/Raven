"""WebSocket Transport — real-time bidirectional module communication.

Enables:
- Real-time updates from modules to clients
- Bidirectional streaming for complex interactions
- Live dashboards with instant updates
- Voice/video streaming channels

Uses FastAPI WebSocket for the transport layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for real-time module communication."""

    def __init__(self) -> None:
        self._connections: dict[str, set] = {}  # topic → set of websockets
        self._handlers: dict[str, Callable] = {}  # topic → message handler

    async def connect(self, websocket: Any, topics: list[str] | None = None) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        topic_list = topics or ["general"]
        for topic in topic_list:
            self._connections.setdefault(topic, set()).add(websocket)
        logger.info("WebSocket connected to topics: %s", topic_list)

    async def disconnect(self, websocket: Any) -> None:
        """Remove a WebSocket connection."""
        for topic, connections in self._connections.items():
            connections.discard(websocket)

    async def broadcast(self, topic: str, data: dict[str, Any]) -> None:
        """Broadcast a message to all connections on a topic."""
        if topic not in self._connections:
            return

        message = json.dumps(data, default=str)
        dead = set()

        for ws in self._connections[topic]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        for ws in dead:
            self._connections[topic].discard(ws)

    async def send_to(self, websocket: Any, data: dict[str, Any]) -> None:
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_text(json.dumps(data, default=str))
        except Exception as exc:
            logger.debug("WebSocket send failed: %s", exc)

    def register_handler(self, topic: str, handler: Callable) -> None:
        """Register a handler for incoming messages on a topic."""
        self._handlers[topic] = handler

    async def handle_message(self, websocket: Any, data: str) -> None:
        """Handle an incoming WebSocket message."""
        try:
            message = json.loads(data)
            topic = message.get("topic", "general")

            # Find and call handler
            handler = self._handlers.get(topic)
            if handler:
                response = await handler(message)
                if response:
                    await self.send_to(websocket, response)
            else:
                # Broadcast to topic subscribers
                await self.broadcast(topic, message)

        except json.JSONDecodeError:
            logger.debug("Invalid JSON in WebSocket message")
        except Exception as exc:
            logger.error("WebSocket message handling error: %s", exc)

    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conn) for conn in self._connections.values())

    def get_topics(self) -> list[str]:
        """Get all active topics with connections."""
        return [topic for topic, conn in self._connections.items() if conn]


# Singleton
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
