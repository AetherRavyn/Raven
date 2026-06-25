from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.provider.registry import (
    PROVIDER_REGISTRY,
    get_provider,
)
from app.provider.health import (
    all_health,
    get_health,
    probe_all,
    probe_provider,
    record_call,
    get_stats,
    all_stats,
)

logger = logging.getLogger(__name__)

_PREFS_FILENAME = "provider_prefs.json"

# Default combos seeded on first run so the dashboard has something
# to show.  These mirror 9router's three-tier "Subscription → Cheap →
# Free" philosophy but use the providers RAVEN actually supports.
_DEFAULT_COMBOS: dict[str, list[str]] = {
    "max-quality": ["anthropic", "openai", "google", "deepseek"],
    "balanced": ["anthropic", "openrouter", "groq", "opencode_zen"],
    "free-only": ["opencode_zen", "groq"],
    "coding": ["deepseek", "opencode_zen", "openrouter", "groq"],
    "local-first": ["ollama", "opencode_zen", "openrouter", "groq"],
}


class ProviderManager:
    """Persistent user preference store for provider ranking and model selection.

    Reads/writes a JSON file (default: ``workspace/provider_prefs.json``) so
    that choices made in the dashboard survive restarts.
    """

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self._workspace_dir = Path(workspace_dir or self._default_workspace())
        self._prefs_path = self._workspace_dir / _PREFS_FILENAME
        self._prefs: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active_provider(self) -> str:
        slot = self._prefs.get("model_slots", {}).get("main", {})
        return slot.get("provider", "") or self._prefs.get("active_provider", "opencode_zen")

    @active_provider.setter
    def active_provider(self, value: str) -> None:
        self._prefs["active_provider"] = value
        self._save()

    @property
    def active_model(self) -> str:
        slot = self._prefs.get("model_slots", {}).get("main", {})
        return slot.get("model", "") or self._prefs.get("active_model", "big-pickle")

    @active_model.setter
    def active_model(self, value: str) -> None:
        self._prefs["active_model"] = value
        self._save()

    def get_enabled_providers(self) -> list[str]:
        """Return list of provider IDs the user has enabled."""
        return list(self._prefs.get("enabled", []))

    def is_enabled(self, provider_id: str) -> bool:
        return provider_id in self._prefs.get("enabled", [])

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        enabled_list: list[str] = list(self._prefs.get("enabled", []))
        if enabled and provider_id not in enabled_list:
            enabled_list.append(provider_id)
        elif not enabled and provider_id in enabled_list:
            enabled_list.remove(provider_id)
        self._prefs["enabled"] = enabled_list
        self._save()

    def get_ranking(self) -> list[str]:
        """Return provider IDs in user-defined priority order (highest first)."""
        return list(self._prefs.get("ranking", []))

    def set_ranking(self, provider_ids: list[str]) -> None:
        self._prefs["ranking"] = provider_ids
        self._save()

    def set_fallback_chain(self, task_type: str, providers: list[str]) -> None:
        fallback = dict(self._prefs.get("fallback_chains", {}))
        fallback[task_type] = providers
        self._prefs["fallback_chains"] = fallback
        self._save()

    def get_fallback_chain(self, task_type: str) -> list[str]:
        return list(self._prefs.get("fallback_chains", {}).get(task_type, []))

    # ── Combos (9router-style named fallback chains) ─────────────

    def get_combos(self) -> dict[str, list[str]]:
        """Return ``{combo_name: [provider_id, ...]}`` ordered by priority.

        A combo is a named sequence of provider IDs the router walks
        in order until one returns a healthy response.  Unlike the
        flat ``ranking`` field, combos are first-class objects the
        operator can create, rename, delete, and activate.
        """
        stored = self._prefs.get("combos", {})
        if not stored:
            return {k: list(v) for k, v in _DEFAULT_COMBOS.items()}
        return {k: list(v) for k, v in stored.items()}

    def get_active_combo(self) -> str | None:
        return self._prefs.get("active_combo") or None

    def set_active_combo(self, name: str | None) -> None:
        if name is None:
            self._prefs.pop("active_combo", None)
        else:
            self._prefs["active_combo"] = name
        self._save()

    def upsert_combo(self, name: str, provider_ids: list[str]) -> None:
        combos = dict(self._prefs.get("combos", {}))
        combos[name] = list(provider_ids)
        self._prefs["combos"] = combos
        self._save()

    def delete_combo(self, name: str) -> bool:
        combos = dict(self._prefs.get("combos", {}))
        if name not in combos:
            return False
        combos.pop(name)
        self._prefs["combos"] = combos
        if self._prefs.get("active_combo") == name:
            self._prefs.pop("active_combo", None)
        self._save()
        return True

    # ── Per-agent model overrides ─────────────────────────────

    def get_agent_model(self, agent_name: str) -> tuple[str, str] | None:
        """Return ``(provider_id, model_id)`` for *agent_name*, or None."""
        agent_models = self._prefs.get("agent_models", {})
        entry = agent_models.get(agent_name)
        if entry and isinstance(entry, dict):
            pid = entry.get("provider", "")
            mid = entry.get("model", "")
            if pid and mid:
                return pid, mid
        return None

    def set_agent_model(self, agent_name: str, provider_id: str, model_id: str) -> None:
        """Assign a specific provider+model to an agent type."""
        agent_models = dict(self._prefs.get("agent_models", {}))
        agent_models[agent_name] = {"provider": provider_id, "model": model_id}
        self._prefs["agent_models"] = agent_models
        self._save()

    def remove_agent_model(self, agent_name: str) -> bool:
        """Remove the per-agent override for *agent_name*."""
        agent_models = dict(self._prefs.get("agent_models", {}))
        if agent_name not in agent_models:
            return False
        del agent_models[agent_name]
        self._prefs["agent_models"] = agent_models
        self._save()
        return True

    def get_all_agent_models(self) -> dict[str, dict[str, str]]:
        return dict(self._prefs.get("agent_models", {}))

    # ── Model slots (main + agent + auxiliary) ─────────────────

    def get_model_slot(self, scope: str) -> tuple[str, str]:
        """Return ``(provider, model)`` for *scope*, or ``("", "")``.
        ``scope`` is ``"main"``, ``"agent:<name>"``, or ``"auxiliary:<task>"``.
        """
        slots = self._prefs.get("model_slots", {})
        entry = slots.get(scope, {})
        return entry.get("provider", ""), entry.get("model", "")

    def set_model_slot(self, scope: str, provider_id: str, model_id: str) -> None:
        """Assign a provider+model to a slot.  Persists immediately."""
        slots = dict(self._prefs.get("model_slots", {}))
        if provider_id == "auto" and not model_id:
            slots.pop(scope, None)
        else:
            slots[scope] = {"provider": provider_id, "model": model_id}
        self._prefs["model_slots"] = slots
        self._save()

    def list_model_slots(self) -> dict[str, dict[str, str]]:
        """Return all configured non-auto slots."""
        return dict(self._prefs.get("model_slots", {}))

    def reset_model_slot(self, scope: str) -> bool:
        """Reset *scope* to auto/default. ``scope="__all__"`` resets all."""
        slots = dict(self._prefs.get("model_slots", {}))
        if scope == "__all__":
            self._prefs["model_slots"] = {}
            self._save()
            return True
        if scope in slots:
            del slots[scope]
            self._prefs["model_slots"] = slots
            self._save()
            return True
        return False

    def resolve_model_slot(self, scope: str) -> tuple[str, str]:
        """Resolve the best ``(provider, model)`` for *scope*.
        If *scope* has an explicit slot → use it.
        If an agent-scope has a per-agent override → use it.
        Otherwise → use the main slot / select_model() cascade.
        """
        pid, mid = self.get_model_slot(scope)
        if pid and mid:
            return pid, mid
        if scope.startswith("agent:"):
            agent_name = scope.split(":", 1)[1]
            override = self.get_agent_model(agent_name)
            if override:
                return override
        return self.select_model()

    def get_authenticated_providers(self) -> list[dict[str, Any]]:
        """Return providers that have credentials configured (key set, OAuth, or local)."""
        from app.settings.config import Config
        from app.provider.registry import PROVIDER_REGISTRY

        result = []
        for p in PROVIDER_REGISTRY:
            if p.auth_type.value == "local":
                result.append({"id": p.id, "name": p.name, "group": p.group, "auth": "local"})
                continue
            if p.auth_type.value == "free":
                result.append({"id": p.id, "name": p.name, "group": p.group, "auth": "free"})
                continue
            config_val = getattr(Config, p.config_attr, None) if p.config_attr else None
            env_val = os.environ.get(p.env_var) if p.env_var else None
            if config_val or env_val:
                result.append({"id": p.id, "name": p.name, "group": p.group, "auth": "key"})
        return result

    # ── Multi-account per provider (round-robin / failover) ──────

    def get_accounts(self, provider_id: str) -> list[dict[str, str]]:
        """Return ``[{label, key_preview}]`` for *provider_id*.

        Multiple accounts let the router round-robin across keys so
        per-provider rate limits are spread out.  This stores labels
        + a short preview only — the actual keys live in ``Config``
        + ``os.environ`` so the existing key-overlay flow keeps
        working.
        """
        accounts = self._prefs.get("accounts", {}).get(provider_id, [])
        return list(accounts)

    def set_accounts(self, provider_id: str, accounts: list[dict[str, str]]) -> None:
        all_acc = dict(self._prefs.get("accounts", {}))
        all_acc[provider_id] = list(accounts)
        self._prefs["accounts"] = all_acc
        self._save()

    # ── Health + stats passthrough (dashboard convenience) ────────

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        return {pid: h.to_dict() for pid, h in all_health().items()}

    def get_all_stats(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in all_stats()]

    def get_stats_for(self, provider_id: str) -> dict[str, Any] | None:
        s = get_stats(provider_id)
        return s.to_dict() if s else None

    async def refresh_health(self, *, timeout: float = 1.5) -> dict[str, dict[str, Any]]:
        """Re-probe every provider in the registry, return a fresh
        health dict for the dashboard.  Fast (parallel + tight timeout).
        """
        pairs = [
            (p.id, p.base_url)
            for p in PROVIDER_REGISTRY
            if p.base_url  # skip CLI-only / no-endpoint providers
        ]
        results = await probe_all(pairs, timeout=timeout)
        return {pid: h.to_dict() for pid, h in results.items()}

    async def probe_one(self, provider_id: str) -> dict[str, Any]:
        info = get_provider(provider_id)
        if info is None:
            return {"ok": False, "error": f"unknown provider '{provider_id}'"}
        h = await probe_provider(provider_id, info.base_url)
        return h.to_dict()

    def record_call(
        self,
        provider_id: str,
        model_id: str,
        *,
        ok: bool,
        latency_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error: str = "",
    ) -> None:
        record_call(
            provider_id,
            model_id,
            ok=ok,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
        )

    # ── Smart selection (combo + health aware) ───────────────────

    def select_with_fallback(
        self,
        task_type: str = "general",
        *,
        skip_unhealthy: bool = True,
    ) -> tuple[str, str, str]:
        """Return ``(provider_id, model_id, source)`` where *source*
        is one of ``"active" | "combo" | "ranking" | "auto"``.

        Resolution order:
        1. User's active provider+model (if healthy)
        2. Active combo walk — first healthy provider in the combo
        3. User's ranking list — first healthy provider
        4. :class:`AutoModelRouter.get_best_model` fallback
        """
        # 1. Active
        active_p = self.active_provider
        active_m = self.active_model
        if active_p:
            if not skip_unhealthy or self._is_healthy(active_p):
                info = get_provider(active_p)
                if info:
                    model = active_m
                    if not any(m.id == model for m in info.models):
                        model = info.default_model
                    return active_p, model, "active"

        # 2. Active combo
        active_combo = self.get_active_combo()
        if active_combo:
            combos = self.get_combos()
            for pid in combos.get(active_combo, []):
                if not skip_unhealthy or self._is_healthy(pid):
                    info = get_provider(pid)
                    if info:
                        return pid, info.default_model, "combo"

        # 3. Ranking
        for pid in self.get_ranking():
            if pid in self.get_enabled_providers():
                if not skip_unhealthy or self._is_healthy(pid):
                    info = get_provider(pid)
                    if info:
                        return pid, info.default_model, "ranking"

        # 4. Auto
        try:
            from app.core.model_router import AutoModelRouter

            pid, mid = AutoModelRouter.get_best_model(role=task_type)
            return pid, mid, "auto"
        except Exception:  # noqa: BLE001
            return "opencode_zen", "big-pickle", "auto"

    def _is_healthy(self, provider_id: str) -> bool:
        h = get_health(provider_id)
        if h is None:
            return True  # unknown → assume healthy; probe will catch it
        return h.ok

    def select_model(self, task_type: str = "general") -> tuple[str, str]:
        """Return the best ``(provider_id, model_id)`` for the task.

        Priority:
        1. User's explicitly selected active provider/model
        2. First enabled+available provider from the user's ranking
        3. Auto-detection (fallback through env vars, local, CLI)
        """
        provider = self.active_provider
        model = self.active_model

        provider_info = get_provider(provider)
        if provider_info:
            models = provider_info.models
            if not model or not any(m.id == model for m in models):
                model = provider_info.default_model
            return provider, model

        ranking = self.get_ranking()
        enabled = self.get_enabled_providers()
        for pid in ranking:
            if pid in enabled or not enabled:
                info = get_provider(pid)
                if info:
                    return pid, info.default_model

        return "opencode_zen", "big-pickle"

    def get_all_providers(self) -> list[dict[str, Any]]:
        """Return full provider list with status for dashboard API."""
        enabled = self.get_enabled_providers()
        ranking = self.get_ranking()
        result: list[dict[str, Any]] = []
        for p in PROVIDER_REGISTRY:
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "group": p.group,
                    "tier": p.tier.value,
                    "auth_type": p.auth_type.value,
                    "description": p.description,
                    "website": p.website,
                    "default_model": p.default_model,
                    "enabled": p.id in enabled,
                    "rank": ranking.index(p.id) + 1 if p.id in ranking else 999,
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
        result.sort(key=lambda x: (x["rank"], x["id"]))
        return result

    def get_models_list(self) -> list[dict[str, Any]]:
        """Return flattened list of all models across all providers."""
        enabled = self.get_enabled_providers()
        models: list[dict[str, Any]] = []
        for p in PROVIDER_REGISTRY:
            for m in p.models:
                models.append(
                    {
                        "provider_id": p.id,
                        "provider_name": p.name,
                        "model_id": m.id,
                        "model_name": m.name,
                        "context": m.context,
                        "tier": m.tier.value,
                        "quality": m.quality,
                        "enabled": p.id in enabled,
                        "active": (p.id == self.active_provider and m.id == self.active_model),
                    }
                )
        models.sort(key=lambda x: x["quality"], reverse=True)
        return models

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _default_workspace(self) -> str:
        for candidate in ("workspace", "data", "."):
            p = Path(candidate)
            if p.is_dir():
                return str(p.resolve())
        return os.getcwd()

    def _load(self) -> None:
        try:
            if self._prefs_path.exists():
                raw = self._prefs_path.read_text(encoding="utf-8")
                self._prefs = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load provider prefs from %s: %s", self._prefs_path, exc)
            self._prefs = {}

    def _save(self) -> None:
        try:
            self._prefs_path.parent.mkdir(parents=True, exist_ok=True)
            self._prefs_path.write_text(
                json.dumps(self._prefs, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save provider prefs to %s: %s", self._prefs_path, exc)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._prefs)
