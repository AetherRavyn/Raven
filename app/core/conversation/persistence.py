"""SQLite persistence for ConversationManager working memory.

Auto-checkpoints working memory to disk on every turn and
auto-restores on session access. Survives process restarts.

Schema:
    conversation_sessions(
        session_id  TEXT PRIMARY KEY,
        user_id     TEXT,
        data        TEXT,       -- JSON from WorkingMemory.to_dict()
        updated_at  TEXT        -- ISO timestamp
    )

Old sessions (>24h idle) are pruned on each save to prevent
unbounded growth.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRUNE_AGE_HOURS = 24


class ConversationPersistence:
    """SQLite-backed persistence for conversation working memory."""

    def __init__(self, db_path: str | None = None) -> None:
        from app.settings.config import Config

        if db_path is None:
            db_path = str(Path(Config.MEMORY_ROOT) / "conversation.sqlite")
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=3000")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                session_id TEXT PRIMARY KEY,
                user_id    TEXT DEFAULT '',
                data       TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_updated
            ON conversation_sessions(updated_at)
        """)
        conn.commit()

    def save(self, session_id: str, data: dict[str, Any], user_id: str = "") -> None:
        """Persist working memory dict. Thread-safe."""
        try:
            conn = self._get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO conversation_sessions "
                "(session_id, user_id, data, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, json.dumps(data, default=str), now),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("ConversationPersistence.save failed for %s: %s", session_id, exc)

    def load(self, session_id: str) -> dict[str, Any] | None:
        """Load working memory dict. Returns None if not found."""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT data FROM conversation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception as exc:
            logger.warning("ConversationPersistence.load failed for %s: %s", session_id, exc)
            return None

    def delete(self, session_id: str) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM conversation_sessions WHERE session_id = ?", (session_id,)
            )
            conn.commit()
        except Exception as exc:
            logger.debug("ConversationPersistence.delete failed: %s", exc)

    def prune_old(self, hours: int = _PRUNE_AGE_HOURS) -> int:
        """Remove sessions idle for more than `hours`. Returns count removed."""
        try:
            conn = self._get_conn()
            cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
            cutoff_str = cutoff_dt.isoformat()
            cur = conn.execute(
                "DELETE FROM conversation_sessions WHERE updated_at < ?", (cutoff_str,)
            )
            conn.commit()
            return cur.rowcount
        except Exception as exc:
            logger.debug("ConversationPersistence.prune_old failed: %s", exc)
            return 0

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """List recent sessions with metadata."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT session_id, user_id, updated_at "
                "FROM conversation_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {"session_id": r[0], "user_id": r[1], "updated_at": r[2]}
                for r in rows
            ]
        except Exception:
            return []
