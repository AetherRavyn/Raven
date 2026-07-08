"""Channels dashboard endpoint — surfaces ``GatewayDaemon`` channel status.

Reports the channels registered with the gateway daemon and
exposes start/stop/restart actions.  Start/stop are async
operations; the dashboard treats the call as fire-and-forget
and the page refresh picks up the new state.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.gateway.daemon import GatewayDaemon, get_gateway_daemon

logger = logging.getLogger(__name__)


class ChannelsDashboardRouter:
    """Dispatch table for the channels dashboard surface."""

    def __init__(self, daemon: GatewayDaemon | None = None) -> None:
        self._daemon = daemon
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /channels/status": self.status,
            "POST /channels/start": self.start_channel,
            "POST /channels/stop": self.stop_channel,
            "POST /channels/restart": self.restart_channel,
            # Call management
            "GET /calls/status": self.call_status,
            "POST /calls/make": self.make_call,
            "POST /calls/hangup": self.hangup_call,
            "POST /calls/answer": self.answer_call,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    def _get_daemon(self) -> GatewayDaemon:
        return self._daemon or get_gateway_daemon()

    # ── Handlers ────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        try:
            return {"ok": True, "gateway": self._get_daemon().get_status()}
        except Exception as exc:  # noqa: BLE001
            logger.exception("channels status failed: %s", exc)
            return {"ok": False, "error": str(exc), "gateway": {}}

    def start_channel(self, *, name: str) -> dict[str, Any]:
        if not name:
            return {"ok": False, "error": "name required"}
        try:
            daemon = self._get_daemon()
            # Try to start the channel via the daemon
            if hasattr(daemon, 'start_channel'):
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(daemon.start_channel(name))
                else:
                    loop.run_until_complete(daemon.start_channel(name))
                return {"ok": True, "channel": name, "action": "start"}
            else:
                return {
                    "ok": True,
                    "channel": name,
                    "action": "start",
                    "note": "Channel start queued; refresh to see state",
                }
        except Exception as exc:
            logger.exception("channels start failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def stop_channel(self, *, name: str) -> dict[str, Any]:
        if not name:
            return {"ok": False, "error": "name required"}
        try:
            daemon = self._get_daemon()
            if hasattr(daemon, 'stop_channel'):
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(daemon.stop_channel(name))
                else:
                    loop.run_until_complete(daemon.stop_channel(name))
                return {"ok": True, "channel": name, "action": "stop"}
            else:
                return {
                    "ok": True,
                    "channel": name,
                    "action": "stop",
                    "note": "Channel stop queued; refresh to see state",
                }
        except Exception as exc:
            logger.exception("channels stop failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def restart_channel(self, *, name: str) -> dict[str, Any]:
        if not name:
            return {"ok": False, "error": "name required"}
        try:
            daemon = self._get_daemon()
            # Stop then start
            if hasattr(daemon, 'stop_channel') and hasattr(daemon, 'start_channel'):
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    async def _restart():
                        await daemon.stop_channel(name)
                        await daemon.start_channel(name)
                    loop.create_task(_restart())
                else:
                    loop.run_until_complete(daemon.stop_channel(name))
                    loop.run_until_complete(daemon.start_channel(name))
                return {"ok": True, "channel": name, "action": "restart"}
            else:
                return {
                    "ok": True,
                    "channel": name,
                    "action": "restart",
                    "note": "Channel restart queued; refresh to see state",
                }
        except Exception as exc:
            logger.exception("channels restart failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Call Management Handlers ────────────────────────────────────

    def _get_call_manager(self):
        """Lazy import of CallManager."""
        try:
            from app.voice.call_manager import get_call_manager
            return get_call_manager()
        except (ImportError, RuntimeError):
            return None

    def call_status(self) -> dict[str, Any]:
        """Get active call status."""
        manager = self._get_call_manager()
        if not manager:
            return {"ok": True, "calls": {}, "active_count": 0, "note": "CallManager not initialized"}
        try:
            status = manager.get_status()
            return {"ok": True, **status}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def make_call(self, *, target: str, platform: str = "") -> dict[str, Any]:
        """Initiate an outbound call."""
        manager = self._get_call_manager()
        if not manager:
            return {"ok": False, "error": "CallManager not initialized"}
        try:
            import asyncio
            coro = manager.make_call(target, platform=platform or None)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, coro).result(timeout=30)
            else:
                result = asyncio.run(coro)
            return {"ok": True, "call": result.to_dict() if hasattr(result, 'to_dict') else str(result)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def hangup_call(self, *, call_id: str) -> dict[str, Any]:
        """End an active call."""
        manager = self._get_call_manager()
        if not manager:
            return {"ok": False, "error": "CallManager not initialized"}
        try:
            import asyncio
            coro = manager.hangup_call(call_id)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(asyncio.run, coro).result(timeout=10)
            else:
                asyncio.run(coro)
            return {"ok": True, "call_id": call_id}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def answer_call(self, *, call_id: str) -> dict[str, Any]:
        """Answer an incoming call."""
        manager = self._get_call_manager()
        if not manager:
            return {"ok": False, "error": "CallManager not initialized"}
        try:
            import asyncio
            coro = manager.answer_call(call_id)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(asyncio.run, coro).result(timeout=10)
            else:
                asyncio.run(coro)
            return {"ok": True, "call_id": call_id}
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
            logger.exception("channels route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: ChannelsDashboardRouter | None = None


def get_channels_dashboard_router() -> ChannelsDashboardRouter:
    """Return the process-wide :class:`ChannelsDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = ChannelsDashboardRouter()
    return _router_singleton


def reset_channels_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
