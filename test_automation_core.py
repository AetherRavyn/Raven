from __future__ import annotations

from app.core.heartbeat import HeartbeatRunner
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger


def test_task_ledger_add_and_list(tmp_path) -> None:
    ledger = TaskLedger(str(tmp_path))
    ledger.add_task("t1", "task", "Write report", user_id="u1")
    tasks = ledger.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Write report"


def test_heartbeat_preview_reads_inbox_and_ledger(tmp_path) -> None:
    inbox = TaskInboxStore(str(tmp_path))
    ledger = TaskLedger(str(tmp_path))
    inbox.add_item("u1", "Follow up with team", kind="follow_up")
    ledger.add_task("t1", "task", "Check inbox", user_id="u1")
    runner = HeartbeatRunner(str(tmp_path))
    preview = runner.inbox.list_items("u1")
    assert preview
    assert runner.ledger.list_tasks()
