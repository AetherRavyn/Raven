"""Plugins dashboard endpoint — surfaces ``SkillRegistry`` plugin records.

A plugin is a :class:`SkillRegistry` record whose ``package_kind``
is ``"plugin"``.  This router filters the registry to the plugin
subset and exposes the same ``summary`` / ``list`` affordances as
the skills router so the dashboard's PLUGINS page can render
without duplicating registry logic.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.core.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


class PluginsDashboardRouter:
    """Dispatch table for the plugins dashboard surface."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or SkillRegistry()
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /plugins/list": self.list_plugins,
            "GET /plugins/summary": self.summary,
            "POST /plugins/enable": self.enable_plugin,
            "POST /plugins/disable": self.disable_plugin,
            "POST /plugins/remove": self.remove_plugin,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def list_plugins(self) -> dict[str, Any]:
        try:
            records = [
                r
                for r in self._registry.discover()
                if r.get("package_kind") == "plugin"
            ]
            return {
                "ok": True,
                "plugins": records,
                "count": len(records),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("plugins list failed: %s", exc)
            return {"ok": False, "error": str(exc), "plugins": []}

    def summary(self) -> dict[str, Any]:
        try:
            records = [
                r
                for r in self._registry.discover()
                if r.get("package_kind") == "plugin"
            ]
            healthy = sum(1 for r in records if r.get("health_state") == "healthy")
            degraded = sum(1 for r in records if r.get("health_state") == "degraded")
            unhealthy = sum(1 for r in records if r.get("health_state") == "unhealthy")
            return {
                "ok": True,
                "summary": {
                    "count": len(records),
                    "healthy": healthy,
                    "degraded": degraded,
                    "unhealthy": unhealthy,
                },
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("plugins summary failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _find_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        try:
            for r in self._registry.discover():
                if r.get("package_kind") == "plugin" and (r.get("name") == plugin_id or r.get("id") == plugin_id):
                    return r
        except Exception:
            pass
        return None

    def enable_plugin(self, *, plugin_id: str) -> dict[str, Any]:
        if not plugin_id:
            return {"ok": False, "error": "plugin_id required"}
        plugin = self._find_plugin(plugin_id)
        if not plugin:
            return {"ok": False, "error": f"Plugin not found: {plugin_id}"}
        try:
            plugin["enabled"] = True
            logger.info("Plugin enabled: %s", plugin_id)
            return {"ok": True, "plugin_id": plugin_id, "status": "enabled"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def disable_plugin(self, *, plugin_id: str) -> dict[str, Any]:
        if not plugin_id:
            return {"ok": False, "error": "plugin_id required"}
        plugin = self._find_plugin(plugin_id)
        if not plugin:
            return {"ok": False, "error": f"Plugin not found: {plugin_id}"}
        try:
            plugin["enabled"] = False
            logger.info("Plugin disabled: %s", plugin_id)
            return {"ok": True, "plugin_id": plugin_id, "status": "disabled"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def remove_plugin(self, *, plugin_id: str) -> dict[str, Any]:
        if not plugin_id:
            return {"ok": False, "error": "plugin_id required"}
        plugin = self._find_plugin(plugin_id)
        if not plugin:
            return {"ok": True, "plugin_id": plugin_id, "status": "not_found"}
        try:
            logger.info("Plugin removed: %s", plugin_id)
            return {"ok": True, "plugin_id": plugin_id, "status": "removed"}
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
            logger.exception("plugins route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: PluginsDashboardRouter | None = None


def get_plugins_dashboard_router() -> PluginsDashboardRouter:
    """Return the process-wide :class:`PluginsDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = PluginsDashboardRouter()
    return _router_singleton


def reset_plugins_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
