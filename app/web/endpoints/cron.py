"""Cron dashboard endpoint — thin wrapper over ``CronEngine``.

Surfaces the dynamic ``~/.raven/memory/cron.json`` store to the
dashboard so an operator can list, toggle, add, and remove jobs
without going to the CLI.  The router is framework-agnostic: it
returns plain dicts and the FastAPI adapter in
:mod:`app.web.server` translates them into HTTP responses.

This module deliberately does not import FastAPI at top level
so the dispatch function can be unit-tested in isolation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.core.cron_engine import CronEngine

logger = logging.getLogger(__name__)


class CronDashboardRouter:
    """Dispatch table for the cron dashboard surface."""

    def __init__(self, engine: CronEngine | None = None) -> None:
        self._engine = engine or CronEngine()
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /cron/list": self.list_jobs,
            "POST /cron/toggle": self.toggle_job,
            "POST /cron/add": self.add_job,
            "POST /cron/remove": self.remove_job,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def list_jobs(self) -> dict[str, Any]:
        try:
            jobs = self._engine.get_jobs()
            return {"ok": True, "jobs": jobs, "count": len(jobs)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("cron list failed: %s", exc)
            return {"ok": False, "error": str(exc), "jobs": []}

    def toggle_job(self, *, job_id: str) -> dict[str, Any]:
        if not job_id:
            return {"ok": False, "error": "job_id required"}
        changed = self._engine.toggle_job(job_id)
        return {"ok": changed, "job_id": job_id}

    def add_job(
        self,
        *,
        job_id: str,
        name: str,
        description: str,
        schedule_type: str,
        action_description: str,
        time_str: str | None = None,
        interval: int | None = None,
    ) -> dict[str, Any]:
        result = self._engine.add_job(
            job_id=job_id,
            name=name,
            description=description,
            schedule_type=schedule_type,
            action_description=action_description,
            time_str=time_str,
            interval=interval,
        )
        if not result.get("success"):
            return {"ok": False, "error": result.get("error", "add_failed")}
        return {"ok": True, "job": result["job"]}

    def remove_job(self, *, job_id: str) -> dict[str, Any]:
        if not job_id:
            return {"ok": False, "error": "job_id required"}
        removed = self._engine.remove_job(job_id)
        return {"ok": removed, "job_id": job_id}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("cron route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: CronDashboardRouter | None = None


def get_cron_dashboard_router() -> CronDashboardRouter:
    """Return the process-wide :class:`CronDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = CronDashboardRouter()
    return _router_singleton


def reset_cron_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
