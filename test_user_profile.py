from __future__ import annotations

from app.core.user_profile import UserProfileStore


def test_profile_store_updates_from_text(tmp_path) -> None:
    store = UserProfileStore(str(tmp_path))
    profile = store.update_from_text(
        "u1", "My name is Alex. I prefer concise answers. My timezone is UTC."
    )
    assert profile.display_name == "Alex"
    assert profile.timezone == "UTC"
    assert profile.preferences


def test_profile_render_contains_sections() -> None:
    store = UserProfileStore("workspace")
    profile = store.load("u1")
    profile.display_name = "Alex"
    profile.preferences = ["concise"]
    rendered = store.render(profile)
    assert "User Profile" in rendered
    assert "Alex" in rendered
    assert "concise" in rendered
