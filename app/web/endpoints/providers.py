"""Providers dashboard endpoint — v37 (2026-06-23).

Lets the operator paste API keys for every LLM provider RAVEN
supports (OpenAI, Anthropic, Google, Groq, xAI, OpenRouter,
NVIDIA NIM, HuggingFace, Bytez, Deepgram, ElevenLabs, etc.)
and have the agent swarm use them via HTTP API immediately.

With this endpoint, the user pastes their key for *any*
provider on the ``/page/providers`` form, the key is written
to ``Config`` and ``os.environ`` (so child processes see it),
and :meth:`AutoModelRouter.get_best_model` re-evaluates on
the next swarm dispatch — picking the new key first.

When no API key is configured, RAVEN falls back to OpenCode Zen
(opencode.ai/zen/v1) which provides 5 free models with no key needed.

What this endpoint is NOT:
  - It does mask the key in the response. Only
    ``status`` (``"set"`` vs ``"unset"``) is returned, never
    the key itself.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Mapping, Tuple

logger = logging.getLogger(__name__)


# Catalog of every provider RAVEN knows about.  Each entry is
# (Config attr, env-var name, label, group, kind, help text).
#
# ``group`` buckets the form for the operator:
#   - "cloud"  → paid hosted APIs (OpenAI, Anthropic, etc.)
#   - "router" → multi-provider aggregators (OpenRouter, Killo, etc.)
#   - "local"  → self-hosted endpoints (Ollama, LM Studio, etc.)
#   - "voice"  → STT/TTS providers (Deepgram, ElevenLabs, etc.)
#   - "search" → web / data search APIs
#   - "other"  → everything else
#
# ``kind`` is one of "key" (secret, masked input) or "url"
# (plain URL, e.g. OLLAMA_BASE_URL).
PROVIDERS: list[tuple[str, str, str, str, str, str]] = [
    # ── cloud LLM providers ─────────────────────────────────────
    (
        "OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "OpenAI",
        "cloud",
        "key",
        "gpt-4o, gpt-4-turbo, o1-preview — used when LLM_PROVIDER=openai",
    ),
    (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "Anthropic",
        "cloud",
        "key",
        "claude-3-5-sonnet, claude-3-opus — used when LLM_PROVIDER=anthropic",
    ),
    (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY",
        "Google Gemini",
        "cloud",
        "key",
        "gemini-1.5-pro, gemini-2.0-flash — used when LLM_PROVIDER=google",
    ),
    (
        "XAI_API_KEY",
        "XAI_API_KEY",
        "xAI (Grok)",
        "cloud",
        "key",
        "grok-2, grok-2-vision — used when LLM_PROVIDER=xai",
    ),
    (
        "GROQ_API_KEY",
        "GROQ_API_KEY",
        "Groq",
        "cloud",
        "key",
        "Fast inference (llama-3.1-70b, mixtral)",
    ),
    # ── multi-provider routers ─────────────────────────────────
    (
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        "OpenRouter",
        "router",
        "key",
        "Any model via one key — used by AutoRouter",
    ),
    (
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA NIM",
        "router",
        "key",
        "Nemotron, Llama-3.1-NIM, etc. — free tier available",
    ),
    (
        "HUGGINGFACE_API_KEY",
        "HUGGINGFACE_API_KEY",
        "HuggingFace",
        "router",
        "key",
        "Inference API for any HF model",
    ),
    ("BYTEZ_API_KEY", "BYTEZ_API_KEY", "Bytez", "router", "key", "Multi-model gateway"),
    (
        "OPENCODE_ZEN_API_KEY",
        "OPENCODE_ZEN_API_KEY",
        "OpenCode Zen (Free)",
        "router",
        "key",
        "opencode.ai/zen/v1 — 5 free models: Big Pickle, DeepSeek V4 Flash, MiMo V2.5, Qwen 3.6 Plus, Nemotron 3 Super",
    ),
    # ── self-hosted local LLM endpoints ────────────────────────
    (
        "OLLAMA_BASE_URL",
        "OLLAMA_BASE_URL",
        "Ollama (local)",
        "local",
        "url",
        "Base URL of your local Ollama server (http://localhost:11434)",
    ),
    (
        "LM_STUDIO_BASE_URL",
        "LM_STUDIO_BASE_URL",
        "LM Studio (local)",
        "local",
        "url",
        "OpenAI-compatible LM Studio endpoint (http://localhost:1234/v1)",
    ),
    (
        "LOCALAI_BASE_URL",
        "LOCALAI_BASE_URL",
        "LocalAI (local)",
        "local",
        "url",
        "LocalAI endpoint (http://localhost:8080/v1)",
    ),
    (
        "VLLM_BASE_URL",
        "VLLM_BASE_URL",
        "vLLM (local)",
        "local",
        "url",
        "vLLM OpenAI-compatible endpoint (http://localhost:8000/v1)",
    ),
    # ── voice / TTS / STT ──────────────────────────────────────
    (
        "DEEPGRAM_API_KEY",
        "DEEPGRAM_API_KEY",
        "Deepgram (STT)",
        "voice",
        "key",
        "Cloud STT — used as a fallback by transcribe.py",
    ),
    (
        "API_KEY_SPEECHMATE",
        "API_KEY_SPEECHMATE",
        "Speechmatics (TTS)",
        "voice",
        "key",
        "Cloud TTS — alternative to Piper (autherRaven)",
    ),
    # ── search / data ──────────────────────────────────────────
    (
        "OPENWEATHERMAP_API_KEY",
        "OPENWEATHERMAP_API_KEY",
        "OpenWeatherMap",
        "search",
        "key",
        "Used by the weather tool",
    ),
    (
        "WOLFRAM_ALPHA_APP_ID",
        "WOLFRAM_ALPHA_APP_ID",
        "Wolfram Alpha",
        "search",
        "key",
        "Computational knowledge engine",
    ),
    (
        "VIRUSTOTAL_API_KEY",
        "VIRUSTOTAL_API_KEY",
        "VirusTotal",
        "search",
        "key",
        "URL / file scanning",
    ),
    (
        "SEARXNG_URL",
        "SEARXNG_URL",
        "SearXNG (self-hosted)",
        "search",
        "url",
        "Self-hosted private metasearch engine",
    ),
    # ── other ──────────────────────────────────────────────────
    ("NOTION_API_KEY", "NOTION_API_KEY", "Notion", "other", "key", "Notion workspace integration"),
    (
        "SLACK_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "Slack Bot Token",
        "other",
        "key",
        "xoxb-… bot token for Slack channel",
    ),
    (
        "SLACK_APP_TOKEN",
        "SLACK_APP_TOKEN",
        "Slack App Token",
        "other",
        "key",
        "xapp-… socket-mode app token",
    ),
    (
        "DISCORD_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
        "Discord Bot Token",
        "other",
        "key",
        "Discord channel bot token",
    ),
    (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "Telegram Bot Token",
        "other",
        "key",
        "Telegram bot token from @BotFather",
    ),
]


def _status_for(value: Any) -> str:
    """Return ``"set"`` if the value is non-empty, else ``"unset"``."""
    if value is None:
        return "unset"
    if isinstance(value, str) and not value.strip():
        return "unset"
    return "set"


class ProvidersRouter:
    """Dispatch table for the Providers dashboard.

    Routes
    ------
    ``GET  /providers/list``     — return every provider's
        current ``status`` (``set``/``unset``) plus the
        :class:`app.core.model_router.AutoModelRouter` pick
        so the UI can show "currently routing via X".
    ``POST /providers/keys``     — apply a set of key/url
        updates to the in-memory overlay and persist them
        to ``.env`` so they survive restarts.
    ``POST /providers/clear``    — drop a specific key (or
        every key) from the overlay and ``.env`` file.
    """

    def __init__(self) -> None:
        self._routes: Dict[str, Callable[..., Dict[str, Any]]] = {
            "GET /providers/list": self.list_providers,
            "POST /providers/keys": self.update_keys,
            "POST /providers/clear": self.clear_keys,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., Dict[str, Any]]]:
        return dict(self._routes)

    # ── Handlers ───────────────────────────────────────────────

    def list_providers(self) -> Dict[str, Any]:
        """Return every provider's current set/unset status.

        Never returns the key itself — only ``status`` and a
        short ``preview`` (first 4 + last 2 chars) so the
        operator can sanity-check which key is loaded.
        """
        from app.settings.config import Config

        groups: Dict[str, list[Dict[str, Any]]] = {}
        for attr, env, label, group, kind, help_text in PROVIDERS:
            value = getattr(Config, attr, None) or os.environ.get(env)
            status = _status_for(value)
            preview = ""
            if status == "set" and isinstance(value, str) and len(value) > 8:
                preview = value[:4] + "…" + value[-2:]
            elif status == "set":
                preview = "(set)"
            entry: Dict[str, Any] = {
                "attr": attr,
                "env": env,
                "label": label,
                "group": group,
                "kind": kind,
                "status": status,
                "preview": preview,
                "help": help_text,
            }
            groups.setdefault(group, []).append(entry)

        # Surface the auto-router's current pick so the UI can
        # show "currently routing through X".
        auto_pick: Dict[str, Any] = {}
        try:
            from app.core.model_router import AutoModelRouter

            pick = AutoModelRouter.get_best_model()
            # AutoModelRouter.get_best_model returns a
            # ``(provider, model)`` tuple, not a dataclass.
            if isinstance(pick, tuple) and len(pick) == 2:
                provider_name, model_name = pick
            else:
                provider_name = getattr(pick, "provider_name", "")
                model_name = getattr(pick, "model_name", "")
            auto_pick = {
                "available": True,
                "provider": provider_name or "",
                "model": model_name or "",
            }
        except Exception as exc:  # noqa: BLE001
            auto_pick = {"available": False, "error": str(exc)[:120]}

        return {
            "ok": True,
            "providers": groups,
            "auto_pick": auto_pick,
            "count": sum(len(v) for v in groups.values()),
        }

    def update_keys(self, **kwargs: Any) -> Dict[str, Any]:
        """Apply a set of key/url updates and persist to .env.

        ``kwargs`` is the parsed form body — keys are
        :data:`PROVIDERS` env-var names (``"OPENAI_API_KEY"``
        etc.).  Unknown keys are rejected with
        ``ok=False, error="unknown_field"`` so a typo doesn't
        silently no-op.
        """
        from app.settings.config import Config

        known: Dict[str, Tuple[str, str, str, str, str]] = {
            env: (attr, label, group, kind, help_text)
            for attr, env, label, group, kind, help_text in PROVIDERS
        }
        applied: list[Dict[str, Any]] = []
        errors: list[Dict[str, str]] = []
        for env_name, raw in kwargs.items():
            if env_name not in known:
                errors.append({"field": env_name, "error": "unknown_field"})
                continue
            attr, label, _group, _kind, _help = known[env_name]
            value = "" if raw is None else str(raw)
            if not value.strip():
                if hasattr(Config, attr):
                    setattr(Config, attr, None)
                os.environ.pop(env_name, None)
                applied.append({"field": env_name, "value": "", "cleared": True})
                logger.info("providers_editor: cleared %s", env_name)
                continue
            setattr(Config, attr, value)
            os.environ[env_name] = value
            applied.append({"field": env_name, "value": "•" * min(8, len(value))})
            logger.info(
                "providers_editor: %s = %s (via dashboard)",
                env_name,
                value[:4] + "…" + value[-2:] if len(value) > 8 else value,
            )
        self._persist_to_env_file()
        return {
            "ok": len(errors) == 0,
            "applied": applied,
            "errors": errors,
            "count": len(applied),
        }

    def clear_keys(self, **kwargs: Any) -> Dict[str, Any]:
        """Drop a specific key (or every key) from the overlay and .env file.

        ``field`` form value names the env-var to clear.
        ``field="__all__"`` clears every provider.
        """
        from app.settings.config import Config

        field = (kwargs.get("field") or "").strip()
        cleared: list[str] = []
        for attr, env, _label, _group, _kind, _help in PROVIDERS:
            if field not in ("", "__all__", env):
                continue
            if hasattr(Config, attr):
                setattr(Config, attr, None)
            os.environ.pop(env, None)
            cleared.append(env)
        self._persist_to_env_file()
        return {"ok": True, "cleared": cleared, "count": len(cleared)}

    # ── .env persistence ────────────────────────────────────────

    def _persist_to_env_file(self) -> None:
        """Write current provider key/URL values from os.environ to the .env file.

        Reads the existing .env, updates matching keys, and writes back.
        Non-provider lines are preserved unchanged.
        """
        from pathlib import Path

        env_path = Path(".env")
        known_env_names = {env for _, env, _, _, _, _ in PROVIDERS}

        existing_lines: list[str] = []
        existing_keys: set[str] = set()
        if env_path.exists():
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()
            for line in existing_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    existing_keys.add(key)

        new_lines: list[str] = []
        seen: set[str] = set()
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in known_env_names:
                    val = os.environ.get(key, "")
                    new_lines.append(f"{key}={val}")
                    seen.add(key)
                    continue
            new_lines.append(line)

        for env_name in sorted(known_env_names):
            if env_name not in seen:
                val = os.environ.get(env_name, "")
                if val:
                    new_lines.append(f"{env_name}={val}")
                    seen.add(env_name)

        new_content = "\n".join(new_lines).strip() + "\n"
        try:
            env_path.write_text(new_content, encoding="utf-8")
            logger.info("providers_editor: persisted %d keys to .env", len(seen))
        except OSError as exc:
            logger.warning("providers_editor: failed to write .env: %s", exc)

    # ── Dispatch ────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> Dict[str, Any]:
        """Look up *route* in the table and call the handler with
        the form kwargs.  Mirrors the pattern in
        :mod:`app.web.endpoints.cron`."""
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("providers route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


# Module-level singleton — the same pattern as
# :mod:`app.web.endpoints.config_editor` and the orchestrator.
_ROUTER_SINGLETON: ProvidersRouter | None = None


def get_providers_router() -> ProvidersRouter:
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        _ROUTER_SINGLETON = ProvidersRouter()
    return _ROUTER_SINGLETON


def reset_providers_router_for_tests() -> None:
    global _ROUTER_SINGLETON
    _ROUTER_SINGLETON = None
