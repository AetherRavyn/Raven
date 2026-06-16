"""Tests for the audit log (part of A4 in the foundation plan)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.audit import AuditEvent, AuditKind, AuditLog, RiskLevel
from app.core.audit import ActionLogger  # legacy compat
from app.core.audit.types import _enum_value


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def audit_log(log_path: Path) -> AuditLog:
    return AuditLog(jsonl_path=log_path)


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------


class TestAuditEvent:
    def test_defaults(self) -> None:
        e = AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="file_read")
        assert e.kind == AuditKind.TOOL_CALL
        assert e.actor == "u1"
        assert e.success is True
        assert e.risk_level == RiskLevel.LOW
        assert e.timestamp.tzinfo is not None
        assert e.id  # auto-generated

    def test_roundtrip(self) -> None:
        e = AuditEvent(
            kind=AuditKind.LLM_CALL,
            actor="agent1",
            action="chat",
            target="gpt-4o",
            context={"user_id": "u1", "platform": "telegram"},
            success=True,
            detail="ok",
            metadata={"tokens": 123},
            risk_level=RiskLevel.MEDIUM,
            duration_ms=1500,
            cost_usd=0.001,
        )
        d = e.to_dict()
        e2 = AuditEvent.from_dict(d)
        assert e2.id == e.id
        assert e2.kind == e.kind
        assert e2.action == e.action
        assert e2.context == e.context
        assert e2.metadata == e.metadata
        assert e2.risk_level == e.risk_level
        assert e2.timestamp == e.timestamp
        assert e2.cost_usd == e.cost_usd

    def test_enum_value_helper(self) -> None:
        assert _enum_value(AuditKind.TOOL_CALL) == "tool_call"
        assert _enum_value(RiskLevel.HIGH) == "high"
        assert _enum_value("plain") == "plain"


# ---------------------------------------------------------------------------
# AuditLog — write
# ---------------------------------------------------------------------------


class TestWrite:
    def test_record_appends_to_file(self, audit_log: AuditLog, log_path: Path) -> None:
        e = AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="file_read")
        eid = audit_log.record(e)
        assert eid == e.id
        # File should now have one line
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        d = json.loads(lines[0])
        assert d["id"] == e.id

    def test_record_never_raises(self, audit_log: AuditLog) -> None:
        # Even with a corrupt event, the log should not raise (the
        # record method itself shouldn't blow up).
        e = AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="u1",
            action="x",
            metadata={"key": "value"},
        )
        eid = audit_log.record(e)
        assert eid

    def test_record_many(self, audit_log: AuditLog) -> None:
        for i in range(50):
            audit_log.record(
                AuditEvent(
                    kind=AuditKind.TOOL_CALL,
                    actor=f"u{i}",
                    action=f"tool_{i}",
                )
            )
        assert audit_log.count() == 50


# ---------------------------------------------------------------------------
# AuditLog — query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_returns_recorded(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="file_read")
        )
        results = audit_log.query()
        assert len(results) == 1
        assert results[0].action == "file_read"

    def test_query_filter_by_kind(self, audit_log: AuditLog) -> None:
        audit_log.record(AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t"))
        audit_log.record(AuditEvent(kind=AuditKind.LLM_CALL, actor="u1", action="l"))
        assert len(audit_log.query(kind="tool_call")) == 1
        assert len(audit_log.query(kind="llm_call")) == 1
        assert len(audit_log.query(kind="config")) == 0

    def test_query_filter_by_actor(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="alice", action="t")
        )
        audit_log.record(AuditEvent(kind=AuditKind.TOOL_CALL, actor="bob", action="t"))
        assert len(audit_log.query(actor="alice")) == 1
        assert len(audit_log.query(actor="bob")) == 1

    def test_query_filter_by_action(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="file_read")
        )
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="file_write")
        )
        assert len(audit_log.query(action="file_read")) == 1

    def test_query_filter_by_success(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t", success=True)
        )
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t", success=False)
        )
        assert len(audit_log.query(success=True)) == 1
        assert len(audit_log.query(success=False)) == 1

    def test_query_filter_by_risk(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="u1",
                action="t",
                risk_level=RiskLevel.LOW,
            )
        )
        audit_log.record(
            AuditEvent(
                kind=AuditKind.SECURITY,
                actor="u1",
                action="block",
                risk_level=RiskLevel.CRITICAL,
            )
        )
        assert len(audit_log.query(risk_level="critical")) == 1
        assert len(audit_log.query(risk_level="low")) == 1

    def test_query_filter_by_date(self, audit_log: AuditLog) -> None:
        old = AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="u1",
            action="old",
            timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        new = AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="u1",
            action="new",
            timestamp=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        audit_log.record(old)
        audit_log.record(new)
        assert (
            len(audit_log.query(since=datetime(2025, 1, 1, tzinfo=timezone.utc))) == 1
        )
        assert (
            len(audit_log.query(until=datetime(2025, 1, 1, tzinfo=timezone.utc))) == 1
        )

    def test_query_text_search(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="u1",
                action="file_read",
                detail="opened secret_file.txt",
            )
        )
        audit_log.record(
            AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="u1",
                action="file_write",
                detail="wrote report.md",
            )
        )
        assert len(audit_log.query(search="secret")) == 1
        assert len(audit_log.query(search="report")) == 1
        assert len(audit_log.query(search="nope")) == 0

    def test_query_pagination(self, audit_log: AuditLog) -> None:
        for i in range(10):
            audit_log.record(
                AuditEvent(
                    kind=AuditKind.TOOL_CALL,
                    actor=f"u{i}",
                    action=f"t{i}",
                )
            )
        assert len(audit_log.query(limit=3)) == 3
        assert len(audit_log.query(limit=3, offset=3)) == 3
        assert len(audit_log.query(limit=3, offset=9)) == 1

    def test_query_newest_first(self, audit_log: AuditLog) -> None:
        for i in range(3):
            audit_log.record(
                AuditEvent(
                    kind=AuditKind.TOOL_CALL,
                    actor="u1",
                    action=f"a{i}",
                )
            )
        results = audit_log.query()
        assert results[0].action == "a2"  # most recent
        assert results[-1].action == "a0"

    def test_query_oldest_first(self, audit_log: AuditLog) -> None:
        for i in range(3):
            audit_log.record(
                AuditEvent(
                    kind=AuditKind.TOOL_CALL,
                    actor="u1",
                    action=f"a{i}",
                )
            )
        results = audit_log.query(newest_first=False)
        assert results[0].action == "a0"


# ---------------------------------------------------------------------------
# AuditLog — get / replay
# ---------------------------------------------------------------------------


class TestGetReplay:
    def test_get_by_id(self, audit_log: AuditLog) -> None:
        e = AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t")
        audit_log.record(e)
        assert audit_log.get(e.id) is not None
        assert audit_log.get("nonexistent") is None

    def test_replay_returns_inputs(self, audit_log: AuditLog) -> None:
        e = AuditEvent(
            kind=AuditKind.TOOL_CALL,
            actor="u1",
            action="file_read",
            target="/etc/hosts",
            metadata={"path": "/etc/hosts", "mode": "r"},
            context={"user_id": "u1", "platform": "telegram"},
        )
        audit_log.record(e)
        replay = audit_log.replay(e.id)
        assert replay is not None
        assert replay["action"] == "file_read"
        assert replay["args"]["path"] == "/etc/hosts"
        assert replay["context"]["user_id"] == "u1"

    def test_replay_missing(self, audit_log: AuditLog) -> None:
        assert audit_log.replay("missing") is None


# ---------------------------------------------------------------------------
# AuditLog — health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_empty(self, audit_log: AuditLog) -> None:
        h = audit_log.health()
        assert h["event_count"] == 0
        assert h["oldest"] is None
        assert h["newest"] is None
        assert h["by_kind"] == {}
        assert h["by_risk_level"] == {}
        assert h["failures"] == 0

    def test_health_aggregates(self, audit_log: AuditLog) -> None:
        audit_log.record(
            AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t", success=True)
        )
        audit_log.record(
            AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="u2",
                action="t",
                success=False,
                risk_level=RiskLevel.HIGH,
            )
        )
        audit_log.record(
            AuditEvent(
                kind=AuditKind.LLM_CALL, actor="u1", action="chat", duration_ms=500
            )
        )
        h = audit_log.health()
        assert h["event_count"] == 3
        assert h["by_kind"]["tool_call"] == 2
        assert h["by_kind"]["llm_call"] == 1
        assert h["by_risk_level"]["high"] == 1
        assert h["failures"] == 1
        assert h["oldest"] is not None
        assert h["newest"] is not None


# ---------------------------------------------------------------------------
# AuditLog — durability + rotation
# ---------------------------------------------------------------------------


class TestDurability:
    def test_reload_after_restart(self, log_path: Path) -> None:
        a = AuditLog(jsonl_path=log_path)
        a.record(AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t"))
        # New instance reads from disk
        b = AuditLog(jsonl_path=log_path)
        assert b.count() == 1

    def test_rotate_moves_file(self, audit_log: AuditLog, log_path: Path) -> None:
        for i in range(3):
            audit_log.record(
                AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action=f"t{i}")
            )
        rotated_to = audit_log.rotate()
        assert rotated_to != log_path
        assert rotated_to.exists()
        assert not log_path.exists()
        # New writes go to the fresh log
        audit_log.record(AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="new"))
        assert audit_log.count() == 1

    def test_clear_resets(self, audit_log: AuditLog, log_path: Path) -> None:
        audit_log.record(AuditEvent(kind=AuditKind.TOOL_CALL, actor="u1", action="t"))
        audit_log.clear()
        assert not log_path.exists()
        assert audit_log.count() == 0

    def test_corrupt_line_skipped(self, log_path: Path) -> None:
        # Manually write a corrupt line + a good line
        log_path.write_text(
            '{"not": "valid"\n{"id": "x", "kind": "tool_call", "actor": "u1", "action": "t", "success": true, "timestamp": "2026-01-01T00:00:00+00:00", "duration_ms": 0, "cost_usd": 0, "risk_level": "low", "context": {}, "metadata": {}}\n'
        )
        a = AuditLog(jsonl_path=log_path)
        # Only the good line should be loaded
        assert a.count() == 1


# ---------------------------------------------------------------------------
# Legacy compat
# ---------------------------------------------------------------------------


class TestLegacyCompat:
    def test_action_logger_writes_event(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        logger = ActionLogger(path=str(p))
        from app.core.action_context import ActionContext

        ctx = ActionContext(
            user_id="u1",
            platform="telegram",
            request_text="hello",
            request_id="r1",
        )
        eid = logger.log_dict(
            kind="tool_call",
            action="file_read",
            context=ctx,
            success=True,
            detail="ok",
        )
        assert eid
        # File should have one line
        assert p.exists()
        d = json.loads(p.read_text().strip())
        assert d["actor"] == "u1"
        assert d["context"]["user_id"] == "u1"

    def test_action_logger_log_action(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        logger = ActionLogger(path=str(p))
        logger.log_action("tool_call", "file_read")
        assert p.exists()
        d = json.loads(p.read_text().strip())
        assert d["action"] == "file_read"
