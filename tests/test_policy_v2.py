"""Tests for app.core.policy_v2."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.core.policy_v2 import (
    DEFAULT_ACTION_RISK,
    RISK_BANDS,
    ApprovalRequest,
    ApprovalStore,
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
    RiskLevel,
    ThresholdConfig,
    TrustStore,
    TrustTier,
    Verdict,
    risk_level_for,
)


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


class TestRiskLevel:
    def test_risk_level_for(self) -> None:
        assert risk_level_for(0) == "low"
        assert risk_level_for(25) == "low"
        assert risk_level_for(26) == "medium"
        assert risk_level_for(50) == "medium"
        assert risk_level_for(51) == "high"
        assert risk_level_for(75) == "high"
        assert risk_level_for(76) == "critical"
        assert risk_level_for(100) == "critical"
        assert risk_level_for(200) == "critical"  # clamps

    def test_risk_bands(self) -> None:
        assert RISK_BANDS[0] == (25, "low")
        assert RISK_BANDS[1] == (50, "medium")
        assert RISK_BANDS[2] == (75, "high")
        assert RISK_BANDS[3] == (100, "critical")


class TestPolicyRequest:
    def test_minimal(self) -> None:
        r = PolicyRequest(user_id="u1", action="list_files")
        assert r.user_id == "u1"
        assert r.action == "list_files"
        assert r.target is None
        assert r.args == {}
        assert r.context == {}

    def test_full(self) -> None:
        r = PolicyRequest(
            user_id="u1",
            action="exec",
            target="/tmp",
            args={"command": "ls"},
            context={"platform": "cli"},
            agent="a1",
            platform="cli",
        )
        assert r.target == "/tmp"
        assert r.args == {"command": "ls"}
        assert r.agent == "a1"


# ---------------------------------------------------------------------------
# ThresholdConfig
# ---------------------------------------------------------------------------


class TestThresholdConfig:
    def test_defaults(self) -> None:
        cfg = ThresholdConfig()
        assert cfg.ask_threshold == 50
        assert cfg.deny_threshold == 85
        assert TrustTier.ADMIN in cfg.tier_damping
        assert cfg.tier_damping[TrustTier.ADMIN] == 0.0

    def test_custom(self) -> None:
        cfg = ThresholdConfig(ask_threshold=20, deny_threshold=70)
        assert cfg.ask_threshold == 20
        assert cfg.deny_threshold == 70


# ---------------------------------------------------------------------------
# TrustStore
# ---------------------------------------------------------------------------


@pytest.fixture
def trust_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestTrustStore:
    def test_default_tier_is_untrusted(self, trust_dir: Path) -> None:
        ts = TrustStore(trust_dir / "t.jsonl")
        assert ts.get_tier("newuser") == TrustTier.UNTRUSTED

    def test_promote_to_new_after_first_safe_use(self, trust_dir: Path) -> None:
        ts = TrustStore(trust_dir / "t.jsonl")
        ts.record_safe_use("u1")
        assert ts.get_tier("u1") == TrustTier.NEW

    def test_persistence_across_instances(self, trust_dir: Path) -> None:
        path = trust_dir / "t.jsonl"
        ts1 = TrustStore(path)
        ts1.record_safe_use("u1")
        ts1.record_safe_use("u1")
        ts2 = TrustStore(path)
        assert ts2.get_tier("u1") == TrustTier.NEW
        assert ts2.get("u1").safe_uses == 2

    def test_demote_after_repeated_denials(self, trust_dir: Path) -> None:
        path = trust_dir / "t.jsonl"
        ts = TrustStore(path)
        ts.set_tier("u1", TrustTier.ESTABLISHED)
        for _ in range(5):
            ts.record_denial("u1")
        assert ts.get_tier("u1") == TrustTier.UNTRUSTED

    def test_safe_use_forgives_one_denial(self, trust_dir: Path) -> None:
        path = trust_dir / "t.jsonl"
        ts = TrustStore(path)
        ts.set_tier("u1", TrustTier.NEW)
        ts.record_denial("u1")
        ts.record_denial("u1")
        ts.record_safe_use("u1")
        assert ts.get("u1").recent_denials == 1

    def test_set_tier_explicit(self, trust_dir: Path) -> None:
        ts = TrustStore(trust_dir / "t.jsonl")
        ts.set_tier("u1", TrustTier.TRUSTED)
        assert ts.get_tier("u1") == TrustTier.TRUSTED

    def test_stats(self, trust_dir: Path) -> None:
        ts = TrustStore(trust_dir / "t.jsonl")
        ts.set_tier("a", TrustTier.ADMIN)
        ts.set_tier("b", TrustTier.TRUSTED)
        ts.set_tier("c", TrustTier.TRUSTED)
        stats = ts.stats()
        assert stats["admin"] == 1
        assert stats["trusted"] == 2

    def test_all_records(self, trust_dir: Path) -> None:
        ts = TrustStore(trust_dir / "t.jsonl")
        ts.set_tier("a", TrustTier.TRUSTED)
        ts.set_tier("b", TrustTier.NEW)
        records = ts.all_records()
        assert len(records) == 2
        assert {r.user_id for r in records} == {"a", "b"}


# ---------------------------------------------------------------------------
# ApprovalStore
# ---------------------------------------------------------------------------


def _make_approval(
    user_id: str = "u1",
    action: str = "rm",
    expires_in: timedelta = timedelta(hours=1),
) -> ApprovalRequest:
    decision = PolicyDecision(
        request_id=str(uuid.uuid4()),
        verdict=Verdict.ASK,
        risk_score=70,
        risk_level=RiskLevel.HIGH,
        trust_tier=TrustTier.NEW,
        reasons=["test"],
    )
    return ApprovalRequest(
        id=str(uuid.uuid4()),
        decision=decision,
        request=PolicyRequest(user_id=user_id, action=action),
        expires_at=datetime.now(timezone.utc) + expires_in,
    )


class TestApprovalStore:
    def test_enqueue_and_get(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a = _make_approval()
        store.enqueue(a)
        fetched = store.get(a.id)
        assert fetched is not None
        assert fetched.id == a.id

    def test_pending_filters_expired(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a = _make_approval(expires_in=timedelta(milliseconds=1))
        store.enqueue(a)
        time.sleep(0.05)
        pending = store.pending()
        assert pending == []  # expired

    def test_pending_includes_unexpired(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a = _make_approval()
        store.enqueue(a)
        pending = store.pending()
        assert len(pending) == 1
        assert pending[0].id == a.id

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jsonl"
        s1 = ApprovalStore(path)
        a = _make_approval()
        s1.enqueue(a)
        s2 = ApprovalStore(path)
        assert s2.get(a.id) is not None

    def test_purge_resolved(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a = _make_approval()
        store.enqueue(a)
        a.status = "approved"
        a.resolved_at = datetime.now(timezone.utc)
        store._rewrite()
        n = store.purge_resolved()
        assert n == 1
        assert store.get(a.id) is None

    def test_all_returns_sorted(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a1 = _make_approval(action="x")
        a2 = _make_approval(action="y")
        store.enqueue(a1)
        time.sleep(0.01)
        store.enqueue(a2)
        all_approvals = store.all()
        assert all_approvals[0].id == a2.id  # newest first

    def test_expire_old(self, tmp_path: Path) -> None:
        store = ApprovalStore(tmp_path / "a.jsonl")
        a = _make_approval(expires_in=timedelta(milliseconds=1))
        store.enqueue(a)
        time.sleep(0.05)
        n = store.expire_old()
        assert n == 1
        expired = store.get(a.id)
        assert expired is not None
        assert expired.status == "expired"


# ---------------------------------------------------------------------------
# PolicyEngine — basic verdict logic
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path: Path) -> PolicyEngine:
    return PolicyEngine(
        trust_store=TrustStore(tmp_path / "trust.jsonl"),
        approval_store=ApprovalStore(tmp_path / "approvals.jsonl"),
    )


class TestPolicyEngineBasic:
    def test_list_files_is_low_risk(self, engine: PolicyEngine) -> None:
        r = engine.evaluate(PolicyRequest(user_id="u1", action="list_files"))
        assert r.verdict == Verdict.ALLOW
        # list_files has no entry in DEFAULT_ACTION_RISK → base 30
        assert r.risk_score <= 30

    def test_rm_is_critical(self, engine: PolicyEngine) -> None:
        r = engine.evaluate(PolicyRequest(user_id="u1", action="rm"))
        assert r.verdict == Verdict.DENY
        assert r.risk_score >= 85

    def test_unknown_action_uses_default_medium(self, engine: PolicyEngine) -> None:
        # Unknown actions default to "medium" base 30 (conservative).
        r = engine.evaluate(PolicyRequest(user_id="u1", action="frobnicate"))
        assert r.risk_score == 30
        assert r.verdict == Verdict.ALLOW

    def test_admin_is_always_allowed(self, tmp_path: Path) -> None:
        trust = TrustStore(tmp_path / "t.jsonl")
        trust.set_tier("admin1", TrustTier.ADMIN)
        e = PolicyEngine(
            trust_store=trust,
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
        )
        r = e.evaluate(PolicyRequest(user_id="admin1", action="rm"))
        assert r.verdict == Verdict.ALLOW
        assert r.adjusted_score == 0
        assert "admin tier" in r.reasons

    def test_trust_tier_in_decision(self, engine: PolicyEngine) -> None:
        r = engine.evaluate(PolicyRequest(user_id="u1", action="list_files"))
        assert r.trust_tier == TrustTier.UNTRUSTED  # first time seen

    def test_always_allow_user(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            always_allow_users={"boss"},
        )
        r = e.evaluate(PolicyRequest(user_id="boss", action="rm"))
        assert r.verdict == Verdict.ALLOW
        assert "always-allow" in " ".join(r.reasons)

    def test_always_allow_action(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            always_allow_actions={"git_op"},
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="git_op"))
        assert r.verdict == Verdict.ALLOW

    def test_always_deny_user(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            always_deny_users={"attacker"},
        )
        r = e.evaluate(PolicyRequest(user_id="attacker", action="list_files"))
        assert r.verdict == Verdict.DENY

    def test_always_deny_action(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            always_deny_actions={"format_disk"},
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="format_disk"))
        assert r.verdict == Verdict.DENY


# ---------------------------------------------------------------------------
# Trust-tier damping
# ---------------------------------------------------------------------------


class TestTrustDamping:
    def test_trusted_reduces_score(self, tmp_path: Path) -> None:
        trust = TrustStore(tmp_path / "t.jsonl")
        trust.set_tier("u1", TrustTier.TRUSTED)
        e = PolicyEngine(
            trust_store=trust,
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        # git_push base = 65; * 0.7 = 45.5 → rounds to 46
        assert r.adjusted_score < r.risk_score
        assert r.adjusted_score == round(r.risk_score * 0.7)

    def test_untrusted_amplifies_score(self, tmp_path: Path) -> None:
        trust = TrustStore(tmp_path / "t.jsonl")
        trust.set_tier("u1", TrustTier.UNTRUSTED)
        e = PolicyEngine(
            trust_store=trust,
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        assert r.adjusted_score > r.risk_score
        assert r.adjusted_score == round(r.risk_score * 1.3)

    def test_established_is_near_one(self, tmp_path: Path) -> None:
        trust = TrustStore(tmp_path / "t.jsonl")
        trust.set_tier("u1", TrustTier.ESTABLISHED)
        e = PolicyEngine(
            trust_store=trust,
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        assert r.adjusted_score == round(r.risk_score * 0.9)


# ---------------------------------------------------------------------------
# Arg risk factors
# ---------------------------------------------------------------------------


class TestArgRiskFactors:
    def test_recursive_flag_adds_risk(self, engine: PolicyEngine) -> None:
        baseline = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "a.txt"})
        )
        recursive = engine.evaluate(
            PolicyRequest(
                user_id="u1", action="file_edit", args={"path": "a.txt", "recursive": True}
            )
        )
        assert recursive.risk_score > baseline.risk_score

    def test_force_flag_adds_risk(self, engine: PolicyEngine) -> None:
        baseline = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "a.txt"})
        )
        forced = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "a.txt", "force": True})
        )
        assert forced.risk_score > baseline.risk_score

    def test_sudo_in_command_adds_risk(self, engine: PolicyEngine) -> None:
        baseline = engine.evaluate(
            PolicyRequest(user_id="u1", action="exec", args={"command": "ls"})
        )
        sudo = engine.evaluate(
            PolicyRequest(user_id="u1", action="exec", args={"command": "sudo apt update"})
        )
        assert sudo.risk_score > baseline.risk_score
        assert any("sudo" in r for r in sudo.reasons)

    def test_system_path_adds_risk(self, engine: PolicyEngine) -> None:
        baseline = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "a.txt"})
        )
        system = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "/etc/passwd"})
        )
        assert system.risk_score > baseline.risk_score
        assert any("/etc/" in r for r in system.reasons)

    def test_path_traversal_adds_risk(self, engine: PolicyEngine) -> None:
        r = engine.evaluate(
            PolicyRequest(user_id="u1", action="file_edit", args={"path": "../../etc/passwd"})
        )
        assert any("traversal" in s for s in r.reasons)

    def test_extra_risk_factors(self, tmp_path: Path) -> None:
        # Extra factors take the args dict (same as ARG_RISK_FACTORS).
        def my_factor(args: dict[str, Any]) -> tuple[int, str]:
            if args.get("secret"):
                return 50, "secret arg present"
            return 0, ""

        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            extra_risk_factors=[my_factor],
        )
        r1 = e.evaluate(PolicyRequest(user_id="u1", action="list_files"))
        r2 = e.evaluate(PolicyRequest(user_id="u1", action="list_files", args={"secret": True}))
        assert r2.risk_score > r1.risk_score
        assert any("secret" in s for s in r2.reasons)


# ---------------------------------------------------------------------------
# ASK verdict → approval queue
# ---------------------------------------------------------------------------


class TestAskVerdict:
    def test_mid_risk_triggers_ask(self, engine: PolicyEngine) -> None:
        # git_push base=65; untrusted * 1.3 = 84 → deny
        # Use a tier that brings it to 50-85 range
        engine.trust.set_tier("u1", TrustTier.ESTABLISHED)
        # base=65, * 0.9 = 58 → ask
        r = engine.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        assert r.verdict == Verdict.ASK

    def test_ask_creates_approval(self, engine: PolicyEngine) -> None:
        engine.trust.set_tier("u1", TrustTier.ESTABLISHED)
        r = engine.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        assert r.verdict == Verdict.ASK
        assert r.approval_id is not None
        pending = engine.approvals.pending()
        assert len(pending) == 1
        assert pending[0].id == r.approval_id

    def test_resolve_approval(self, engine: PolicyEngine) -> None:
        engine.trust.set_tier("u1", TrustTier.ESTABLISHED)
        r = engine.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        approval_id = r.approval_id
        assert approval_id is not None
        approval = engine.resolve_approval(
            approval_id, approved=True, resolved_by="admin1", note="ok"
        )
        assert approval.status == "approved"
        assert approval.resolved_by == "admin1"
        assert approval.resolution_note == "ok"
        a = engine.approvals.get(approval_id)
        assert a is not None
        assert a.status == "approved"
        assert a.resolved_by == "admin1"
        assert a.resolution_note == "ok"

    def test_resolve_unknown_approval_raises(self, engine: PolicyEngine) -> None:
        with pytest.raises(KeyError):
            engine.resolve_approval("nonexistent", approved=True, resolved_by="admin1")

    def test_approval_includes_request(self, engine: PolicyEngine) -> None:
        engine.trust.set_tier("u1", TrustTier.ESTABLISHED)
        r = engine.evaluate(PolicyRequest(user_id="u1", action="git_push", target="main"))
        assert r.approval_id is not None
        a = engine.approvals.get(r.approval_id)
        assert a is not None
        assert a.request is not None
        assert a.request.user_id == "u1"
        assert a.request.target == "main"


# ---------------------------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------------------------


class TestThresholds:
    def test_lower_ask_threshold_asks_more(self, tmp_path: Path) -> None:
        # Default ask_threshold=50, so adjusted=49 should ALLOW.
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            thresholds=ThresholdConfig(ask_threshold=10, deny_threshold=85),
        )
        e.trust.set_tier("u1", TrustTier.TRUSTED)
        r = e.evaluate(PolicyRequest(user_id="u1", action="git_push"))
        # git_push base 65 * 0.7 = 45 → ASK with new threshold
        assert r.verdict == Verdict.ASK

    def test_higher_deny_threshold_denies_less(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            thresholds=ThresholdConfig(ask_threshold=50, deny_threshold=100),
        )
        # rm base 95 + /etc path +30 = 125 → still deny if 100 >= 95
        r = e.evaluate(PolicyRequest(user_id="u1", action="rm"))
        assert r.verdict == Verdict.DENY  # still denied because score > 100

    def test_higher_deny_threshold_allows_rm(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            thresholds=ThresholdConfig(ask_threshold=20, deny_threshold=200),
        )
        # rm = 95, < 200 → ASK not DENY
        r = e.evaluate(PolicyRequest(user_id="u1", action="rm"))
        assert r.verdict == Verdict.ASK


# ---------------------------------------------------------------------------
# Custom action risk table
# ---------------------------------------------------------------------------


class TestCustomActionRisk:
    def test_override_action_risk(self, tmp_path: Path) -> None:
        e = PolicyEngine(
            trust_store=TrustStore(tmp_path / "t.jsonl"),
            approval_store=ApprovalStore(tmp_path / "a.jsonl"),
            action_risk={"my_action": 10},
        )
        r = e.evaluate(PolicyRequest(user_id="u1", action="my_action"))
        assert r.risk_score == 10

    def test_default_table_contains_critical(self) -> None:
        assert "rm" in DEFAULT_ACTION_RISK
        assert "sudo" in DEFAULT_ACTION_RISK
        assert "format_disk" in DEFAULT_ACTION_RISK
        assert DEFAULT_ACTION_RISK["rm"] == 95
        assert DEFAULT_ACTION_RISK["format_disk"] == 100


# ---------------------------------------------------------------------------
# Concurrency / thread safety
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_evaluations(self, engine: PolicyEngine) -> None:
        results: list[PolicyDecision] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            r = engine.evaluate(PolicyRequest(user_id=f"u{i}", action="list_files"))
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 20
        assert all(r.verdict == Verdict.ALLOW for r in results)
        # Trust records should have been created
        assert len(engine.trust.all_records()) == 20

    def test_concurrent_enqueues(self, engine: PolicyEngine) -> None:
        engine.trust.set_tier("u1", TrustTier.ESTABLISHED)

        def worker() -> None:
            engine.evaluate(PolicyRequest(user_id="u1", action="git_push"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All 10 should have created ASK requests
        assert len(engine.approvals.pending()) == 10
