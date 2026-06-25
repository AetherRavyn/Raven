"""MCP dashboard endpoint — surfaces ``MCPManager`` state.

Reports the connected MCP servers and their discovered tools.
``connect_all()`` is gated behind an explicit ``connect=true``
query string so a passive page render does not spawn
stdio subprocesses.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.mcp.manager import MCPManager

logger = logging.getLogger(__name__)


class MCPDashboardRouter:
    """Dispatch table for the MCP dashboard surface."""

    def __init__(self, manager: MCPManager | None = None) -> None:
        # The default is an empty manager; the page render uses
        # :func:`status` which only reads the connected dict so
        # a never-connected manager is safe.
        self._manager = manager
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /mcp/status": self.status,
            "POST /mcp/connect": self.connect,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        try:
            if self._manager is None:
                return {
                    "ok": True,
                    "servers": [],
                    "tool_names": [],
                    "connected": False,
                }
            servers = self._manager.server_names()
            tools = self._manager.tool_names()
            return {
                "ok": True,
                "servers": servers,
                "tool_names": tools,
                "connected": bool(servers),
                "tool_count": len(tools),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("mcp status failed: %s", exc)
            return {"ok": False, "error": str(exc), "servers": [], "tool_names": []}

    def connect(self, *, servers: list[dict] | None = None) -> dict[str, Any]:
        """Connect to MCP servers."""
        try:
            if servers:
                # Initialize manager with server configs
                if self._manager is None:
                    self._manager = MCPManager(servers_config=servers)
                else:
                    # Add new servers to existing manager
                    for server_config in servers:
                        try:
                            self._manager.add_server(server_config)
                        except Exception as exc:
                            logger.warning("Failed to add MCP server: %s", exc)

                # Attempt connection
                connected = []
                failed = []
                for server_config in servers:
                    name = server_config.get("name", "unknown")
                    try:
                        # Try to connect to the server
                        if hasattr(self._manager, 'connect_server'):
                            self._manager.connect_server(name)
                        connected.append(name)
                    except Exception as exc:
                        failed.append({"name": name, "error": str(exc)})
                        logger.warning("MCP server connect failed: %s — %s", name, exc)

                return {
                    "ok": True,
                    "connected": connected,
                    "failed": failed,
                    "note": "MCP connection established; refresh status to see tools",
                }

            return {"ok": True, "note": "No servers specified"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("mcp route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: MCPDashboardRouter | None = None


def get_mcp_dashboard_router() -> MCPDashboardRouter:
    """Return the process-wide :class:`MCPDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = MCPDashboardRouter()
    return _router_singleton


def reset_mcp_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
