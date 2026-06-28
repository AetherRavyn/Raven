"""Uncertainty Estimator — quantifies how confident Raven should be.

Combines multiple signals to estimate response confidence:

1. **Tool success rate** — percentage of tool calls that succeeded
2. **KG coverage** — whether entities in the query have KG facts
3. **Correction history** — how often similar queries needed corrections
4. **Response quality** — response length vs. query complexity

Returns a score 0.0–1.0.  Below 0.3 → generate a clarifying question.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class UncertaintyEstimator:
    """Estimates response confidence from execution signals."""

    def __init__(
        self,
        kg_manager: Any | None = None,
        correction_store: Any | None = None,
    ) -> None:
        self._kg = kg_manager
        self._corrections = correction_store

    # ── Public API ───────────────────────────────────────────────────

    def estimate(
        self,
        turn_result: dict[str, Any] | None,
        query: str,
    ) -> float:
        """Compute overall confidence score for a turn result.

        Args:
            turn_result: Dict from ``execute_turn()`` with keys
                ``success``, ``tool_calls``, ``response``, ``latency_ms``.
            query: The original user query.

        Returns:
            Float 0.0 (very uncertain) to 1.0 (very confident).
        """
        if turn_result is None:
            return 0.0

        signals: list[tuple[float, float]] = []  # (weight, score)

        # 1. Overall success signal (weight: 3.0)
        signals.append(self._signal_success(turn_result))

        # 2. Tool call success rate (weight: 2.0)
        signals.append(self._signal_tool_health(turn_result))

        # 3. KG coverage of query entities (weight: 1.5)
        signals.append(self._signal_kg_coverage(query))

        # 4. Correction history penalty (weight: 1.5)
        signals.append(self._signal_correction_history(query))

        # 5. Response quality heuristic (weight: 1.0)
        signals.append(self._signal_response_quality(turn_result, query))

        # Weighted average
        total_weight = sum(w for w, _ in signals)
        if total_weight == 0:
            return 0.5

        weighted = sum(w * s for w, s in signals)
        confidence = weighted / total_weight

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, confidence))

    def needs_clarification(self, confidence: float, threshold: float = 0.3) -> bool:
        """Return True if confidence is low enough to warrant a follow-up."""
        return confidence < threshold

    def generate_clarifying_question(
        self, query: str, turn_result: dict[str, Any] | None = None
    ) -> str:
        """Generate an appropriate clarifying question based on the signals.

        Uses the weakest signal to determine what kind of clarification
        is needed.
        """
        # Simple rule-based question generation
        # In production, this would use the LLM

        query_lower = query.lower()

        # Check for ambiguous references
        if re.search(r"\b(it|that|this|there|they)\b", query_lower) and len(query) < 60:
            return 'Could you clarify what "{}" refers to?'.format(
                self._extract_ambiguous_term(query)
            )

        # Check for "how" / "why" without specific context
        if query_lower.startswith(("how", "why")) and len(query.split()) < 5:
            return "Could you provide a bit more context about what you're asking?"

        # Check for missing entity
        if turn_result:
            tools = turn_result.get("tool_calls", [])
            if not tools:
                return "I'm not entirely sure I understood correctly. Could you rephrase or provide more details?"
            failed = [t for t in tools if not t.get("success", False)]
            if failed:
                tool_names = ", ".join(t.get("tool", "") for t in failed[:2])
                return (
                    f"I had trouble with {tool_names}. "
                    "Could you double-check the details and try again?"
                )

        return "I'm not confident about that answer. Could you verify or provide more information?"

    # ── Signal Estimators ────────────────────────────────────────────

    def _signal_success(self, turn_result: dict[str, Any]) -> tuple[float, float]:
        """Weight=3.0: overall turn success."""
        success = turn_result.get("success", False)
        return (3.0, 1.0 if success else 0.0)

    def _signal_tool_health(self, turn_result: dict[str, Any]) -> tuple[float, float]:
        """Weight=2.0: fraction of tool calls that succeeded."""
        tool_calls = turn_result.get("tool_calls", [])
        if not tool_calls:
            return (2.0, 0.7)  # No tools used → moderate confidence
        succeeded = sum(1 for t in tool_calls if t.get("success", False))
        rate = succeeded / len(tool_calls)
        return (2.0, rate)

    def _signal_kg_coverage(self, query: str) -> tuple[float, float]:
        """Weight=1.5: does the KG have facts about query entities?"""
        if self._kg is None:
            return (1.5, 0.5)  # Neutral when no KG available

        entities = self._extract_entities(query)
        if not entities:
            return (1.5, 0.7)  # No entities → moderate confidence

        covered = 0
        for entity in entities:
            try:
                facts = self._kg.query(entity)
                if facts and len(facts) > 0:
                    covered += 1
            except Exception:
                continue

        rate = covered / len(entities) if entities else 0.5
        return (1.5, rate)

    def _signal_correction_history(self, query: str) -> tuple[float, float]:
        """Weight=1.5: penalty if similar queries needed corrections.

        A correction for a similar query type means we should be
        less confident.
        """
        if self._corrections is None:
            return (1.5, 0.5)  # Neutral

        try:
            corrections = self._corrections.get_recent(n=50)
        except Exception:
            return (1.5, 0.5)

        if not corrections:
            return (1.5, 0.5)

        query_lower = query.lower()
        query_topic = self._detect_topic(query_lower)

        # Count recent corrections in the same topic
        same_topic = sum(1 for c in corrections if getattr(c, "topic", "general") == query_topic)

        if same_topic == 0:
            return (1.5, 0.6)  # Slightly above neutral — no past issues
        if same_topic <= 2:
            return (1.5, 0.4)  # Some past issues
        return (1.5, 0.2)  # Many past issues in this topic

    def _signal_response_quality(
        self, turn_result: dict[str, Any], query: str
    ) -> tuple[float, float]:
        """Weight=1.0: response quality heuristics.

        Short answers to complex/long questions → low confidence.
        """
        response = turn_result.get("response", "")
        if not response:
            return (1.0, 0.0)

        query_len = len(query)
        response_len = len(response)

        # Very short response to a detailed question
        if query_len > 100 and response_len < 50:
            return (1.0, 0.2)

        # Reasonable response length
        if response_len > query_len * 0.5:
            return (1.0, 0.8)

        # Short response to short question
        if query_len < 30 and 10 <= response_len <= 200:
            return (1.0, 0.7)

        return (1.0, 0.5)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Simple entity extraction (capitalized words).

        Matches the heuristic used in the CuriosityModule for
        consistency.
        """
        words = text.split()
        entities: list[str] = []
        i = 0
        while i < len(words):
            word = words[i]
            if (
                word[0].isupper()
                and len(word) > 1
                and word.lower()
                not in {
                    "i",
                    "my",
                    "the",
                    "this",
                    "that",
                    "what",
                    "how",
                    "why",
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
        return entities[:5]

    @staticmethod
    def _detect_topic(text: str) -> str:
        """Detect topic category, matching CorrectionLearner's scheme."""
        if any(w in text for w in ("name", "called", "labeled")):
            return "naming"
        if any(w in text for w in ("date", "time", "when", "schedule")):
            return "temporal"
        if any(w in text for w in ("file", "path", "directory", "folder")):
            return "filesystem"
        if any(w in text for w in ("code", "function", "variable", "class", "bug")):
            return "code"
        if any(w in text for w in ("fact", "number", "data", "statistic", "percent")):
            return "factual"
        if any(w in text for w in ("prefer", "like", "want", "need", "style")):
            return "preference"
        return "general"

    @staticmethod
    def _extract_ambiguous_term(query: str) -> str:
        """Extract the likely ambiguous reference from a query."""
        # Try to find the first pronoun or vague noun
        match = re.search(r"\b(it|that|this|there|they)\b", query, re.IGNORECASE)
        if match:
            return match.group(1)
        return "that"


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_UNCERTAINTY: UncertaintyEstimator | None = None


def get_uncertainty_estimator() -> UncertaintyEstimator:
    global _GLOBAL_UNCERTAINTY
    if _GLOBAL_UNCERTAINTY is None:
        _GLOBAL_UNCERTAINTY = UncertaintyEstimator()
    return _GLOBAL_UNCERTAINTY
