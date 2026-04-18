from __future__ import annotations

from datetime import datetime, timezone

from app.core.proactive import (
    ProactiveDigest,
    build_cross_platform_targets,
    build_follow_up_message,
    next_daily_run,
)


def test_proactive_digest_renders_bullets() -> None:
    digest = ProactiveDigest(title="Briefing", items=["One", "Two"])
    text = digest.render()
    assert "Briefing" in text
    assert "- One" in text


def test_follow_up_message_mentions_question() -> None:
    text = build_follow_up_message("the meeting", age_hours=12)
    assert "the meeting" in text
    assert "12 hours" in text


def test_next_daily_run_returns_future_time() -> None:
    run_at = next_daily_run(23, 59)
    assert run_at.tzinfo is timezone.utc


def test_cross_platform_targets_parse_config(monkeypatch) -> None:
    monkeypatch.setenv("MORNING_BRIEFING_USERS", "telegram:1:2,discord:3:4")
    targets = build_cross_platform_targets()
    assert len(targets) == 2
    assert targets[0].platform == "telegram"
    assert targets[1].chat_id == "4"
