"""RLHF — Reinforcement Learning from Human Feedback for Raven.

Uses existing preference signals (thumbs up/down, corrections, feedback scores)
to bias the model router toward response strategies that users prefer.

The key insight: we already track confidence scores, helpfulness scores, and
feedback counts for every learning item and response. This module closes the
loop by using those signals to influence future behavior.

Architecture:
    PreferenceStore  — records explicit (thumbs) and implicit (correction → no
                       repeat) preference signals
    RlhfRouter       — wraps the model router to prefer providers/styles that
                       historically get better feedback for a given task type
    RlhfCrystallizer — extracts "rules of thumb" from high-preference responses
                       and injects them into the system prompt
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PreferenceSample:
    """A single preference signal from user feedback."""

    task_type: str  # e.g. "research", "coding", "writing", "general"
    provider_id: str
    model_id: str
    response_style: str  # e.g. "concise", "detailed", "creative", "analytical"
    preferred: bool  # True = positive signal, False = negative
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    context_hint: str = ""


class PreferenceStore:
    """SQLite-backed store for preference signals.

    Tracks per-provider, per-style preference aggregates and supports
    decay-weighted queries.
    """

    def __init__(self, db_path: str | Path = "workspace/memory/rlhf.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL DEFAULT '',
                response_style TEXT NOT NULL DEFAULT 'general',
                preferred INTEGER NOT NULL,
                context_hint TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pref_task ON preferences(task_type);
            CREATE INDEX IF NOT EXISTS idx_pref_provider ON preferences(provider_id);
        """)

    def record(
        self,
        task_type: str,
        provider_id: str,
        model_id: str = "",
        response_style: str = "general",
        preferred: bool = True,
        context_hint: str = "",
    ) -> int:
        """Record a single preference signal.

        Args:
            task_type: Category like research, coding, writing, general.
            provider_id: The LLM provider used.
            model_id: The specific model used.
            response_style: Style like concise, detailed, creative.
            preferred: True for positive signal, False for negative.
            context_hint: Optional free-text context.

        Returns:
            The new row ID.
        """
        cur = self._conn.execute(
            "INSERT INTO preferences (task_type, provider_id, model_id, response_style, preferred, context_hint) VALUES (?, ?, ?, ?, ?, ?)",
            (task_type, provider_id, model_id, response_style, 1 if preferred else 0, context_hint),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_preference_score(
        self,
        provider_id: str,
        task_type: str | None = None,
        *,
        decay_days: float = 30.0,
    ) -> float:
        """Return a preference score [0, 1] for a given provider.

        Uses time-decayed weighting — recent signals count more.
        0 = always negative, 1 = always positive, 0.5 = no data.
        """
        import time

        now = time.time()
        decay_seconds = decay_days * 86400

        rows = self._conn.execute(
            "SELECT preferred, created_at FROM preferences WHERE provider_id = ?",
            (provider_id,),
        ).fetchall()

        if not rows:
            return 0.5

        total_weight = 0.0
        weighted_sum = 0.0

        for row in rows:
            age_seconds = now - datetime.fromisoformat(row["created_at"]).timestamp()
            weight = max(0.01, 1.0 - (age_seconds / decay_seconds))
            weighted_sum += weight * (1.0 if row["preferred"] else 0.0)
            total_weight += weight

        return weighted_sum / max(total_weight, 0.001)

    def get_top_providers(self, task_type: str, n: int = 3) -> list[dict[str, Any]]:
        """Return the top-N providers ranked by preference score for a task type."""
        rows = self._conn.execute(
            """
            SELECT provider_id,
                   AVG(CASE WHEN preferred THEN 1.0 ELSE 0.0 END) as score,
                   COUNT(*) as samples
            FROM preferences
            WHERE task_type = ?
            GROUP BY provider_id
            ORDER BY score DESC
            LIMIT ?
            """,
            (task_type, n),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_preferred_style(self, task_type: str) -> str:
        """Return the most preferred response style for a task type."""
        row = self._conn.execute(
            """
            SELECT response_style, AVG(CASE WHEN preferred THEN 1.0 ELSE 0.0 END) as score
            FROM preferences
            WHERE task_type = ?
            GROUP BY response_style
            ORDER BY score DESC
            LIMIT 1
            """,
            (task_type,),
        ).fetchone()
        return str(row["response_style"]) if row else "general"


class RlhfRouter:
    """Wraps the model router to inject preference data.

    When the orchestrator needs to pick a provider for a task, this module
    biases the selection toward providers that historically get better feedback
    for similar tasks.
    """

    def __init__(self, store: PreferenceStore | None = None) -> None:
        self._store = store or PreferenceStore()

    async def rank_providers(
        self,
        task_type: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rank candidate providers by RLHF preference score.

        Args:
            task_type: e.g. "research", "coding", "writing", "general"
            candidates: list of {provider_id, model_id, base_score}

        Returns:
            Sorted copy of candidates with 'rlhf_score' added.
        """
        scored: list[dict[str, Any]] = []
        for c in candidates:
            pref = self._store.get_preference_score(
                c["provider_id"],
                task_type=task_type,
            )
            c["rlhf_score"] = pref
            # Blend base score with RLHF (70% base, 30% RLHF when data exists)
            if pref != 0.5:
                c["blended_score"] = 0.7 * c.get("base_score", 0.5) + 0.3 * pref
            else:
                c["blended_score"] = c.get("base_score", 0.5)
            scored.append(c)

        return sorted(scored, key=lambda x: x["blended_score"], reverse=True)


class RlhfCrystallizer:
    """Extracts learned preferences into actionable prompt rules.

    When we see strong preference patterns (e.g. "user prefers concise
    answers for coding tasks"), we crystallize them into rules that get
    injected into the system prompt.
    """

    def __init__(self, store: PreferenceStore | None = None) -> None:
        self._store = store or PreferenceStore()

    def build_preference_prompt(self) -> str:
        """Build a system prompt addendum from learned preferences."""
        parts: list[str] = []
        styles_seen: set[str] = set()

        # Get task types that have preference data
        task_rows = self._store._conn.execute(
            "SELECT DISTINCT task_type FROM preferences WHERE preferred = 1"
        ).fetchall()

        for row in task_rows:
            task_type = row["task_type"]
            style = self._store.get_preferred_style(task_type)
            if style not in styles_seen:
                styles_seen.add(style)
                parts.append(f"- For {task_type} tasks, user prefers {style} responses.")

        if not parts:
            return ""

        return "\n".join(["", "## Learned Preferences (RLHF)", ""] + parts)


# Singleton
_pref_store: PreferenceStore | None = None


def get_preference_store() -> PreferenceStore:
    """Return the singleton PreferenceStore instance."""
    global _pref_store
    if _pref_store is None:
        _pref_store = PreferenceStore()
    return _pref_store


def record_feedback(
    task_type: str,
    provider_id: str,
    preferred: bool,
    model_id: str = "",
    response_style: str = "",
) -> None:
    """Convenience: record a preference signal from anywhere."""
    store = get_preference_store()
    store.record(
        task_type=task_type,
        provider_id=provider_id,
        model_id=model_id,
        response_style=response_style or "general",
        preferred=preferred,
    )
