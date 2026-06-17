"""Tests for app.core.trust.audit_viewer (Day 27)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.audit.log import AuditLog
from app.core.audit.types import AuditEvent, AuditKind, RiskLevel
from app.core.trust.audit_viewer import (
    AuditFilter,
    AuditViewer,
    TimelineBucket,
    get_default_audit_viewer,
    reset_default_audit_viewer,
    set_default_audit_viewer,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_audit_viewer()
    yield
    reset_default_audit_viewer()


@pytest.fixture
def log(tmp_path) -> AuditLog:
    return AuditLog(jsonl_path=tmp_path / "audit.log")


@pytest.fixture
def viewer(log: AuditLog) -> AuditViewer:
    return AuditViewer(log=log)


def _event(
    *,
    kind: AuditKind = AuditKind.TOOL_CALL,
    actor: str = "agent",
    action: str = "t1",
    target: str | None = None,
    user_id: str | None = "u1",
    risk: RiskLevel = RiskLevel.LOW,
    success: bool = True,
    turn_id: str | None = None,
    when: datetime | None = None,
    duration_ms: int = 0,
    cost_usd: float = 0.0,
) -> AuditEvent:
    ctx: dict[str, object] = {}
    if user_id is not None:
        ctx["user_id"] = user_id
    meta: dict[str, object] = {}
    if turn_id is not None:
        meta["turn_id"] = turn_id
    return AuditEvent(
        kind=kind,
        actor=actor,
        action=action,
        target=target,
        context=ctx,
        success=success,
        risk_level=risk,
        timestamp=when or datetime.now(timezone.utc),
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        metadata=meta,
    )


# --------------------------------------------------------------------------- #
# AuditFilter.matches                                                         #
# --------------------------------------------------------------------------- #


class TestAuditFilter:
    def test_no_filters_matches_everything(self) -> None:
        e = _event()
        assert AuditFilter().matches(e) is True

    def test_kind_filter(self) -> None:
        e = _event(kind=AuditKind.TOOL_CALL)
        assert AuditFilter(kind=AuditKind.TOOL_CALL).matches(e) is True
        assert AuditFilter(kind=AuditKind.PLAN).matches(e) is False

    def test_actor_filter(self) -> None:
        e = _event(actor="alice")
        assert AuditFilter(actor="alice").matches(e) is True
        assert AuditFilter(actor="bob").matches(e) is False

    def test_tool_name_matches_action(self) -> None:
        e = _event(action="calendar.delete")
        assert AuditFilter(tool_name="calendar.delete").matches(e) is True

    def test_tool_name_matches_target(self) -> None:
        e = _event(action="call", target="calendar.delete")
        assert AuditFilter(tool_name="calendar.delete").matches(e) is True

    def test_user_id_filter(self) -> None:
        e = _event(user_id="alice")
        assert AuditFilter(user_id="alice").matches(e) is True
        assert AuditFilter(user_id="bob").matches(e) is False

    def test_risk_filter(self) -> None:
        e = _event(risk=RiskLevel.HIGH)
        assert AuditFilter(risk_level=RiskLevel.HIGH).matches(e) is True
        assert AuditFilter(risk_level=RiskLevel.LOW).matches(e) is False

    def test_turn_id_filter(self) -> None:
        e = _event(turn_id="turn_1")
        assert AuditFilter(turn_id="turn_1").matches(e) is True
        assert AuditFilter(turn_id="turn_2").matches(e) is False

    def test_time_window(self) -> None:
        now = datetime.now(timezone.utc)
        e = _event(when=now)
        assert AuditFilter(since=now - timedelta(hours=1)).matches(e) is True
        assert AuditFilter(since=now + timedelta(hours=1)).matches(e) is False
        assert AuditFilter(until=now + timedelta(hours=1)).matches(e) is True
        assert AuditFilter(until=now - timedelta(hours=1)).matches(e) is False

    def test_success_only(self) -> None:
        e = _event(success=True)
        assert AuditFilter(success_only=True).matches(e) is True
        assert AuditFilter(success_only=False).matches(e) is False

    def test_failed_only(self) -> None:
        e = _event(success=False)
        assert AuditFilter(failed_only=True).matches(e) is True
        assert AuditFilter(failed_only=False).matches(e) is False

    def test_metadata_contains(self) -> None:
        e = _event(turn_id="t1")
        assert AuditFilter(metadata_contains={"turn_id": "t1"}).matches(e) is True
        assert AuditFilter(metadata_contains={"turn_id": "t2"}).matches(e) is False


# --------------------------------------------------------------------------- #
# AuditViewer recent / get                                                    #
# --------------------------------------------------------------------------- #


class TestRecentAndGet:
    def test_recent_returns_newest_first(self, viewer: AuditViewer, log: AuditLog) -> None:
        old = _event(action="old", when=datetime(2020, 1, 1, tzinfo=timezone.utc))
        new = _event(action="new", when=datetime(2030, 1, 1, tzinfo=timezone.utc))
        log.record(old)
        log.record(new)
        result = viewer.recent(10)
        assert result[0].action == "new"
        assert result[1].action == "old"

    def test_recent_respects_n(self, viewer: AuditViewer, log: AuditLog) -> None:
        for i in range(5):
            log.record(_event(action=f"t{i}"))
        assert len(viewer.recent(3)) == 3

    def test_get_by_id(self, viewer: AuditViewer, log: AuditLog) -> None:
        e = _event()
        log.record(e)
        found = viewer.get(e.id)
        assert found is not None
        assert found.id == e.id
        assert found.action == e.action

    def test_get_missing(self, viewer: AuditViewer) -> None:
        assert viewer.get("nope") is None


# --------------------------------------------------------------------------- #
# AuditViewer query / count                                                   #
# --------------------------------------------------------------------------- #


class TestQuery:
    def test_query_empty(self, viewer: AuditViewer) -> None:
        assert viewer.query() == []

    def test_query_all(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event())
        log.record(_event())
        assert len(viewer.query()) == 2

    def test_query_with_filter(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event(action="t1"))
        log.record(_event(action="t2"))
        result = viewer.query(AuditFilter(tool_name="t1"))
        assert len(result) == 1
        assert result[0].action == "t1"

    def test_query_respects_limit(self, viewer: AuditViewer, log: AuditLog) -> None:
        for i in range(10):
            log.record(_event(action=f"t{i}"))
        assert len(viewer.query(AuditFilter(limit=3))) == 3

    def test_count(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event())
        log.record(_event(success=False))
        assert viewer.count() == 2
        assert viewer.count(AuditFilter(success_only=True)) == 1
        assert viewer.count(AuditFilter(failed_only=True)) == 1


# --------------------------------------------------------------------------- #
# AuditViewer summary                                                         #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_summary_empty(self, viewer: AuditViewer) -> None:
        s = viewer.summary()
        assert s.total == 0
        assert s.successful == 0
        assert s.failed == 0

    def test_summary_counts(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event(kind=AuditKind.TOOL_CALL, success=True, cost_usd=0.5, duration_ms=100))
        log.record(_event(kind=AuditKind.PLAN, success=False, cost_usd=0.3, duration_ms=200))
        s = viewer.summary()
        assert s.total == 2
        assert s.successful == 1
        assert s.failed == 1
        assert s.by_kind["tool_call"] == 1
        assert s.by_kind["plan"] == 1
        assert s.total_cost_usd == pytest.approx(0.8)
        assert s.total_duration_ms == 300
        assert s.first_at is not None
        assert s.last_at is not None

    def test_summary_to_dict(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event())
        d = viewer.summary().to_dict()
        assert "total" in d
        assert "by_kind" in d
        assert isinstance(d["by_kind"], dict)


# --------------------------------------------------------------------------- #
# AuditViewer timeline                                                        #
# --------------------------------------------------------------------------- #


class TestTimeline:
    def test_timeline_empty(self, viewer: AuditViewer) -> None:
        assert viewer.timeline() == []

    def test_timeline_groups_by_hour(self, viewer: AuditViewer, log: AuditLog) -> None:
        now = datetime.now(timezone.utc)
        log.record(_event(when=now))
        log.record(_event(when=now))
        log.record(_event(when=now - timedelta(hours=2)))
        buckets = viewer.timeline(bucket="hour")
        assert len(buckets) == 2
        assert isinstance(buckets[0], TimelineBucket)

    def test_timeline_unknown_bucket_raises(self, viewer: AuditViewer) -> None:
        with pytest.raises(ValueError):
            viewer.timeline(bucket="century")

    def test_timeline_bucket_count(self, viewer: AuditViewer, log: AuditLog) -> None:
        now = datetime.now(timezone.utc)
        for _ in range(3):
            log.record(_event(when=now))
        buckets = viewer.timeline(bucket="hour")
        assert len(buckets) == 1
        assert buckets[0].count == 3


# --------------------------------------------------------------------------- #
# AuditViewer replay                                                          #
# --------------------------------------------------------------------------- #


class TestReplay:
    def test_replay_returns_all_for_turn(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event(turn_id="t1", action="a"))
        log.record(_event(turn_id="t1", action="b"))
        log.record(_event(turn_id="t2", action="c"))
        result = viewer.replay("t1")
        assert len(result) == 2
        assert result[0].action == "a"
        assert result[1].action == "b"

    def test_replay_empty(self, viewer: AuditViewer) -> None:
        assert viewer.replay("nope") == []


# --------------------------------------------------------------------------- #
# Time-window shortcuts                                                       #
# --------------------------------------------------------------------------- #


class TestTimeWindows:
    def test_last_hour(self, viewer: AuditViewer, log: AuditLog) -> None:
        now = datetime.now(timezone.utc)
        log.record(_event(when=now))
        log.record(_event(when=now - timedelta(hours=2)))
        result = viewer.last_hour()
        assert len(result) == 1

    def test_last_day(self, viewer: AuditViewer, log: AuditLog) -> None:
        now = datetime.now(timezone.utc)
        log.record(_event(when=now))
        log.record(_event(when=now - timedelta(days=2)))
        result = viewer.last_day()
        assert len(result) == 1

    def test_last_hour_user_filter(self, viewer: AuditViewer, log: AuditLog) -> None:
        now = datetime.now(timezone.utc)
        log.record(_event(when=now, user_id="u1"))
        log.record(_event(when=now, user_id="u2"))
        result = viewer.last_hour(user_id="u1")
        assert len(result) == 1


# --------------------------------------------------------------------------- #
# Export                                                                      #
# --------------------------------------------------------------------------- #


class TestExport:
    def test_to_dicts(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event())
        dicts = viewer.to_dicts()
        assert len(dicts) == 1
        assert isinstance(dicts[0], dict)
        assert "id" in dicts[0]

    def test_to_dicts_with_filter(self, viewer: AuditViewer, log: AuditLog) -> None:
        log.record(_event(action="t1"))
        log.record(_event(action="t2"))
        dicts = viewer.to_dicts(filter=AuditFilter(tool_name="t1"))
        assert len(dicts) == 1


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default_creates_singleton(self) -> None:
        v1 = get_default_audit_viewer()
        v2 = get_default_audit_viewer()
        assert v1 is v2

    def test_set_replaces(self) -> None:
        custom = AuditViewer()
        set_default_audit_viewer(custom)
        try:
            assert get_default_audit_viewer() is custom
        finally:
            set_default_audit_viewer(None)
        assert get_default_audit_viewer() is not custom
