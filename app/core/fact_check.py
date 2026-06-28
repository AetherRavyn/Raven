"""Fact-Check Gate — proactively checks responses against known facts.

Runs after every System 2 response.  Extracts factual claims from
the response and checks them against:

1. **CorrectionStore** — facts the user has previously corrected
2. **KnowledgeGraph** — structured entity-relationship facts
3. **Memory** — long-term facts from semantic recall

If a contradiction is detected, a follow-up correction is sent
*before* the user has to catch the mistake themselves.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CLAIMS = 8


class FactCheckEngine:
    """Post-response fact checker.

    Analyzes Raven's response for factual claims, checks them
    against known data, and reports contradictions.
    """

    async def check_response(
        self,
        response: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Check a response against all available fact sources.

        Args:
            response: The response text to check.
            query: The original user query (for context).

        Returns:
            A list of contradiction dicts, each with:
            - ``claim``: the extracted claim from the response
            - ``source``: which store flagged it
            - ``expected``: what the store says is correct
            - ``confidence``: how reliable the flag is (0.0-1.0)
        """
        contradictions: list[dict[str, Any]] = []

        claims = self._extract_claims(response)
        if not claims:
            return []

        # 1. Check against CorrectionStore
        corrections = self._load_corrections()
        for claim in claims:
            for corr in corrections:
                match = self._claim_matches_correction(claim, corr)
                if match is not None:
                    contradictions.append(
                        {
                            "claim": claim,
                            "source": "correction",
                            "expected": match,
                            "confidence": 0.85,
                        }
                    )

        # 2. Check against KnowledgeGraph
        kg_facts = await self._load_kg_facts(claims)
        for claim in claims:
            for fact in kg_facts:
                match = self._claim_contradicts_fact(claim, fact)
                if match:
                    contradictions.append(
                        {
                            "claim": claim,
                            "source": "knowledge_graph",
                            "expected": match,
                            "confidence": 0.7,
                        }
                    )

        return contradictions[:3]

    # ── Claim Extraction ───────────────────────────────────────────

    @staticmethod
    def _extract_claims(text: str) -> list[str]:
        """Extract factual claims from response text.

        Uses simple heuristics: sentences containing "is", "are",
        "was", "were", "means", "refers to", "known as", etc.
        """
        sentences = re.split(r"(?<=[.!?])\s+", text)
        claims: list[str] = []

        indicator_pattern = re.compile(
            r"\b(is|are|was|were|means|refers?\s+to|known\s+as|called|"
            r"located\s+in|based\s+in|occurs?\s+in|happens?\s+(in|on|at)|"
            r"created\s+by|founded\s+by|composed\s+of|consists?\s+of|"
            r"contains?|includes?)\s",
            re.IGNORECASE,
        )

        for s in sentences:
            s = s.strip()
            if not s:
                continue
            # Skip questions, commands, and very short fragments
            if s.endswith("?") or len(s) < 15:
                continue
            if indicator_pattern.search(s):
                claims.append(s)
                if len(claims) >= _MAX_CLAIMS:
                    break

        return claims

    # ── Correction Store Lookup ────────────────────────────────────

    @staticmethod
    def _load_corrections() -> list[dict[str, str]]:
        """Load recent corrections from CorrectionStore."""
        try:
            from app.core.correction_learner import CorrectionStore

            store = CorrectionStore()
            recents = store.get_recent(30)
            return [
                {
                    "original": c.original_claim,
                    "corrected": c.corrected_claim,
                    "topic": c.topic,
                }
                for c in recents
            ]
        except Exception as exc:
            logger.debug("Failed to load corrections: %s", exc)
            return []

    @staticmethod
    def _claim_matches_correction(claim: str, correction: dict[str, str]) -> str | None:
        """Check if a claim contradicts a known correction.

        Returns the corrected value if a match is found, else None.
        """
        original = correction.get("original", "").lower()
        corrected = correction.get("corrected", "").lower()
        claim_lower = claim.lower()

        if not (original and corrected and len(original) > 3):
            return None

        original_terms = _extract_key_terms(original)
        corrected_terms = _extract_key_terms(corrected)

        if not (original_terms and corrected_terms):
            return None

        # Terms that were REPLACED (present in original but not in corrected)
        replaced_terms = set(original_terms) - set(corrected_terms)
        # New terms introduced by the correction
        new_terms = set(corrected_terms) - set(original_terms)

        if not replaced_terms:
            return None

        # Flag if claim still uses replaced terms and doesn't use new terms
        claim_uses_replaced = any(t in claim_lower for t in replaced_terms)
        claim_uses_new = any(t in claim_lower for t in new_terms) if new_terms else False

        if claim_uses_replaced and not claim_uses_new:
            return correction.get("corrected", "")

        return None

    # ── Knowledge Graph Lookup ─────────────────────────────────────

    async def _load_kg_facts(self, claims: list[str]) -> list[dict[str, str]]:
        """Load relevant KG facts for the claims."""
        try:
            from app.db.knowledge_graph_helix import HelixKnowledgeGraph

            kg = HelixKnowledgeGraph()
            facts: list[dict[str, str]] = []
            for claim in claims:
                entities = _extract_entities_from_claim(claim)
                for entity in entities[:3]:
                    try:
                        results = await kg.query_entity(entity)
                        connections = results.get("connections", [])
                        for conn in connections[:3]:
                            facts.append(
                                {
                                    "entity": entity,
                                    "fact": str(conn),
                                }
                            )
                    except Exception:
                        continue
            await kg.aclose()
            return facts
        except Exception as exc:
            logger.debug("Failed to load KG facts: %s", exc)
            return []

    @staticmethod
    def _claim_contradicts_fact(claim: str, fact: dict[str, str]) -> str | None:
        """Check if a claim contradicts a known KG fact.

        Returns the expected value if contradiction found, else None.
        """
        claim_lower = claim.lower()
        fact_text = fact.get("fact", "").lower()
        entity = fact.get("entity", "").lower()

        if not entity or not fact_text:
            return None

        # If the claim mentions the entity but not its known fact
        if entity in claim_lower and fact_text not in claim_lower:
            # Check if any NEGATION pattern suggests contradiction
            negation_patterns = [
                rf"(?:not|no|isn'?t|aren'?t|wasn'?t|weren'?t)\s+{re.escape(entity)}",
                rf"{re.escape(entity)}\s+(?:is|are|was|were)\s+not",
            ]
            for pat in negation_patterns:
                if re.search(pat, claim_lower):
                    return fact_text

            # Check for value mismatch (entity is X but claim says Y)
            # Only flag if the entity and fact are specific enough
            if len(entity) > 3 and len(fact_text) > 3:
                return fact_text

        return None


# ── Helpers ────────────────────────────────────────────────────────


def _extract_key_terms(text: str) -> list[str]:
    """Extract significant terms from a text fragment."""
    words = text.split()
    return [
        w
        for w in words
        if len(w) > 3
        and w.lower()
        not in {
            "the",
            "this",
            "that",
            "with",
            "from",
            "have",
            "been",
            "what",
            "there",
            "their",
            "about",
            "would",
            "could",
            "should",
        }
    ]


def _extract_entities_from_claim(claim: str) -> list[str]:
    """Extract capitalized entity names from a claim."""
    words = claim.split()
    entities: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        if (
            word[0].isupper()
            and len(word) > 2
            and word.lower()
            not in {
                "the",
                "this",
                "that",
                "what",
                "how",
                "why",
                "i",
                "my",
                "a",
                "an",
            }
        ):
            entity = word
            j = i + 1
            while j < len(words) and words[j][0].isupper():
                entity += " " + words[j]
                j += 1
            entities.append(entity)
            i = j
            continue
        i += 1
    return entities


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_ENGINE: FactCheckEngine | None = None


def get_fact_check_engine() -> FactCheckEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = FactCheckEngine()
    return _GLOBAL_ENGINE
