"""Message — JSON-RPC-style message format for module communication.

Every interaction between modules uses this standardized format:
- Request: "I need X" → module processes → Response: "Here's X"
- Event: "Something happened" → module reacts
- Stream: "Here's a chunk of data" → module processes incrementally
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"
    STREAM = "stream"
    STREAM_END = "stream_end"


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class Message:
    """A standardized message for module communication."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.REQUEST
    source: str = ""  # sender module name
    target: str = ""  # receiver module name
    method: str = ""  # e.g. "smart_home.turn_on", "camera.snapshot"
    params: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    task_state: TaskState | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        if self.task_state:
            d["task_state"] = self.task_state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=MessageType(data.get("type", "request")),
            source=data.get("source", ""),
            target=data.get("target", ""),
            method=data.get("method", ""),
            params=data.get("params", {}),
            result=data.get("result"),
            error=data.get("error"),
            task_state=TaskState(data["task_state"]) if data.get("task_state") else None,
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> Message:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def request(cls, method: str, params: dict[str, Any], source: str = "", target: str = "") -> Message:
        return cls(type=MessageType.REQUEST, method=method, params=params, source=source, target=target)

    @classmethod
    def response(cls, request_id: str, result: Any, source: str = "") -> Message:
        return cls(id=request_id, type=MessageType.RESPONSE, result=result, source=source)

    @classmethod
    def make_error(cls, request_id: str, error_msg: str, source: str = "") -> Message:
        return cls(id=request_id, type=MessageType.ERROR, error=error_msg, source=source)

    @classmethod
    def event(cls, method: str, params: dict[str, Any], source: str = "") -> Message:
        return cls(type=MessageType.EVENT, method=method, params=params, source=source)
