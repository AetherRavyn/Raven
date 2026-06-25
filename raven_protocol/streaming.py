"""Streaming Transport — Server-Sent Events for real-time module updates.

Enables clients to subscribe to module events via SSE.
Used for real-time updates from IoT sensors, autonomous actions, etc.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from raven_protocol.message import Message, MessageType

logger = logging.getLogger(__name__)


class StreamManager:
    """Manages SSE streams for real-time module updates."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}  # topic → queues

    def subscribe(self, topic: str) -> asyncio.Queue:
        """Subscribe to a topic and return a queue for receiving events."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(queue)
        logger.info("Stream subscribed to topic: %s", topic)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from a topic."""
        if topic in self._subscribers:
            self._subscribers[topic] = [q for q in self._subscribers[topic] if q is not queue]

    async def publish(self, topic: str, message: Message) -> None:
        """Publish a message to all subscribers of a topic."""
        if topic not in self._subscribers:
            return

        data = message.to_json()
        dead_queues = []

        for queue in self._subscribers[topic]:
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                dead_queues.append(queue)

        # Clean up full queues
        for q in dead_queues:
            self._subscribers[topic].remove(q)

    async def event_stream(self, topic: str) -> AsyncGenerator[str, None]:
        """Generate an SSE event stream for a topic."""
        queue = self.subscribe(topic)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(topic, queue)

    def get_topics(self) -> list[str]:
        """List all active topics."""
        return list(self._subscribers.keys())


# Singleton
_stream_manager: StreamManager | None = None


def get_stream_manager() -> StreamManager:
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = StreamManager()
    return _stream_manager
