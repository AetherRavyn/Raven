from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS learnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT    NOT NULL,
    topic         TEXT    NOT NULL DEFAULT '',
    content       TEXT    NOT NULL,
    confidence    REAL    NOT NULL DEFAULT 0.5,
    metadata      TEXT    NOT NULL DEFAULT '{}',
    source        TEXT    NOT NULL DEFAULT '',
    turn_created  INTEGER NOT NULL DEFAULT 0,
    turn_last_used INTEGER NOT NULL DEFAULT 0,
    use_count     INTEGER NOT NULL DEFAULT 0,
    helpfulness_score REAL NOT NULL DEFAULT 0.0,
    feedback_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type);
CREATE INDEX IF NOT EXISTS idx_learnings_topic ON learnings(topic);
CREATE INDEX IF NOT EXISTS idx_learnings_confidence ON learnings(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_learnings_created ON learnings(created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
    topic, content, metadata,
    content='learnings',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_learnings_ai AFTER INSERT ON learnings BEGIN
    INSERT INTO learnings_fts(rowid, topic, content, metadata)
    VALUES (new.id, new.topic, new.content, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS trg_learnings_ad AFTER DELETE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, topic, content, metadata)
    VALUES ('delete', old.id, old.topic, old.content, old.metadata);
END;

CREATE TRIGGER IF NOT EXISTS trg_learnings_au AFTER UPDATE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, topic, content, metadata)
    VALUES ('delete', old.id, old.topic, old.content, old.metadata);
    INSERT INTO learnings_fts(rowid, topic, content, metadata)
    VALUES (new.id, new.topic, new.content, new.metadata);
END;
"""


class LearningStore:
    """Unified SQLite + FTS5 store for all learning signals.

    Replaces CorrectionStore, PromptImprover, SuccessPatternLearner,
    FactExtractor, and LearningHealthMonitor with a single queryable store.
    """

    def __init__(self, db_path: str | Path = "workspace/memory/learning.db") -> None:
        """Initialize the learning store.

        Args:
            db_path: Path to the SQLite database file.
        """
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
        """Create tables and indexes if they don't exist."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    def add(
        self,
        type_: str,
        content: str,
        *,
        topic: str = "",
        confidence: float = 0.5,
        metadata: dict[str, Any] | None = None,
        source: str = "",
        turn: int = 0,
    ) -> int:
        """Store a new learning item.

        Args:
            type_: Category (e.g. correction, insight, success_pattern).
            content: The learning content text.
            topic: Optional topic label for grouping.
            confidence: Initial confidence score [0, 1].
            metadata: Arbitrary key-value metadata.
            source: Origin identifier (e.g. system, user, migration).
            turn: Conversation turn number when created.

        Returns:
            The new row ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO learnings (type, topic, content, confidence, metadata, source, turn_created, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                type_,
                topic,
                content,
                confidence,
                json.dumps(metadata or {}),
                source,
                turn,
                now,
                now,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get(self, id_: int) -> dict[str, Any] | None:
        """Retrieve a single learning item by ID.

        Args:
            id_: The row ID.

        Returns:
            Dict of the row, or None if not found.
        """
        row = self._conn.execute("SELECT * FROM learnings WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None

    def search(
        self,
        query: str,
        *,
        type_: str | None = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Full-text search across learnings using FTS5.

        Args:
            query: Free-text search string (stripped of FTS special chars).
            type_: Optional type filter.
            limit: Max results.
            min_confidence: Minimum confidence threshold.

        Returns:
            List of matching rows, ordered by FTS rank.
        """
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return []
        sql = """
            SELECT l.*, rank
            FROM learnings_fts
            JOIN learnings l ON l.id = learnings_fts.rowid
            WHERE learnings_fts MATCH ?
        """
        params: list[Any] = [fts_query]
        if type_:
            sql += " AND l.type = ?"
            params.append(type_)
        if min_confidence > 0:
            sql += " AND l.confidence >= ?"
            params.append(min_confidence)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_recent(
        self,
        *,
        type_: str | None = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Get the most recently created learning items.

        Args:
            type_: Optional type filter.
            limit: Max results.
            min_confidence: Minimum confidence threshold.

        Returns:
            List of recent rows ordered by created_at DESC.
        """
        sql = "SELECT * FROM learnings WHERE 1=1"
        params: list[Any] = []
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        if min_confidence > 0:
            sql += " AND confidence >= ?"
            params.append(min_confidence)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_by_topic(
        self,
        topic: str,
        *,
        type_: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find learning items by exact topic match.

        Args:
            topic: The topic string to match.
            type_: Optional type filter.
            limit: Max results.

        Returns:
            List of matching rows ordered by confidence DESC.
        """
        sql = "SELECT * FROM learnings WHERE topic = ?"
        params: list[Any] = [topic]
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        sql += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def record_use(self, id_: int) -> None:
        """Increment the use counter for a learning item.

        Args:
            id_: The row ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            UPDATE learnings
            SET use_count = use_count + 1, turn_last_used = MAX(turn_last_used, 1), updated_at = ?
            WHERE id = ?
            """,
            (now, id_),
        )
        self._conn.commit()

    def record_feedback(self, id_: int, helpful: bool) -> None:
        """Record explicit thumbs-up/down feedback.

        Args:
            id_: The row ID.
            helpful: True for positive feedback, False for negative.
        """
        now = datetime.now(timezone.utc).isoformat()
        delta = 1.0 if helpful else -0.5
        self._conn.execute(
            """
            UPDATE learnings
            SET helpfulness_score = helpfulness_score + ?,
                feedback_count = feedback_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (delta, now, id_),
        )
        self._conn.commit()

    def update_confidence(self, id_: int, confidence: float) -> None:
        """Update the confidence score for a learning item.

        Args:
            id_: The row ID.
            confidence: New confidence value [0, 1].
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE learnings SET confidence = ?, updated_at = ? WHERE id = ?",
            (confidence, now, id_),
        )
        self._conn.commit()

    # ── dedup / pruning ─────────────────────────────────────────────────

    def find_duplicate(
        self, type_: str, content: str, *, threshold: float = 0.9
    ) -> dict[str, Any] | None:
        """Fuzzy dedup via FTS5 — find the closest match above threshold."""
        # Use FTS5 snippet matching for near-exact dedup
        rows = self.search(content, type_=type_, limit=3)
        for r in rows:
            if self._similarity(r["content"], content) >= threshold:
                return r
        return None

    def prune(
        self,
        *,
        min_confidence: float = 0.3,
        max_per_type: int = 100,
        max_total: int = 500,
    ) -> dict[str, int]:
        """Remove low-confidence and excess learning items.

        Args:
            min_confidence: Items below this threshold are removed.
            max_per_type: Max items allowed per type.
            max_total: Absolute max items across all types.

        Returns:
            Dict with keys 'low_confidence' and 'excess' counting removals.
        """
        removed = {"low_confidence": 0, "excess": 0}

        # Remove low-confidence items
        cur = self._conn.execute("DELETE FROM learnings WHERE confidence < ?", (min_confidence,))
        removed["low_confidence"] = cur.rowcount

        # Cap per type
        for row in self._conn.execute(
            "SELECT type, COUNT(*) as cnt FROM learnings GROUP BY type"
        ).fetchall():
            type_ = row["type"]
            count = row["cnt"]
            if count > max_per_type:
                excess = count - max_per_type
                ids_to_remove = [
                    r["id"]
                    for r in self._conn.execute(
                        """
                        SELECT id FROM learnings
                        WHERE type = ?
                        ORDER BY confidence ASC, use_count ASC, helpfulness_score ASC
                        LIMIT ?
                        """,
                        (type_, excess),
                    ).fetchall()
                ]
                for id_ in ids_to_remove:
                    self._conn.execute("DELETE FROM learnings WHERE id = ?", (id_,))
                removed["excess"] += len(ids_to_remove)

        # Cap total
        count = self._conn.execute("SELECT COUNT(*) as c FROM learnings").fetchone()["c"]
        if count > max_total:
            excess = count - max_total
            ids_to_remove = [
                r["id"]
                for r in self._conn.execute(
                    """
                    SELECT id FROM learnings
                    ORDER BY confidence ASC, use_count ASC, helpfulness_score ASC
                    LIMIT ?
                    """,
                    (excess,),
                ).fetchall()
            ]
            for id_ in ids_to_remove:
                self._conn.execute("DELETE FROM learnings WHERE id = ?", (id_,))
            removed["excess"] += len(ids_to_remove)

        self._conn.commit()
        return removed

    # ── analytics ───────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the store contents.

        Returns:
            Dict with total count, per-type breakdown, and average confidence.
        """
        stats: dict[str, Any] = {"total": 0, "by_type": {}, "avg_confidence": 0.0}
        row = self._conn.execute(
            "SELECT COUNT(*) as c, AVG(confidence) as avg FROM learnings"
        ).fetchone()
        stats["total"] = row["c"] or 0
        stats["avg_confidence"] = row["avg"] or 0.0
        for r in self._conn.execute(
            "SELECT type, COUNT(*) as cnt FROM learnings GROUP BY type"
        ).fetchall():
            stats["by_type"][r["type"]] = r["cnt"]
        return stats

    def get_context(self, query: str, *, max_items: int = 5, min_confidence: float = 0.4) -> str:
        """Return a formatted string of relevant learnings for prompt injection."""
        results = self.search(query, limit=max_items, min_confidence=min_confidence)
        if not results:
            return ""
        lines: list[str] = ["Relevant learnings from past interactions:"]
        for r in results:
            tag = r["type"].replace("_", " ").title()
            lines.append(f"- [{tag}] {r['content'][:200]}")
            meta = (
                json.loads(r["metadata"])
                if isinstance(r["metadata"], str)
                else r.get("metadata", {})
            )
            if meta.get("source"):
                lines[-1] += f" (source: {meta['source']})"
            self.record_use(r["id"])
        return "\n".join(lines)

    def vacuum(self) -> int:
        """Run VACUUM to reclaim SQLite space from deleted rows.

        Returns the size delta in bytes (positive = space reclaimed), or 0
        if the database file doesn't exist or VACUUM fails.
        """
        path = self._db_path
        before = path.stat().st_size if path.exists() else 0
        try:
            self._conn.execute("VACUUM")
            self._conn.commit()
        except Exception:
            logger.warning("VACUUM failed on %s", path)
            return 0
        after = path.stat().st_size if path.exists() else 0
        return max(0, before - after)

    # ── migration helpers ───────────────────────────────────────────────

    def migrate_from_json(self, type_: str, items: list[dict[str, Any]]) -> int:
        """Bulk-import items from a legacy JSON store."""
        count = 0
        for item in items:
            dup = self.find_duplicate(type_, item.get("content", item.get("corrected_claim", "")))
            if dup:
                continue
            self.add(
                type_=type_,
                content=item.get("content", item.get("corrected_claim", "")),
                topic=item.get("topic", ""),
                confidence=item.get("confidence", 0.5),
                metadata={
                    k: v
                    for k, v in item.items()
                    if k not in ("content", "topic", "confidence", "type")
                },
                source=item.get("source", "migration"),
            )
            count += 1
        return count

    def most_used(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most frequently used learnings, by use_count."""
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM learnings ORDER BY use_count DESC, helpfulness_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]

    def topic_trends(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return topic frequency counts, sorted by count descending."""
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT topic, COUNT(*) as cnt FROM learnings WHERE topic != '' GROUP BY topic ORDER BY cnt DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]

    # ── internal ────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize query for FTS5 MATCH by stripping special chars."""
        import re

        # Replace FTS5 special characters with space
        cleaned = re.sub(r'[+^~*(){}@"\[\]/\\-]', " ", query)
        words = [w for w in cleaned.split() if w.strip() and w.lower() not in ("or", "and", "not")]
        return " ".join(words) if words else ""

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Simple token-overlap similarity for dedup."""
        if not a or not b:
            return 0.0
        a_tokens = set(a.lower().split())
        b_tokens = set(b.lower().split())
        if not a_tokens or not b_tokens:
            return 0.0
        intersection = a_tokens & b_tokens
        return len(intersection) / max(len(a_tokens), len(b_tokens))

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def clear(self) -> None:
        """Delete all learning items and rebuild FTS index."""
        self._conn.executescript("DELETE FROM learnings; DELETE FROM learnings_fts;")
        self._conn.commit()


# Singleton
_store: LearningStore | None = None


def get_learning_store(db_path: str | Path | None = None) -> LearningStore:
    """Return the singleton LearningStore instance.

    Args:
        db_path: Optional path override; only used on first call.

    Returns:
        The shared LearningStore instance.
    """
    global _store
    if _store is None:
        _store = LearningStore(db_path or "workspace/memory/learning.db")
    return _store
