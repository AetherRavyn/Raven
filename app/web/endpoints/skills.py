"""Skills dashboard endpoint — thin wrapper over ``SkillRegistry``.

Lists the discovered skills/plugins/integrations manifest
records and exposes a few affordances for the operator: the
summary roll-up, the onboarding queue, and a force-reload
action (delete the cached summary to force a fresh
``discover()`` on next render).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.core.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillsDashboardRouter:
    """Dispatch table for the skills dashboard surface."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or SkillRegistry()
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /skills/list": self.list_skills,
            "GET /skills/summary": self.summary,
            "GET /skills/onboarding": self.onboarding,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def list_skills(self) -> dict[str, Any]:
        try:
            records = self._registry.discover()
            return {
                "ok": True,
                "skills": records,
                "count": len(records),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("skills list failed: %s", exc)
            return {"ok": False, "error": str(exc), "skills": []}

    def summary(self) -> dict[str, Any]:
        try:
            return {"ok": True, "summary": self._registry.summary()}
        except Exception as exc:  # noqa: BLE001
            logger.exception("skills summary failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def onboarding(self) -> dict[str, Any]:
        try:
            records = self._registry.onboarding_queue()
            return {
                "ok": True,
                "queue": records,
                "count": len(records),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("skills onboarding failed: %s", exc)
            return {"ok": False, "error": str(exc), "queue": []}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("skills route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: SkillsDashboardRouter | None = None


def get_skills_dashboard_router() -> SkillsDashboardRouter:
    """Return the process-wide :class:`SkillsDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = SkillsDashboardRouter()
    return _router_singleton


def reset_skills_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
