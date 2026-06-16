"""Policy engine v2 (part of A4 in the foundation plan).

The policy engine is the single gate between the runtime and a
tool call.  It computes a per-action risk score, applies a
trust-tier damping factor, and returns a verdict:

- :class:`Verdict.ALLOW` — proceed
- :class:`Verdict.ASK`   — require explicit approval (queued)
- :class:`Verdict.DENY`  — block the call entirely

Public API:
- :class:`PolicyEngine` — the main entry point.  Call
  :meth:`evaluate` with a :class:`PolicyRequest` and get a
  :class:`PolicyDecision`.  Use :meth:`resolve_approval` to
  record the outcome of a pending approval.
- :class:`ThresholdConfig` — tunable risk thresholds.
- :class:`TrustStore`, :class:`ApprovalStore` — persistent
  backends for trust tiers and the approval queue.
- Types: :class:`PolicyRequest`, :class:`PolicyDecision`,
  :class:`ApprovalRequest`, :class:`TrustTier`, :class:`Verdict`,
  :class:`RiskLevel`.
"""

from app.core.policy_v2.engine import PolicyEngine, ThresholdConfig
from app.core.policy_v2.store import (
    DEFAULT_APPROVAL_PATH,
    DEFAULT_TRUST_PATH,
    ApprovalStore,
    TrustRecord,
    TrustStore,
)
from app.core.policy_v2.types import (
    ARG_RISK_FACTORS,
    DEFAULT_ACTION_RISK,
    RISK_BANDS,
    ApprovalRequest,
    PolicyDecision,
    PolicyRequest,
    RiskLevel,
    TrustTier,
    Verdict,
    risk_level_for,
)

__all__ = [
    # Engine
    "PolicyEngine",
    "ThresholdConfig",
    # Stores
    "TrustStore",
    "TrustRecord",
    "ApprovalStore",
    "DEFAULT_TRUST_PATH",
    "DEFAULT_APPROVAL_PATH",
    # Types
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
