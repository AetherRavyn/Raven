"""Token Counter — estimate token counts for context window management.

Uses character-based estimation (~4 chars per token) as default,
with optional tiktoken for precise counts.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Approximate tokens per character for English text
_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. Fast char-based estimation."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # Multimodal content array
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
        # Overhead for role, tool_call structures etc.
        total += 4
    return total


def should_compress(messages: list[dict[str, Any]], max_tokens: int = 100_000) -> bool:
    """Check if message list exceeds token budget."""
    return estimate_messages_tokens(messages) > max_tokens


def get_token_usage(messages: list[dict[str, Any]], max_tokens: int = 100_000) -> dict[str, Any]:
    """Get token usage statistics for a message list."""
    total = estimate_messages_tokens(messages)
    by_role: dict[str, int] = {}
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        tokens = estimate_tokens(content) if isinstance(content, str) else 0
        by_role[role] = by_role.get(role, 0) + tokens
    return {
        "total_tokens": total,
        "by_role": by_role,
        "message_count": len(messages),
        "utilization": f"{total / max_tokens * 100:.1f}%" if max_tokens else "unknown",
    }
