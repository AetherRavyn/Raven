"""Policy engine v2.

The engine is the single gate between the runtime and a tool call.
It takes a :class:`PolicyRequest` and returns a :class:`PolicyDecision`
with verdict (``allow`` / ``ask`` / ``deny``) and risk metadata.

Pipeline
--------
1. Compute the raw risk score for the action (table lookup) +
   per-arg risk factors.
2. Apply trust-tier damping: trusted users get their risk reduced,
   untrusted users amplified.
3. Compare the adjusted score against the configured thresholds to
   pick a verdict.
4. If ``ask``, push an :class:`ApprovalRequest` to the queue and
   record an audit event.

The engine is async for the parts that talk to the audit log
(HelixDB KV write) but the decision itself is pure CPU.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.audit import AuditEvent, AuditKind, AuditLog
from app.core.audit.types import RiskLevel as AuditRiskLevel
from app.core.policy_v2.store import ApprovalStore, TrustStore
from app.core.policy_v2.types import (
    ARG_RISK_FACTORS,
    DEFAULT_ACTION_RISK,
    ApprovalRequest,
    PolicyDecision,
    PolicyRequest,
    RiskLevel,
    TrustTier,
    Verdict,
    risk_level_for,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ThresholdConfig:
    """Tunable thresholds for the policy engine.

    ``ask_threshold`` is the inclusive lower bound for asking; scores
    at or above this trigger :class:`Verdict.ASK` (or :class:`Verdict.DENY`
    if they also meet ``deny_threshold``).  ``deny_threshold`` is the
    inclusive lower bound for outright denial.
    """

    ask_threshold: int = 50
    deny_threshold: int = 85
    # Trust-tier damping: each tier is a multiplier on the raw score.
    # < 1.0 reduces risk (trusted), > 1.0 amplifies (untrusted).
    tier_damping: dict[TrustTier, float] = field(
        default_factory=lambda: {
            TrustTier.ADMIN: 0.0,       # admins always allowed
            TrustTier.TRUSTED: 0.7,
            TrustTier.ESTABLISHED: 0.9,
            TrustTier.NEW: 1.0,
            TrustTier.UNTRUSTED: 1.3,
        }
    )


class PolicyEngine:
    """The policy gate.

    Stateless except for the trust store, the approval store, and
    the audit log.  Multiple engines can coexist (e.g. one per
    tenant) without coordination.
    """

    def __init__(
        self,
        *,
        trust_store: TrustStore | None = None,
        approval_store: ApprovalStore | None = None,
        audit_log: AuditLog | None = None,
        thresholds: ThresholdConfig | None = None,
        action_risk: dict[str, int] | None = None,
        # Users / actions that are always allowed, regardless of risk.
        always_allow_users: Iterable[str] = (),
        always_allow_actions: Iterable[str] = (),
        # Users / actions that are always denied.
        always_deny_users: Iterable[str] = (),
        always_deny_actions: Iterable[str] = (),
        # Custom risk factors.  Each is a callable that takes the
        # request and returns a (delta, reason) pair.
        extra_risk_factors: Iterable[Any] = (),
    ) -> None:
        self.trust = trust_store or TrustStore()
        self.approvals = approval_store or ApprovalStore()
        self.audit = audit_log
        self.thresholds = thresholds or ThresholdConfig()
        self.action_risk = dict(action_risk or DEFAULT_ACTION_RISK)
        self._always_allow_users = {str(u) for u in always_allow_users}
        self._always_allow_actions = {str(a) for a in always_allow_actions}
        self._always_deny_users = {str(u) for u in always_deny_users}
        self._always_deny_actions = {str(a) for a in always_deny_actions}
        self._extra_factors = list(extra_risk_factors)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        """Evaluate a request synchronously.  See class docstring for
        the pipeline.
        """
        request_id = uuid.uuid4().hex
        reasons: list[str] = []

        # 1. Hard deny/allow
        if request.user_id in self._always_deny_users:
            return self._build_decision(
                request_id,
                request,
                Verdict.DENY,
                100,
                RiskLevel.CRITICAL,
                reasons=["user in always-deny list"],
            )
        if request.action in self._always_deny_actions:
            return self._build_decision(
                request_id,
                request,
                Verdict.DENY,
                100,
                RiskLevel.CRITICAL,
                reasons=["action in always-deny list"],
            )
        if request.user_id in self._always_allow_users:
            return self._build_decision(
                request_id,
                request,
                Verdict.ALLOW,
                0,
                RiskLevel.LOW,
                reasons=["user in always-allow list"],
            )
        if request.action in self._always_allow_actions:
            return self._build_decision(
                request_id,
                request,
                Verdict.ALLOW,
                0,
                RiskLevel.LOW,
                reasons=["action in always-allow list"],
            )

        # 2. Compute raw risk score
        raw_score, risk_factors = self._compute_risk(request)
        if request.risk_score is not None:
            raw_score = max(raw_score, request.risk_score)
            reasons.append(
                f"caller-supplied score {request.risk_score} (max with computed)"
            )
        reasons.extend(risk_factors)

        # 3. Trust tier + damping
        tier = self.trust.get_tier(request.user_id)
        if tier == TrustTier.ADMIN:
            return self._build_decision(
                request_id,
                request,
                Verdict.ALLOW,
                0,
                RiskLevel.LOW,
                reasons=["admin tier"],
            )
        damping = self.thresholds.tier_damping.get(tier, 1.0)
        adjusted = int(round(raw_score * damping))
        adjusted = max(0, min(100, adjusted))
        reasons.append(f"tier={tier.value} damping={damping:.2f}")

        # 4. Verdict
        if adjusted >= self.thresholds.deny_threshold:
            verdict = Verdict.DENY
        elif adjusted >= self.thresholds.ask_threshold:
            verdict = Verdict.ASK
        else:
            verdict = Verdict.ALLOW

        decision = self._build_decision(
            request_id,
            request,
            verdict,
            raw_score,
            risk_level_for(adjusted),
            reasons,
            adjusted,
            tier,
        )

        # 5. If ask, enqueue an approval
        if verdict == Verdict.ASK:
            approval = ApprovalRequest(decision=decision, request=request)
            self.approvals.enqueue(approval)
            decision.approval_id = approval.id
            reasons.append(f"approval queued as {approval.id}")
            decision.reasons = reasons

        # 6. Audit
        if self.audit is not None:
            self.audit.record(
                AuditEvent(
                    kind=AuditKind.POLICY,
                    actor=request.user_id,
                    action=request.action,
                    target=request.target,
                    context={
                        "request_id": request_id,
                        "verdict": verdict.value,
                        "risk_score": raw_score,
                        "adjusted_score": adjusted,
                        "trust_tier": tier.value,
                        "platform": request.platform,
                        "agent": request.agent,
                    },
                    success=verdict != Verdict.DENY,
                    risk_level=AuditRiskLevel.CRITICAL
                    if verdict == Verdict.DENY
                    else risk_level_for(adjusted),
                    detail="; ".join(reasons),
                    metadata={"args": _truncate_args(request.args)},
                )
            )
        return decision

    async def evaluate_async(self, request: PolicyRequest) -> PolicyDecision:
        """Async wrapper for callers already in an event loop."""
        return self.evaluate(request)

    def resolve_approval(
        self, approval_id: str, *, approved: bool, resolved_by: str,
        note: str | None = None,
    ) -> ApprovalRequest:
        """Mark a pending approval as approved or denied.

        Approved requests implicitly bump the user's trust tier.
        Denied requests are recorded for the audit log but do not
        decay trust (the user *did* the right thing by asking).
        """
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"unknown approval: {approval_id}")
        with self._lock:
            approval.status = "approved" if approved else "denied"
            approval.resolved_at = datetime.now(timezone.utc)
            approval.resolved_by = resolved_by
            approval.resolution_note = note
        if approved and approval.request is not None:
            self.trust.record_safe_use(approval.request.user_id)
        if self.audit is not None:
            self.audit.record(
                AuditEvent(
                    kind=AuditKind.APPROVAL,
                    actor=resolved_by,
                    action=approval.request.action if approval.request else "approval",
                    target=approval_id,
                    context={
                        "verdict": "approved" if approved else "denied",
                        "resolved_by": resolved_by,
                        "note": note,
                    },
                    success=approved,
                )
            )
        return approval

    def pending_approvals(self) -> list[ApprovalRequest]:
        return self.approvals.pending()

    def trust_tier(self, user_id: str) -> TrustTier:
        return self.trust.get_tier(user_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_risk(
        self, request: PolicyRequest
    ) -> tuple[int, list[str]]:
        base = self.action_risk.get(request.action, 30)  # unknown action = medium
        reasons: list[str] = [f"action {request.action!r} base={base}"]
        delta_total = 0
        for fn in list(ARG_RISK_FACTORS) + self._extra_factors:
            try:
                delta, why = fn(request.args)
            except Exception as e:  # noqa: BLE001
                logger.debug("risk factor %s raised: %s", fn, e)
                continue
            if delta:
                delta_total += delta
                if why:
                    reasons.append(f"+{delta} {why}")
        score = max(0, min(100, base + delta_total))
        return score, reasons

    def _build_decision(
        self,
        request_id: str,
        request: PolicyRequest,
        verdict: Verdict,
        score: int,
        level: RiskLevel,
        reasons: list[str],
        adjusted: int | None = None,
        tier: TrustTier | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            request_id=request_id,
            verdict=verdict,
            risk_score=score,
            risk_level=level,
            trust_tier=tier or self.trust.get_tier(request.user_id),
            reasons=list(reasons),
            adjusted_score=adjusted if adjusted is not None else score,
        )


def _truncate_args(args: dict[str, Any], max_len: int = 200) -> dict[str, Any]:
    """Truncate string args so the audit log doesn't blow up."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_len:
            out[k] = v[:max_len] + f"...({len(v) - max_len} more)"
        else:
            out[k] = v
    return out


__all__ = ["PolicyEngine", "ThresholdConfig"]
