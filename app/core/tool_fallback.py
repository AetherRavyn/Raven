"""Tool Fallback Registry — automatic alternative tool selection on failure.

When a tool fails, the agent automatically tries an alternative instead
of retrying the same tool.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Fallback chains: primary tool → ordered list of alternatives
FALLBACK_CHAINS: dict[str, list[str]] = {
    "web_search": ["searxng_search", "web_fetch", "url_metadata"],
    "searxng_search": ["web_search", "web_fetch"],
    "web_fetch": ["browser", "url_metadata"],
    "stock_quote": ["web_search", "crypto_price"],
    "crypto_price": ["web_search", "stock_quote"],
    "email_send": ["platform_messaging"],
    "google_calendar": ["todo_list", "reminder"],
    "reminder": ["google_calendar", "todo_list"],
    "weather": ["web_search"],
    "maps_geocoding": ["web_search", "nominatim"],
    "translation": ["web_search"],
    "pdf_reader": ["web_fetch"],
    "docx_reader": ["web_fetch"],
    "excel_reader": ["bash_execute"],
    "image_generation": ["web_search"],
    "camera_snapshot": ["web_search"],
}

# Track consecutive failures per tool in the current turn
_failure_counts: dict[str, int] = {}


def get_fallback(tool_name: str, failed_tools: set[str] | None = None) -> str | None:
    """Get the next fallback tool for a failed tool.

    Returns the first alternative that hasn't been tried yet.
    """
    chain = FALLBACK_CHAINS.get(tool_name, [])
    failed = failed_tools or set()
    for alt in chain:
        if alt not in failed:
            return alt
    return None


def record_failure(tool_name: str) -> None:
    """Record a tool failure for streak tracking."""
    _failure_counts[tool_name] = _failure_counts.get(tool_name, 0) + 1


def reset_failures() -> None:
    """Reset failure counts at the start of a new turn."""
    _failure_counts.clear()


def get_failure_count(tool_name: str) -> int:
    """Get the failure count for a tool."""
    return _failure_counts.get(tool_name, 0)
