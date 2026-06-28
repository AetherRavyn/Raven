from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.learning_db import get_learning_store
from app.core.skill_crystallizer import SkillCrystallizer

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """Active knowledge management over the LearningStore.

    Detects duplicates, merges similar items, flags contradictions,
    archives stale knowledge, and promotes high-value items to skills.
    Neither Hermes Agent nor OpenClaw has an equivalent — this is the
    brain that keeps learned knowledge clean, non-contradictory, and
    increasingly valuable over time.
    """

    def __init__(
        self,
        store: Any | None = None,
        crystallizer: Any | None = None,
    ) -> None:
        self._store = store or get_learning_store()
        self._crystallizer = crystallizer or SkillCrystallizer()

    # ── public API ──────────────────────────────────────────────────────

    def consolidate_all(
        self,
        *,
        similarity_threshold: float = 0.8,
        stale_days: int = 30,
        promote_confidence: float = 0.85,
        promote_min_uses: int = 5,
    ) -> dict[str, Any]:
        """Run all consolidation passes in dependency order.

        Returns a summary dict with counts for each operation.
        """
        results: dict[str, Any] = {
            "merges": 0,
            "deletions": 0,
            "contradictions": [],
            "promotions": [],
            "errors": [],
        }

        # 1. Merge near-duplicates (also eliminates exact duplicates)
        try:
            merged = self._dedup_and_merge(similarity_threshold=similarity_threshold)
            results["merges"] = merged
            if merged:
                logger.info("Consolidation: merged %d duplicate learnings", merged)
        except Exception as exc:
            logger.warning("Consolidation dedup failed: %s", exc)
            results["errors"].append(f"dedup: {exc}")

        # 2. Detect contradictions
        try:
            contradictions = self._detect_contradictions()
            results["contradictions"] = contradictions
            if contradictions:
                logger.info("Consolidation: found %d potential contradictions", len(contradictions))
        except Exception as exc:
            logger.warning("Consolidation contradiction detection failed: %s", exc)
            results["errors"].append(f"contradiction: {exc}")

        # 3. Archive stale items
        try:
            archived = self._archive_stale(stale_days=stale_days)
            results["deletions"] = archived
            if archived:
                logger.info("Consolidation: archived %d stale learnings", archived)
        except Exception as exc:
            logger.warning("Consolidation archive failed: %s", exc)
            results["errors"].append(f"archive: {exc}")

        # 4. Promote high-value items to skills
        try:
            promoted = self._promote_to_skills(
                min_confidence=promote_confidence,
                min_uses=promote_min_uses,
            )
            results["promotions"] = promoted
            if promoted:
                logger.info("Consolidation: promoted %d items to skills", len(promoted))
        except Exception as exc:
            logger.warning("Consolidation promotion failed: %s", exc)
            results["errors"].append(f"promote: {exc}")

        return results

    def get_contradictions_report(self) -> list[dict[str, Any]]:
        """Return detailed contradictions for human review."""
        return self._detect_contradictions()

    def get_stale_items(self, stale_days: int = 30) -> list[dict[str, Any]]:
        """Return items that would be archived (dry-run)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        all_items = self._store.get_recent(limit=1000, min_confidence=0.0)
        stale = []
        for item in all_items:
            if item.get("use_count", 0) > 0:
                continue
            created = item.get("created_at", "")
            if created and created < cutoff:
                if item.get("confidence", 0) < 0.4:
                    stale.append(item)
        return stale

    # ── pass 1: dedup & merge ──────────────────────────────────────────

    def _dedup_and_merge(self, similarity_threshold: float = 0.8) -> int:
        """Find and merge near-duplicate learnings within each type."""
        merged_count = 0
        types = self._store.get_stats().get("by_type", {})

        for type_ in types:
            items = self._store.get_recent(type_=type_, limit=500, min_confidence=0.0)
            for i in range(len(items)):
                if items[i] is None:
                    continue
                for j in range(i + 1, len(items)):
                    if items[j] is None:
                        continue
                    score = self._compute_similarity(items[i]["content"], items[j]["content"])
                    if score >= similarity_threshold:
                        self._merge_pair(items[i], items[j])
                        items[j] = None  # mark as consumed
                        merged_count += 1
                        logger.debug(
                            "Merged duplicate (similarity=%.2f): %s",
                            score,
                            items[i]["content"][:50],
                        )

        return merged_count

    def _merge_pair(self, keep: dict[str, Any], remove: dict[str, Any]) -> None:
        """Merge *remove* into *keep*, then delete *remove*."""
        keep_id = keep["id"]
        remove_id = remove["id"]

        # Keep the higher-confidence version
        final_confidence = max(keep.get("confidence", 0.0), remove.get("confidence", 0.0))
        final_content = (
            keep["content"]
            if keep.get("confidence", 0.0) >= remove.get("confidence", 0.0)
            else remove["content"]
        )
        final_uses = (keep.get("use_count", 0) or 0) + (remove.get("use_count", 0) or 0)
        final_feedback = (keep.get("helpfulness_score", 0.0) or 0.0) + (
            remove.get("helpfulness_score", 0.0) or 0.0
        )

        self._store.update_confidence(keep_id, final_confidence)
        if final_content != keep["content"]:
            self._store._conn.execute(
                "UPDATE learnings SET content = ? WHERE id = ?",
                (final_content, keep_id),
            )
        self._store._conn.execute(
            "UPDATE learnings SET use_count = ?, helpfulness_score = ? WHERE id = ?",
            (final_uses, final_feedback, keep_id),
        )
        self._store._conn.execute("DELETE FROM learnings WHERE id = ?", (remove_id,))
        self._store._conn.commit()

    # ── pass 2: contradiction detection ─────────────────────────────────

    def _detect_contradictions(self) -> list[dict[str, Any]]:
        """Find items within the same topic that may contradict each other.

        Uses a two-phase approach:
        1. High structural similarity + different key values → contradiction
        2. Low token overlap on same topic → possible contradiction
        """
        import re

        contradictions: list[dict[str, Any]] = []
        topics: dict[str, list[dict[str, Any]]] = {}

        for row in self._store.get_recent(limit=1000, min_confidence=0.0):
            topic = (row.get("topic") or "").strip().lower()
            if not topic:
                continue
            topics.setdefault(topic, []).append(row)

        for topic, items in topics.items():
            if len(items) < 2:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if a["type"] != b["type"]:
                        continue

                    sim = self._compute_similarity(a["content"], b["content"])
                    content_a, content_b = a["content"], b["content"]

                    # Phase 1: High structural similarity + different key values
                    # (same sentence structure but different numbers/entities)
                    if 0.5 <= sim < 0.95:
                        values_a = set(re.findall(r"\d+", content_a))
                        values_b = set(re.findall(r"\d+", content_b))
                        has_diff_values = bool(values_a and values_b and values_a != values_b)
                        has_diff_quotes = self._quotes_differ(content_a, content_b)
                        if has_diff_values or has_diff_quotes:
                            contradictions.append(
                                self._make_contradiction(topic, a, b, sim, "different_values")
                            )

                    # Phase 2: Low token overlap on same topic (very different claims)
                    if sim < 0.35:
                        contradictions.append(
                            self._make_contradiction(topic, a, b, sim, "low_overlap")
                        )

        return contradictions[:50]

    @staticmethod
    def _quotes_differ(a: str, b: str) -> bool:
        """Check if quoted strings differ between two texts."""
        import re

        quotes_a = set(re.findall(r'"([^"]*)"', a))
        quotes_b = set(re.findall(r'"([^"]*)"', b))
        if quotes_a and quotes_b:
            return quotes_a != quotes_b
        # Also check single-quoted or path-like patterns
        paths_a = set(re.findall(r"(?:/[a-zA-Z0-9._-]+)+", a))
        paths_b = set(re.findall(r"(?:/[a-zA-Z0-9._-]+)+", b))
        if paths_a and paths_b:
            return paths_a != paths_b
        return False

    @staticmethod
    def _make_contradiction(
        topic: str,
        a: dict[str, Any],
        b: dict[str, Any],
        sim: float,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "topic": topic,
            "type": a["type"],
            "reason": reason,
            "item_a": {"id": a["id"], "content": a["content"][:150]},
            "item_b": {"id": b["id"], "content": b["content"][:150]},
            "similarity": round(sim, 3),
        }

    # ── pass 3: archive stale ───────────────────────────────────────────

    def _archive_stale(self, stale_days: int = 30) -> int:
        """Delete low-confidence, never-used items older than *stale_days*."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        cur = self._store._conn.execute(
            """
            DELETE FROM learnings
            WHERE confidence < 0.4
              AND (use_count IS NULL OR use_count = 0)
              AND created_at < ?
            """,
            (cutoff,),
        )
        self._store._conn.commit()
        return cur.rowcount

    # ── pass 4: promote to skills ───────────────────────────────────────

    def _promote_to_skills(
        self,
        min_confidence: float = 0.85,
        min_uses: int = 5,
    ) -> list[str]:
        """Auto-crystallize high-value items into skill files."""
        promoted: list[str] = []
        type_topics: dict[str, set[str]] = {}

        high_value = self._store.get_recent(limit=200, min_confidence=min_confidence)
        for item in high_value:
            if (item.get("use_count") or 0) < min_uses:
                continue
            type_ = item["type"]
            topic = item.get("topic", "") or "general"
            type_topics.setdefault(type_, set()).add(topic)

        for type_, topics in type_topics.items():
            for topic in topics:
                name = self._crystallizer.crystallize_topic(
                    type_, topic, min_confidence=min_confidence
                )
                if name:
                    promoted.append(name)

        return promoted

    # ── similarity helpers ──────────────────────────────────────────────

    @staticmethod
    def _compute_similarity(a: str, b: str) -> float:
        """Token-overlap Jaccard similarity."""
        if not a or not b:
            return 0.0
        a_tokens = set(a.lower().split())
        b_tokens = set(b.lower().split())
        if not a_tokens or not b_tokens:
            return 0.0
        intersection = a_tokens & b_tokens
        return len(intersection) / max(len(a_tokens | b_tokens), 1)


# Singleton
_engine: ConsolidationEngine | None = None


def get_consolidation_engine(
    store: Any | None = None,
    crystallizer: Any | None = None,
) -> ConsolidationEngine:
    global _engine
    if _engine is None:
        _engine = ConsolidationEngine(store=store, crystallizer=crystallizer)
    return _engine
