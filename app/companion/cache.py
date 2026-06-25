"""Offline event cache + outgoing action queue.

The companion must keep working when the orchestrator is unreachable.
Two queues handle this:

  1. **Event replay** — when the companion reconnects, it asks the
     server for everything that happened while it was offline.  We
     don't have that yet, so this side just buffers the last 24 h of
     *locally observed* events so the UI can show them during the
     outage.  When the server comes back, the renderer is responsible
     for de-duplicating replayed events against the local buffer.

  2. **Outgoing actions** — while the server is unreachable, the
     companion stores user-issued commands locally and drains them
     FIFO when the connection returns.  Commands get a stable ID
     so the server can dedup.

Both queues are SQLite-backed so they survive a process restart.  The
TTL is configurable (default 24 h) and eviction is O(N) on every
write — fine for the expected volumes (≤ a few thousand events/day).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS event_buffer (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal',
    payload     TEXT NOT NULL,
    ts_ms       INTEGER NOT NULL,
    delivered   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_event_buffer_ts ON event_buffer(ts_ms);
CREATE INDEX IF NOT EXISTS idx_event_buffer_channel ON event_buffer(channel);

CREATE TABLE IF NOT EXISTS outgoing_actions (
    id          TEXT PRIMARY KEY,
    intent      TEXT NOT NULL,
    args        TEXT NOT NULL,
    created_ms  INTEGER NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT
);
CREATE INDEX IF NOT EXISTS idx_outgoing_created ON outgoing_actions(created_ms);
"""


class OfflineCache:
    """Buffer events + queue outgoing commands while disconnected."""

    def __init__(
        self,
        sqlite_path: str | Path | None = None,
        ttl_s: int = 24 * 60 * 60,
    ) -> None:
        self._ttl_s = ttl_s
        self._lock = threading.RLock()
        self._path: Optional[Path] = (
            Path(sqlite_path) if sqlite_path else None
        )
        # In-memory mode: keep a single shared connection so the
        # schema persists across `_connect()` calls.  Each call to
        # `_connect()` for a file-backed store opens a fresh
        # connection and re-runs the schema (idempotent).
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        if self._path is None:
            # Use a long-lived in-memory connection.
            self._memory_conn = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._memory_conn.executescript(SCHEMA)
            self._memory_conn.commit()
        else:
            # File-backed: open once, run schema, close.
            with self._connect() as conn:
                conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._path is None and self._memory_conn is not None:
            # Reuse the shared in-memory connection.  The lock
            # guarantees serialised access from multiple threads.
            yield self._memory_conn
            self._memory_conn.commit()
            return
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── event buffer ──────────────────────────────────────────────

    def buffer_event(
        self,
        event_id: str,
        channel: str,
        payload: dict[str, Any],
        priority: str = "normal",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO event_buffer "
                "(id, channel, priority, payload, ts_ms, delivered) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (
                    event_id,
                    channel,
                    priority,
                    json.dumps(payload),
                    int(time.time() * 1000),
                ),
            )
        self._evict_old_events()

    def mark_event_delivered(self, event_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE event_buffer SET delivered = 1 WHERE id = ?",
                (event_id,),
            )

    def recent_events(
        self,
        *,
        channel: str | None = None,
        since_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            sql = "SELECT id, channel, priority, payload, ts_ms, delivered FROM event_buffer"
            params: list[Any] = []
            where: list[str] = []
            if channel is not None:
                where.append("channel = ?")
                params.append(channel)
            if since_ms is not None:
                where.append("ts_ms >= ?")
                params.append(since_ms)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY ts_ms DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[3])
            except Exception:  # noqa: BLE001
                payload = {"_raw": row[3]}
            out.append({
                "id": row[0],
                "channel": row[1],
                "priority": row[2],
                "payload": payload,
                "ts_ms": row[4],
                "delivered": bool(row[5]),
            })
        return out

    def _evict_old_events(self) -> None:
        cutoff = int(time.time() * 1000) - self._ttl_s * 1000
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM event_buffer WHERE ts_ms < ?", (cutoff,)
            )

    def pending_event_count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM event_buffer WHERE delivered = 0"
            ).fetchone()
            return int(row[0] if row else 0)

    # ── outgoing actions ──────────────────────────────────────────

    def queue_action(
        self, action_id: str, intent: str, args: dict[str, Any]
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO outgoing_actions "
                "(id, intent, args, created_ms, attempts, last_error) "
                "VALUES (?, ?, ?, ?, 0, NULL)",
                (
                    action_id,
                    intent,
                    json.dumps(args),
                    int(time.time() * 1000),
                ),
            )

    def pending_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, intent, args, created_ms, attempts, last_error "
                "FROM outgoing_actions ORDER BY created_ms ASC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                args = json.loads(row[2])
            except Exception:  # noqa: BLE001
                args = {}
            out.append({
                "id": row[0],
                "intent": row[1],
                "args": args,
                "created_ms": row[3],
                "attempts": row[4],
                "last_error": row[5],
            })
        return out

    def mark_action_sent(self, action_id: str, error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            if error is None:
                conn.execute(
                    "DELETE FROM outgoing_actions WHERE id = ?", (action_id,)
                )
            else:
                conn.execute(
                    "UPDATE outgoing_actions SET attempts = attempts + 1, "
                    "last_error = ? WHERE id = ?",
                    (error, action_id),
                )

    def pending_action_count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM outgoing_actions"
            ).fetchone()
            return int(row[0] if row else 0)

    # ── health ────────────────────────────────────────────────────

    def purge(self) -> None:
        """Drop everything.  Tests use this between cases."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM event_buffer")
            conn.execute("DELETE FROM outgoing_actions")

    @property
    def ttl_s(self) -> int:
        return self._ttl_s

    @property
    def is_persistent(self) -> bool:
        return self._path is not None


__all__ = ["OfflineCache"]