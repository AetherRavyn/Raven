from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from agent_reach.core import AgentReach

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class InternetIntelTool(BaseTool):
    """Free-first internet intelligence: search, read, and coverage checks."""

    def __init__(self, reach: AgentReach | None = None):
        self._reach = reach or AgentReach()

    def get_name(self) -> str:
        return "internet_intel"

    def get_description(self) -> str:
        return (
            "Free-first internet intelligence for search, discovery, and reading. "
            "Uses DuckDuckGo, Jina Reader, GitHub gh CLI, yt-dlp, RSS, Reddit JSON, V2EX, Xueqiu, and Exa when available."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to run.",
                    required=True,
                    enum=["search", "discover", "read", "status", "report"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query for search/discover operations.",
                    required=False,
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to read.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max number of results to return.",
                    required=False,
                ),
                ToolParameter(
                    name="sources",
                    type="string",
                    description="Optional source list (comma-separated) or 'all'.",
                    required=False,
                ),
                ToolParameter(
                    name="max_chars",
                    type="integer",
                    description="Character cap for reading operations.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = str(kwargs.get("operation") or "").strip().lower()
        query = kwargs.get("query") or ""
        url = kwargs.get("url") or ""
        limit = int(kwargs.get("limit") or 8)
        sources = kwargs.get("sources")
        max_chars = int(kwargs.get("max_chars") or 4000)

        if operation == "status":
            return self._reach.status()
        if operation == "report":
            return {"success": True, "report": self._reach.coverage_report()}
        if operation == "read":
            if not url:
                return {"success": False, "error": "url is required"}
            return self._reach.read(url, max_chars=max_chars)
        if operation == "discover":
            if not query:
                return {"success": False, "error": "query is required"}
            return self._reach.discover(
                query=query, limit=limit, sources=sources, max_chars=max_chars
            )
        if operation == "search":
            if not query:
                return {"success": False, "error": "query is required"}
            return self._reach.search(query=query, limit=limit, sources=sources)

        return {"success": False, "error": f"Unknown operation: {operation}"}
