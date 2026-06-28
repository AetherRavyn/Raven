"""Context References Tool — Expand @file, @folder, @url, @git references.

Agents use this to pull external context into conversations.
The orchestrator also auto-expands @references in user messages.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class ContextTool(BaseTool):
    """Expand @references to inject external context into messages.

    Supports: @file <path>, @folder <path>, @url <url>,
    @git diff, @git log [N], @context <name>.
    """

    group = "system"

    def get_name(self) -> str:
        return "context"

    def get_description(self) -> str:
        return (
            "Expands @references to inject file contents, folder listings, "
            "web page content, git diffs, and context files into messages. "
            "Supports: @file <path>, @folder <path>, @url <url>, "
            "@git diff, @git log [N], @context <name>."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Message text containing @references to expand",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        text = kwargs.get("text", "")
        if not text:
            return {"success": False, "error": "text is required"}

        try:
            from app.core.context_references import get_context_resolver

            resolver = get_context_resolver()
            expanded_text, resolved_refs = resolver.resolve_references(text)

            return {
                "success": True,
                "expanded_text": expanded_text,
                "references_expanded": len(resolved_refs),
                "resolved": [
                    {
                        "type": r["type"],
                        "query": r.get("query", ""),
                        "content_length": r.get("content_length", 0),
                        "content_preview": r.get("content_preview", "")[:200],
                    }
                    for r in resolved_refs
                ],
            }
        except Exception as e:
            logger.exception("Context reference expansion failed")
            return {"success": False, "error": str(e)}
