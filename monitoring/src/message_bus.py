import json
import logging
import threading
from typing import Callable, Any, Dict, List
from collections import defaultdict

logger = logging.getLogger(__name__)


class MessageBus:
    """In-process pub/sub for microservices architecture.

    Replaces the Redis-backed implementation. For single-process
    deployments this is sufficient. For multi-process, swap in a
    Redis or MQTT backend.
    """

    def __init__(self, redis_url: str | None = None):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, callback: Callable):
        with self._lock:
            self.subscribers[topic].append(callback)

    def publish(self, topic: str, payload: Any):
        with self._lock:
            handlers = list(self.subscribers.get(topic, []))
        for callback in handlers:
            try:
                callback(payload)
            except Exception as e:
                logger.error(f"Error in subscriber for {topic}: {e}")

    def stop(self):
        pass
