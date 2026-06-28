"""Success Pattern Learner — Raven learns from what worked.

The rest of the self-improvement system focuses on failures
(corrections, low confidence, fact-check contradictions).
This module balances the picture by identifying *successful*
interaction patterns and reinforcing them.

Sources of success signals:
  - Turns with high confidence from UncertaintyEstimator
  - Turns where all tool calls succeeded
  - Turns with positive user feedback
  - Turns that did not need any follow-up correction
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class SuccessPatternLearner:
    """Identifies and reinforces successful interaction patterns."""

    def __init__(self) -> None:
        self._patterns: Counter[str] = Counter()

    def record_success(
        self,
        query: str,
        response: str,
        tool_calls: list[dict[str, Any]],
        latency_ms: float,
        confidence: float = 0.5,
    ) -> str | None:
        """Record a successful turn and extract its pattern.

        Args:
            query: The user's query.
            response: The response text.
            tool_calls: Tool calls made during the turn.
            latency_ms: Turn duration.
            confidence: Confidence score (0-1).

        Returns:
            A pattern label if this turn is notable, else None.
        """
        label = self._classify_pattern(query, tool_calls)

        if label:
            self._patterns[label] += 1
            self._persist(label, query, response, tool_calls, confidence)
            if self._patterns[label] >= 3:
                logger.info(
                    "Success pattern '%s' strengthened (%d occurrences)",
                    label,
                    self._patterns[label],
                )
            return label

        return None

    def get_encouragement_prompt(self) -> str:
        """Generate a system-prompt section from successful patterns.

        Injected into the prompt to reinforce what works.
        """
        if not self._patterns:
            return ""

        top = self._patterns.most_common(3)
        lines = ["## Success Patterns (keep doing what works)"]
        for label, count in top:
            if count >= 3:
                lines.append(f"- {self._describe_pattern(label)} (confirmed {count} times)")
        return "\n".join(lines) if len(lines) > 1 else ""

    # ── Pattern Classification ────────────────────────────────────

    @staticmethod
    def _classify_pattern(
        query: str,
        tool_calls: list[dict[str, Any]],
    ) -> str | None:
        """Classify the interaction into a success pattern.

        Returns a label like ``web_research``, ``code_generation``,
        ``file_operation``, or ``simple_qa``, or None if unclassified.
        """
        tools_used = {t.get("tool", "") for t in tool_calls if t.get("success", False)}

        query_lower = query.lower()

        # Web research pattern
        if tools_used & {"web_fetch", "web_search", "internet_intel"}:
            return "web_research"

        # Code pattern
        if tools_used & {"read_file", "write_file", "edit_file", "grep"} and any(
            w in query_lower for w in ("code", "function", "bug", "implement", "test")
        ):
            return "code_generation"

        # Git pattern
        if tools_used & {"git_status", "git_diff", "git_log", "git_commit"}:
            return "git_operation"

        # File operation pattern
        if tools_used & {"read_file", "write_file", "list_files", "glob"}:
            return "file_operation"

        # Data lookup pattern
        if tools_used & {"kg_query", "memory_recall", "knowledge_graph"}:
            return "data_lookup"

        # No tools → simple Q&A
        if not tool_calls:
            return "simple_qa"

        return None

    @staticmethod
    def _describe_pattern(label: str) -> str:
        """Human-readable description of a pattern label."""
        descriptions = {
            "web_research": "When answering factual questions, fetch live data from the web before responding",
            "code_generation": "When writing code, use file tools to read context and verify the output",
            "git_operation": "When managing git, use dedicated git tools for accuracy",
            "file_operation": "When working with files, use file tools to ensure precision",
            "data_lookup": "When asked about specific facts, query the knowledge graph first",
            "simple_qa": "When answering simple questions, be direct and concise",
        }
        return descriptions.get(label, f"Use '{label}' approach for consistent results")

    # ── Persistence ───────────────────────────────────────────────

    def _persist(
        self,
        label: str,
        query: str,
        response: str,
        tool_calls: list[dict[str, Any]],
        confidence: float,
    ) -> None:
        """Log success pattern for later analysis."""
        try:
            from pathlib import Path

            from app.settings.config import Config

            path = Path(Config.MEMORY_ROOT) / "success_patterns.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            with open(path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "label": label,
                            "query": query[:100],
                            "confidence": round(confidence, 2),
                            "tools": [t.get("tool", "") for t in tool_calls],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as exc:
            logger.debug("Failed to persist success pattern: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_LEARNER: SuccessPatternLearner | None = None


def get_success_pattern_learner() -> SuccessPatternLearner:
    global _GLOBAL_LEARNER
    if _GLOBAL_LEARNER is None:
        _GLOBAL_LEARNER = SuccessPatternLearner()
    return _GLOBAL_LEARNER
