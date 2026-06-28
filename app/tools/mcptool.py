"""MCP Management Tool — Agent-driven MCP server connection management.

Allows agents to connect to public or custom MCP servers, list available
tools, and disconnect — all at runtime.

Uses the existing ``MCPRegistry`` from ``app.core.mcp_client``.
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
        self._registry = None

    def get_name(self) -> str:
        return "mcp_manage"

    def get_description(self) -> str:
        return (
            "Manages MCP (Model Context Protocol) server connections. "
            "Actions: 'list' (show available/public servers), 'connect' (attach a server), "
            "'disconnect' (detach), 'tools' (list tools from a server), "
            "'register' (add a custom server), 'categories' (browse by category). "
            "Connected MCP servers provide additional tools the agent can use."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: list, connect, disconnect, tools, register, categories",
                    required=True,
                    enum=["list", "connect", "disconnect", "tools", "register", "categories"],
                ),
                ToolParameter(
                    name="server_name",
                    type="string",
                    description="Server name (required for connect, disconnect, tools, register)",
                    required=False,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Executable for custom server (required for connect/register, e.g. 'npx', 'uvx', 'python')",
                    required=False,
                ),
                ToolParameter(
                    name="args",
                    type="string",
                    description="Space-separated CLI arguments for the server command",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Server description (register action)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        try:
            if action == "list":
                return self._list()
            elif action == "categories":
                return self._categories()
            elif action == "connect":
                return await self._connect(kwargs)
            elif action == "disconnect":
                return await self._disconnect(kwargs)
            elif action == "tools":
                return self._tools(kwargs)
            elif action == "register":
                return self._register(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("MCP management failed for action=%s", action)
            return {"success": False, "error": str(e)}

    def _get_registry(self):
        if self._registry is None:
            from app.core.mcp_client import get_mcp_registry

            self._registry = get_mcp_registry()
        return self._registry

    def _list(self) -> dict[str, Any]:
        registry = self._get_registry()
        servers = registry.list_servers()
        return {
            "success": True,
            "server_count": len(servers),
            "servers": servers,
        }

    def _categories(self) -> dict[str, Any]:
        registry = self._get_registry()
        cats = registry.list_categories()
        return {
            "success": True,
            "category_count": len(cats),
            "categories": cats,
        }

    async def _connect(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        command = kwargs.get("command", "").strip()
        args_str = kwargs.get("args", "").strip()

        if not name:
            return {"success": False, "error": "server_name is required"}

        registry = self._get_registry()

        if command:
            # Custom server: register then connect
            args = args_str.split() if args_str else []
            registry.register_server(
                name,
                {
                    "command": command,
                    "args": args,
                    "description": kwargs.get("description", f"Custom MCP server: {name}"),
                },
            )

        result = await registry.connect_server(name)
        if result.get("success"):
            return {
                "success": True,
                "message": f"Connected to MCP server '{name}' ({result['tools_count']} tools available)",
                "tools": result["tools"],
            }
        return {"success": False, "error": result.get("error", "Connection failed")}

    async def _disconnect(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        if not name:
            return {"success": False, "error": "server_name is required"}
        registry = self._get_registry()
        client = registry._clients.pop(name, None)
        if client:
            await client.disconnect()
            return {"success": True, "message": f"Disconnected from '{name}'"}
        return {"success": False, "error": f"Server '{name}' is not connected"}

    def _tools(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        registry = self._get_registry()

        if name:
            client = registry._clients.get(name)
            if not client:
                return {"success": False, "error": f"Server '{name}' is not connected"}
            raw_tools = client.get_tools()
            return {
                "success": True,
                "server_name": name,
                "tool_count": len(raw_tools),
                "tools": [
                    {"name": t.get("name"), "description": t.get("description", "")}
                    for t in raw_tools
                ],
            }

        all_tools = registry.get_all_tools()
        by_server: dict[str, list[dict[str, str]]] = {}
        for t in all_tools:
            srv = t["server"]
            by_server.setdefault(srv, []).append(
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                }
            )
        return {
            "success": True,
            "tools_by_server": by_server,
        }

    def _register(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("server_name", "").strip()
        command = kwargs.get("command", "").strip()
        args_str = kwargs.get("args", "").strip()

        if not name or not command:
            return {"success": False, "error": "server_name and command are required"}
        args = args_str.split() if args_str else []

        registry = self._get_registry()
        registry.register_server(
            name,
            {
                "command": command,
                "args": args,
                "description": kwargs.get("description", f"Custom MCP server: {name}"),
            },
        )
        return {
            "success": True,
            "message": f"Registered custom MCP server '{name}' (use connect to attach)",
        }
