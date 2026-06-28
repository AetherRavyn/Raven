from __future__ import annotations

import logging
from typing import Any

from app.core.learning_db import get_learning_store

logger = logging.getLogger(__name__)


class IntelligentRetriever:
    """Query-time retrieval from the unified LearningStore.

    Replaces the bootstrapper's prompt-injection-of-everything with
    targeted FTS5 retrieval — only the top-k most relevant learnings
    are injected, keeping the prompt lean.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store or get_learning_store()

    @property
    def store(self):
        return self._store

    # ── public API ──────────────────────────────────────────────────────

    def get_injection_block(
        self,
        query: str,
        *,
        max_items: int = 5,
        min_confidence: float = 0.4,
        include_types: list[str] | None = None,
    ) -> str:
        """Return a formatted block of relevant learnings for prompt injection.

        Each item records a use automatically for feedback tracking.
        """
        results = self._retrieve(
            query,
            max_items=max_items,
            min_confidence=min_confidence,
            types=include_types,
        )
        if not results:
            return ""

        lines: list[str] = [
            "---",
            "## Relevant Learnings",
            "The following past learnings may be relevant to this request:",
        ]
        for r in results:
            badge = self._badge(r["confidence"])
            tag = r["type"].replace("_", " ").title()
            lines.append(f"{badge} **{tag}**: {r['content'][:200]}")
            if r.get("topic"):
                lines[-1] += f" *(topic: {r['topic']})*"

        lines.append("---")
        return "\n".join(lines)

    def get_compact_context(
        self,
        query: str,
        *,
        max_items: int = 3,
        min_confidence: float = 0.5,
    ) -> str:
        """Ultra-lean context block for token-constrained environments."""
        results = self._retrieve(
            query,
            max_items=max_items,
            min_confidence=min_confidence,
        )
        if not results:
            return ""
        items = [f"  {r['content'][:120]}" for r in results]
        return "Past learnings:\n" + "\n".join(items)

    def get_topics_summary(self) -> str:
        """Return a one-line summary of topics learned."""
        stats = self._store.get_stats()
        types = stats.get("by_type", {})
        parts = [f"{k}: {v}" for k, v in sorted(types.items())]
        return f"Learned {stats['total']} items over {len(parts)} categories. " + ", ".join(parts)

    # ── feedback tracking ───────────────────────────────────────────────

    def record_injection_feedback(
        self,
        injection_text: str,
        response_success: bool,
    ) -> int:
        """Record feedback for items mentioned in an injection block.

        Returns the number of items updated.
        """
        count = 0
        for line in injection_text.splitlines():
            for word in line.split():
                word_clean = word.strip("*():,.!?")
                # Try to find a learning by content prefix
                results = self._store.search(word_clean, limit=5, min_confidence=0.0)
                for r in results:
                    if r["content"][:50] in injection_text:
                        self._store.record_feedback(r["id"], helpful=response_success)
                        count += 1
                        break
        return count

    # ── internal helpers ────────────────────────────────────────────────

    def _retrieve(
        self,
        query: str,
        *,
        max_items: int = 5,
        min_confidence: float = 0.4,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant learnings for a query."""
        results: list[dict[str, Any]] = []

        # Try FTS5 search first
        for type_ in types or [None]:
            batch = self._store.search(
                query,
                type_=type_,
                limit=max_items,
                min_confidence=min_confidence,
            )
            results.extend(batch)

        # Dedup by id
        seen: set[int] = set()
        deduped = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)
                self._store.record_use(r["id"])

        return deduped[:max_items]

    @staticmethod
    def _badge(confidence: float) -> str:
        if confidence >= 0.9:
            return "⭐"
        if confidence >= 0.7:
            return "✅"
        return "📘"
