"""Tests for the audit dashboard API (FastAPI router)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.audit import AuditEvent, AuditKind, AuditLog, RiskLevel
from app.core.audit.api import build_router
from app.core.policy_v2 import ApprovalStore, PolicyEngine, TrustStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_log(tmp_path: Path) -> AuditLog:
    return AuditLog(jsonl_path=tmp_path / "audit.jsonl")


@pytest.fixture
def policy_engine(tmp_path: Path) -> PolicyEngine:
    return PolicyEngine(
        trust_store=TrustStore(tmp_path / "trust.jsonl"),
        approval_store=ApprovalStore(tmp_path / "approvals.jsonl"),
    )


@pytest.fixture
def app(audit_log: AuditLog, policy_engine: PolicyEngine) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(audit_log, policy_engine))
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _seed(audit_log: AuditLog) -> None:
    """Insert a few events into the log."""
    audit_log.record(
        AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="u1",
            action="list_files",
            target="/tmp",
            risk_level=RiskLevel.LOW,
        )
    )
    audit_log.record(
        AuditEvent(
            kind=AuditKind.POLICY,
            actor="u1",
            action="rm",
            target="/etc/passwd",
            success=False,
            risk_level=RiskLevel.CRITICAL,
            detail="denied",
        )
    )
    audit_log.record(
        AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="admin",
            action="git_push",
            target="main",
            risk_level=RiskLevel.MEDIUM,
            duration_ms=120,
            cost_usd=0.005,
        )
    )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEventsAPI:
    def test_list_all(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/events")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 3
        assert len(body["events"]) == 3

    def test_filter_by_kind(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/events?kind=policy")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["action"] == "rm"

    def test_filter_by_actor(
        self, client: TestClient, audit_log: AuditLog
    ) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/events?actor=admin")
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["actor"] == "admin"

    def test_filter_by_success(
        self, client: TestClient, audit_log: AuditLog
    ) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/events?success=false")
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["action"] == "rm"

    def test_pagination(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/events?limit=2&offset=0")
        body = r.json()
        assert body["count"] == 2
        assert body["limit"] == 2

    def test_get_by_id(
        self, client: TestClient, audit_log: AuditLog
    ) -> None:
        _seed(audit_log)
        events = audit_log.query(limit=10)
        eid = events[0].id
        r = client.get(f"/api/audit/events/{eid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == eid

    def test_get_by_id_not_found(self, client: TestClient) -> None:
        r = client.get("/api/audit/events/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStatsAPI:
    def test_basic_stats(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/stats")
        body = r.json()
        assert body["total"] == 3
        assert body["by_kind"]["tool_call"] == 2
        assert body["by_kind"]["policy"] == 1
        assert body["by_risk"]["critical"] == 1
        assert body["by_success"]["success"] == 2
        assert body["by_success"]["failure"] == 1


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class TestTimelineAPI:
    def test_text_table(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/timeline")
        assert r.status_code == 200
        body = r.text
        # Headers are uppercased; values are lowercased enum strings.
        assert "KIND" in body
        assert "tool_call" in body
        assert "list_files" in body

    def test_empty_timeline(self, client: TestClient) -> None:
        r = client.get("/api/audit/timeline")
        assert r.status_code == 200
        assert "no events" in r.text


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExportAPI:
    def test_csv_export(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/export.csv")
        assert r.status_code == 200
        body = r.text
        assert "timestamp,kind,actor" in body
        assert "list_files" in body

    def test_json_export(self, client: TestClient, audit_log: AuditLog) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/export.json")
        body = r.json()
        assert isinstance(body, list)
        assert len(body) == 3
        assert body[0]["kind"] == "tool_call"

    def test_csv_export_with_kind_filter(
        self, client: TestClient, audit_log: AuditLog
    ) -> None:
        _seed(audit_log)
        r = client.get("/api/audit/export.csv?kind=policy")
        body = r.text
        assert "rm" in body
        # The list_files row should be excluded.
        lines = body.strip().splitlines()
        assert len(lines) == 2  # header + 1


# ---------------------------------------------------------------------------
# Approvals queue
# ---------------------------------------------------------------------------


class TestApprovalsAPI:
    def test_list_pending_empty(self, client: TestClient) -> None:
        r = client.get("/api/audit/approvals/pending")
        body = r.json()
        assert body["count"] == 0
        assert body["approvals"] == []

    def test_list_pending_after_ask(
        self, client: TestClient, policy_engine: PolicyEngine
    ) -> None:
        # Set up an ASK scenario: established user + git_push.
        policy_engine.trust.set_tier("u1", "established")
        policy_engine.evaluate(
            _make_request("u1", "git_push", {"branch": "main"})
        )
        r = client.get("/api/audit/approvals/pending")
        body = r.json()
        assert body["count"] == 1
        assert body["approvals"][0]["status"] == "pending"

    def test_resolve_approval(
        self,
        client: TestClient,
        policy_engine: PolicyEngine,
        audit_log: AuditLog,
    ) -> None:
        from app.core.policy_v2 import PolicyRequest

        policy_engine.trust.set_tier("u1", "established")
        decision = policy_engine.evaluate(
            PolicyRequest(user_id="u1", action="git_push", target="main")
        )
        approval_id = decision.approval_id
        assert approval_id is not None

        r = client.post(
            f"/api/audit/approvals/{approval_id}/resolve",
            params={"approved": "true", "resolved_by": "admin1", "note": "ok"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["resolved_by"] == "admin1"
        # The resolve call also records an audit event
        events = audit_log.query(kind="approval", limit=10)
        assert len(events) >= 1

    def test_resolve_unknown(self, client: TestClient) -> None:
        r = client.post(
            "/api/audit/approvals/nonexistent/resolve",
            params={"approved": "true", "resolved_by": "x"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthAPI:
    def test_health(self, client: TestClient) -> None:
        r = client.get("/api/audit/health")
        body = r.json()
        assert body["ok"] is True
        assert body["policy_v2"] is True

    def test_health_no_policy(
        self, audit_log: AuditLog
    ) -> None:
        app = FastAPI()
        app.include_router(build_router(audit_log=audit_log, policy_engine=None))
        c = TestClient(app)
        r = c.get("/api/audit/health")
        body = r.json()
        assert body["ok"] is True
        assert body["policy_v2"] is False


# ---------------------------------------------------------------------------
# Service-unavailable handling
# ---------------------------------------------------------------------------


class TestServiceUnavailable:
    def test_events_no_log(self) -> None:
        app = FastAPI()
        app.include_router(build_router(audit_log=None))
        c = TestClient(app)
        r = c.get("/api/audit/events")
        assert r.status_code == 503

    def test_approvals_no_engine(self, audit_log: AuditLog) -> None:
        app = FastAPI()
        app.include_router(build_router(audit_log=audit_log, policy_engine=None))
        c = TestClient(app)
        r = c.get("/api/audit/approvals/pending")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user_id: str, action: str, args: dict):
    from app.core.policy_v2 import PolicyRequest

    return PolicyRequest(user_id=user_id, action=action, args=args)
