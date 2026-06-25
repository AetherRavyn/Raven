"""MCP Server — Expose AetherRavyn as an MCP (Model Context Protocol) tool server.

This allows external agents, IDEs, and MCP clients to discover and invoke
AetherRavyn's tools over the standard MCP protocol. Combined with the existing
MCP client (manager.py), this gives AetherRavyn full bidirectional MCP support.

Usage:
    # Start as standalone MCP server
    ravyn mcp-serve

    # Or programmatically
    server = MCPServer(tools=[...])
    await server.serve_stdio()

Protocol:
    - Transport: stdio (stdin/stdout JSON-RPC)
    - Discovery: tools/list → returns all registered tools
    - Invocation: tools/call → executes tool and returns result
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# MCP JSON-RPC message types
_JSONRPC_VERSION = "2.0"


@dataclass(slots=True)
class MCPToolDescriptor:
    """MCP-compatible tool descriptor."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPServer:
    """Exposes AetherRavyn tools as an MCP server over stdio transport.

    This implements the MCP server protocol:
    - initialize → server capabilities
    - tools/list → enumerate all available tools
    - tools/call → invoke a tool by name with arguments
    - notifications/initialized → client confirms init

    The server wraps any list of BaseTool instances and makes them
    discoverable and callable via MCP.
    """

    def __init__(
        self,
        server_name: str = "aetherravyn",
        server_version: str = "1.0.0",
    ) -> None:
        self._server_name = server_name
        self._server_version = server_version
        self._tools: dict[str, Any] = {}  # name → BaseTool
        self._descriptors: list[MCPToolDescriptor] = []
        self._initialized = False

    # ── Tool Registration ───────────────────────────────────────────

    def register_tool(self, tool: Any) -> None:
        """Register a BaseTool instance for MCP exposure."""
        name = tool.get_name()
        self._tools[name] = tool
        schema = tool.get_schema()

        # Convert ToolSchema to MCP input_schema format
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in schema.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        input_schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            input_schema["required"] = required

        self._descriptors.append(
            MCPToolDescriptor(
                name=name,
                description=schema.description,
                input_schema=input_schema,
            )
        )
        logger.debug("MCP server registered tool: %s", name)

    def register_tools_from_runtime(self, runtime: Any) -> None:
        """Register all tools from an AgentRuntime instance."""
        for tool in runtime.tools.values():
            self.register_tool(tool)
        logger.info(
            "MCP server registered %d tools from runtime", len(self._tools)
        )

    # ── Protocol Handlers ───────────────────────────────────────────

    async def _handle_initialize(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle initialize request."""
        self._initialized = True
        return self._make_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": self._server_name,
                    "version": self._server_version,
                },
            },
        )

    async def _handle_tools_list(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle tools/list request."""
        tools = []
        for desc in self._descriptors:
            tools.append({
                "name": desc.name,
                "description": desc.description,
                "inputSchema": desc.input_schema,
            })
        return self._make_response(request_id, {"tools": tools})

    async def _handle_tools_call(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        tool = self._tools.get(tool_name)
        if tool is None:
            return self._make_error(
                request_id,
                code=-32601,
                message=f"Tool not found: {tool_name}",
            )

        try:
            result = await tool.execute(**arguments)
            # Format result as MCP content blocks
            if isinstance(result, dict):
                text = result.get("result") or result.get("output") or json.dumps(result)
            else:
                text = str(result)

            is_error = False
            if isinstance(result, dict) and result.get("success") is False:
                is_error = True
                text = result.get("error") or text

            return self._make_response(
                request_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "isError": is_error,
                },
            )
        except Exception as exc:
            logger.error("MCP tool execution error (%s): %s", tool_name, exc)
            return self._make_response(
                request_id,
                {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            )

    # ── Message Routing ─────────────────────────────────────────────

    async def _handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Route an incoming JSON-RPC message to the appropriate handler."""
        method = message.get("method", "")
        request_id = message.get("id")
        params = message.get("params") or {}

        # Notifications (no id) — just acknowledge
        if request_id is None:
            if method == "notifications/initialized":
                logger.debug("MCP client confirmed initialization")
            return None

        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
        }

        handler = handlers.get(method)
        if handler is None:
            return self._make_error(
                request_id,
                code=-32601,
                message=f"Method not found: {method}",
            )

        return await handler(request_id, params)

    # ── Stdio Transport ─────────────────────────────────────────────

    async def serve_stdio(self) -> None:
        """Run the MCP server over stdio (stdin/stdout).

        Reads JSON-RPC messages from stdin, processes them, and writes
        responses to stdout. This is the standard MCP transport.
        """
        logger.info(
            "MCP server starting: %s v%s (%d tools)",
            self._server_name,
            self._server_version,
            len(self._tools),
        )

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin.buffer
        )

        writer_transport, writer_protocol = (
            await asyncio.get_event_loop().connect_write_pipe(
                asyncio.streams.FlowControlMixin, sys.stdout.buffer
            )
        )
        writer = asyncio.StreamWriter(
            writer_transport, writer_protocol, None, asyncio.get_event_loop()
        )

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # EOF

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError as exc:
                    logger.warning("Invalid JSON received: %s", exc)
                    continue

                response = await self._handle_message(message)
                if response is not None:
                    response_bytes = (
                        json.dumps(response, ensure_ascii=False) + "\n"
                    ).encode("utf-8")
                    writer.write(response_bytes)
                    await writer.drain()

        except asyncio.CancelledError:
            logger.info("MCP server shutting down")
        except Exception as exc:
            logger.error("MCP server error: %s", exc)
        finally:
            writer.close()

    # ── JSON-RPC Helpers ────────────────────────────────────────────

    @staticmethod
    def _make_response(request_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    @staticmethod
    def _make_error(
        request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    # ── Diagnostics ─────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return server status for diagnostics."""
        return {
            "name": self._server_name,
            "version": self._server_version,
            "initialized": self._initialized,
            "tools_count": len(self._tools),
            "tools": [d.name for d in self._descriptors],
        }


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_MCP_SERVER: MCPServer | None = None


def get_mcp_server() -> MCPServer:
    """Get or create the global MCPServer instance."""
    global _GLOBAL_MCP_SERVER
    if _GLOBAL_MCP_SERVER is None:
        _GLOBAL_MCP_SERVER = MCPServer()
    return _GLOBAL_MCP_SERVER
