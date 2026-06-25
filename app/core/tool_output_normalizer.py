"""Tool Output Normalizer — extracts key fields from raw tool JSON results.

Saves tokens by compressing verbose tool outputs into structured summaries.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Max chars for tool output before truncation
MAX_TOOL_OUTPUT_CHARS = 4000


def normalize_tool_output(
    tool_name: str,
    result: dict[str, Any] | str,
    max_chars: int = MAX_TOOL_OUTPUT_CHARS,
) -> str:
    """Normalize and truncate tool output for LLM consumption.

    Extracts the most important fields and truncates to save tokens.
    """
    if isinstance(result, str):
        return result[:max_chars]

    if not isinstance(result, dict):
        return str(result)[:max_chars]

    # Tool-specific normalization
    extractors = {
        "web_search": _extract_search_results,
        "searxng_search": _extract_search_results,
        "stock_quote": _extract_stock,
        "weather": _extract_weather,
        "file_operations": _extract_file_ops,
        "bash_execute": _extract_bash,
        "knowledge_graph": _extract_kg,
    }

    extractor = extractors.get(tool_name)
    if extractor:
        return extractor(result, max_chars)

    # Generic normalization: keep error or top-level keys
    if "error" in result:
        return f"Error: {result['error']}"[:max_chars]

    output = json.dumps(result, default=str, ensure_ascii=False)
    return output[:max_chars]


def _extract_search_results(result: dict, max_chars: int) -> str:
    """Extract search result titles and snippets."""
    results = result.get("results", result.get("data", []))
    if isinstance(results, list):
        parts = []
        for r in results[:5]:
            title = r.get("title", "")
            snippet = r.get("snippet", r.get("description", ""))[:200]
            url = r.get("url", "")
            parts.append(f"- {title}\n  {snippet}\n  {url}")
        output = "\n".join(parts)
    else:
        output = json.dumps(result, default=str)[:max_chars]
    return output[:max_chars]


def _extract_stock(result: dict, max_chars: int) -> str:
    """Extract stock quote key fields."""
    fields = []
    for key in ["symbol", "price", "change", "change_percent", "volume", "name"]:
        if key in result:
            fields.append(f"{key}: {result[key]}")
    return "\n".join(fields) if fields else json.dumps(result, default=str)[:max_chars]


def _extract_weather(result: dict, max_chars: int) -> str:
    """Extract weather key fields."""
    fields = []
    for key in ["location", "temperature", "condition", "humidity", "wind", "forecast"]:
        if key in result:
            val = result[key]
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val[:3])
            fields.append(f"{key}: {val}")
    return "\n".join(fields) if fields else json.dumps(result, default=str)[:max_chars]


def _extract_file_ops(result: dict, max_chars: int) -> str:
    """Extract file operation results."""
    if "content" in result:
        content = result["content"]
        return content[:max_chars] if isinstance(content, str) else str(content)[:max_chars]
    return json.dumps(result, default=str)[:max_chars]


def _extract_bash(result: dict, max_chars: int) -> str:
    """Extract bash output."""
    output = result.get("output", result.get("stdout", ""))
    if output:
        lines = output.strip().split("\n")
        if len(lines) > 30:
            return "\n".join(lines[:20]) + f"\n... ({len(lines) - 20} more lines)"
        return output[:max_chars]
    return json.dumps(result, default=str)[:max_chars]


def _extract_kg(result: dict, max_chars: int) -> str:
    """Extract knowledge graph results."""
    entities = result.get("entities", result.get("results", []))
    if isinstance(entities, list) and entities:
        parts = []
        for e in entities[:10]:
            if isinstance(e, dict):
                name = e.get("name", e.get("entity", ""))
                rels = e.get("relationships", e.get("edges", []))
                parts.append(f"- {name}: {len(rels)} relationships")
            else:
                parts.append(f"- {e}")
        return "\n".join(parts)
    return json.dumps(result, default=str)[:max_chars]
