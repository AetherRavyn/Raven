"""Profiles dashboard endpoint — thin wrapper over ``UserProfileStore``.

Surfaces the per-user profile store to the dashboard.  The
read-only v32 contract is list user IDs and load a single
profile.  Update-by-text (the ``update_from_text`` helper)
lands in v34 to avoid a circular concern with the
``update_from_text`` keyword extractor.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from app.core.user_profile import UserProfileStore

logger = logging.getLogger(__name__)


class ProfilesDashboardRouter:
    """Dispatch table for the profiles dashboard surface."""

    def __init__(self, store: UserProfileStore | None = None) -> None:
        self._store = store or UserProfileStore()
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /profiles/list": self.list_profiles,
            "GET /profiles/load": self.load_profile,
            "POST /profiles/save": self.save_profile,
            "POST /profiles/delete": self.delete_profile,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────────

    def list_profiles(self) -> dict[str, Any]:
        try:
            profiles_dir = self._store.profiles_dir
            ids: list[str] = []
            if profiles_dir.exists():
                for path in sorted(profiles_dir.glob("*.json")):
                    ids.append(path.stem)
            return {"ok": True, "user_ids": ids, "count": len(ids)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("profiles list failed: %s", exc)
            return {"ok": False, "error": str(exc), "user_ids": []}

    def load_profile(self, *, user_id: str) -> dict[str, Any]:
        if not user_id:
            return {"ok": False, "error": "user_id required"}
        try:
            profile = self._store.load(user_id)
            return {
                "ok": True,
                "user_id": profile.user_id,
                "display_name": profile.display_name,
                "preferences": profile.preferences,
                "facts": profile.facts,
                "projects": profile.projects,
                "pinned": profile.pinned,
                "updated_at": profile.updated_at,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("profiles load failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def save_profile(self, **kwargs: Any) -> dict[str, Any]:
        user_id = kwargs.get("user_id", "")
        if not user_id:
            return {"ok": False, "error": "user_id required"}
        try:
            profile = self._store.load(user_id)
            for field in ("display_name", "preferences", "facts", "projects", "pinned"):
                if field in kwargs:
                    setattr(profile, field, kwargs[field])
            self._store.save(profile)
            logger.info("Profile saved: %s", user_id)
            return {"ok": True, "user_id": user_id}
        except Exception as exc:
            logger.exception("profiles save failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def delete_profile(self, *, user_id: str) -> dict[str, Any]:
        if not user_id:
            return {"ok": False, "error": "user_id required"}
        try:
            profile_path = self._store.profiles_dir / f"{user_id}.json"
            if profile_path.exists():
                profile_path.unlink()
                logger.info("Profile deleted: %s", user_id)
                return {"ok": True, "user_id": user_id, "status": "deleted"}
            return {"ok": True, "user_id": user_id, "status": "not_found"}
        except Exception as exc:
            logger.exception("profiles delete failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("profiles route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: ProfilesDashboardRouter | None = None


def get_profiles_dashboard_router() -> ProfilesDashboardRouter:
    """Return the process-wide :class:`ProfilesDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = ProfilesDashboardRouter()
    return _router_singleton


def reset_profiles_dashboard_router_for_tests() -> None:  # pragma: no cover
    global _router_singleton
    _router_singleton = None
