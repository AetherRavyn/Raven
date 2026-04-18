from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from app.core.action_context import ActionContext
from app.core.audit import ActionLogger, AuditEvent
from app.core.botsignal import BotSignal
from app.core.security import SecurityGuard
from monitoring.src.message_bus import MessageBus


def test_security_guard_denies_when_admin_list_empty() -> None:
    guard = SecurityGuard()
    guard.admin_users = []
    assert guard.is_admin("123") is False


def test_action_logger_writes_jsonl(tmp_path: Path) -> None:
    logger = ActionLogger(path=str(tmp_path / "audit.log"))
    ctx = ActionContext(user_id="u1", platform="telegram", request_text="hello")
    logger.record(
        AuditEvent(kind="message", action="send", context=ctx, metadata={"x": 1})
    )

    data = (tmp_path / "audit.log").read_text(encoding="utf-8").strip()
    payload = json.loads(data)
    assert payload["kind"] == "message"
    assert payload["action"] == "send"
    assert payload["context"]["user_id"] == "u1"


def test_message_bus_uses_configured_redis_url(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://example.com:6379/1")
    with mock.patch("redis.Redis.from_url") as from_url:
        MessageBus()
        from_url.assert_called_once_with(
            "redis://example.com:6379/1", decode_responses=True
        )
