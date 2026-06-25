"""MCP Management Tool — Agent-driven MCP server connection management.

Allows agents to connect to, list, and disconnect from MCP servers
at runtime. Discovered tools are automatically available to the agent
for invocation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class MCPManagementTool(BaseTool):
    """Manage MCP server connections: connect, list, disconnect.

    Agents use this to dynamically discover and attach external tools
    from MCP-compatible servers at runtime.
    """

    group = "agent"

    def __init__(self) -> None:
        self._manager = None

    def get_name(self) -> str:
        return "mcp_manage"

    def get_description(self) -> str:
        return (
            "Manages MCP (Model Context Protocol) server connections. "
            "Actions: 'connect' (attach a new MCP server), 'list' (show connected servers), "
            "'disconnect' (detach a server), 'tools' (list tools from a server). "
            "MCP servers provide additional tools the agent can use."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: connect, list, disconnect, tools",
                    required=True,
                    enum=["connect", "list", "disconnect", "tools"],
                ),
                ToolParameter(
                    name="server_name",
                    type="string",
                    description="Human label for the MCP server (required for connect, disconnect, tools)",
                    required=False,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Executable to launch the server (required for connect, e.g. 'npx', 'python', 'uvx')",
                    required=False,
                ),
                ToolParameter(
                    name="args",
                    type="string",
                    description="Space-separated CLI arguments for the server command (required for connect)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")

        try:
            if action == "connect":
                return await self._connect(kwargs)
            elif action == "list":
                return self._list()
            elif action == "disconnect":
                return await self._disconnect(kwargs)
            elif action == "tools":
                return self._tools(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("MCP management failed for action=%s", action)
            return {"success": False, "error": str(e)}

    def _get_manager(self):
        if self._manager is None:
            from app.mcp.manager import get_mcp_manager
            self._manager = get_mcp_manager()
        return self._manager

    async def _connect(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        command = kwargs.get("command", "").strip()
        args_str = kwargs.get("args", "").strip()

        if not name:
            return {"success": False, "error": "server_name is required"}
        if not command:
            return {"success": False, "error": "command is required (e.g. 'npx', 'python', 'uvx')"}

        args = [a.strip() for a in args_str.split() if a.strip()] if args_str else []

        manager = self._get_manager()
        result = await manager.connect(name, command, args)

        if result["success"]:
            return {
                "success": True,
                "message": f"Connected to MCP server '{name}' ({result['tool_count']} tools available)",
                "tools": result["tools"],
            }
        return result

    def _list(self) -> dict[str, Any]:
        manager = self._get_manager()
        servers = manager.list_servers()
        if not servers:
            return {
                "success": True,
                "servers": [],
                "message": "No MCP servers connected. Use action='connect' to add one.",
            }
        return {
            "success": True,
            "server_count": len(servers),
            "servers": servers,
        }

    async def _disconnect(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        if not name:
            return {"success": False, "error": "server_name is required"}
        manager = self._get_manager()
        return await manager.disconnect(name)

    def _tools(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        manager = self._get_manager()
        if name:
            adapters = manager.get_tools(server_name=name)
            return {
                "success": True,
                "server_name": name,
                "tool_count": len(adapters),
                "tools": [t.get_name() for t in adapters],
            }
        # Show all tools across all servers
        servers = manager.list_servers()
        all_tools = {}
        for srv in servers:
            adapters = manager.get_tools(server_name=srv["name"])
            all_tools[srv["name"]] = [t.get_name() for t in adapters]
        return {
            "success": True,
            "tools_by_server": all_tools,
        }
