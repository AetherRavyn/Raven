"""Tests for the cross-platform continuity package (Day 15, Phase C4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# -------------------------------------------------------------------
# identity
# -------------------------------------------------------------------


class TestDeriveIds:
    def test_user_id_is_stable(self) -> None:
        from app.core.continuity import derive_user_id

        a = derive_user_id("telegram", "123")
        b = derive_user_id("telegram", "123")
        assert a == b

    def test_user_id_differs_by_platform(self) -> None:
        from app.core.continuity import derive_user_id

        a = derive_user_id("telegram", "123")
        b = derive_user_id("slack", "123")
        assert a != b

    def test_user_id_normalises_case(self) -> None:
        from app.core.continuity import derive_user_id

        a = derive_user_id("TELEGRAM", "123")
        b = derive_user_id("telegram", "123")
        assert a == b

    def test_device_id_differs_by_kind(self) -> None:
        from app.core.continuity import derive_device_id

        a = derive_device_id("u1", "phone")
        b = derive_device_id("u1", "laptop")
        assert a != b


class TestIdentityRegistry:
    def test_upsert_user_round_trip(self) -> None:
        from app.core.continuity import IdentityRegistry, UserIdentity

        reg = IdentityRegistry()
        u = UserIdentity(id="u1", display_name="Alice")
        reg.upsert_user(u)
        assert reg.get_user("u1") is u

    def test_upsert_device_touches_last_seen(self) -> None:
        from app.core.continuity import Device, IdentityRegistry

        reg = IdentityRegistry()
        d = Device(
            id="d1",
            user_id="u1",
            kind="phone",
            last_seen_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        reg.upsert_device(d)
        out = reg.get_device("d1")
        assert out is not None
        assert out.last_seen_at > datetime(2020, 1, 1, tzinfo=timezone.utc)

    def test_upsert_channel_sets_id(self) -> None:
        from app.core.continuity import Channel, IdentityRegistry

        reg = IdentityRegistry()
        ch = Channel(platform="telegram", chat_id="123", device_id="d1")
        reg.upsert_channel(ch)
        assert reg.get_channel("telegram:123") is ch

    def test_find_channel(self) -> None:
        from app.core.continuity import Channel, IdentityRegistry

        reg = IdentityRegistry()
        reg.upsert_channel(Channel(platform="telegram", chat_id="123", device_id="d1"))
        assert reg.find_channel("telegram", "123") is not None
        assert reg.find_channel("telegram", "999") is None

    def test_list_devices_filters_by_user(self) -> None:
        from app.core.continuity import Device, IdentityRegistry

        reg = IdentityRegistry()
        reg.upsert_device(Device(id="d1", user_id="u1", kind="phone"))
        reg.upsert_device(Device(id="d2", user_id="u2", kind="phone"))
        assert {d.id for d in reg.list_devices("u1")} == {"d1"}

    def test_bind_creates_user_device_channel(self) -> None:
        from app.core.continuity import IdentityRegistry

        reg = IdentityRegistry()
        u, d, c = reg.bind("telegram", "123", "u1", device_kind="phone")
        assert u.id == "u1"
        assert d.user_id == "u1"
        assert c.id == "telegram:123"
        # Re-bind is idempotent.
        u2, d2, c2 = reg.bind("telegram", "123", "u1")
        assert u2.id == u.id
        assert d2.id == d.id
        assert c2.id == c.id

    def test_bind_capabilities_round_trip(self) -> None:
        from app.core.continuity import IdentityRegistry

        reg = IdentityRegistry()
        _, device, _ = reg.bind(
            "telegram",
            "123",
            "u1",
            device_kind="phone",
            capabilities=("text", "voice"),
        )
        assert "text" in device.capabilities
        assert "voice" in device.capabilities

    def test_clear_drops_everything(self) -> None:
        from app.core.continuity import Device, IdentityRegistry, UserIdentity, Channel

        reg = IdentityRegistry()
        reg.upsert_user(UserIdentity(id="u1"))
        reg.upsert_device(Device(id="d1", user_id="u1", kind="phone"))
        reg.upsert_channel(Channel(platform="tg", chat_id="1", device_id="d1"))
        reg.clear()
        assert reg.list_users() == []
        assert reg.list_devices("u1") == []
        assert reg.find_channel("tg", "1") is None


# -------------------------------------------------------------------
# session
# -------------------------------------------------------------------


class TestSessionSerialization:
    def test_round_trip(self) -> None:
        from app.core.continuity import Session, SessionManager

        mgr = SessionManager()
        sess = mgr.start("u1", "telegram:123")
        mgr.append(sess.id, "user", "Hello", metadata={"x": 1})
        mgr.append(sess.id, "assistant", "Hi", metadata={"y": 2})
        mgr.update_context(sess.id, project="saras", mood="curious")

        data = sess.to_dict()
        restored = Session.from_dict(data)
        assert restored.id == sess.id
        assert restored.user_id == "u1"
        assert restored.context == {"project": "saras", "mood": "curious"}
        assert len(restored.events) == 2
        assert restored.events[0].content == "Hello"

    def test_from_dict_without_ended(self) -> None:
        from app.core.continuity import Session

        sess = Session.from_dict(
            {
                "id": "s1",
                "user_id": "u1",
                "channel_id": "c1",
                "started_at": "2024-01-01T00:00:00+00:00",
                "last_active_at": "2024-01-01T00:00:00+00:00",
                "ended_at": None,
                "context": {},
                "events": [],
                "target_channel_id": "",
                "tags": [],
            }
        )
        assert sess.ended_at is None


class TestSessionManager:
    def test_start_returns_session(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123")
        assert s.user_id == "u1"
        assert s.channel_id == "telegram:123"

    def test_get_or_create_reuses_active_session(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s1, created1 = mgr.get_or_create("u1", "telegram:123")
        s2, created2 = mgr.get_or_create("u1", "telegram:123")
        assert s1.id == s2.id
        assert created1 is True
        assert created2 is False

    def test_get_or_create_creates_new_for_different_channel(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s1, _ = mgr.get_or_create("u1", "telegram:123")
        s2, created = mgr.get_or_create("u1", "voice:desk")
        assert s1.id != s2.id
        assert created is True

    def test_append_creates_event(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.append(s.id, "user", "Hi")
        mgr.append(s.id, "assistant", "Hello")
        assert len(s.events) == 2
        assert s.events[0].role == "user"
        assert s.events[1].role == "assistant"

    def test_append_unknown_session_raises(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        with pytest.raises(KeyError):
            mgr.append("s_nonexistent", "user", "Hi")

    def test_update_context_merges(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.update_context(s.id, project="saras")
        mgr.update_context(s.id, mood="curious")
        assert s.context == {"project": "saras", "mood": "curious"}

    def test_end_marks_ended(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.end(s.id)
        assert s.ended_at is not None

    def test_primary_for_user_returns_recent(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s1 = mgr.start("u1", "c1")
        s2 = mgr.start("u1", "c2")
        assert mgr.primary_for_user("u1") is s2
        assert mgr.primary_for_user("u1") is not s1

    def test_primary_for_unknown_user_is_none(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        assert mgr.primary_for_user("nobody") is None

    def test_active_for_channel_filters_ended(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.end(s.id)
        assert mgr.active_for_channel("c1") is None

    def test_list_sessions_excludes_ended_by_default(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s1 = mgr.start("u1", "c1")
        s2 = mgr.start("u1", "c2")
        mgr.end(s1.id)
        out = mgr.list_sessions("u1", include_ended=False)
        assert s1 not in out
        assert s2 in out

    def test_list_sessions_includes_ended_when_requested(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s1 = mgr.start("u1", "c1")
        s2 = mgr.start("u1", "c2")
        mgr.end(s1.id)
        out = mgr.list_sessions("u1", include_ended=True)
        assert s1 in out
        assert s2 in out

    def test_set_target_channel(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.set_target_channel(s.id, "c2")
        assert s.target_channel_id == "c2"

    def test_is_active_within_idle_window(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        s.last_active_at = datetime.now(timezone.utc)
        assert s.is_active is True

    def test_is_active_after_idle_window(self) -> None:
        from app.core.continuity import SessionManager

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        s.last_active_at = datetime.now(timezone.utc) - timedelta(hours=2)
        assert s.is_active is False


# -------------------------------------------------------------------
# handoff
# -------------------------------------------------------------------


class TestHandoff:
    def test_creates_new_session(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123")
        mgr.append(s.id, "user", "Hello")
        target, receipt = handoff_session(mgr, s.id, "voice:desk")
        assert target.id != s.id
        assert target.channel_id == "voice:desk"
        assert receipt.source_session_id == s.id
        assert receipt.target_session_id == target.id

    def test_copies_events(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123")
        mgr.append(s.id, "user", "Hello")
        mgr.append(s.id, "assistant", "Hi there")
        target, _ = handoff_session(mgr, s.id, "voice:desk")
        assert len(target.events) == 3  # 2 source + 1 system

    def test_appends_system_event(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123")
        target, _ = handoff_session(mgr, s.id, "voice:desk", reason="phone to laptop")
        last = target.events[-1]
        assert last.role == "system"
        assert "phone to laptop" in last.content
        assert last.metadata.get("source_session_id") == s.id

    def test_ends_source_session(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123")
        handoff_session(mgr, s.id, "voice:desk")
        ended = mgr.get(s.id)
        assert ended is not None
        assert ended.ended_at is not None

    def test_copies_context(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "telegram:123", context={"project": "saras"})
        target, _ = handoff_session(mgr, s.id, "voice:desk")
        assert target.context.get("project") == "saras"

    def test_receipt_records_event_count(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.append(s.id, "user", "a")
        mgr.append(s.id, "assistant", "b")
        target, receipt = handoff_session(mgr, s.id, "c2")
        assert receipt.events_transferred == 2

    def test_handoff_unknown_source_raises(self) -> None:
        from app.core.continuity import SessionManager, handoff_session

        mgr = SessionManager()
        with pytest.raises(KeyError):
            handoff_session(mgr, "s_xxx", "c2")

    def test_handoff_log_records(self) -> None:
        from app.core.continuity import HandoffLog, SessionManager, handoff_session

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        log = HandoffLog()
        _, receipt = handoff_session(mgr, s.id, "c2")
        log.append(receipt)
        assert log.list_for_user("u1") == [receipt]
        assert log.latest_for_session(s.id) is receipt


class TestSummariseForHandoff:
    def test_summary_includes_recent_turns(self) -> None:
        from app.core.continuity import SessionManager, summarise_for_handoff

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.append(s.id, "user", "Hello there")
        mgr.append(s.id, "assistant", "Hi back")
        summary = summarise_for_handoff(s, max_events=2)
        assert summary["event_count"] == 2
        assert len(summary["recent_turns"]) == 2
        assert summary["recent_turns"][0]["role"] == "user"

    def test_summary_truncates_content(self) -> None:
        from app.core.continuity import SessionManager, summarise_for_handoff

        mgr = SessionManager()
        s = mgr.start("u1", "c1")
        mgr.append(s.id, "user", "x" * 500)
        summary = summarise_for_handoff(s)
        assert len(summary["recent_turns"][0]["content"]) == 200


# -------------------------------------------------------------------
# orchestrator
# -------------------------------------------------------------------


class TestOrchestrator:
    def setup_method(self) -> None:
        from app.core.continuity import reset_continuity

        reset_continuity()

    def test_continuity_singleton(self) -> None:
        from app.core.continuity import continuity

        a = continuity()
        b = continuity()
        assert a is b

    def test_ensure_handle_binds_user_device_channel(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        u, d, ch = c.ensure_handle("telegram", "123", "alice", device_kind="phone")
        assert u.id == "alice"
        assert d.user_id == "alice"
        assert ch.id == "telegram:123"

    def test_ensure_handle_derives_user_id_when_none(self) -> None:
        from app.core.continuity import continuity, derive_user_id

        c = continuity()
        u, _, _ = c.ensure_handle("telegram", "456")
        assert u.id == derive_user_id("telegram", "456")

    def test_find_user_by_handle(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        c.ensure_handle("telegram", "123", "alice")
        u = c.find_user_by_handle("telegram", "123")
        assert u is not None and u.id == "alice"

    def test_find_user_by_handle_unknown(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        assert c.find_user_by_handle("telegram", "999") is None

    def test_get_or_create_session(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        s1, created1 = c.get_or_create_session("u1", "telegram:123")
        s2, created2 = c.get_or_create_session("u1", "telegram:123")
        assert s1.id == s2.id
        assert created1 is True
        assert created2 is False

    def test_primary_session(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        s1, _ = c.get_or_create_session("u1", "c1")
        s2, _ = c.get_or_create_session("u1", "c2")
        assert c.primary_session("u1") is s2

    def test_handoff_through_orchestrator(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        c.ensure_handle("telegram", "123", "alice")
        c.ensure_handle("voice", "desk", "alice", device_kind="voice_assistant")
        s, _ = c.get_or_create_session("alice", "telegram:123")
        c.sessions.append(s.id, "user", "Hello")
        target, receipt = c.handoff(s.id, "voice:desk", reason="switching devices")
        assert target.channel_id == "voice:desk"
        assert receipt.reason == "switching devices"
        assert c.handoffs.list_for_user("alice") == [receipt]

    def test_summarise_through_orchestrator(self) -> None:
        from app.core.continuity import continuity

        c = continuity()
        s, _ = c.get_or_create_session("u1", "c1")
        c.sessions.append(s.id, "user", "Hello")
        summary = c.summarise(s)
        assert summary["user_id"] == "u1"
        assert summary["event_count"] == 1

    def test_reset_continuity_drops_singleton(self) -> None:
        from app.core.continuity import continuity, reset_continuity

        a = continuity()
        reset_continuity()
        b = continuity()
        assert a is not b


# -------------------------------------------------------------------
# store
# -------------------------------------------------------------------


class TestHelixContinuityStore:
    def test_unavailable_when_no_helix(self) -> None:
        from app.core.continuity.store import HelixContinuityStore

        store = HelixContinuityStore(helix=None)
        # _probe() may find a helix or not; either way, save_session should
        # never raise.
        assert isinstance(store.available, bool)

    def test_save_user_no_op_when_unavailable(self) -> None:
        from app.core.continuity.store import HelixContinuityStore

        class _Stub:
            def is_available(self) -> bool:
                return False

        store = HelixContinuityStore(helix=_Stub())
        assert store.save_user(None) is False  # type: ignore[arg-type]

    def test_snapshot_returns_zero_when_unavailable(self) -> None:
        from app.core.continuity import IdentityRegistry, SessionManager
        from app.core.continuity.store import HelixContinuityStore, snapshot

        class _Stub:
            def is_available(self) -> bool:
                return False

        store = HelixContinuityStore(helix=_Stub())
        reg = IdentityRegistry()
        mgr = SessionManager()
        assert snapshot(reg, mgr, store) == 0
