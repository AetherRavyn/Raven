from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class KanbanCard:
    id: int = 0
    title: str = ""
    description: str = ""
    agent_id: str = ""
    status: TaskStatus = TaskStatus.BACKLOG
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    created_at: str = ""
    updated_at: str = ""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kanban_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'backlog',
    priority INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    blocked_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kanban_status ON kanban_cards(status);
CREATE INDEX IF NOT EXISTS idx_kanban_agent ON kanban_cards(agent_id);
"""


class KanbanBoard:
    """Kanban board with SQLite persistence for multi-agent task management."""

    def __init__(self, db_path: str | Path = "workspace/memory/kanban.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ── connection management ───────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    def create_card(
        self,
        title: str,
        description: str = "",
        agent_id: str = "",
        priority: int = 0,
        tags: list[str] | None = None,
    ) -> KanbanCard:
        """Create a new card on the board.

        Args:
            title: Card title.
            description: Optional description.
            agent_id: Optional agent assignment.
            priority: Priority value (higher = more important).
            tags: Optional list of tag strings.

        Returns:
            The newly created KanbanCard.
        """
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags or [])
        cur = self._conn.execute(
            """
            INSERT INTO kanban_cards (title, description, agent_id, status, priority, tags, blocked_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                description,
                agent_id,
                TaskStatus.BACKLOG.value,
                priority,
                tags_json,
                "",
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_card(cur.lastrowid)  # type: ignore[arg-type]

    def get_card(self, card_id: int) -> KanbanCard | None:
        """Retrieve a card by its ID.

        Args:
            card_id: The card ID.

        Returns:
            KanbanCard if found, None otherwise.
        """
        row = self._conn.execute("SELECT * FROM kanban_cards WHERE id = ?", (card_id,)).fetchone()
        return self._row_to_card(row) if row else None

    def update_card(self, card_id: int, **fields: Any) -> bool:
        """Update one or more fields on a card.

        Args:
            card_id: The card ID.
            **fields: Column-value pairs to update.

        Returns:
            True if a row was updated, False otherwise.
        """
        allowed = {
            "title",
            "description",
            "agent_id",
            "status",
            "priority",
            "tags",
            "blocked_reason",
        }
        updates: dict[str, Any] = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now

        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [card_id]

        cur = self._conn.execute(f"UPDATE kanban_cards SET {set_clause} WHERE id = ?", values)
        self._conn.commit()
        return cur.rowcount > 0

    def move_card(self, card_id: int, new_status: TaskStatus) -> bool:
        """Move a card to a new status.

        Args:
            card_id: The card ID.
            new_status: The target TaskStatus.

        Returns:
            True if the card was moved, False if the card doesn't exist.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "UPDATE kanban_cards SET status = ?, updated_at = ? WHERE id = ?",
            (new_status.value, now, card_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def block_card(self, card_id: int, reason: str) -> bool:
        """Block a card with a reason.

        Args:
            card_id: The card ID.
            reason: Why the card is blocked.

        Returns:
            True if the card was blocked, False if it doesn't exist.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "UPDATE kanban_cards SET status = ?, blocked_reason = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.BLOCKED.value, reason, now, card_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def unblock_card(self, card_id: int) -> bool:
        """Unblock a card and return it to its previous logical status.

        Since we track only the current status, blocked cards are moved
        back to IN_PROGRESS when unblocked.

        Args:
            card_id: The card ID.

        Returns:
            True if the card was unblocked, False if it doesn't exist.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "UPDATE kanban_cards SET status = ?, blocked_reason = '', updated_at = ? WHERE id = ? AND status = ?",
            (TaskStatus.IN_PROGRESS.value, now, card_id, TaskStatus.BLOCKED.value),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_card(self, card_id: int) -> bool:
        """Delete a card from the board.

        Args:
            card_id: The card ID.

        Returns:
            True if a row was deleted, False otherwise.
        """
        cur = self._conn.execute("DELETE FROM kanban_cards WHERE id = ?", (card_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ── queries ─────────────────────────────────────────────────────────

    def list_cards(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[KanbanCard]:
        """List cards with optional filters.

        Args:
            status: Filter by TaskStatus.
            agent_id: Filter by assigned agent.

        Returns:
            List of matching KanbanCards, ordered by priority DESC then created_at ASC.
        """
        sql = "SELECT * FROM kanban_cards WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY priority DESC, created_at ASC"
        return [self._row_to_card(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_board_summary(self) -> dict[str, Any]:
        """Return aggregate statistics about the board.

        Returns:
            Dict with counts per status, total agents, blocked count, and average age in hours.
        """
        summary: dict[str, Any] = {
            "total": 0,
            "by_status": {},
            "agents": set(),
            "blocked_count": 0,
            "avg_age_hours": 0.0,
        }

        rows = self._conn.execute("SELECT * FROM kanban_cards").fetchall()
        summary["total"] = len(rows)

        now = datetime.now(timezone.utc)
        total_age_hours = 0.0
        for row in rows:
            card = self._row_to_card(row)
            status_val = card.status.value
            summary["by_status"][status_val] = summary["by_status"].get(status_val, 0) + 1
            if card.agent_id:
                summary["agents"].add(card.agent_id)
            if card.status == TaskStatus.BLOCKED:
                summary["blocked_count"] += 1
            try:
                created = datetime.fromisoformat(card.created_at)
                total_age_hours += (now - created).total_seconds() / 3600
            except Exception:
                pass

        summary["agents"] = sorted(summary["agents"])
        summary["agent_count"] = len(summary["agents"])
        if summary["total"] > 0:
            summary["avg_age_hours"] = round(total_age_hours / summary["total"], 2)

        return summary

    def get_agent_queue(self, agent_id: str) -> list[KanbanCard]:
        """Return the queue of non-terminal cards for a given agent.

        Cards are sorted by priority descending, then created_at ascending.
        Terminal statuses (DONE) are excluded.

        Args:
            agent_id: The agent identifier.

        Returns:
            List of KanbanCards assigned to the agent.
        """
        rows = self._conn.execute(
            """
            SELECT * FROM kanban_cards
            WHERE agent_id = ? AND status != ?
            ORDER BY priority DESC, created_at ASC
            """,
            (agent_id, TaskStatus.DONE.value),
        ).fetchall()
        return [self._row_to_card(r) for r in rows]

    # ── internal ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> KanbanCard:
        tags: list[str] = []
        try:
            parsed = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
            tags = list(parsed) if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        return KanbanCard(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            agent_id=row["agent_id"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            tags=tags,
            blocked_reason=row["blocked_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def clear(self) -> None:
        """Delete all cards from the board."""
        self._conn.execute("DELETE FROM kanban_cards")
        self._conn.commit()
