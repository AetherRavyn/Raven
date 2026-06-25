"""MCP Client — connect to Model Context Protocol servers.

Provides:
- MCPClient: connect to any MCP server (stdio or HTTP transport)
- MCPRegistry: pre-configured registry of public MCP servers
- Tool discovery: extract tools from MCP servers and register them
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


# Public MCP server registry — curated list of useful MCP servers
PUBLIC_MCP_SERVERS: dict[str, dict[str, Any]] = {
    # Reference servers (official)
    "filesystem": {
        "description": "Secure file operations with access controls",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "category": "files",
    },
    "github": {
        "description": "GitHub repository management, issues, PRs",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        "category": "development",
    },
    "postgres": {
        "description": "PostgreSQL database access with schema inspection",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
        "category": "database",
    },
    "memory": {
        "description": "Knowledge graph-based persistent memory",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "category": "memory",
    },
    "git": {
        "description": "Git repository tools (read, search, manipulate)",
        "command": "uvx",
        "args": ["mcp-server-git"],
        "category": "development",
    },
    "brave-search": {
        "description": "Web and local search via Brave Search API",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": ""},
        "category": "search",
    },
    "google-maps": {
        "description": "Location services, directions, and place details",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-maps"],
        "env": {"GOOGLE_MAPS_API_KEY": ""},
        "category": "location",
    },
    "google-drive": {
        "description": "File access and search for Google Drive",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "category": "files",
    },
    "slack": {
        "description": "Channel management and messaging",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {
            "SLACK_BOT_TOKEN": "",
            "SLACK_TEAM_ID": "",
        },
        "category": "messaging",
    },
    "redis": {
        "description": "Redis key-value store operations",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-redis"],
        "category": "database",
    },
    "sentry": {
        "description": "Issue tracking and analysis from Sentry.io",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sentry"],
        "env": {"SENTRY_AUTH_TOKEN": ""},
        "category": "monitoring",
    },
    "everything": {
        "description": "Reference server with prompts, resources, and tools",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "category": "utility",
    },
    "sequential-thinking": {
        "description": "Dynamic problem-solving through thought sequences",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "category": "reasoning",
    },
    # Community MCP servers
    "puppeteer": {
        "description": "Browser automation and web scraping",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "category": "browser",
    },
    "notion": {
        "description": "Notion workspace management",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-notion"],
        "env": {"NOTION_API_KEY": ""},
        "category": "productivity",
    },
    "stripe": {
        "description": "Stripe payment processing",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-stripe"],
        "env": {"STRIPE_SECRET_KEY": ""},
        "category": "finance",
    },
    "vercel": {
        "description": "Vercel deployment management",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-vercel"],
        "env": {"VERCEL_TOKEN": ""},
        "category": "deployment",
    },
    "cloudflare": {
        "description": "Cloudflare Workers and infrastructure",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-cloudflare"],
        "env": {"CLOUDFLARE_API_TOKEN": ""},
        "category": "deployment",
    },
    "docker": {
        "description": "Docker container management",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-docker"],
        "category": "infrastructure",
    },
}


class MCPClient:
    """Connect to an MCP server and invoke tools."""

    def __init__(self, server_config: dict[str, Any]) -> None:
        self._config = server_config
        self._process: subprocess.Popen | None = None
        self._tools: list[dict[str, Any]] = []
        self._connected = False
        self._request_id = 0

    async def connect(self) -> dict[str, Any]:
        """Connect to the MCP server via stdio transport."""
        command = self._config.get("command", "npx")
        args = self._config.get("args", [])
        env = self._config.get("env", {})

        try:
            import os
            full_env = os.environ.copy()
            full_env.update({k: v for k, v in env.items() if v})

            self._process = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
            )

            # Send initialize request
            init_response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "raven-mcp-client", "version": "1.0.0"},
            })

            # Get tools list
            tools_response = await self._send_request("tools/list", {})
            self._tools = tools_response.get("tools", [])
            self._connected = True

            return {
                "success": True,
                "tools_count": len(self._tools),
                "tools": [t.get("name", "") for t in self._tools],
            }

        except Exception as e:
            return {"error": str(e)[:500]}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool."""
        if not self._connected:
            return {"error": "Not connected. Call connect() first."}

        response = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        return response

    def get_tools(self) -> list[dict[str, Any]]:
        """Get available tools from this server."""
        return self._tools

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to the MCP server."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return {"error": "Process not running"}

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            request_bytes = json.dumps(request).encode() + b"\n"
            self._process.stdin.write(request_bytes)
            self._process.stdin.flush()

            # Read response (non-blocking with timeout)
            import select
            ready, _, _ = select.select([self._process.stdout], [], [], 10)
            if ready:
                response_line = self._process.stdout.readline().decode().strip()
                if response_line:
                    return json.loads(response_line)
            return {"error": "Timeout waiting for response"}
        except Exception as e:
            return {"error": str(e)[:500]}

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=5)
            self._process = None
        self._connected = False


class MCPRegistry:
    """Registry of MCP servers — manages connections and tool discovery."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._configs: dict[str, dict[str, Any]] = dict(PUBLIC_MCP_SERVERS)

    def list_servers(self) -> list[dict[str, Any]]:
        """List all known MCP servers."""
        servers = []
        for name, config in self._configs.items():
            servers.append({
                "name": name,
                "description": config.get("description", ""),
                "category": config.get("category", ""),
                "connected": name in self._clients and self._clients[name]._connected,
            })
        return servers

    def list_categories(self) -> dict[str, list[str]]:
        """List servers grouped by category."""
        categories: dict[str, list[str]] = {}
        for name, config in self._configs.items():
            cat = config.get("category", "other")
            categories.setdefault(cat, []).append(name)
        return categories

    async def connect_server(self, name: str) -> dict[str, Any]:
        """Connect to an MCP server."""
        config = self._configs.get(name)
        if not config:
            return {"error": f"Server '{name}' not found in registry"}

        client = MCPClient(config)
        result = await client.connect()
        if result.get("success"):
            self._clients[name] = client
        return result

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on a connected MCP server."""
        client = self._clients.get(server)
        if not client or not client._connected:
            return {"error": f"Server '{server}' not connected"}
        return await client.call_tool(tool, args)

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools from all connected MCP servers."""
        all_tools = []
        for name, client in self._clients.items():
            if client._connected:
                for tool in client.get_tools():
                    all_tools.append({
                        "server": name,
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("inputSchema", {}),
                    })
        return all_tools

    async def disconnect_all(self) -> None:
        """Disconnect all MCP servers."""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()

    def register_server(self, name: str, config: dict[str, Any]) -> None:
        """Register a custom MCP server."""
        self._configs[name] = config


# Singleton
_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
    return _registry
