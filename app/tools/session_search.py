"""Session Search Tool — FTS5 full-text search across conversation history.

Agents use this to recall past conversations, find specific information
from earlier sessions, and retrieve conversational context.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class SessionSearchTool(BaseTool):
    """Full-text search across all conversation sessions.

    Uses FTS5 indexing for fast, relevant results. Supports
    returning individual matching messages or conversational
    snippets with surrounding context.
    """

    group = "memory"

    def get_name(self) -> str:
        return "session_search"

    def get_description(self) -> str:
        return (
            "Searches past conversations using full-text search. "
            "Use this to recall information from earlier sessions, find "
            "specific facts, or retrieve conversation context. "
            "Set mode='conversation' to get surrounding messages as context."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (supports FTS5 syntax: words, phrases in quotes, OR, AND)",
                    required=True,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'messages' for individual matches (default), "
                    "'conversation' for snippets with surrounding context",
                    required=False,
                    enum=["messages", "conversation"],
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum results (default: 10 for messages, 5 for conversations)",
                    required=False,
                ),
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="Optional: restrict search to a specific session",
                    required=False,
                ),
                ToolParameter(
                    name="rebuild_index",
                    type="boolean",
                    description="Force a full rebuild of the search index (default: false)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "").strip()
        mode = kwargs.get("mode", "messages")
        session_id = kwargs.get("session_id", "").strip() or None
        rebuild = kwargs.get("rebuild_index", False)

        try:
            from app.core.session import SessionManager
            from app.settings.config import Config

            manager = SessionManager(workspace_dir=Config.MEMORY_ROOT)

            if rebuild:
                result = manager.rebuild_index()
                return {
                    "success": True,
                    "message": f"Index rebuilt: {result.get('messages_indexed', 0)} messages from {result.get('files_scanned', 0)} sessions",
                    **result,
                }

            if mode == "conversation":
                limit = min(int(kwargs.get("limit", 5)), 25)
                results = manager.search_conversations(query, limit=limit)
            else:
                limit = min(int(kwargs.get("limit", 10)), 50)
                results = manager.search_sessions(query, limit=limit, session_id=session_id)

            return {
                "success": True,
                "query": query,
                "mode": mode,
                "result_count": len(results),
                "results": results,
            }

        except Exception as e:
            logger.exception("Session search failed")
            return {"success": False, "error": str(e)}
