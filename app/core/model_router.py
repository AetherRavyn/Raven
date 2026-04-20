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

        if route_kind in {"local", "cheap"} and await self._local_available():
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
            "opencode": Config.OPENCODE_MODEL,
            "qwen_cli": Config.QWEN_CLI_MODEL,
            "gemini_cli": Config.GEMINI_CLI_MODEL,
            "kilocode": Config.KILOCODE_MODEL,
            "killo": "qwen/qwen3-coder:free",
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
            # Quick check to see if the local service is up
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=0.1) as response:
                return response.status == 200
        except (urllib.error.URLError, Exception):
            return False

    @classmethod
    def get_best_model(cls, role: str = "general") -> tuple[str, str]:
        import shutil
        from app.settings.config import Config

        override = cls._configured_override()
        if override:
            return override

        # 0. Check fast local services
        if cls._check_local_endpoint(f"{Config.VLLM_BASE_URL}/models"):
            return "vllm", "local-model"
        if cls._check_local_endpoint(f"{Config.LM_STUDIO_BASE_URL}/models"):
            return "lm_studio", "local-model"
        if cls._check_local_endpoint(f"{Config.LOCALAI_BASE_URL}/models"):
            return "localai", "local-model"
        if cls._check_local_endpoint(f"{Config.OLLAMA_BASE_URL}/api/tags"):
            return "ollama", Config.OLLAMA_MODEL

        # 1. High-tier APIs
        if getattr(Config, "ANTHROPIC_API_KEY", None):
            return "anthropic", "claude-3-5-sonnet-20241022"
        if getattr(Config, "OPENAI_API_KEY", None):
            return "openai", "gpt-4o"
        if getattr(Config, "GOOGLE_API_KEY", None) or getattr(
            Config, "GEMINI_API_KEY", None
        ):
            return "google", "gemini-1.5-pro"

        # 2. Aggregator APIs
        if getattr(Config, "OPENROUTER_API_KEY", None):
            return "openrouter", "anthropic/claude-3.5-sonnet"
        if getattr(Config, "NVIDIA_NIM_API_KEY", None):
            return "nvidia", "meta/llama3-70b-instruct"
        if getattr(Config, "HUGGINGFACE_API_KEY", None):
            return "huggingface", "meta-llama/Meta-Llama-3-70B-Instruct"
        if getattr(Config, "BYTEZ_API_KEY", None):
            return "bytez", "meta-llama/Meta-Llama-3-70B-Instruct"

        # 3. Local CLI Proxies
        cli_tools = [
            ("opencode", "opencode", Config.OPENCODE_MODEL),
            ("qwen", "qwen_cli", Config.QWEN_CLI_MODEL),
            ("gemini", "gemini_cli", Config.GEMINI_CLI_MODEL),
            ("kilocode", "kilocode", Config.KILOCODE_MODEL),
            ("gh", "cli_proxy", "cli/gh-copilot"),
            ("jules", "jules", ""),
            ("claude", "claude_cli", ""),
        ]

        for tool_cmd, provider_name, model_name in cli_tools:
            if shutil.which(tool_cmd):
                return provider_name, model_name

        # 4. Free fallback
        return "killo", "qwen/qwen3-coder:free"

    @classmethod
    def get_available_models(cls, role: str = "general") -> list[tuple[str, str]]:
        import shutil
        from app.settings.config import Config

        override = cls._configured_override()
        if override:
            return [override]

        available = []

        # 0. Check fast local services
        if cls._check_local_endpoint(f"{Config.VLLM_BASE_URL}/models"):
            available.append(("vllm", "local-model"))
        if cls._check_local_endpoint(f"{Config.LM_STUDIO_BASE_URL}/models"):
            available.append(("lm_studio", "local-model"))
        if cls._check_local_endpoint(f"{Config.LOCALAI_BASE_URL}/models"):
            available.append(("localai", "local-model"))
        if cls._check_local_endpoint(f"{Config.OLLAMA_BASE_URL}/api/tags"):
            available.append(("ollama", Config.OLLAMA_MODEL))

        # 1. High-tier APIs
        if getattr(Config, "ANTHROPIC_API_KEY", None):
            available.append(("anthropic", "claude-3-5-sonnet-20241022"))
        if getattr(Config, "OPENAI_API_KEY", None):
            available.append(("openai", "gpt-4o"))
        if getattr(Config, "GOOGLE_API_KEY", None) or getattr(
            Config, "GEMINI_API_KEY", None
        ):
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

        # 3. Local CLI providers. Prefer direct provider CLIs before the Killo free fallback.
        cli_tools = [
            ("opencode", "opencode", Config.OPENCODE_MODEL),
            ("qwen", "qwen_cli", Config.QWEN_CLI_MODEL),
            ("gemini", "gemini_cli", Config.GEMINI_CLI_MODEL),
            ("kilocode", "kilocode", Config.KILOCODE_MODEL),
            ("gh", "cli_proxy", "cli/gh-copilot"),
            ("jules", "jules", ""),
            ("claude", "claude_cli", ""),
        ]

        for tool_cmd, provider_name, model_name in cli_tools:
            if shutil.which(tool_cmd):
                available.append((provider_name, model_name))

        # 4. Free fallback after direct providers.
        available.append(("killo", "qwen/qwen3-coder:free"))

        return available
