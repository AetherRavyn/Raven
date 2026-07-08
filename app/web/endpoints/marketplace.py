"""Marketplace dashboard endpoint — wrapper over ``SkillMarketplace``.

Provides endpoints to search, install, publish and manage skills from remote hubs.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.core.skill_marketplace import SkillMarketplace

logger = logging.getLogger(__name__)


class MarketplaceDashboardRouter:
    """Dispatch table for the skill marketplace surface."""

    def __init__(self, marketplace: SkillMarketplace | None = None) -> None:
        self._marketplace = marketplace or SkillMarketplace()
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /marketplace/hubs": self.list_hubs,
            "GET /marketplace/search": self.search,
            "POST /marketplace/install": self.install,
            "POST /marketplace/publish": self.publish,
            "POST /marketplace/scan": self.scan,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def list_hubs(self) -> dict[str, Any]:
        try:
            hubs = self._marketplace.list_hubs()
            return {"ok": True, "hubs": hubs}
        except Exception as exc:
            logger.exception("marketplace list hubs failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def search(self, *, query: str = "", include_remote: bool = True) -> dict[str, Any]:
        try:
            results = self._marketplace.search(query, include_remote=include_remote)
            return {"ok": True, "results": results, "count": len(results)}
        except Exception as exc:
            logger.exception("marketplace search failed: %s", exc)
            return {"ok": False, "error": str(exc), "results": []}

    def install(self, *, skill_name: str, source: str) -> dict[str, Any]:
        if not skill_name or not source:
            return {"ok": False, "error": "skill_name and source required"}
        try:
            result = self._marketplace.install(skill_name, source)
            return {"ok": True, "result": result}
        except Exception as exc:
            logger.exception("marketplace install failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def publish(self, *, skill_name: str, description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        if not skill_name:
            return {"ok": False, "error": "skill_name required"}
        try:
            result = self._marketplace.publish(skill_name, description=description, tags=tags)
            return {"ok": True, "result": result}
        except Exception as exc:
            logger.exception("marketplace publish failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def scan(self, *, skill_name: str) -> dict[str, Any]:
        # Simple wrapper to scan an installed skill
        from app.core.skill_marketplace import SkillSecurityScanner
        try:
            skill_dir = self._marketplace._installed_dir / skill_name
            if not skill_dir.exists():
                return {"ok": False, "error": "Skill not found"}
            scanner = SkillSecurityScanner()
            report = scanner.scan(skill_dir)
            return {"ok": True, "report": report}
        except Exception as exc:
            logger.exception("marketplace scan failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:
            logger.exception("marketplace route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: MarketplaceDashboardRouter | None = None


def get_marketplace_dashboard_router() -> MarketplaceDashboardRouter:
    """Return the process-wide :class:`MarketplaceDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = MarketplaceDashboardRouter()
    return _router_singleton

def reset_marketplace_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
