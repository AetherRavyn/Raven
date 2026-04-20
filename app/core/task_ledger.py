from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LedgerTask:
    task_id: str
    task_type: str
    title: str
    status: str = "open"
    source: str = "runtime"
    user_id: str | None = None
    platform: str | None = None
    chat_id: str | None = None
    due_at: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TaskLedger:
    """Persistent ledger for detached work, cron jobs, hooks, and workflows."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self.workspace_dir = Path(Config.STATE_DB_PATH).parent
        self.ledger_file = self.workspace_dir / "task_ledger.jsonl"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _read_tasks(self) -> list[LedgerTask]:
        tasks: list[LedgerTask] = []
        if not self.ledger_file.exists():
            return tasks
        try:
            for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                tasks.append(LedgerTask(**json.loads(line)))
        except Exception as exc:
            logger.debug("Failed to read task ledger: %s", exc)
        return tasks

    def _write_tasks(self, tasks: list[LedgerTask]) -> None:
        try:
            self.ledger_file.write_text(
                "\n".join(json.dumps(asdict(task), ensure_ascii=True) for task in tasks)
                + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to write task ledger: %s", exc)

    def add_task(
        self,
        task_id: str,
        task_type: str,
        title: str,
        *,
        source: str = "runtime",
        user_id: str | None = None,
        platform: str | None = None,
        chat_id: str | None = None,
        due_at: str | None = None,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerTask:
        tasks = self._read_tasks()
        task = LedgerTask(
            task_id=task_id,
            task_type=task_type,
            title=title,
            source=source,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            due_at=due_at,
            workflow_id=workflow_id,
            metadata=metadata or {},
        )
        tasks.append(task)
        self._write_tasks(tasks)
        return task

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        tasks = self._read_tasks()
        if status:
            tasks = [task for task in tasks if task.status == status]
        return [asdict(task) for task in tasks]

    def update_status(self, task_id: str, status: str) -> bool:
        tasks = self._read_tasks()
        changed = False
        for task in tasks:
            if task.task_id == task_id:
                task.status = status
                task.updated_at = datetime.now(timezone.utc).isoformat()
                changed = True
        if changed:
            self._write_tasks(tasks)
        return changed

    def record_hook(
        self,
        hook_name: str,
        title: str,
        *,
        user_id: str | None = None,
        platform: str | None = None,
        chat_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerTask:
        task_id = f"hook_{hook_name}_{len(self._read_tasks()) + 1}"
        return self.add_task(
            task_id,
            "hook",
            title,
            source="hook",
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            metadata=metadata or {},
        )
