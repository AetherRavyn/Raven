from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from app.provider.factory import create_provider
from app.settings.config import Config
from app.core.feedback import FeedbackStore


@dataclass(slots=True)
class RouteDecision:
    provider: Any
    model_name: str
    route_kind: str
    rationale: str


class ModelRouter:
    """Very small model router that prefers a local provider for cheap work."""

    def __init__(self, default_provider: Any, default_model: str) -> None:
        self.default_provider = default_provider
        self.default_model = default_model
        self._local_provider: Any | None = None
        self._local_health: bool | None = None
        self.feedback = FeedbackStore()

    def classify(self, text: str) -> str:
        lowered = text.lower().strip()
        if any(word in lowered for word in ("hello", "hi", "time", "status", "os")):
            return "local"
        if any(
            phrase in lowered
            for phrase in (
                "search",
                "summary",
                "summarize",
                "explain",
                "what is",
                "how do",
                "compare",
                "why",
            )
        ):
            return "cheap"
        return "deep"

    def _get_local_provider(self) -> Any | None:
        if self._local_provider is None and self._local_health is not False:
            try:
                from app.provider.manager import ProviderManager

                pm = ProviderManager()
                pm_provider, _ = pm.select_model()
                if pm_provider not in {"opencode_zen", "ollama"}:
                    self._local_health = False
                    return None
                self._local_provider = create_provider("ollama")
            except Exception:
                self._local_provider = None
        return self._local_provider

    async def _local_available(self) -> bool:
        if self._local_health is not None:
            return self._local_health

        provider = self._get_local_provider()
        if provider is None:
            self._local_health = False
            return False

        health = getattr(provider, "health", None)
        if not callable(health):
            self._local_health = False
            return False

        try:
            value = health()
            if inspect.isawaitable(value):
                value = await value
            self._local_health = bool(value)
        except Exception:
            self._local_health = False
        return self._local_health

    async def resolve(self, text: str) -> RouteDecision:
        route_kind = self.classify(text)
        route_bias = self.feedback.score("route", route_kind)
        if route_bias > 0.25:
            route_kind = "local" if route_kind != "deep" else route_kind

        # Only route cheap queries to a local provider when the
        # default provider is also local or free-tier.  If the
        # user has a premium API key configured (anthropic, openai,
        # google) or a free cloud gateway (opencode_zen), skip the
        # local shortcut — those providers are already reliable.
        _default_is_localish = self._default_is_free_or_local()

        if (
            route_kind in {"local", "cheap"}
            and _default_is_localish
            and await self._local_available()
        ):
            provider = self._get_local_provider() or self.default_provider
            model_name = getattr(provider, "_model", None) or Config.OLLAMA_MODEL
            return RouteDecision(
                provider=provider,
                model_name=model_name,
                route_kind=route_kind,
                rationale="local-first",
            )

        return RouteDecision(
            provider=self.default_provider,
            model_name=self.default_model,
            route_kind=route_kind,
            rationale="default",
        )

    def _default_is_free_or_local(self) -> bool:
        """Return True if the default provider is local/free, meaning
        the local Ollama shortcut still makes sense as a cost-saver."""
        from app.provider.manager import ProviderManager

        try:
            pm = ProviderManager()
            pm_provider, _ = pm.select_model()
        except Exception:
            pm_provider = "opencode_zen"
        _free_or_local = {
            "opencode_zen",
            "ollama",
            "lm_studio",
            "localai",
            "vllm",
        }
        return pm_provider in _free_or_local

    def record_feedback(self, route_kind: str, reward: float, reason: str = "") -> None:
        try:
            self.feedback.add_feedback(
                user_id="system",
                item_type="route",
                item_id=route_kind,
                reward=reward,
                reason=reason,
            )
        except Exception:
            pass


class AutoModelRouter:
    """Dynamically routes to the best available model based on environment configuration."""

    @classmethod
    def default_model_for_provider(cls, provider_name: str) -> str:
        normalized = (provider_name or "").strip().lower()
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "google": "gemini-1.5-pro",
            "openrouter": "anthropic/claude-3.5-sonnet",
            "nvidia": "meta/llama3-70b-instruct",
            "huggingface": "meta-llama/Meta-Llama-3-70B-Instruct",
            "bytez": "meta-llama/Meta-Llama-3-70B-Instruct",
            "ollama": Config.OLLAMA_MODEL,
            "opencode_zen": Config.OPENCODE_ZEN_MODEL,
        }
        return defaults.get(normalized, "")

    @classmethod
    def _configured_override(cls) -> tuple[str, str] | None:
        provider = (getattr(Config, "LLM_PROVIDER", "") or "").strip().lower()
        if provider in {"", "auto", "default"}:
            return None
        model = (getattr(Config, "LLM_MODEL", "") or "").strip()
        return provider, model or cls.default_model_for_provider(provider)

    @classmethod
    def _check_local_endpoint(cls, url: str) -> bool:
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as response:
                return response.status == 200
        except (urllib.error.URLError, Exception):
            return False

    @classmethod
    def get_best_model(cls, role: str = "general") -> tuple[str, str]:
        from app.settings.config import Config

        # 0a. ProviderManager combo — if the user picked a combo,
        #     trust it first (it's the 9router-style named fallback).
        try:
            from app.provider.manager import ProviderManager

            manager = ProviderManager()
            pid, mid, _source = manager.select_with_fallback(task_type=role)
            # If the combo / ranking picked something real, return it.
            # We do not skip when source == "auto" — fall through to
            # the legacy logic below for legacy defaults.
            if pid and mid and _source in {"active", "combo", "ranking"}:
                return pid, mid
        except Exception:
            pass

        override = cls._configured_override()
        if override:
            return override

        # 1. High-tier APIs — try what the user paid for first.
        # Skip keys that are clearly test/placeholder values.
        _skip_keys = {"", "sk-dashboard-paste-test", "no-key-needed", "none", "undefined"}
        if getattr(Config, "ANTHROPIC_API_KEY", None) and Config.ANTHROPIC_API_KEY not in _skip_keys:
            return "anthropic", "claude-3-5-sonnet-20241022"
        if getattr(Config, "OPENAI_API_KEY", None) and Config.OPENAI_API_KEY not in _skip_keys:
            return "openai", "gpt-4o"
        if getattr(Config, "GOOGLE_API_KEY", None) and Config.GOOGLE_API_KEY not in _skip_keys:
            return "google", "gemini-1.5-pro"
        if getattr(Config, "GEMINI_API_KEY", None) and Config.GEMINI_API_KEY not in _skip_keys:
            return "google", "gemini-1.5-pro"

        # 2. OpenCode Zen — free cloud gateway, always available, no key needed.
        # Comes BEFORE local Ollama because local is unreliable (crashes, model
        # not loaded, etc).  OpenCode Zen's 5 free models are always reachable.
        return "opencode_zen", Config.OPENCODE_ZEN_MODEL

    @classmethod
    def get_available_models(cls, role: str = "general") -> list[tuple[str, str]]:
        from app.settings.config import Config

        override = cls._configured_override()
        if override:
            return [override]

        available = []

        # 1. High-tier APIs — try what user paid for first
        if getattr(Config, "ANTHROPIC_API_KEY", None):
            available.append(("anthropic", "claude-3-5-sonnet-20241022"))
        if getattr(Config, "OPENAI_API_KEY", None):
            available.append(("openai", "gpt-4o"))
        if getattr(Config, "GOOGLE_API_KEY", None) or getattr(Config, "GEMINI_API_KEY", None):
            available.append(("google", "gemini-1.5-pro"))

        # 2. Aggregator APIs
        if getattr(Config, "OPENROUTER_API_KEY", None):
            available.append(("openrouter", "anthropic/claude-3.5-sonnet"))
        if getattr(Config, "NVIDIA_NIM_API_KEY", None):
            available.append(("nvidia", "meta/llama3-70b-instruct"))
        if getattr(Config, "HUGGINGFACE_API_KEY", None):
            available.append(("huggingface", "meta-llama/Meta-Llama-3-70B-Instruct"))
        if getattr(Config, "BYTEZ_API_KEY", None):
            available.append(("bytez", "meta-llama/Meta-Llama-3-70B-Instruct"))

        # 3. OpenCode Zen — free cloud gateway, always available
        available.append(("opencode_zen", Config.OPENCODE_ZEN_MODEL))

        # 4. Local endpoints (last resort — unreliable when Ollama crashes)
        if cls._check_local_endpoint(f"{Config.VLLM_BASE_URL}/models"):
            available.append(("vllm", "local-model"))
        if cls._check_local_endpoint(f"{Config.LM_STUDIO_BASE_URL}/models"):
            available.append(("lm_studio", "local-model"))
        if cls._check_local_endpoint(f"{Config.LOCALAI_BASE_URL}/models"):
            available.append(("localai", "local-model"))
        if cls._check_local_endpoint(f"{Config.OLLAMA_BASE_URL}/api/tags"):
            available.append(("ollama", Config.OLLAMA_MODEL))

        return available
