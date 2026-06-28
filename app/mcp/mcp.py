"""MCP — Model Context Protocol support for Raven.

This module provides a convenience re-export of the self-serving MCP server
so external agents, IDEs, and MCP clients can discover and invoke Raven's
tools over the standard MCP protocol.

Quick start:
    from app.mcp import get_mcp_server, MCPServer

    server = get_mcp_server()
    server.register_tool(my_tool)
    await server.serve_stdio()

Or from the CLI:
    python -m app.mcp.mcp  # starts the server with all registered tools
"""

from app.mcp.server import MCPServer, MCPToolDescriptor, get_mcp_server

__all__ = ["MCPServer", "MCPToolDescriptor", "get_mcp_server"]
