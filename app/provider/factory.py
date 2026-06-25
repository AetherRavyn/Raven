from __future__ import annotations

from typing import Any

from app.provider.anthropic import AnthropicProviderClient
from app.provider.base import BaseLLMProvider
from app.provider.google import GoogleProviderClient
from app.provider.openai import OpenAIProviderClient
from app.provider.xai import XAIGrpcClient


def create_provider(name: str, **kwargs: Any) -> BaseLLMProvider | Any:
    normalized = (name or "").strip().lower()
    if normalized in {"openai"}:
        return OpenAIProviderClient(**kwargs)
    if normalized in {"anthropic", "claude"}:
        return AnthropicProviderClient(**kwargs)
    if normalized in {"google", "gemini"}:
        return GoogleProviderClient(**kwargs)
    if normalized in {"opencode_zen", "opencodezen"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.OPENCODE_ZEN_BASE_URL)
        kwargs.pop("api_key", None)
        return OpenAIProviderClient(api_key="", base_url=base_url, **kwargs)
    if normalized in {"xai", "grok", "xai_grpc"}:
        return XAIGrpcClient(**kwargs)
    if normalized in {"ollama"}:
        from app.providers.ollama.client import OllamaProvider  # noqa: PLC0415
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.OLLAMA_BASE_URL)
        model = kwargs.pop("model", Config.OLLAMA_MODEL)
        return OllamaProvider(base_url, model)
    if normalized in {"openrouter"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", "https://openrouter.ai/api/v1")
        api_key = kwargs.pop("api_key", Config.OPENROUTER_API_KEY)
        return OpenAIProviderClient(api_key=api_key, base_url=base_url, **kwargs)
    if normalized in {"nvidia"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", "https://integrate.api.nvidia.com/v1")
        api_key = kwargs.pop("api_key", Config.NVIDIA_NIM_API_KEY)
        return OpenAIProviderClient(api_key=api_key, base_url=base_url, **kwargs)
    if normalized in {"huggingface"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", "https://api-inference.huggingface.co/v1")
        api_key = kwargs.pop("api_key", Config.HUGGINGFACE_API_KEY)
        return OpenAIProviderClient(api_key=api_key, base_url=base_url, **kwargs)
    if normalized in {"bytez"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", "https://api.bytez.com/v1")
        api_key = kwargs.pop("api_key", Config.BYTEZ_API_KEY)
        return OpenAIProviderClient(api_key=api_key, base_url=base_url, **kwargs)
    if normalized in {"lm_studio"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.LM_STUDIO_BASE_URL)
        return OpenAIProviderClient(api_key="lm-studio", base_url=base_url, **kwargs)
    if normalized in {"localai"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.LOCALAI_BASE_URL)
        return OpenAIProviderClient(api_key="localai", base_url=base_url, **kwargs)
    if normalized in {"vllm"}:
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.VLLM_BASE_URL)
        return OpenAIProviderClient(api_key="vllm", base_url=base_url, **kwargs)
    raise ValueError(
        f"Unsupported provider '{name}'. Supported: openai, anthropic, google, opencode_zen, xai, ollama, openrouter, nvidia, huggingface, bytez, lm_studio, localai, vllm."
    )
