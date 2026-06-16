"""Tests for app.core.audit.dashboard."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.audit import (
    AuditEvent,
    AuditKind,
    RiskLevel,
    compute_stats,
    format_csv,
    format_json,
    format_timeline,
)


def _ev(
    kind: str = "tool_call",
    actor: str = "u1",
    action: str = "list_files",
    success: bool = True,
    risk: str = "low",
    detail: str | None = None,
    duration_ms: int = 0,
    cost_usd: float = 0.0,
    ts: datetime | None = None,
) -> AuditEvent:
    return AuditEvent(
        kind=AuditKind(kind),
        actor=actor,
        action=action,
        detail=detail,
        success=success,
        risk_level=RiskLevel(risk),
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        timestamp=ts or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------


class TestComputeStats:
    def test_empty(self) -> None:
        s = compute_stats([])
        assert s.total == 0
        assert s.by_kind == {}
        assert s.by_risk == {}

    def test_counts_by_kind(self) -> None:
        events = [
            _ev(kind="tool_call"),
            _ev(kind="tool_call"),
            _ev(kind="policy"),
        ]
        s = compute_stats(events)
        assert s.total == 3
        assert s.by_kind == {"tool_call": 2, "policy": 1}

    def test_counts_by_risk(self) -> None:
        events = [
            _ev(risk="low"),
            _ev(risk="high"),
            _ev(risk="critical"),
        ]
        s = compute_stats(events)
        assert s.by_risk == {"low": 1, "high": 1, "critical": 1}

    def test_counts_success(self) -> None:
        events = [
            _ev(success=True),
            _ev(success=False),
            _ev(success=True),
        ]
        s = compute_stats(events)
        assert s.by_success == {"success": 2, "failure": 1}

    def test_counts_by_actor(self) -> None:
        events = [
            _ev(actor="u1"),
            _ev(actor="u1"),
            _ev(actor="admin"),
        ]
        s = compute_stats(events)
        assert s.by_actor == {"u1": 2, "admin": 1}

    def test_duration_and_cost(self) -> None:
        events = [
            _ev(duration_ms=100, cost_usd=0.01),
            _ev(duration_ms=200, cost_usd=0.02),
        ]
        s = compute_stats(events)
        assert s.duration_total_ms == 300
        assert s.cost_total_usd == pytest.approx(0.03)

    def test_time_range_filter(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            _ev(ts=now - timedelta(hours=2)),
            _ev(ts=now - timedelta(hours=1)),
            _ev(ts=now),
            _ev(ts=now + timedelta(hours=1)),
        ]
        s = compute_stats(
            events,
            since=(now - timedelta(hours=1, minutes=30)).isoformat(),
            until=now.isoformat(),
        )
        assert s.total == 2  # the -1h and 0h ones

    def test_to_dict_round_trip(self) -> None:
        s = compute_stats([_ev()])
        d = s.to_dict()
        assert "total" in d
        assert "by_kind" in d
        assert d["total"] == 1


# ---------------------------------------------------------------------------
# format_timeline
# ---------------------------------------------------------------------------


class TestFormatTimeline:
    def test_empty(self) -> None:
        assert format_timeline([]) == ""

    def test_basic_table(self) -> None:
        events = [
            _ev(action="list_files", detail="ok"),
            _ev(action="rm", detail="deny", success=False, risk="high"),
        ]
        text = format_timeline(events)
        assert "list_files" in text
        assert "rm" in text
        assert "deny" in text
        # Header row + separator + 2 data rows
        assert len(text.splitlines()) == 4

    def test_max_rows(self) -> None:
        events = [_ev(action=f"a{i}") for i in range(10)]
        text = format_timeline(events, max_rows=3)
        assert len(text.splitlines()) == 5  # header + sep + 3 rows

    def test_columns(self) -> None:
        events = [_ev()]
        text = format_timeline(events, columns=("actor", "action"))
        # Header should show the chosen columns only
        assert "ACTOR" in text
        assert "ACTION" in text
        assert "KIND" not in text  # not in custom columns

    def test_boolean_rendering(self) -> None:
        events = [_ev(success=True), _ev(success=False)]
        text = format_timeline(events, columns=("action", "success"))
        assert "ok" in text
        assert "fail" in text

    def test_none_renders_empty(self) -> None:
        ev = _ev(detail=None)
        text = format_timeline([ev], columns=("detail",))
        # The empty string is fine — just no crash.
        assert text  # header still present


# ---------------------------------------------------------------------------
# format_csv
# ---------------------------------------------------------------------------


class TestFormatCSV:
    def test_empty(self) -> None:
        # Empty event list still emits a header (callers can drop it
        # with include_header=False if they want a truly empty CSV).
        text = format_csv([])
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 1
        assert "timestamp" in rows[0]

    def test_empty_no_header(self) -> None:
        text = format_csv([], include_header=False)
        assert text == ""

    def test_header_and_rows(self) -> None:
        events = [
            _ev(action="list_files", detail="ok"),
            _ev(action="rm", success=False),
        ]
        text = format_csv(events)
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0][0] == "timestamp"
        assert "action" in rows[0]
        assert len(rows) == 3  # header + 2

    def test_no_header(self) -> None:
        events = [_ev()]
        text = format_csv(events, include_header=False)
        rows = list(csv.reader(io.StringIO(text)))
        assert "timestamp" not in rows[0][0]  # first row is data, not header
        assert len(rows) == 1

    def test_nested_fields_jsonified(self) -> None:
        ev = _ev()
        ev.context = {"path": "/tmp"}
        text = format_csv([ev], columns=("action", "context"))
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["action", "context"]
        # The "context" cell must be JSON.
        context_cell = rows[1][1]
        assert context_cell.startswith("{")
        parsed = json.loads(context_cell)
        assert parsed == {"path": "/tmp"}

    def test_custom_columns(self) -> None:
        events = [_ev()]
        text = format_csv(events, columns=("actor", "action"))
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["actor", "action"]


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------


class TestFormatJSON:
    def test_empty(self) -> None:
        text = format_json([])
        assert json.loads(text) == []

    def test_basic(self) -> None:
        events = [_ev(action="a"), _ev(action="b")]
        text = format_json(events)
        parsed = json.loads(text)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["action"] == "a"

    def test_round_trip(self) -> None:
        events = [_ev()]
        text = format_json(events)
        parsed = json.loads(text)
        assert parsed[0]["kind"] == "tool_call"
        assert parsed[0]["actor"] == "u1"
