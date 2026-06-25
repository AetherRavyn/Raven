"""SQLite-backed persistence for proactive rate-limit state.

Replaces InMemoryRateLimitStore for production use. Survives
process restarts. Auto-prunes entries older than 24h.

Schema:
    proactive_deliveries(user_id TEXT, ts REAL)
    proactive_seen(user_id TEXT, fingerprint TEXT, ts REAL, PRIMARY KEY(user_id, fingerprint))
    proactive_feedback(user_id TEXT, kind_source TEXT, ts REAL)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_AGE_S = 86400.0  # 24 hours


class SQLiteRateLimitStore:
    """SQLite-backed RateLimitStore. Drop-in replacement for InMemoryRateLimitStore."""

    def __init__(self, db_path: str | None = None) -> None:
        from app.settings.config import Config

        if db_path is None:
            db_path = str(Path(Config.MEMORY_ROOT) / "proactive.sqlite")
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
            CREATE TABLE IF NOT EXISTS proactive_deliveries (
                user_id TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proactive_seen (
                user_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                ts REAL NOT NULL,
                PRIMARY KEY (user_id, fingerprint)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proactive_feedback (
                user_id TEXT NOT NULL,
                kind_source TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_del_user ON proactive_deliveries(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_user ON proactive_feedback(user_id, kind_source)")
        conn.commit()

    def _prune(self, user_id: str, now: float) -> None:
        cutoff = now - _MAX_AGE_S
        conn = self._get_conn()
        conn.execute("DELETE FROM proactive_deliveries WHERE user_id=? AND ts<?", (user_id, cutoff))
        conn.execute("DELETE FROM proactive_seen WHERE user_id=? AND ts<?", (user_id, cutoff))
        conn.execute("DELETE FROM proactive_feedback WHERE user_id=? AND ts<?", (user_id, cutoff))
        conn.commit()

    def last_delivered(self, user_id: str) -> list[float]:
        now = time.time()
        self._prune(user_id, now)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ts FROM proactive_deliveries WHERE user_id=? ORDER BY ts", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def record(self, user_id: str, ts: float) -> None:
        conn = self._get_conn()
        conn.execute("INSERT INTO proactive_deliveries (user_id, ts) VALUES (?, ?)", (user_id, ts))
        conn.commit()

    def seen(self, user_id: str, fingerprint: str, within_s: float) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT ts FROM proactive_seen WHERE user_id=? AND fingerprint=?",
            (user_id, fingerprint),
        ).fetchone()
        if row is None:
            return False
        return (time.time() - row[0]) <= within_s

    def mark_seen(self, user_id: str, fingerprint: str, ts: float) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO proactive_seen (user_id, fingerprint, ts) VALUES (?, ?, ?)",
            (user_id, fingerprint, ts),
        )
        conn.commit()

    def feedback_count(self, user_id: str, kind_source: str, since: float) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM proactive_feedback WHERE user_id=? AND kind_source=? AND ts>=?",
            (user_id, kind_source, since),
        ).fetchone()
        return row[0] if row else 0

    def record_feedback(self, user_id: str, kind_source: str, ts: float) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO proactive_feedback (user_id, kind_source, ts) VALUES (?, ?, ?)",
            (user_id, kind_source, ts),
        )
        conn.commit()
