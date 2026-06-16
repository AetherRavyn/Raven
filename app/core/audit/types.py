"""Public types for the audit log.

Every meaningful runtime action — tool call, agent handoff, approval,
config change, security event — is recorded as an :class:`AuditEvent`.
The event is structured so a dashboard can filter, search, and
replay it without re-parsing free text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AuditKind(str, Enum):
    """Coarse categories so the dashboard can colour-code at a glance."""

    TOOL_CALL = "tool_call"
    AGENT_HANDOFF = "agent_handoff"
    APPROVAL = "approval"
    POLICY = "policy"
    CONFIG = "config"
    SECURITY = "security"
    LLM_CALL = "llm_call"
    PLAN = "plan"
    GOAL = "goal"
    COST = "cost"
    CUSTOM = "custom"


class RiskLevel(str, Enum):
    """Severity assigned by the policy engine (or inferred)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class AuditEvent:
    """One row in the audit log."""

    kind: AuditKind | str
    actor: str
    action: str
    target: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel | str = RiskLevel.LOW
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0
    cost_usd: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self, *, redact: bool = True, redact_config: Any | None = None) -> dict[str, Any]:
        """Serialize the event to a dict.

        ``redact=True`` (the default) runs the payload through
        :mod:`app.core.audit.redaction` so credentials never reach
        the on-disk JSONL.  Set ``redact=False`` only for tests
        that need to inspect the raw value.
        """
        raw = {
            "id": self.id,
            "kind": _enum_value(self.kind),
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "context": self.context,
            "success": self.success,
            "detail": self.detail,
            "metadata": self.metadata,
            "risk_level": _enum_value(self.risk_level),
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }
        if not redact:
            return raw
        # Local import keeps the redaction module optional and
        # avoids a cycle: types.py is imported by redaction tests.
        from app.core.audit.redaction import redact_dict

        return redact_dict(raw, config=redact_config)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditEvent":
        ts = d.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return cls(
            id=d.get("id") or uuid.uuid4().hex,
            kind=d.get("kind", AuditKind.CUSTOM),
            actor=d.get("actor", "system"),
            action=d.get("action", ""),
            target=d.get("target"),
            context=dict(d.get("context") or {}),
            success=bool(d.get("success", True)),
            detail=d.get("detail"),
            metadata=dict(d.get("metadata") or {}),
            risk_level=d.get("risk_level", RiskLevel.LOW),
            timestamp=ts or datetime.now(timezone.utc),
            duration_ms=int(d.get("duration_ms", 0)),
            cost_usd=float(d.get("cost_usd", 0.0)),
        )


def _enum_value(v: Any) -> Any:
    if hasattr(v, "value"):
        return v.value
    return v


__all__ = ["AuditKind", "RiskLevel", "AuditEvent"]
