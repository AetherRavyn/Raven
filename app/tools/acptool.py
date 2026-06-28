"""ACP Tool — Agent Communication Protocol for IDE/tool integration.

Enables agents to use the ACP (Agent Communication Protocol) to
communicate with external tools like IDEs, editors, and CI/CD pipelines.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class AcpTool(BaseTool):
    """Communicate with external tools via ACP (Agent Communication Protocol).

    Actions: ping, execute, list_tools, read_file, search, status.
    External tools (IDEs, editors) can also POST directly to /acp.
    """

    group = "system"

    def get_name(self) -> str:
        return "acp"

    def get_description(self) -> str:
        return (
            "Agent Communication Protocol — interact with external tools "
            "like IDEs, editors, and CI/CD. Actions: ping (check connectivity), "
            "execute (run shell command), list_tools (discover available tools), "
            "read_file (read a file), search (search conversations), "
            "status (system health)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="ACP action to perform",
                    required=True,
                    enum=["ping", "execute", "list_tools", "read_file", "search", "status"],
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Shell command (required for execute)",
                    required=False,
                ),
                ToolParameter(
                    name="filepath",
                    type="string",
                    description="File path (required for read_file)",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (required for search)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from app.core.acp import get_acp_handler

        action = kwargs.get("action", "")
        if not action:
            return {"success": False, "error": "action is required"}

        handler = get_acp_handler()
        body = {
            "action": action,
            "params": {
                "command": kwargs.get("command", ""),
                "filepath": kwargs.get("filepath", ""),
                "query": kwargs.get("query", ""),
            },
        }

        try:
            result = await handler.handle_request(body)
            return {"success": result.get("success", False), **result}
        except Exception as e:
            logger.exception("ACP action failed")
            return {"success": False, "error": str(e)}
