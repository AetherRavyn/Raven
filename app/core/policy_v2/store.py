"""Persistent stores for trust tiers and approval queue.

These are deliberately small, in-process, JSONL-backed stores.
They are designed to survive a restart (rebuild from disk on
init) and to be queryable from a dashboard.

For multi-host deployments, swap the backing JSONL for HelixDB KV;
the public API is the same.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.policy_v2.types import (
    ApprovalRequest,
    TrustTier,
)

logger = logging.getLogger(__name__)


DEFAULT_TRUST_PATH = Path("workspace/state/trust.jsonl")
DEFAULT_APPROVAL_PATH = Path("workspace/state/approvals.jsonl")


# ---------------------------------------------------------------------------
# Trust store
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrustRecord:
    user_id: str
    tier: TrustTier
    safe_uses: int = 0
    last_used: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Track recent misuse so we can decay trust on bad behavior.
    recent_denials: int = 0
    last_decision_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tier": self.tier.value,
            "safe_uses": self.safe_uses,
            "last_used": self.last_used.isoformat(),
            "recent_denials": self.recent_denials,
            "last_decision_at": self.last_decision_at.isoformat(),
            "first_seen": self.first_seen.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrustRecord":
        return cls(
            user_id=d["user_id"],
            tier=TrustTier(d.get("tier", "untrusted")),
            safe_uses=int(d.get("safe_uses", 0)),
            last_used=datetime.fromisoformat(d["last_used"]),
            recent_denials=int(d.get("recent_denials", 0)),
            last_decision_at=datetime.fromisoformat(d["last_decision_at"]),
            first_seen=datetime.fromisoformat(d["first_seen"]),
        )


class TrustStore:
    """Per-user trust records, persisted to JSONL.

    Trust promotion rules:
    - ``UNTRUSTED`` (default) → ``NEW`` after 1st safe use
    - ``NEW`` → ``ESTABLISHED`` after 7 days + 10 safe uses
    - ``ESTABLISHED`` → ``TRUSTED`` after 30 days + 100 safe uses

    Trust demotion (recent denials):
    - any tier → ``UNTRUSTED`` after 5 recent denials
    """

    PROMOTION_RULES = [
        # (min_age, min_safe_uses, target_tier)
        (timedelta(days=30), 100, TrustTier.TRUSTED),
        (timedelta(days=7), 10, TrustTier.ESTABLISHED),
        (timedelta(0), 1, TrustTier.NEW),
    ]
    DEMOTION_THRESHOLD = 5

    def __init__(self, path: Path | str = DEFAULT_TRUST_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, TrustRecord] = {}
        self._lock = threading.RLock()
        self._loaded = False
        self._load()

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            self._loaded = True
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        r = TrustRecord.from_dict(d)
                        self._records[r.user_id] = r
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except OSError as e:
            logger.error("trust store load failed: %s", e)
        self._loaded = True

    def _flush(self) -> None:
        with self._path.open("w", encoding="utf-8") as f:
            for r in self._records.values():
                f.write(json.dumps(r.to_dict()) + "\n")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get(self, user_id: str) -> TrustRecord:
        """Return the record for ``user_id``, creating a default if new."""
        with self._lock:
            r = self._records.get(user_id)
            if r is None:
                r = TrustRecord(user_id=user_id, tier=TrustTier.UNTRUSTED)
                self._records[user_id] = r
                self._flush()
            return r

    def get_tier(self, user_id: str) -> TrustTier:
        return self.get(user_id).tier

    def record_safe_use(self, user_id: str) -> TrustTier:
        """Bump the safe-use count and possibly promote."""
        with self._lock:
            r = self.get(user_id)
            r.safe_uses += 1
            r.last_used = datetime.now(timezone.utc)
            r.last_decision_at = r.last_used
            r.recent_denials = max(0, r.recent_denials - 1)  # forgive one
            self._maybe_promote(r)
            self._flush()
        return r.tier

    def record_denial(self, user_id: str) -> TrustTier:
        """Note a denial and possibly demote."""
        with self._lock:
            r = self.get(user_id)
            r.recent_denials += 1
            r.last_decision_at = datetime.now(timezone.utc)
            if r.recent_denials >= self.DEMOTION_THRESHOLD:
                r.tier = TrustTier.UNTRUSTED
            self._flush()
        return r.tier

    def set_tier(self, user_id: str, tier: TrustTier | str) -> None:
        if not isinstance(tier, TrustTier):
            tier = TrustTier(str(tier))
        with self._lock:
            r = self.get(user_id)
            r.tier = tier
            r.last_decision_at = datetime.now(timezone.utc)
            self._flush()

    def all_records(self) -> list[TrustRecord]:
        with self._lock:
            return list(self._records.values())

    def stats(self) -> dict[str, int]:
        with self._lock:
            out: dict[str, int] = defaultdict(int)
            for r in self._records.values():
                out[r.tier.value] += 1
        return dict(out)

    def _maybe_promote(self, r: TrustRecord) -> None:
        if r.tier == TrustTier.TRUSTED:
            return  # already at the top
        if r.tier == TrustTier.UNTRUSTED:
            # Need at least one safe use to leave UNTRUSTED.
            if r.safe_uses >= 1:
                r.tier = TrustTier.NEW
            return
        now = datetime.now(timezone.utc)
        age = now - r.first_seen
        for min_age, min_uses, target in self.PROMOTION_RULES:
            if target == r.tier:
                # We only consider promoting *above* the current tier.
                continue
            if (
                age >= min_age
                and r.safe_uses >= min_uses
                and self._tier_order(target) > self._tier_order(r.tier)
            ):
                r.tier = target
                return

    @staticmethod
    def _tier_order(t: TrustTier) -> int:
        return {
            TrustTier.UNTRUSTED: 0,
            TrustTier.NEW: 1,
            TrustTier.ESTABLISHED: 2,
            TrustTier.TRUSTED: 3,
            TrustTier.ADMIN: 4,
        }.get(t, 0)


# ---------------------------------------------------------------------------
# Approval store
# ---------------------------------------------------------------------------


class ApprovalStore:
    """Pending and recently-resolved approval requests.

    The store keeps an in-memory mirror of the on-disk JSONL so
    queries are fast.  The JSONL is the source of truth; the
    in-memory mirror is rebuilt on first use.
    """

    def __init__(self, path: Path | str = DEFAULT_APPROVAL_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._approvals: dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()
        self._loaded = False
        self._load()

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            self._loaded = True
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        a = _approval_from_dict(d)
                        self._approvals[a.id] = a
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except OSError as e:
            logger.error("approval store load failed: %s", e)
        self._loaded = True

    def _append(self, approval: ApprovalRequest) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(approval.to_dict(), default=str) + "\n")

    def _rewrite(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for a in self._approvals.values():
                f.write(json.dumps(a.to_dict(), default=str) + "\n")
        try:
            tmp.replace(self._path)
        except OSError:
            # Fallback: leave the temp, it's the same content.
            pass

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def enqueue(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            self._approvals[approval.id] = approval
            self._append(approval)
        return approval

    def get(self, approval_id: str) -> ApprovalRequest | None:
        self._load()
        with self._lock:
            return self._approvals.get(approval_id)

    def pending(self) -> list[ApprovalRequest]:
        self._load()
        with self._lock:
            return sorted(
                (a for a in self._approvals.values() if a.status == "pending" and not a.is_expired),
                key=lambda a: a.created_at,
            )

    def all(self) -> list[ApprovalRequest]:
        self._load()
        with self._lock:
            return sorted(
                self._approvals.values(),
                key=lambda a: a.created_at,
                reverse=True,
            )

    def expire_old(self) -> int:
        """Mark expired-but-still-pending approvals as ``expired``.

        Returns the number of approvals that were expired in this
        pass.  Callers may run this on a schedule.
        """
        self._load()
        with self._lock:
            n = 0
            for a in self._approvals.values():
                if a.status == "pending" and a.is_expired:
                    a.status = "expired"
                    a.resolved_at = datetime.now(timezone.utc)
                    n += 1
            if n:
                self._rewrite()
        return n

    def purge_resolved(self, older_than: timedelta | None = None) -> int:
        """Drop resolved approvals from memory + disk.

        Returns the count removed.  ``older_than=None`` removes all
        non-pending approvals.
        """
        self._load()
        now = datetime.now(timezone.utc)
        with self._lock:
            to_drop: list[str] = []
            for a in self._approvals.values():
                if a.status == "pending":
                    continue
                if older_than is not None:
                    if a.resolved_at is None or (now - a.resolved_at) < older_than:
                        continue
                to_drop.append(a.id)
            for aid in to_drop:
                self._approvals.pop(aid, None)
            if to_drop:
                self._rewrite()
        return len(to_drop)


def _approval_from_dict(d: dict[str, Any]) -> ApprovalRequest:
    from app.core.policy_v2.types import (
        PolicyDecision,
        PolicyRequest,
        RiskLevel,
        TrustTier,
        Verdict,
    )

    dec_d = d.get("decision", {})
    dec = PolicyDecision(
        request_id=dec_d.get("request_id", ""),
        verdict=Verdict(dec_d.get("verdict", "ask")),
        risk_score=int(dec_d.get("risk_score", 0)),
        risk_level=RiskLevel(dec_d.get("risk_level", "low")),
        trust_tier=TrustTier(dec_d.get("trust_tier", "untrusted")),
        reasons=list(dec_d.get("reasons", [])),
        approval_id=dec_d.get("approval_id"),
        adjusted_score=int(dec_d.get("adjusted_score", 0)),
        timestamp=datetime.fromisoformat(dec_d["timestamp"])
        if "timestamp" in dec_d
        else datetime.now(timezone.utc),
    )
    req_d = d.get("request")
    req = None
    if req_d is not None:
        req = PolicyRequest(
            user_id=req_d.get("user_id", ""),
            action=req_d.get("action", ""),
            target=req_d.get("target"),
            args=dict(req_d.get("args", {})),
            context=dict(req_d.get("context", {})),
            agent=req_d.get("agent"),
            platform=req_d.get("platform"),
        )
    return ApprovalRequest(
        id=d.get("id", ""),
        decision=dec,
        request=req,
        status=d.get("status", "pending"),
        created_at=datetime.fromisoformat(d["created_at"])
        if "created_at" in d
        else datetime.now(timezone.utc),
        expires_at=datetime.fromisoformat(d["expires_at"])
        if "expires_at" in d
        else datetime.now(timezone.utc) + timedelta(hours=1),
        resolved_at=datetime.fromisoformat(d["resolved_at"]) if d.get("resolved_at") else None,
        resolved_by=d.get("resolved_by"),
        resolution_note=d.get("resolution_note"),
    )


__all__ = [
    "TrustRecord",
    "TrustStore",
    "ApprovalStore",
    "DEFAULT_TRUST_PATH",
    "DEFAULT_APPROVAL_PATH",
]
