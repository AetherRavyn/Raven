"""Pairing dashboard endpoint — surfaces ``DMPairingManager`` state.

Lists pending and approved pairing requests and exposes
approve/revoke actions.  The pair code itself is generated
by the bot (not the dashboard), so the page does not expose
a "create code" form.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Callable, Mapping

from app.core.dm_pairing import DMPairingManager, get_dm_pairing_manager

logger = logging.getLogger(__name__)


class PairingDashboardRouter:
    """Dispatch table for the pairing dashboard surface."""

    def __init__(self, manager: DMPairingManager | None = None) -> None:
        self._manager = manager
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /pairing/list": self.list_requests,
            "POST /pairing/approve": self.approve_code,
            "POST /pairing/revoke": self.revoke_pairing,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    def _get_manager(self) -> DMPairingManager:
        return self._manager or get_dm_pairing_manager()

    # ── Handlers ────────────────────────────────────────────────────

    def list_requests(self) -> dict[str, Any]:
        try:
            mgr = self._get_manager()
            pending = [asdict(p) for p in mgr.get_pending_requests()]
            paired = [asdict(p) for p in mgr.get_paired_users()]
            return {
                "ok": True,
                "pending": pending,
                "paired": paired,
                "pending_count": len(pending),
                "paired_count": len(paired),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("pairing list failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "pending": [],
                "paired": [],
            }

    def approve_code(self, *, code: str, approved_by: str = "admin") -> dict[str, Any]:
        if not code:
            return {"ok": False, "error": "code required"}
        try:
            ok = self._get_manager().approve_code(code, approved_by=approved_by)
            return {"ok": ok, "code": code}
        except Exception as exc:  # noqa: BLE001
            logger.exception("pairing approve failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def revoke_pairing(self, *, user_id: str, platform: str) -> dict[str, Any]:
        if not user_id or not platform:
            return {"ok": False, "error": "user_id and platform required"}
        try:
            ok = self._get_manager().revoke_pairing(user_id, platform)
            return {"ok": ok, "user_id": user_id, "platform": platform}
        except Exception as exc:  # noqa: BLE001
            logger.exception("pairing revoke failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("pairing route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: PairingDashboardRouter | None = None


def get_pairing_dashboard_router() -> PairingDashboardRouter:
    """Return the process-wide :class:`PairingDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = PairingDashboardRouter()
    return _router_singleton


def reset_pairing_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
