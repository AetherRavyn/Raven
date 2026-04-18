import json
import logging
import os
import threading
import redis
from typing import Callable, Any, Dict, List
from collections import defaultdict

from app.settings.config import Config

logger = logging.getLogger(__name__)


class MessageBus:
    """Redis-backed pub/sub for v4 microservices architecture."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL") or Config.REDIS_URL
        self.redis_client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._stop = threading.Event()
        self._thread = None

    def subscribe(self, topic: str, callback: Callable):
        if topic not in self.subscribers:
            self.pubsub.subscribe(topic)
            if not self._thread or not self._thread.is_alive():
                self._start_listening()
        self.subscribers[topic].append(callback)

    def publish(self, topic: str, payload: Any):
        try:
            message = json.dumps(payload)
            self.redis_client.publish(topic, message)
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")

    def _start_listening(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self):
        for message in self.pubsub.listen():
            if self._stop.is_set():
                break
            if message["type"] == "message":
                topic = message["channel"]
                try:
                    payload = json.loads(message["data"])
                    for callback in self.subscribers.get(topic, []):
                        try:
                            callback(payload)
                        except Exception as e:
                            logger.error(f"Error in subscriber for {topic}: {e}")
                except Exception as e:
                    logger.error(f"Failed to process message from {topic}: {e}")

    def stop(self):
        self._stop.set()
        self.pubsub.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
