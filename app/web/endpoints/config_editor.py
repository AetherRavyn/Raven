"""Config-editor endpoint — v34 (2026-06-21).

Lets the operator set RAVEN env vars from the dashboard's
``/page/models`` form.  Two operations:

* ``GET  /config/show`` — return the *current* effective value
  for every editable field, plus the original ``.env``-file
  value (so the UI can show "shadowed" rows when the in-memory
  overlay diverges from disk).
* ``POST /config/update`` — write one or more fields to the
  in-memory overlay (mutates :class:`app.settings.config.Config`
  class attributes, just like the autouse
  :func:`isolated_singleton` test fixture does).  The overlay
  is *process-local*: the change is not persisted across
  restarts.

Why a process-local overlay, not a ``.env`` write:
the dashboard's editor is a *what-if* tool, not a deployment
system.  Writing to ``.env`` would risk leaving the user with
a half-written file on a bot crash.  The overlay lets them
flip a setting, see the result, and restart to keep it.  The
existing :file:`.env.example` documents the canonical value.

The router is framework-agnostic: returns plain dicts so the
FastAPI adapter in :mod:`app.web.server` translates them.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)


# Fields the operator is allowed to edit from the dashboard.
# Each entry: (Config attr, env-var name, kind, help text).
# ``kind`` is one of:
#   - "bool"   → parsed via {"1","true","yes","on"}
#   - "int"    → int(...)
#   - "float"  → float(...)
#   - "str"    → as-is
#   - "path"   → as-is, but the editor shows whether the file
#               exists on disk (for PIPER_VOICE_MODEL, etc.)
EDITABLE: list[tuple[str, str, str, str]] = [
    # ── LLM provider + model ─────────────────────────────────────
    ("LLM_PROVIDER", "LLM_PROVIDER", "str",
     "Active LLM provider: ollama, openai, anthropic, helix"),
    ("LLM_MODEL", "LLM_MODEL", "str",
     "Model name passed to the provider (e.g. gpt-4o, gemma:7b)"),
    ("LOCAL_LIGHT_MODEL", "LOCAL_LIGHT_MODEL", "str",
     "Fast 'System 1' model for short replies"),
    ("CLOUD_HEAVY_MODEL", "CLOUD_HEAVY_MODEL", "str",
     "Slow 'System 2' model for deep reasoning"),
    # ── Voice STT (whisper.cpp) ──────────────────────────────────
    ("WHISPER_CPP_MODEL", "WHISPER_CPP_MODEL", "path",
     "Path to ggml-tiny.bin (download with scripts/download-whisper-model.sh)"),
    ("WHISPER_CPP_LANGUAGE", "WHISPER_CPP_LANGUAGE", "str",
     "Whisper language code (en, es, fr, ...)"),
    ("WHISPER_CPP_THREADS", "WHISPER_CPP_THREADS", "int",
     "CPU threads for whisper.cpp (default 2)"),
    ("WHISPER_CPP_OFFLINE", "WHISPER_CPP_OFFLINE", "bool",
     "true → fail fast if model is missing (no auto-download)"),
    # ── TTS (Piper) ─────────────────────────────────────────────
    ("PIPER_VOICE_MODEL", "PIPER_VOICE_MODEL", "path",
     "Path to the Piper .onnx voice model (autherRaven by default)"),
    ("PIPER_VOICE_NAME", "PIPER_VOICE_NAME", "str",
     "Human-readable voice name shown in the chat header"),
    # ── Voice output ────────────────────────────────────────────
    ("ENABLE_LOCAL_VOICE", "ENABLE_LOCAL_VOICE", "bool",
     "true → on-device mic + speaker pipeline (pipeline.py)"),
    ("ENABLE_BROWSER_VOICE", "ENABLE_BROWSER_VOICE", "bool",
     "true → browser MediaRecorder + WS /voice/{user_id}"),
    ("VOICE_REPLY_WITH_AUDIO", "VOICE_REPLY_WITH_AUDIO", "bool",
     "true → every chat reply gets a TTS audio frame"),
    # ── Dashboard / network ─────────────────────────────────────
    ("WEB_DASHBOARD_ENABLED", "WEB_DASHBOARD_ENABLED", "bool",
     "true → /page/chat etc. available"),
    ("WEB_DASHBOARD_PORT", "WEB_DASHBOARD_PORT", "int",
     "Port the dashboard binds (default 8090)"),
    ("DASHBOARD_PORT", "DASHBOARD_PORT", "int",
     "Legacy / alternate dashboard port (default 8765)"),
    # ── Memory / knowledge graph ────────────────────────────────
    ("MEMORY_BACKEND", "MEMORY_BACKEND", "str",
     "helix (default) — vector/graph store"),
    ("KG_BACKEND", "KG_BACKEND", "str",
     "helix (default) — knowledge graph backend"),
    ("MEMORY_EMBEDDING_MODEL", "MEMORY_EMBEDDING_MODEL", "str",
     "HuggingFace sentence-transformer model name"),
]


def _coerce(attr: str, kind: str, raw: str) -> Any:
    """Coerce a form value to the right Python type.

    Booleans accept the standard truthy set; integers and
    floats use plain ``int()``/``float()``; strings and paths
    pass through.  Raises :class:`ValueError` on a malformed
    value so the API returns 400.
    """
    if kind == "bool":
        return str(raw).lower() in {"1", "true", "yes", "on"}
    if kind == "int":
        return int(str(raw).strip())
    if kind == "float":
        return float(str(raw).strip())
    return str(raw)


class ConfigEditorRouter:
    """Dispatch table for the config-editor surface.

    Mirrors the pattern in :mod:`app.web.endpoints.cron` so the
    FastAPI adapter in :mod:`app.web.server` can call
    ``router.dispatch("POST /config/update", key=value, ...)``.
    """

    def __init__(self) -> None:
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /config/show": self.show,
            "POST /config/update": self.update,
            "POST /config/reset": self.reset_overlay,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ────────────────────────────────────────────────

    def show(self) -> dict[str, Any]:
        """Return the current effective + env values for every
        editable field.

        ``effective`` is what :class:`app.settings.config.Config`
        returns *right now* (which may be a process-local
        overlay set via :meth:`update`).  ``env`` is the value
        the running process saw in its environment at boot —
        if ``effective`` differs from ``env`` the UI should
        show "(overridden)" so the operator knows the change
        is process-local.
        """
        from app.settings.config import Config

        fields: list[dict[str, Any]] = []
        for attr, env_name, kind, help_text in EDITABLE:
            current = getattr(Config, attr, None)
            env_raw = os.environ.get(env_name)
            if env_raw is None:
                env_disp = None
            else:
                env_disp = env_raw
            entry: dict[str, Any] = {
                "attr": attr,
                "env": env_name,
                "kind": kind,
                "value": current,
                "env_value": env_disp,
                "help": help_text,
                "overridden": env_disp is not None and str(current) != env_disp,
            }
            if kind == "path":
                entry["path_exists"] = bool(
                    current and os.path.exists(str(current))
                )
            fields.append(entry)
        return {"ok": True, "fields": fields, "count": len(fields)}

    def update(self, **kwargs: Any) -> dict[str, Any]:
        """Apply a set of field updates to the in-memory overlay.

        ``kwargs`` is the parsed form body — keys are
        :data:`EDITABLE` attr names (e.g. ``"LLM_PROVIDER"``).
        Unknown keys are rejected with ``ok=False, error=
        "unknown_field"`` so a typo doesn't silently no-op.
        """
        from app.settings.config import Config

        editable = {attr: (env, kind, help_text) for attr, env, kind, help_text in EDITABLE}
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for key, raw in kwargs.items():
            if key not in editable:
                errors.append({"field": key, "error": "unknown_field"})
                continue
            env_name, kind, _help = editable[key]
            try:
                coerced = _coerce(key, kind, raw)
            except (ValueError, TypeError) as exc:
                errors.append({"field": key, "error": f"bad_value: {exc}"})
                continue
            setattr(Config, key, coerced)
            # Also write to os.environ so child processes
            # spawned *after* the overlay (e.g. the KG tool,
            # the TTS engine) see the new value.
            os.environ[env_name] = str(coerced)
            applied.append({"field": key, "value": coerced})
            logger.info(
                "config_editor: %s = %r (via dashboard)", key, coerced,
            )
        return {
            "ok": len(errors) == 0,
            "applied": applied,
            "errors": errors,
            "count": len(applied),
        }

    def reset_overlay(self) -> dict[str, Any]:
        """Drop every overlay so the process reverts to the
        env-var value.  Useful when an operator wants to undo
        a series of in-memory tweaks without restarting."""
        from app.settings.config import Config

        restored: list[str] = []
        for attr, env_name, _kind, _help in EDITABLE:
            env_raw = os.environ.get(env_name)
            if env_raw is None:
                continue
            try:
                # Re-coerce from the original env value.
                coerced = _coerce(attr, _kind, env_raw)
            except (ValueError, TypeError):
                continue
            setattr(Config, attr, coerced)
            restored.append(attr)
        return {"ok": True, "restored": restored, "count": len(restored)}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        """Look up *route* in the table and call the handler with
        the form kwargs.  Mirrors the pattern in
        :mod:`app.web.endpoints.cron`."""
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("config_editor route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


# Module-level singleton — the same pattern as
# :mod:`app.web.endpoints.cron` and the orchestrator.
_ROUTER_SINGLETON: ConfigEditorRouter | None = None


def get_config_editor_router() -> ConfigEditorRouter:
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        _ROUTER_SINGLETON = ConfigEditorRouter()
    return _ROUTER_SINGLETON


def reset_config_editor_router_for_tests() -> None:
    global _ROUTER_SINGLETON
    _ROUTER_SINGLETON = None
