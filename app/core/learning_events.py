"""Learning event log — thread-safe ring buffer of learning system events.

Scheduler tasks emit events here. The dashboard polls /api/learning/events
to show a live feed. Notifications are sent to the user for high-value events.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_LOG: deque[dict[str, Any]] = deque(maxlen=100)
_EVENT_LOCK = threading.Lock()


def push_event(
    kind: str, title: str, detail: str = "", *, metadata: dict[str, Any] | None = None
) -> None:
    """Push an event into the ring buffer."""
    with _EVENT_LOCK:
        _EVENT_LOG.append(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "metadata": metadata or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


def get_events(limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
    """Return recent events, newest first."""
    with _EVENT_LOCK:
        all_events = list(_EVENT_LOG)
    all_events.reverse()
    if kind:
        all_events = [e for e in all_events if e["kind"] == kind]
    return all_events[:limit]


def clear_events() -> None:
    with _EVENT_LOCK:
        _EVENT_LOG.clear()
