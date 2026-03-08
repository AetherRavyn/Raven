# app/tools/searxngtool.py
"""SearXNGTool — privacy-respecting search via a self-hosted SearXNG instance."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class SearXNGTool(BaseTool):
    """Search the web via a self-hosted SearXNG instance."""

    def get_name(self) -> str:
        return "searxng_search"

    def get_description(self) -> str:
        return (
            "Search the web using a self-hosted SearXNG instance for privacy-respecting results. "
            "Returns titles, URLs, and content snippets. Useful as an alternative to Google "
            "or Bing when SEARXNG_URL is configured."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query string.",
                    required=True,
                ),
                ToolParameter(
                    name="categories",
                    type="string",
                    description=(
                        "Comma-separated SearXNG categories "
                        "(e.g. 'general', 'news', 'images', 'science', 'it'). "
                        "Defaults to 'general'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Search language code (e.g. 'en', 'de'). Defaults to 'en'.",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of results to return (default: 10, max: 50).",
                    required=False,
                ),
                ToolParameter(
                    name="time_range",
                    type="string",
                    description="Filter results by age: 'day', 'week', 'month', 'year'.",
                    required=False,
                    enum=["day", "week", "month", "year"],
                ),
                ToolParameter(
                    name="safe_search",
                    type="integer",
                    description="Safe-search level: 0=off, 1=moderate, 2=strict. Defaults to 1.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        searxng_url = (Config.SEARXNG_URL or "").rstrip("/")
        if not searxng_url:
            return {"success": False, "error": "SEARXNG_URL not configured."}

        query: str = (kwargs.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "'query' is required."}

        categories: str = kwargs.get("categories") or "general"
        language: str = kwargs.get("language") or "en"
        max_results: int = min(int(kwargs.get("max_results", 10)), 50)
        time_range: str | None = kwargs.get("time_range")
        safe_search: int = int(kwargs.get("safe_search", 1))

        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
            "categories": categories,
            "language": language,
            "safesearch": safe_search,
        }
        if time_range:
            params["time_range"] = time_range

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{searxng_url}/search",
                    params=params,
                    headers={"Accept": "application/json"},
                )

            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"SearXNG error {resp.status_code}: {resp.text[:300]}",
                }

            data = resp.json()
            raw_results: List[Dict[str, Any]] = data.get("results", [])[:max_results]

            results: List[Dict[str, str]] = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "engine": r.get("engine", ""),
                }
                for r in raw_results
            ]

            return {
                "success": True,
                "query": query,
                "categories": categories,
                "result_count": len(results),
                "results": results,
                "answers": data.get("answers", []),
                "infoboxes": data.get("infoboxes", []),
            }

        except Exception as exc:
            logger.exception("SearXNGTool error")
            return {"success": False, "error": str(exc)}
