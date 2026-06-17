"""Tests for app.core.trust.rollback (Day 26)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.trust.rollback import (
    RollbackAction,
    RollbackManager,
    RollbackRegistry,
    RollbackResult,
    RollbackStatus,
    get_default_rollback_manager,
    reset_default_rollback_manager,
    set_default_rollback_manager,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_rollback_manager()
    yield
    reset_default_rollback_manager()


@pytest.fixture
def rm() -> RollbackManager:
    return RollbackManager()


# --------------------------------------------------------------------------- #
# Recording                                                                   #
# --------------------------------------------------------------------------- #


class TestRecord:
    def test_record_returns_action_id(self, rm: RollbackManager) -> None:
        aid = rm.record(
            tool_name="calendar.delete",
            args={"event_id": "evt_1"},
            user_id="u1",
            undo=lambda: None,
        )
        assert isinstance(aid, str)
        assert len(aid) > 0

    def test_record_stores_action(self, rm: RollbackManager) -> None:
        rm.record(
            tool_name="t1",
            args={"x": 1},
            user_id="u1",
            undo=lambda: None,
        )
        assert len(rm) == 1

    def test_record_stores_args(self, rm: RollbackManager) -> None:
        rm.record(
            tool_name="t1",
            args={"key": "value"},
            user_id="u1",
            undo=lambda: None,
        )
        actions = rm.history()
        assert actions[0].args == {"key": "value"}

    def test_record_stores_user_id(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="alice", undo=lambda: None)
        assert rm.history()[0].user_id == "alice"

    def test_record_default_args_empty(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        assert rm.history()[0].args == {}


# --------------------------------------------------------------------------- #
# Undo last                                                                   #
# --------------------------------------------------------------------------- #


class TestUndoLast:
    def test_undo_last_calls_undo(self, rm: RollbackManager) -> None:
        called: list[int] = []
        rm.record(tool_name="t1", user_id="u1", undo=lambda: called.append(1))
        result = rm.undo_last()
        assert result is not None
        assert result.status is RollbackStatus.SUCCESS
        assert called == [1]

    def test_undo_last_returns_none_when_empty(self, rm: RollbackManager) -> None:
        assert rm.undo_last() is None

    def test_undo_last_only_most_recent(self, rm: RollbackManager) -> None:
        first_called: list[bool] = []
        second_called: list[bool] = []
        rm.record(tool_name="t1", user_id="u1", undo=lambda: first_called.append(True))
        rm.record(tool_name="t1", user_id="u1", undo=lambda: second_called.append(True))
        rm.undo_last()
        assert first_called == []
        assert second_called == [True]

    def test_undo_last_filtered_by_user(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t1", user_id="u2", undo=lambda: None)
        result = rm.undo_last(user_id="u1")
        assert result is not None
        # u1's action was undone; u2's was not.
        u1_actions = [a for a in rm.history() if a.user_id == "u1"]
        u2_actions = [a for a in rm.history() if a.user_id == "u2"]
        assert u1_actions[0].undone is True
        assert u2_actions[0].undone is False

    def test_undo_last_filtered_by_tool(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u1", undo=lambda: None)
        result = rm.undo_last(tool_name="t1")
        assert result is not None
        assert result.tool_name == "t1"

    def test_undo_last_skips_already_undone(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.undo_last()
        assert rm.undo_last() is None

    def test_undo_last_captures_failure(self, rm: RollbackManager) -> None:
        def boom() -> None:
            raise RuntimeError("nope")

        rm.record(tool_name="t1", user_id="u1", undo=boom)
        result = rm.undo_last()
        assert result is not None
        assert result.status is RollbackStatus.FAILED
        assert "nope" in (result.error or "")


# --------------------------------------------------------------------------- #
# Undo since / last hour / all                                                #
# --------------------------------------------------------------------------- #


class TestUndoSince:
    def test_undo_since_runs_all_within_window(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u1", undo=lambda: None)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        results = rm.undo_since(cutoff)
        assert len(results) == 2

    def test_undo_since_skips_older(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        # All in the past.
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        results = rm.undo_since(future)
        assert results == []

    def test_undo_last_hour(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u1", undo=lambda: None)
        results = rm.undo_last_hour()
        assert len(results) == 2

    def test_undo_all(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t3", user_id="u2", undo=lambda: None)
        results = rm.undo_all()
        assert len(results) == 3

    def test_undo_all_filtered_by_user(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u2", undo=lambda: None)
        results = rm.undo_all(user_id="u1")
        assert len(results) == 1
        assert results[0].tool_name == "t1"


# --------------------------------------------------------------------------- #
# Undo by id                                                                  #
# --------------------------------------------------------------------------- #


class TestUndoById:
    def test_undo_by_id(self, rm: RollbackManager) -> None:
        aid = rm.record(tool_name="t1", user_id="u1", undo=lambda: "restored")
        result = rm.undo_by_id(aid)
        assert result is not None
        assert result.result == "restored"

    def test_undo_by_id_missing(self, rm: RollbackManager) -> None:
        assert rm.undo_by_id("nope") is None

    def test_undo_by_id_already_undone(self, rm: RollbackManager) -> None:
        aid = rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.undo_by_id(aid)
        assert rm.undo_by_id(aid) is None


# --------------------------------------------------------------------------- #
# History filtering                                                           #
# --------------------------------------------------------------------------- #


class TestHistory:
    def test_history_default_includes_undone(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.undo_last()
        assert len(rm.history()) == 1

    def test_history_excludes_undone(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.undo_last()
        assert len(rm.history(include_undone=False)) == 0

    def test_history_filtered_by_user(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u2", undo=lambda: None)
        assert len(rm.history(user_id="u1")) == 1

    def test_history_filtered_by_tool(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.record(tool_name="t2", user_id="u1", undo=lambda: None)
        assert len(rm.history(tool_name="t1")) == 1

    def test_history_newest_first(self, rm: RollbackManager) -> None:
        rm.record(tool_name="first", user_id="u1", undo=lambda: None)
        rm.record(tool_name="second", user_id="u1", undo=lambda: None)
        actions = rm.history()
        assert actions[0].tool_name == "second"
        assert actions[1].tool_name == "first"


# --------------------------------------------------------------------------- #
# Registry bounded                                                            #
# --------------------------------------------------------------------------- #


class TestRegistryBounded:
    def test_maxlen_drops_oldest(self) -> None:
        reg = RollbackRegistry(maxlen=3)
        for i in range(5):
            action = RollbackAction(
                action_id=str(i),
                tool_name=f"t{i}",
                args={},
                user_id="u1",
                undo=lambda: None,
                timestamp=datetime.now(timezone.utc),
            )
            reg.add(action)
        assert len(reg) == 3
        # Oldest two (t0, t1) are gone; newest three (t2, t3, t4) remain.
        assert reg.get("0") is None
        assert reg.get("1") is None
        assert reg.get("4") is not None


# --------------------------------------------------------------------------- #
# Action mark_undone                                                          #
# --------------------------------------------------------------------------- #


class TestActionMarkUndone:
    def test_mark_undone_success(self) -> None:
        action = RollbackAction(
            action_id="a1",
            tool_name="t1",
            args={},
            user_id="u1",
            undo=lambda: None,
            timestamp=datetime.now(timezone.utc),
        )
        action.mark_undone(result="ok")
        assert action.undone is True
        assert action.status is RollbackStatus.SUCCESS
        assert action.undo_result == "ok"
        assert action.undone_at is not None

    def test_mark_undone_failure(self) -> None:
        action = RollbackAction(
            action_id="a1",
            tool_name="t1",
            args={},
            user_id="u1",
            undo=lambda: None,
            timestamp=datetime.now(timezone.utc),
        )
        action.mark_undone(error="boom", status=RollbackStatus.FAILED)
        assert action.status is RollbackStatus.FAILED
        assert action.undo_error == "boom"


# --------------------------------------------------------------------------- #
# RollbackResult                                                              #
# --------------------------------------------------------------------------- #


class TestRollbackResult:
    def test_ok_property(self) -> None:
        r = RollbackResult(
            action_id="a", tool_name="t", status=RollbackStatus.SUCCESS,
        )
        assert r.ok is True

    def test_ok_property_failed(self) -> None:
        r = RollbackResult(
            action_id="a", tool_name="t", status=RollbackStatus.FAILED,
        )
        assert r.ok is False


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default_creates_singleton(self) -> None:
        m1 = get_default_rollback_manager()
        m2 = get_default_rollback_manager()
        assert m1 is m2

    def test_set_replaces(self) -> None:
        custom = RollbackManager()
        set_default_rollback_manager(custom)
        try:
            assert get_default_rollback_manager() is custom
        finally:
            set_default_rollback_manager(None)
        assert get_default_rollback_manager() is not custom

    def test_reset_clears(self) -> None:
        get_default_rollback_manager()
        reset_default_rollback_manager()
        m1 = get_default_rollback_manager()
        assert len(m1) == 0


# --------------------------------------------------------------------------- #
# Reset                                                                       #
# --------------------------------------------------------------------------- #


class TestReset:
    def test_reset_clears_history(self, rm: RollbackManager) -> None:
        rm.record(tool_name="t1", user_id="u1", undo=lambda: None)
        rm.reset()
        assert len(rm) == 0
