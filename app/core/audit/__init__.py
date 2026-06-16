"""Queryable audit log (part of A4 in the foundation plan).

Public API:
- :class:`AuditEvent` — a single structured event.
- :class:`AuditKind`, :class:`RiskLevel` — enums used by events.
- :class:`AuditLog` — the log itself.  Append-only, JSONL-backed,
  with a query API and optional HelixDB replication.
- :class:`ActionLogger` — thin legacy-compatible wrapper.
- :func:`get_action_logger` — process-wide singleton.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.audit.log import DEFAULT_PATH, HELIX_KV_PREFIX, AuditLog
from app.core.audit.redaction import (
    DEFAULT_PLACEHOLDER,
    DEFAULT_RULES,
    RedactionConfig,
    redact_dict,
    safe_for_log,
)
from app.core.audit.types import AuditEvent, AuditKind, RiskLevel
from app.core.audit.dashboard import (
    DEFAULT_COLUMNS,
    AuditStats,
    compute_stats,
    format_csv,
    format_json,
    format_timeline,
)

logger = logging.getLogger(__name__)


class ActionLogger:
    """Legacy-compatible thin wrapper around :class:`AuditLog`.

    New code should construct an :class:`AuditLog` directly and
    inject it where needed.  This class exists so existing call
    sites — ``get_action_logger()`` etc. — keep working.
    """

    def __init__(self, path: str = "workspace/audit.log") -> None:
        self.path = Path(path)
        self._log = AuditLog(jsonl_path=self.path)

    def log(self, event: AuditEvent) -> str:
        return self._log.record(event)

    def record(self, event: AuditEvent) -> str:
        return self._log.record(event)

    def log_dict(
        self,
        *,
        kind: str,
        action: str,
        context: Any = None,
        success: bool = True,
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
        risk_level: str = "low",
    ) -> str:
        return self._log.record(
            AuditEvent(
                kind=kind,
                actor=(
                    getattr(context, "user_id", "system")
                    if context is not None
                    else "system"
                ),
                action=action,
                target=(
                    getattr(context, "request_id", None)
                    if context is not None
                    else None
                ),
                context=(
                    {
                        "user_id": getattr(context, "user_id", None),
                        "platform": getattr(context, "platform", None),
                        "request_id": getattr(context, "request_id", None),
                        "request_text": getattr(context, "request_text", None),
                        "risk_level": getattr(context, "risk_level", None),
                    }
                    if context is not None
                    else {}
                ),
                success=success,
                detail=detail,
                metadata=metadata or {},
                risk_level=risk_level,
            )
        )

    def log_action(
        self,
        kind: str,
        action: str,
        context: Any = None,
        success: bool = True,
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.log_dict(
            kind=kind,
            action=action,
            context=context,
            success=success,
            detail=detail,
            metadata=metadata,
        )


_DEFAULT_LOGGER: ActionLogger | None = None


def get_action_logger() -> ActionLogger:
    """Return a process-wide ActionLogger, creating it on first use."""
    global _DEFAULT_LOGGER
    if _DEFAULT_LOGGER is None:
        _DEFAULT_LOGGER = ActionLogger()
    return _DEFAULT_LOGGER


__all__ = [
    "AuditEvent",
    "AuditKind",
    "RiskLevel",
    "AuditLog",
    "ActionLogger",
    "get_action_logger",
    "DEFAULT_PATH",
    "HELIX_KV_PREFIX",
    # Redaction
    "RedactionConfig",
    "DEFAULT_RULES",
    "DEFAULT_PLACEHOLDER",
    "redact_dict",
    "safe_for_log",
    # Dashboard
    "AuditStats",
    "DEFAULT_COLUMNS",
    "compute_stats",
    "format_timeline",
    "format_csv",
    "format_json",
]
