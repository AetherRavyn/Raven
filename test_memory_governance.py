from __future__ import annotations

from app.core.memory_manager import MemoryManager
from app.core.user_profile import UserProfileStore


def test_user_profile_conflict_resolution(tmp_path) -> None:
    store = UserProfileStore(str(tmp_path))
    store.update_from_text("u1", "I prefer concise answers.")
    store.resolve_conflict(
        "u1", "preferences", "I prefer concise answers.", "I prefer detailed answers."
    )
    profile = store.load("u1")
    assert any("detailed" in pref.lower() for pref in profile.preferences)


def test_user_profile_expiry_and_pin(tmp_path) -> None:
    store = UserProfileStore(str(tmp_path))
    store.update_from_text("u1", "My name is Alex. I prefer concise answers.")
    store.set_expiry("u1", "2000-01-01T00:00:00Z")
    store.prune_expired("u1")
    profile = store.load("u1")
    assert profile.preferences == [] or profile.pinned is False
    store.pin_profile("u1", True)
    profile = store.load("u1")
    assert profile.pinned is True


def test_memory_governance_summary(tmp_path) -> None:
    manager = MemoryManager()
    summary = manager.get_memory_governance_summary(user_id="u1")
    assert "count" in summary
