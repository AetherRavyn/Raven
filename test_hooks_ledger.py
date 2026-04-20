from __future__ import annotations

import pytest

from app.core.hooks import HookDispatcher
from app.core.task_ledger import TaskLedger


@pytest.mark.asyncio
async def test_hook_dispatch_can_record_ledger(tmp_path) -> None:
    ledger = TaskLedger(str(tmp_path))
    dispatcher = HookDispatcher()

    async def _handler(payload):
        ledger.record_hook(
            hook_name="turn_completed",
            title=payload["text"],
            user_id=payload["user_id"],
            platform=payload["platform"],
            chat_id=payload["session_id"],
        )

    dispatcher.register("turn_completed", _handler)
    await dispatcher.dispatch(
        "turn_completed",
        {"user_id": "u1", "platform": "web", "session_id": "s1", "text": "done"},
    )
    tasks = ledger.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "hook"
