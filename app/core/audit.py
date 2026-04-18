from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.action_context import ActionContext

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuditEvent:
    kind: str
    action: str
    context: ActionContext | None = None
    success: bool = True
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ActionLogger:
    def __init__(self, path: str = "workspace/audit.log") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: AuditEvent) -> None:
        payload = {
            "timestamp": event.timestamp,
            "kind": event.kind,
            "action": event.action,
            "success": event.success,
            "detail": event.detail,
            "metadata": event.metadata,
            "context": asdict(event.context) if event.context else None,
        }
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.warning("Failed to write audit event: %s", exc)


_GLOBAL_ACTION_LOGGER = ActionLogger()


def get_action_logger() -> ActionLogger:
    return _GLOBAL_ACTION_LOGGER
