"""Trajectory Compressor — Reclaim context window by compressing conversation history.

Inspired by Hermes Agent's `/compress` command and OpenClaw's `/compact` command.
When conversations get long, this module summarizes earlier turns while preserving
key facts, decisions, and context — allowing AetherRavyn to maintain coherent
conversations without hitting token limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompressionResult:
    """Result of a trajectory compression operation."""

    original_messages: int
    compressed_messages: int
    original_tokens_est: int
    compressed_tokens_est: int
    savings_pct: float
    summary: str
    preserved_facts: list[str]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TrajectoryCompressor:
    """Compresses conversation trajectories to reclaim context window space.

    Compression strategies:
    1. **Sliding Window** — Keep only the last N messages in full
    2. **Summary Injection** — Summarize older messages into a compact block
    3. **Fact Extraction** — Extract key facts/decisions from history
    4. **Tool Result Trimming** — Collapse verbose tool outputs
    """

    def __init__(
        self,
        max_history_messages: int = 40,
        summary_window: int = 10,
        max_tool_result_chars: int = 500,
    ) -> None:
        self._max_history = max_history_messages
        self._summary_window = summary_window
        self._max_tool_result = max_tool_result_chars

    def compress(
        self,
        messages: list[dict[str, Any]],
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], CompressionResult]:
        """Compress a message list, returning the compressed list and stats.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            force: If True, always compress even if under threshold.

        Returns:
            Tuple of (compressed_messages, compression_result).
        """
        if not messages:
            return messages, CompressionResult(
                original_messages=0,
                compressed_messages=0,
                original_tokens_est=0,
                compressed_tokens_est=0,
                savings_pct=0.0,
                summary="No messages to compress.",
                preserved_facts=[],
            )

        original_count = len(messages)
        original_tokens = self._estimate_tokens(messages)

        # Only compress if we have enough messages or if forced
        if not force and original_count <= self._max_history:
            return messages, CompressionResult(
                original_messages=original_count,
                compressed_messages=original_count,
                original_tokens_est=original_tokens,
                compressed_tokens_est=original_tokens,
                savings_pct=0.0,
                summary="No compression needed.",
                preserved_facts=[],
            )

        # Split messages into "old" (to compress) and "recent" (to keep)
        keep_count = min(self._summary_window, len(messages))
        old_messages = messages[:-keep_count] if keep_count < len(messages) else []
        recent_messages = messages[-keep_count:]

        if not old_messages:
            return messages, CompressionResult(
                original_messages=original_count,
                compressed_messages=original_count,
                original_tokens_est=original_tokens,
                compressed_tokens_est=original_tokens,
                savings_pct=0.0,
                summary="Not enough old messages to compress.",
                preserved_facts=[],
            )

        # Extract facts and decisions from old messages
        facts = self._extract_facts(old_messages)

        # Build a summary of the old conversation
        summary = self._build_summary(old_messages, facts)

        # Trim tool results in recent messages
        trimmed_recent = self._trim_tool_results(recent_messages)

        # Build the compressed message list
        compressed: list[dict[str, Any]] = []

        # Inject the summary as a system message
        if summary:
            compressed.append({
                "role": "system",
                "content": (
                    f"[Compressed conversation history — {len(old_messages)} earlier messages]\n"
                    f"{summary}"
                ),
            })

        # Add the recent messages
        compressed.extend(trimmed_recent)

        compressed_tokens = self._estimate_tokens(compressed)
        savings = (
            ((original_tokens - compressed_tokens) / original_tokens * 100)
            if original_tokens > 0
            else 0.0
        )

        result = CompressionResult(
            original_messages=original_count,
            compressed_messages=len(compressed),
            original_tokens_est=original_tokens,
            compressed_tokens_est=compressed_tokens,
            savings_pct=round(savings, 1),
            summary=summary,
            preserved_facts=facts,
        )

        logger.info(
            "Compressed trajectory: %d→%d messages, ~%d→~%d tokens (%.1f%% savings)",
            original_count,
            len(compressed),
            original_tokens,
            compressed_tokens,
            savings,
        )

        return compressed, result

    def _extract_facts(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract key facts and decisions from a message history."""
        facts: list[str] = []

        for msg in messages:
            content = str(msg.get("content") or "")
            role = msg.get("role", "")

            # Extract user decisions/commands
            if role == "user":
                # Decisions (affirmative responses)
                if any(kw in content.lower() for kw in [
                    "yes", "approved", "confirmed", "go ahead", "sounds good",
                    "do it", "perfect", "agreed",
                ]):
                    facts.append(f"User approved: {content[:100]}")

                # Explicit preferences
                if any(kw in content.lower() for kw in [
                    "prefer", "always", "never", "don't", "want", "use",
                ]):
                    facts.append(f"User preference: {content[:100]}")

            # Extract assistant decisions/results
            if role == "assistant":
                # File operations
                for pattern in [
                    r"(?:created|wrote|saved|updated)\s+(?:file\s+)?[`'\"]?([^\s`'\"]+)",
                    r"(?:deployed|installed|configured)\s+(\w+)",
                ]:
                    import re
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        facts.append(f"Action taken: {match.group(0)[:100]}")

                # Error resolutions
                if any(kw in content.lower() for kw in ["fixed", "resolved", "solved"]):
                    facts.append(f"Issue resolved: {content[:100]}")

        # Deduplicate and limit
        seen: set[str] = set()
        unique_facts: list[str] = []
        for fact in facts:
            normalized = fact.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_facts.append(fact)

        return unique_facts[:20]  # Cap at 20 facts

    def _build_summary(
        self, messages: list[dict[str, Any]], facts: list[str]
    ) -> str:
        """Build a textual summary of compressed messages."""
        parts: list[str] = []

        # Count by role
        user_msgs = [m for m in messages if m.get("role") == "user"]
        asst_msgs = [m for m in messages if m.get("role") == "assistant"]

        parts.append(
            f"Earlier conversation: {len(user_msgs)} user messages, "
            f"{len(asst_msgs)} assistant responses."
        )

        # Topic extraction from user messages
        topics: set[str] = set()
        for msg in user_msgs:
            content = str(msg.get("content") or "")
            # Extract meaningful words (>4 chars, skip common words)
            import re
            words = re.findall(r"\b[a-zA-Z]{4,}\b", content.lower())
            for word in words:
                if word not in _COMMON_WORDS and len(topics) < 10:
                    topics.add(word)

        if topics:
            parts.append(f"Topics discussed: {', '.join(sorted(topics)[:8])}")

        # Include preserved facts
        if facts:
            parts.append("\nKey facts from conversation:")
            for fact in facts[:10]:
                parts.append(f"- {fact}")

        return "\n".join(parts)

    def _trim_tool_results(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Trim verbose tool results in messages while keeping essential info."""
        trimmed: list[dict[str, Any]] = []
        for msg in messages:
            content = str(msg.get("content") or "")
            role = msg.get("role", "")

            # Only trim tool/function results, not user or assistant messages
            if role in ("tool", "function") and len(content) > self._max_tool_result:
                content = (
                    content[: self._max_tool_result]
                    + f"\n...[trimmed {len(content) - self._max_tool_result} chars]"
                )
                trimmed.append({**msg, "content": content})
            else:
                trimmed.append(msg)

        return trimmed

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Rough token count estimation (~4 chars per token)."""
        total_chars = sum(
            len(str(msg.get("content") or "")) + len(str(msg.get("role") or ""))
            for msg in messages
        )
        return total_chars // 4


# Common words to skip in topic extraction
_COMMON_WORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "were", "will",
    "would", "could", "should", "about", "their", "there", "which",
    "when", "where", "what", "some", "more", "other", "them", "they",
    "your", "than", "also", "just", "very", "make", "like", "know",
    "want", "need", "here", "give", "take", "come", "each", "well",
    "work", "call", "help", "tell", "look", "find", "then", "much",
    "good", "back", "into", "only", "over", "such", "after", "year",
    "most", "long", "great", "little", "right", "still", "small",
    "made", "does", "before", "many", "between", "being", "under",
    "same", "another", "think", "these", "might", "because", "first",
    "while", "even", "must", "part", "keep", "thing", "every",
    "please", "sure", "okay", "going", "using",
})


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_COMPRESSOR: TrajectoryCompressor | None = None


def get_trajectory_compressor() -> TrajectoryCompressor:
    """Get or create the global TrajectoryCompressor instance."""
    global _GLOBAL_COMPRESSOR
    if _GLOBAL_COMPRESSOR is None:
        _GLOBAL_COMPRESSOR = TrajectoryCompressor()
    return _GLOBAL_COMPRESSOR
