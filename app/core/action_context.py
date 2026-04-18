from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionContext:
    user_id: str
    platform: str
    request_text: str
    request_id: str | None = None
    risk_level: str = "low"
    memory_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
