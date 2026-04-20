from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.session import SessionManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InboxItem:
    item_id: str
    user_id: str
    title: str
    kind: str = "task"
    status: str = "open"
    source: str = "runtime"
    due_at: str | None = None
    platform: str | None = None
    chat_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TaskInboxStore:
    """Persistent long-horizon inbox for unresolved tasks, reminders, and follow-ups."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        from app.settings.config import Config
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.inbox_file = self.workspace_dir / "task_inbox.jsonl"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _read_items(self) -> list[InboxItem]:
        items: list[InboxItem] = []
        if not self.inbox_file.exists():
            return items
        try:
            for line in self.inbox_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                items.append(InboxItem(**raw))
        except Exception as exc:
            logger.debug("Failed to read inbox: %s", exc)
        return items

    def _write_items(self, items: list[InboxItem]) -> None:
        try:
            self.inbox_file.write_text(
                "\n".join(json.dumps(asdict(item), ensure_ascii=True) for item in items)
                + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to write inbox: %s", exc)

    def add_item(
        self,
        user_id: str,
        title: str,
        *,
        kind: str = "task",
        source: str = "runtime",
        due_at: str | None = None,
        platform: str | None = None,
        chat_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> InboxItem:
        items = self._read_items()
        item = InboxItem(
            item_id=f"inbox_{user_id}_{len(items) + 1}",
            user_id=user_id,
            title=title,
            kind=kind,
            source=source,
            due_at=due_at,
            platform=platform,
            chat_id=chat_id,
            context=context or {},
        )
        items.append(item)
        self._write_items(items)
        return item

    def list_items(
        self, user_id: str | None = None, status: str = "open"
    ) -> list[dict[str, Any]]:
        items = self._read_items()
        filtered = [
            item
            for item in items
            if item.status == status and (user_id is None or item.user_id == user_id)
        ]
        return [asdict(item) for item in filtered]

    def complete_item(self, item_id: str) -> bool:
        items = self._read_items()
        changed = False
        for item in items:
            if item.item_id == item_id:
                item.status = "done"
                item.updated_at = datetime.now(timezone.utc).isoformat()
                changed = True
        if changed:
            self._write_items(items)
        return changed

    def get_summary(self, user_id: str | None = None) -> dict[str, int]:
        items = self.list_items(user_id=user_id)
        summary = {"open": 0, "done": 0, "follow_up": 0, "task": 0, "reminder": 0}
        for item in items:
            kind = str(item.get("kind", "task"))
            summary[kind] = summary.get(kind, 0) + 1
            summary[item.get("status", "open")] = (
                summary.get(item.get("status", "open"), 0) + 1
            )
        return summary

    def ingest_session_tasks(
        self, session_id: str, user_id: str, workspace_dir: str | None = None
    ) -> list[InboxItem]:
        manager = SessionManager(workspace_dir or str(self.workspace_dir))
        messages = manager.load_session(session_id)
        created: list[InboxItem] = []
        for msg in messages:
            content = str(msg.get("content", ""))
            lower = content.lower()
            if any(
                phrase in lower
                for phrase in ("todo", "task", "follow up", "remind me", "please do")
            ):
                created.append(
                    self.add_item(
                        user_id,
                        title=content[:240],
                        kind="task",
                        source="session",
                        context={"session_id": session_id, "role": msg.get("role")},
                    )
                )
        return created
