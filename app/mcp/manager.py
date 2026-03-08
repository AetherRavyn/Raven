# app/mcp/manager.py
"""MCP dynamic tool discovery — load tools from configured MCP servers.

MCPManager connects to one or more MCP servers via stdio transport,
lists their tools, and wraps each one in a MCPToolAdapter (BaseTool)
so they can be registered with AgentRuntime.register_tool().

Usage:
    manager = MCPManager(servers_config=[
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
        }
    ])
    await manager.connect_all()
    for tool in manager.get_mcp_tools_as_base_tools():
        runtime.register_tool(tool)
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
        session: Any,  # mcp.ClientSession
        tool: Any,  # mcp tool descriptor (has .name, .description, .inputSchema)
    ) -> None:
        self._session = session
        self._tool = tool
        self._name = tool.name
        self._description = tool.description or ""
        self._schema = self._build_schema(tool)

    # ── BaseTool interface ──────────────────────────────────────────────────

    def get_name(self) -> str:
        return self._name

    def get_description(self) -> str:
        return self._description

    def get_schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        # Strip the injected _request kwarg (not meaningful for MCP calls)
        kwargs.pop("_request", None)
        try:
            result = await self._session.call_tool(self._name, arguments=kwargs)
            # MCP result is a list of content blocks; concatenate text parts
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

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_schema(tool: Any) -> ToolSchema:
        params: list[ToolParameter] = []
        input_schema: dict = {}

        # inputSchema may be a dict or a Pydantic model
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

    Args:
        servers_config: list of dicts with keys:
            - ``name``    (str)  human label
            - ``command`` (str)  executable, e.g. "npx" or "python"
            - ``args``    (list) arguments to the command
            - ``env``     (dict, optional) extra environment variables
    """

    def __init__(self, servers_config: list[dict]) -> None:
        self._servers = servers_config
        # name → (session, list[tool])
        self._connected: dict[str, tuple[Any, list[Any]]] = {}
        self._lock = asyncio.Lock()

    async def connect_all(self) -> None:
        """Connect to all configured servers concurrently."""
        tasks = [self._connect_server(cfg) for cfg in self._servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for cfg, result in zip(self._servers, results):
            if isinstance(result, Exception):
                logger.error(
                    "MCPManager: failed to connect to server '%s': %s",
                    cfg.get("name", "?"),
                    result,
                )

    async def _connect_server(self, config: dict) -> None:
        """Connect to a single MCP server and register its tools."""
        try:
            from mcp import ClientSession, StdioServerParameters  # noqa: PLC0415
            from mcp.client.stdio import stdio_client  # noqa: PLC0415
        except ImportError as exc:
            logger.warning(
                "mcp package not installed — MCPManager unavailable: %s", exc
            )
            return

        name = config.get("name", config.get("command", "unknown"))
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    tools = list(tools_result.tools or [])
                    logger.info(
                        "MCPManager: connected to '%s', discovered %d tool(s): %s",
                        name,
                        len(tools),
                        [t.name for t in tools],
                    )
                    async with self._lock:
                        self._connected[name] = (session, tools)
                    # Keep the context alive until explicitly disconnected
                    await asyncio.Future()  # suspended until cancelled
        except asyncio.CancelledError:
            logger.debug("MCPManager: connection to '%s' cancelled", name)
        except Exception as exc:
            logger.error("MCPManager: error with server '%s': %s", name, exc)
            raise

    def get_mcp_tools_as_base_tools(self) -> list[BaseTool]:
        """Return all discovered MCP tools as MCPToolAdapter instances.

        Call this after ``connect_all()`` has been awaited.
        """
        adapters: list[BaseTool] = []
        for _server_name, (session, tools) in self._connected.items():
            for tool in tools:
                adapters.append(MCPToolAdapter(session=session, tool=tool))
        return adapters

    def tool_names(self) -> list[str]:
        """Return a flat list of all discovered tool names."""
        names: list[str] = []
        for _, (_, tools) in self._connected.items():
            names.extend(t.name for t in tools)
        return names

    def server_names(self) -> list[str]:
        return list(self._connected.keys())
