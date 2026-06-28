"""Response Quality Scorer — evaluates Raven's responses on multiple dimensions.

Scores each response without an LLM call using lightweight heuristics:

1. **Completeness** — does the response fully address the query?
2. **Conciseness** — is the response appropriately sized for the query?
3. **Correctness signals** — are there signs of hallucination or contradiction?

Each dimension produces a 0.0–1.0 score.  An overall quality score is
computed as a weighted average.  Scores feed into the health monitor
for trend tracking and can trigger self-correction for very low scores.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ResponseQualityScorer:
    """Evaluates response quality using text heuristics."""

    def score(
        self,
        response: str,
        query: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Score a response on multiple quality dimensions.

        Args:
            response: The response text.
            query: The original user query.
            tool_calls: Tool calls made during the turn (optional).

        Returns:
            Dict with dimension scores, overall score, and flags.
        """
        if not response:
            return {
                "overall": 0.0,
                "completeness": 0.0,
                "conciseness": 0.0,
                "correctness_signals": 0.0,
                "flags": ["empty_response"],
            }

        completeness = self._score_completeness(response, query)
        conciseness = self._score_conciseness(response, query)
        correctness = self._score_correctness_signals(response)

        weights = {"completeness": 2.0, "conciseness": 1.0, "correctness": 1.5}
        total_weight = sum(weights.values())
        overall = (
            completeness * weights["completeness"]
            + conciseness * weights["conciseness"]
            + correctness * weights["correctness"]
        ) / total_weight

        flags: list[str] = []
        if completeness < 0.4:
            flags.append("incomplete")
        if conciseness < 0.3:
            flags.append("verbose")
        if correctness < 0.4:
            flags.append("possible_hallucination")
        if len(response) < 10:
            flags.append("too_short")

        return {
            "overall": round(overall, 3),
            "completeness": round(completeness, 3),
            "conciseness": round(conciseness, 3),
            "correctness_signals": round(correctness, 3),
            "flags": flags,
        }

    def is_low_quality(self, score_result: dict[str, Any], threshold: float = 0.3) -> bool:
        """Return True if the response is likely low quality."""
        return score_result.get("overall", 0.0) < threshold

    # ── Dimension Scorers ──────────────────────────────────────────

    @staticmethod
    def _score_completeness(response: str, query: str) -> float:
        """Score how completely the response addresses the query.

        Checks:
        - Response covers all numbered/listed items from query
        - Response contains key terms from the query
        - Response is not truncated mid-sentence
        """
        query_lower = query.lower()
        response_lower = response.lower()

        # Check for covered items (numbered lists, bullet points)
        query_has_list = bool(re.search(r"(?:^|\n)\s*[-\d.]", query))
        response_has_list = bool(re.search(r"(?:^|\n)\s*[-\d.]", response))

        # Key term coverage
        query_words = {
            w.strip(".,!?;:'\"()[]{}")
            for w in query_lower.split()
            if len(w) > 3
            and any(c.isalpha() for c in w)
            and w.strip(".,!?;:'\"()[]{}") not in _QUERY_STOP_WORDS
        }
        if not query_words:
            return 0.7  # Very short query → assume complete

        covered = sum(1 for w in query_words if w in response_lower)
        term_coverage = covered / len(query_words)

        # Truncation check — ends with incomplete sentence or cutoff
        ends_complete = bool(re.search(r"[.!?]\s*$", response.strip()))
        is_truncated = bool(re.search(r"(?:and|or|the|a|an|to|with)\s*$", response.lower()))

        score = term_coverage * 0.6
        if query_has_list and response_has_list:
            score += 0.2
        if ends_complete:
            score += 0.1
        if is_truncated:
            score -= 0.2

        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_conciseness(response: str, query: str) -> float:
        """Score whether the response is appropriately sized.

        Very short query → short response is good.
        Complex query → appropriately detailed response is good.
        """
        query_len = len(query)
        response_len = len(response)

        # Tiny response to any query → low quality
        if response_len < 15:
            return 0.2

        # Very short query (greeting, simple Q)
        if query_len < 20:
            if response_len < 100:
                return 0.9  # Short and sweet
            if response_len < 300:
                return 0.7  # A bit verbose for a simple query
            return 0.3  # Way too long

        # Medium query (20-100 chars)
        if query_len < 100:
            if response_len < 50:
                return 0.3  # Too short for the question
            if response_len < query_len * 6:
                return 0.8  # Good ratio
            return 0.5  # Somewhat verbose

        # Long/complex query (>100 chars)
        if response_len < query_len * 0.3:
            return 0.3  # Too short for a complex question
        if response_len > query_len * 10:
            return 0.4  # Too verbose
        return 0.8  # Good ratio

    @staticmethod
    def _score_correctness_signals(response: str) -> float:
        """Score signals that suggest correctness or hallucination.

        Checks for:
        - Hedge words (suggests uncertainty)
        - Contradiction patterns
        - Excessive confidence about numbers
        """
        lower = response.lower()

        score = 0.8  # Start high, penalize

        # Hedge words suggest low confidence
        hedge_count = sum(1 for w in _HEDGE_WORDS if w in lower)
        score -= hedge_count * 0.08

        # Vague quantification
        if re.search(r"\b(some|several|many|a lot|various)\b", lower):
            score -= 0.05

        # Unsourced specific claims (may indicate hallucination)
        specific_patterns = re.findall(r"\b(\d{3,}|exactly|precisely|specifically)\b", lower)
        has_citation = bool(re.search(r"\[\d+\]|\(source|according to", lower))
        if specific_patterns and not has_citation:
            score -= 0.1

        # Self-contradiction patterns
        if re.search(r"\b(however|but\s+actually|on\s+the\s+other\s+hand)\b", lower):
            if re.search(r"\b(not\s+sure|might\s+be\s+wrong|could\s+be\s+incorrect)\b", lower):
                score -= 0.1

        # I think / I believe / I'm not sure
        if re.search(r"\bi\s+(think|believe|guess|suppose|assume)\b", lower):
            score -= 0.1

        return max(0.0, min(1.0, score))


_HEDGE_WORDS = {
    "maybe",
    "perhaps",
    "possibly",
    "probably",
    "likely",
    "might",
    "could",
    "may",
    "seems",
    "appears",
    "i think",
    "i believe",
    "i guess",
    "i assume",
}

_QUERY_STOP_WORDS = {
    "what",
    "how",
    "why",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "does",
    "do",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "shall",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "been",
    "being",
    "this",
    "that",
    "these",
    "those",
    "there",
    "their",
    "they",
    "them",
    "tell",
    "give",
    "show",
    "find",
    "need",
    "want",
    "like",
}
