"""Public types for Policy v2.

The policy engine is the single gate between the runtime and a
tool call.  It takes a :class:`PolicyRequest` and returns a
:class:`PolicyDecision` with one of three verdicts:

- ``allow`` — proceed
- ``ask``   — require explicit approval before proceeding
- ``deny``  — block the call entirely

Risk is a continuous score in ``[0, 100]`` plus a discrete
:class:`RiskLevel`.  Trust tier modifies the score: high-trust
users see their risk damped, low-trust users see it amplified.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable


class Verdict(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Risk band thresholds (inclusive upper bound).
RISK_BANDS: list[tuple[int, RiskLevel]] = [
    (25, RiskLevel.LOW),
    (50, RiskLevel.MEDIUM),
    (75, RiskLevel.HIGH),
    (100, RiskLevel.CRITICAL),
]


def risk_level_for(score: int) -> RiskLevel:
    """Map a numeric score to a :class:`RiskLevel`."""
    for upper, lvl in RISK_BANDS:
        if score <= upper:
            return lvl
    return RiskLevel.CRITICAL


class TrustTier(str, Enum):
    """Per-user trust band.  Higher tier = lower scrutiny."""

    UNTRUSTED = "untrusted"      # default for new users
    NEW = "new"                  # first week of activity
    ESTABLISHED = "established"  # 1+ week, no recent misuse
    TRUSTED = "trusted"          # long history of safe use
    ADMIN = "admin"              # in Config.ADMIN_USER_IDS


@dataclass(slots=True)
class PolicyRequest:
    """A request to the policy engine."""

    user_id: str
    action: str  # tool name or event kind
    target: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    # The runtime may pass a pre-computed risk score from a tool
    # metadata table.  If None, the engine computes one.
    risk_score: int | None = None
    risk_factors: list[str] = field(default_factory=list)
    # Optional: the agent making the call (for per-agent policy).
    agent: str | None = None
    # Optional: the platform (telegram, discord, web, …) — used for
    # multi-channel approval routing.
    platform: str | None = None


@dataclass(slots=True)
class PolicyDecision:
    """The policy engine's verdict on a :class:`PolicyRequest`."""

    request_id: str
    verdict: Verdict
    risk_score: int
    risk_level: RiskLevel
    trust_tier: TrustTier
    reasons: list[str] = field(default_factory=list)
    # If verdict == ask, this is the id of the queued approval.
    approval_id: str | None = None
    # The (possibly adjusted) score after trust-tier damping.
    adjusted_score: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "verdict": self.verdict.value,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "trust_tier": self.trust_tier.value,
            "reasons": list(self.reasons),
            "approval_id": self.approval_id,
            "adjusted_score": self.adjusted_score,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(slots=True)
class ApprovalRequest:
    """A pending approval, waiting for a human to weigh in."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    decision: PolicyDecision = field(
        default_factory=lambda: PolicyDecision(
            request_id="",
            verdict=Verdict.ASK,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            trust_tier=TrustTier.UNTRUSTED,
        )
    )
    request: PolicyRequest | None = None
    status: str = "pending"  # pending | approved | denied | expired
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=1)
    )
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decision": self.decision.to_dict(),
            "request": (
                {
                    "user_id": self.request.user_id,
                    "action": self.request.action,
                    "target": self.request.target,
                    "args": self.request.args,
                    "context": self.request.context,
                    "agent": self.request.agent,
                    "platform": self.request.platform,
                }
                if self.request is not None
                else None
            ),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
        }


# Risk weights per action.  These are deliberately conservative
# defaults; deployment-specific tuning happens in a config file.
DEFAULT_ACTION_RISK: dict[str, int] = {
    # Low risk — read-only, no side effects
    "file_read": 5,
    "search": 5,
    "fetch": 5,
    "weather": 2,
    "calendar_read": 5,
    # Medium risk — local writes, code changes
    "file_write": 35,
    "file_edit": 35,
    "exec": 60,
    "git_op": 30,
    # High risk — privileged operations
    "git_push": 65,
    "docker_exec": 75,
    "send_email": 50,
    "send_message": 30,
    # Critical — destructive
    "rm": 95,
    "drop_table": 95,
    "format_disk": 100,
    "kill_process": 70,
    "sudo": 90,
}

# Args that, if present, multiply risk.  Each entry is a callable
# that takes the args dict and returns a (delta, reason) pair.
def _contains(args: dict[str, Any], key: str, *bad_values: Any) -> tuple[int, str]:
    if key in args and args[key] in bad_values:
        return 20, f"arg {key}={args[key]!r}"
    return 0, ""


def _has_sudo(args: dict[str, Any]) -> tuple[int, str]:
    cmd = str(args.get("command", "") or args.get("cmd", ""))
    if "sudo" in cmd or "su -" in cmd:
        return 25, "contains sudo/su"
    return 0, ""


def _destructive_path(args: dict[str, Any]) -> tuple[int, str]:
    path = str(args.get("path", "") or args.get("file_path", ""))
    if not path:
        return 0, ""
    if path.startswith("/etc/") or path.startswith("/boot/") or path.startswith("/sys/"):
        return 30, f"system path {path}"
    if path.startswith("/"):
        return 10, f"absolute path {path}"
    if ".." in path:
        return 20, f"path traversal {path}"
    return 0, ""


ARG_RISK_FACTORS: list[Callable[[dict[str, Any]], tuple[int, str]]] = [
    lambda args: _contains(args, "recursive", True, "true", "True", "yes"),
    lambda args: _contains(args, "force", True, "true", "True", "yes"),
    lambda args: _contains(args, "operation", "delete", "drop", "truncate"),
    _has_sudo,
    _destructive_path,
]


__all__ = [
    "Verdict",
    "RiskLevel",
    "TrustTier",
    "RISK_BANDS",
    "risk_level_for",
    "PolicyRequest",
    "PolicyDecision",
    "ApprovalRequest",
    "DEFAULT_ACTION_RISK",
    "ARG_RISK_FACTORS",
]
