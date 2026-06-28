"""Fact Extractor — converts user corrections into structured KG facts.

When a user corrects Raven, the correction contains a factual statement.
This module extracts that statement and persists it in the Knowledge
Graph so the FactCheckEngine can check against it using structured
queries instead of fragile text matching.

Flow:
  1. Correction detected → extract claim → parse as subject-relation-object
  2. Store in KG via HelixKnowledgeGraph.add_relationship()
  3. FactCheckEngine queries KG for contradictions in future responses
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class FactExtractor:
    """Extracts structured facts from user corrections and stores them in the KG."""

    async def extract_and_store(
        self,
        corrected_claim: str,
        topic: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Parse a correction into a KG fact and store it.

        Args:
            corrected_claim: The corrected value (e.g. "Paris is the capital of France").
            topic: Correction topic (e.g. "factual", "naming").
            user_id: Optional user ID for scoping.

        Returns:
            Dict with extraction result.
        """
        fact = self._parse_fact(corrected_claim, topic)
        if fact is None:
            return {"success": False, "reason": "could not parse fact"}

        # Store in KG
        kg_result = await self._store_in_kg(fact, user_id)
        if kg_result.get("success"):
            logger.info(
                "Stored fact in KG: [%s] --(%s)--> [%s]",
                fact["entity1"],
                fact["relation"],
                fact["entity2"],
            )
            return {"success": True, "fact": fact, "kg_result": kg_result}

        return {"success": False, "reason": "KG storage failed", "fact": fact}

    # ── Fact Parsing ──────────────────────────────────────────────

    @staticmethod
    def _parse_fact(claim: str, topic: str) -> dict[str, str] | None:
        """Parse a natural language claim into entity1-relation-entity2.

        Supports patterns like:
          - "X is Y" → (X, is, Y)
          - "X is located in Y" → (X, located_in, Y)
          - "X was created by Y" → (X, created_by, Y)
          - "X means Y" → (X, means, Y)
          - capitalization: "The capital of France is Paris" → tricky
        """
        claim = claim.strip().rstrip(".")

        # Pattern: "X is/are/was/were Y" (simple attribution)
        m = re.match(
            r"(.+?)\s+(?:is|are|was|were)\s+(.+)",
            claim,
            re.IGNORECASE,
        )
        if m:
            entity1 = m.group(1).strip()
            entity2 = m.group(2).strip()
            # Heuristic: if entity1 contains common relation words, try
            # the "of" pattern instead
            if any(w in entity1.lower() for w in ("the", "of", "type", "kind", "sort")):
                return FactExtractor._parse_of_pattern(claim, topic)
            return {
                "entity1": entity1,
                "relation": FactExtractor._normalise_relation("is", topic),
                "entity2": entity2,
                "topic": topic,
            }

        # Pattern: "X means Y"
        m = re.match(r"(.+?)\s+means\s+(.+)", claim, re.IGNORECASE)
        if m:
            return {
                "entity1": m.group(1).strip(),
                "relation": "means",
                "entity2": m.group(2).strip(),
                "topic": topic,
            }

        # Pattern: "X refers to Y"
        m = re.match(r"(.+?)\s+refers?\s+to\s+(.+)", claim, re.IGNORECASE)
        if m:
            return {
                "entity1": m.group(1).strip(),
                "relation": "refers_to",
                "entity2": m.group(2).strip(),
                "topic": topic,
            }

        return None

    @staticmethod
    def _parse_of_pattern(claim: str, topic: str) -> dict[str, str] | None:
        """Parse "the [relation] of [entity1] is [entity2]" patterns.

        Example: "The capital of France is Paris"
          → (France, has_capital, Paris)
        """
        m = re.match(
            r"the\s+(.+?)\s+of\s+(.+?)\s+(?:is|are|was|were)\s+(.+)",
            claim,
            re.IGNORECASE,
        )
        if m:
            relation = m.group(1).strip()
            entity1 = m.group(2).strip()
            entity2 = m.group(3).strip()
            return {
                "entity1": entity1,
                "relation": FactExtractor._normalise_relation(relation, topic),
                "entity2": entity2,
                "topic": topic,
            }
        return None

    @staticmethod
    def _normalise_relation(relation: str, topic: str) -> str:
        """Map natural language relation to KG relation."""
        relation_lower = relation.lower().strip()

        mapping = {
            "is": "is",
            "are": "is",
            "was": "is",
            "were": "is",
            "means": "means",
            "refers to": "refers_to",
            "refers": "refers_to",
            "called": "named",
            "named": "named",
            "known as": "aka",
            "capital": "has_capital",
            "capital of": "has_capital",
            "located in": "located_in",
            "based in": "located_in",
            "located at": "located_at",
            "created by": "created_by",
            "founded by": "founded_by",
            "composed of": "composed_of",
            "consists of": "composed_of",
            "contains": "contains",
            "includes": "includes",
            "part of": "part_of",
            "member of": "member_of",
            "type of": "type_of",
            "kind of": "type_of",
            "example of": "example_of",
            "author of": "authored",
            "written by": "authored",
            "owner": "owned_by",
            "created": "created_by",
        }

        return mapping.get(
            relation_lower,
            f"has_{relation_lower.replace(' ', '_')}",
        )

    # ── KG Storage ────────────────────────────────────────────────

    @staticmethod
    async def _store_in_kg(
        fact: dict[str, str],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Store a parsed fact in the Knowledge Graph."""
        try:
            from app.db.knowledge_graph_helix import (
                HelixKnowledgeGraph,
            )

            kg = HelixKnowledgeGraph()
            result = await kg.add_relationship(
                entity1=fact["entity1"],
                relation=fact["relation"],
                entity2=fact["entity2"],
                user_id=user_id,
                kind1="fact",
                kind2="value",
                source="correction",
                topic=fact.get("topic", "general"),
            )
            await kg.aclose()
            return result
        except Exception as exc:
            logger.debug("KG storage failed: %s", exc)
            return {"success": False, "error": str(exc)}


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_EXTRACTOR: FactExtractor | None = None


def get_fact_extractor() -> FactExtractor:
    global _GLOBAL_EXTRACTOR
    if _GLOBAL_EXTRACTOR is None:
        _GLOBAL_EXTRACTOR = FactExtractor()
    return _GLOBAL_EXTRACTOR
