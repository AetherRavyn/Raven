"""Provider management dashboard API — model selection, ranking, enable/disable.

These endpoints power the "Providers" management UI where users can:
- See all 40+ providers and their models
- Enable/disable providers
- Set provider priority order
- Select the active provider and model
- View the current model selection

Differs from ``app.web.endpoints.providers`` (which manages API keys):
this module manages *which* provider/model is used, not *how to auth*.
"""

from __future__ import annotations

import logging
from typing import Any

from app.provider.manager import ProviderManager

logger = logging.getLogger(__name__)


class ProviderManagerDashboard:
    """JSON API router for provider management dashboard.

    Matches the dispatch pattern in :mod:`app.web.endpoints.cron`:
    a ``_routes`` dict maps route strings to handler methods.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._manager = ProviderManager(workspace_dir)
        self._orchestrator: Any = None
        self._routes: dict[str, Any] = {
            "GET /providers/status": self._get_providers_status,
            "GET /models": self._get_models,
            "GET /models/current": self._get_current_model,
            "POST /providers/enable": self._post_providers_enable,
            "POST /providers/rank": self._post_providers_rank,
            "POST /models/select": self._post_models_select,
            # v35 (2026-06-23): combos + health + stats — 9router-style.
            "GET /combos": self._get_combos,
            "POST /combos": self._post_combos,
            "PUT /combos": self._put_combos,
            "DELETE /combos": self._delete_combos,
            "POST /combos/activate": self._post_combos_activate,
            "GET /providers/health/all": self._get_providers_health_all,
            "POST /providers/health/check": self._post_providers_health_check,
            "GET /providers/stats": self._get_providers_stats,
            "POST /providers/select-with-fallback": self._post_select_with_fallback,
            # v36 (2026-06-23): per-agent model overrides
            "GET /agent-models": self._get_agent_models,
            "POST /agent-models": self._post_agent_models,
            "DELETE /agent-models": self._delete_agent_models,
            # v37 (2026-06-23): model slots + provider browsing
            "GET /models/options": self._get_models_options,
            "POST /models/set": self._post_models_set,
            "GET /models/slots": self._get_models_slots,
            "POST /models/reset": self._post_models_reset,
        }

    def bind_orchestrator(self, orch: Any) -> None:
        self._orchestrator = orch

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as exc:
            logger.exception("Provider manager route %s raised: %s", route, exc)
            return {"ok": False, "error": str(exc), "route": route}

    def _get_providers_status(self) -> dict[str, Any]:
        providers = self._manager.get_all_providers()
        active_provider = self._manager.active_provider
        active_model = self._manager.active_model
        return {
            "ok": True,
            "providers": providers,
            "active_provider": active_provider,
            "active_model": active_model,
        }

    def _get_models(self) -> dict[str, Any]:
        models = self._manager.get_models_list()
        return {
            "ok": True,
            "models": models,
            "count": len(models),
        }

    def _get_current_model(self) -> dict[str, Any]:
        provider, model = self._manager.select_model()
        return {
            "ok": True,
            "provider": provider,
            "model": model,
        }

    def _post_providers_enable(
        self,
        provider_id: str = "",
        enabled: str = "true",
    ) -> dict[str, Any]:
        is_enabled = enabled.lower() in {"true", "1", "yes"}
        if not provider_id:
            return {"ok": False, "error": "provider_id required"}
        self._manager.set_enabled(provider_id, is_enabled)
        return {
            "ok": True,
            "provider_id": provider_id,
            "enabled": is_enabled,
        }

    def _post_providers_rank(self, ranking: str = "") -> dict[str, Any]:
        ranking_list: list[str] = []
        if isinstance(ranking, str):
            ranking_list = [p.strip() for p in ranking.split(",") if p.strip()]
        elif isinstance(ranking, list):
            ranking_list = ranking
        if not ranking_list:
            return {"ok": False, "error": "ranking required (comma-separated provider IDs)"}
        self._manager.set_ranking(ranking_list)
        return {"ok": True, "ranking": ranking_list}

    def _post_models_select(
        self,
        provider_id: str = "",
        model_id: str = "",
    ) -> dict[str, Any]:
        if not provider_id or not model_id:
            return {"ok": False, "error": "provider_id and model_id required"}
        self._manager.active_provider = provider_id
        self._manager.active_model = model_id
        self._manager.set_model_slot("main", provider_id, model_id)
        if self._orchestrator and hasattr(self._orchestrator, "_agent_runtime"):
            try:
                self._orchestrator._agent_runtime.set_model(provider_id, model_id)
            except Exception as exc:
                logger.warning("Failed to update runtime model: %s", exc)
        return {"ok": True, "active_provider": provider_id, "active_model": model_id}

    # ── v35 (2026-06-23): Combos ───────────────────────────────────

    def _get_combos(self) -> dict[str, Any]:
        return {
            "ok": True,
            "combos": self._manager.get_combos(),
            "active_combo": self._manager.get_active_combo(),
        }

    def _post_combos(self, name: str = "", providers: str = "") -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "name required"}
        ids = [p.strip() for p in (providers or "").split(",") if p.strip()]
        if not ids:
            return {"ok": False, "error": "providers required (comma-separated)"}
        self._manager.upsert_combo(name, ids)
        return {"ok": True, "name": name, "providers": ids}

    def _put_combos(self, name: str = "", providers: str = "") -> dict[str, Any]:
        return self._post_combos(name=name, providers=providers)

    def _delete_combos(self, name: str = "") -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "name required"}
        ok = self._manager.delete_combo(name)
        return {"ok": ok, "name": name, "deleted": ok}

    def _post_combos_activate(self, name: str = "") -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            self._manager.set_active_combo(None)
            return {"ok": True, "active_combo": None, "deactivated": True}
        combos = self._manager.get_combos()
        if name not in combos:
            return {"ok": False, "error": f"unknown combo '{name}'"}
        self._manager.set_active_combo(name)
        return {"ok": True, "active_combo": name}

    # ── v35 (2026-06-23): Health + stats ──────────────────────────

    async def _get_providers_health_all(self) -> dict[str, Any]:
        # Probing is async + per-provider; reuse the manager helper.
        try:
            health = await self._manager.refresh_health()
        except Exception as exc:
            logger.warning("refresh_health failed: %s", exc)
            health = self._manager.get_all_health()
        return {"ok": True, "health": health}

    async def _post_providers_health_check(self, provider_id: str = "") -> dict[str, Any]:
        provider_id = (provider_id or "").strip()
        if not provider_id:
            return {"ok": False, "error": "provider_id required"}
        try:
            result = await self._manager.probe_one(provider_id)
            return {"ok": True, "health": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider_id": provider_id}

    def _get_providers_stats(self) -> dict[str, Any]:
        return {"ok": True, "stats": self._manager.get_all_stats()}

    def _post_select_with_fallback(self, task_type: str = "general") -> dict[str, Any]:
        try:
            pid, mid, source = self._manager.select_with_fallback(task_type=task_type)
            return {
                "ok": True,
                "provider": pid,
                "model": mid,
                "source": source,
                "task_type": task_type,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "task_type": task_type}

    # ── v36 (2026-06-23): Per-agent model overrides ──────────────

    def _get_agent_models(self) -> dict[str, Any]:
        return {"ok": True, "agent_models": self._manager.get_all_agent_models()}

    def _post_agent_models(
        self,
        agent_name: str = "",
        provider_id: str = "",
        model_id: str = "",
    ) -> dict[str, Any]:
        agent_name = (agent_name or "").strip()
        provider_id = (provider_id or "").strip()
        model_id = (model_id or "").strip()
        if not agent_name or not provider_id or not model_id:
            return {"ok": False, "error": "agent_name, provider_id, and model_id required"}
        self._manager.set_agent_model(agent_name, provider_id, model_id)
        return {
            "ok": True,
            "agent_name": agent_name,
            "provider_id": provider_id,
            "model_id": model_id,
        }

    def _delete_agent_models(self, agent_name: str = "") -> dict[str, Any]:
        agent_name = (agent_name or "").strip()
        if not agent_name:
            return {"ok": False, "error": "agent_name required"}
        removed = self._manager.remove_agent_model(agent_name)
        return {"ok": removed, "agent_name": agent_name, "removed": removed}

    # ── v37 (2026-06-23): Model slots + provider browsing ──────

    def _get_models_options(self) -> dict[str, Any]:
        """Return authenticated providers with their curated model lists.
        This is the data the dashboard "Models" page uses to populate
        the provider→model picker (two-column UI like Hermes Agent).
        """
        from app.provider.registry import PROVIDER_REGISTRY

        authenticated = self._manager.get_authenticated_providers()
        auth_ids = {a["id"] for a in authenticated}

        providers = []
        for p in PROVIDER_REGISTRY:
            if p.id not in auth_ids:
                continue
            providers.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "group": p.group,
                    "tier": p.tier.value,
                    "auth_type": p.auth_type.value,
                    "default_model": p.default_model,
                    "models": [
                        {
                            "id": m.id,
                            "name": m.name,
                            "context": m.context,
                            "tier": m.tier.value,
                            "quality": m.quality,
                        }
                        for m in p.models
                    ],
                }
            )

        current_slots = self._manager.list_model_slots()

        return {
            "ok": True,
            "providers": providers,
            "slots": current_slots,
            "count": len(providers),
        }

    def _post_models_set(
        self,
        scope: str = "main",
        provider_id: str = "",
        model_id: str = "",
    ) -> dict[str, Any]:
        """Set a model slot.  *scope* is ``"main"``, ``"agent:<name>"``,
        or ``"auxiliary:<task>"``.  ``provider_id="auto"`` resets the slot.
        """
        scope = (scope or "").strip()
        provider_id = (provider_id or "").strip()
        model_id = (model_id or "").strip()
        if not scope:
            return {"ok": False, "error": "scope required"}
        if provider_id == "auto":
            self._manager.set_model_slot(scope, "auto", "")
            return {"ok": True, "scope": scope, "provider": "auto", "model": "", "reset": True}
        if not model_id:
            return {"ok": False, "error": "model_id required when provider_id is not 'auto'"}
        self._manager.set_model_slot(scope, provider_id, model_id)
        if scope == "main" and self._orchestrator and hasattr(self._orchestrator, "_agent_runtime"):
            try:
                self._orchestrator._agent_runtime.set_model(provider_id, model_id)
            except Exception as exc:
                logger.warning("Failed to update runtime model: %s", exc)
        return {
            "ok": True,
            "scope": scope,
            "provider": provider_id,
            "model": model_id,
        }

    def _get_models_slots(self) -> dict[str, Any]:
        """Return all currently configured model slots."""
        slots = self._manager.list_model_slots()
        resolved = {}
        for scope_key in {"main"} | {f"agent:{n}" for n in self._manager.get_all_agent_models()}:
            pid, mid = self._manager.resolve_model_slot(scope_key)
            resolved[scope_key] = {"provider": pid, "model": mid}
        return {"ok": True, "slots": slots, "resolved": resolved}

    def _post_models_reset(self, scope: str = "__all__") -> dict[str, Any]:
        """Reset model slot(s).  ``scope="__all__"`` resets all."""
        scope = (scope or "__all__").strip()
        removed = self._manager.reset_model_slot(scope)
        return {"ok": True, "scope": scope, "removed": removed}


_provider_manager_dashboard: ProviderManagerDashboard | None = None


def get_provider_manager_dashboard(
    workspace_dir: str | None = None,
) -> ProviderManagerDashboard:
    global _provider_manager_dashboard
    if _provider_manager_dashboard is None:
        _provider_manager_dashboard = ProviderManagerDashboard(workspace_dir)
    return _provider_manager_dashboard
