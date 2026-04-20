from __future__ import annotations

from app.core.task_inbox import TaskInboxStore


def test_task_inbox_add_list_complete(tmp_path) -> None:
    store = TaskInboxStore(str(tmp_path))
    item = store.add_item(
        "u1", "Follow up on the report", kind="follow_up", source="test"
    )
    items = store.list_items("u1")
    assert len(items) == 1
    assert items[0]["title"] == "Follow up on the report"
    assert store.complete_item(item.item_id) is True
    done_items = store.list_items("u1", status="done")
    assert len(done_items) == 1


def test_task_inbox_summary_counts(tmp_path) -> None:
    store = TaskInboxStore(str(tmp_path))
    store.add_item("u1", "Task one", kind="task")
    store.add_item("u1", "Follow up", kind="follow_up")
    summary = store.get_summary("u1")
    assert summary["open"] >= 2
    assert summary["task"] >= 1
    assert summary["follow_up"] >= 1
