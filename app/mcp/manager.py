"""MCP dynamic tool discovery — load tools from configured MCP servers.

MCPManager connects to one or more MCP servers via stdio transport,
lists their tools, and wraps each one in a MCPToolAdapter (BaseTool)
so they can be registered with AgentRuntime.register_tool().

Usage:
    manager = MCPManager()
    await manager.connect("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"])
    for tool in manager.get_tools():
        runtime.register_tool(tool)
    ...
    await manager.disconnect("filesystem")
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


# ─── Adapter: wraps a single MCP tool as a BaseTool ────────────────────────────


class MCPToolAdapter(BaseTool):
    """Wraps an MCP tool as a BaseTool so AgentRuntime can call it."""

    def __init__(
        self,
        session: Any,
        tool: Any,
        server_name: str = "",
    ) -> None:
        self._session = session
        self._tool = tool
        self._server_name = server_name
        self._name = tool.name
        self._description = tool.description or ""
        self._schema = self._build_schema(tool)

    def get_name(self) -> str:
        return self._name

    def get_description(self) -> str:
        return self._description

    def get_schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        kwargs.pop("_request", None)
        try:
            result = await self._session.call_tool(self._name, arguments=kwargs)
            text_parts = []
            for block in result.content or []:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
            return {"success": True, "result": "\n".join(text_parts)}
        except Exception as exc:
            logger.error("MCPToolAdapter.execute %s error: %s", self._name, exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _build_schema(tool: Any) -> ToolSchema:
        params: list[ToolParameter] = []
        input_schema: dict = {}
        if hasattr(tool, "inputSchema") and tool.inputSchema:
            raw = tool.inputSchema
            input_schema = raw if isinstance(raw, dict) else raw.model_dump()
        properties = input_schema.get("properties") or {}
        required_names = set(input_schema.get("required") or [])
        for prop_name, prop_def in properties.items():
            params.append(
                ToolParameter(
                    name=prop_name,
                    type=prop_def.get("type", "string"),
                    description=prop_def.get("description", ""),
                    required=prop_name in required_names,
                    enum=prop_def.get("enum") or [],
                )
            )
        return ToolSchema(
            name=tool.name,
            description=tool.description or "",
            parameters=params,
        )


# ─── Manager ────────────────────────────────────────────────────────────────────


class MCPManager:
    """Connects to multiple MCP servers and exposes their tools as BaseTools.

    Manages the full lifecycle: connect → get_tools → disconnect.
    Each connection runs in an asyncio task that keeps the subprocess alive.
    """

    def __init__(self) -> None:
        # server_name → connection state
        self._connections: dict[str, dict[str, Any]] = {}

    async def connect(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Connect to an MCP server and discover its tools.

        Args:
            name: Human label for this server.
            command: Executable (e.g. ``npx``, ``python``, ``uvx``).
            args: CLI arguments.
            env: Extra environment variables.

        Returns:
            dict with ``success``, ``name``, ``tool_count``, and list of ``tools``.
        """
        if name in self._connections:
            return {"success": False, "error": f"Server '{name}' is already connected"}

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            return {"success": False, "error": f"mcp package not installed: {exc}"}

        params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
        )

        try:
            read, write = await stdio_client(params).__aenter__()
            session = await ClientSession(read, write).__aenter__()
            await session.initialize()
            tools_result = await session.list_tools()
            tools = list(tools_result.tools or [])
        except Exception as exc:
            return {"success": False, "error": f"Failed to connect to '{name}': {exc}"}

        # Store the connection
        self._connections[name] = {
            "session": session,
            "tools": tools,
            "read": read,
            "write": write,
            "command": command,
            "args": args or [],
            "env": env or {},
        }

        tool_names = [t.name for t in tools]
        logger.info(
            "MCP: connected to '%s' (%s), discovered %d tool(s): %s",
            name,
            command,
            len(tools),
            tool_names,
        )

        return {
            "success": True,
            "name": name,
            "tool_count": len(tools),
            "tools": tool_names,
        }

    async def disconnect(self, name: str) -> dict[str, Any]:
        """Disconnect from an MCP server and clean up resources."""
        conn = self._connections.pop(name, None)
        if conn is None:
            return {"success": False, "error": f"Server '{name}' is not connected"}

        try:
            session = conn["session"]
            read = conn["read"]
            write = conn["write"]
            await session.__aexit__(None, None, None)
            await write.close()
            logger.info("MCP: disconnected from '%s'", name)
        except Exception as exc:
            logger.error("MCP: error disconnecting '%s': %s", name, exc)

        return {"success": True, "message": f"Disconnected from '{name}'"}

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for name in list(self._connections.keys()):
            await self.disconnect(name)

    def get_tools(self, server_name: str | None = None) -> list[BaseTool]:
        """Return MCPToolAdapter instances for connected servers.

        Args:
            server_name: If set, only return tools from that server.

        Returns:
            List of ``MCPToolAdapter`` instances.
        """
        adapters: list[BaseTool] = []
        for srv_name, conn in self._connections.items():
            if server_name is not None and srv_name != server_name:
                continue
            for tool in conn["tools"]:
                adapters.append(MCPToolAdapter(
                    session=conn["session"],
                    tool=tool,
                    server_name=srv_name,
                ))
        return adapters

    def list_servers(self) -> list[dict[str, Any]]:
        """Return status for all connected servers."""
        return [
            {
                "name": name,
                "command": conn["command"],
                "tool_count": len(conn["tools"]),
                "tools": [t.name for t in conn["tools"]],
            }
            for name, conn in self._connections.items()
        ]

    def is_connected(self, name: str) -> bool:
        return name in self._connections


# Global singleton
_mcp_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager
