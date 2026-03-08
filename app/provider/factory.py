from __future__ import annotations

from typing import Any

from app.provider.anthropic import AnthropicProviderClient
from app.provider.base import BaseLLMProvider
from app.provider.google import GoogleProviderClient
from app.provider.openai import OpenAIProviderClient
from app.provider.xai import XAIGrpcClient
from app.providers.killo_provider import KilloProviderClient


def create_provider(name: str, **kwargs: Any) -> BaseLLMProvider | Any:
    normalized = (name or "").strip().lower()
    if normalized in {"openai"}:
        return OpenAIProviderClient(**kwargs)
    if normalized in {"anthropic", "claude"}:
        return AnthropicProviderClient(**kwargs)
    if normalized in {"google", "gemini"}:
        return GoogleProviderClient(**kwargs)
    if normalized in {"killo", "kilo"}:
        return KilloProviderClient(**kwargs)
    if normalized in {"xai", "grok", "xai_grpc"}:
        return XAIGrpcClient(**kwargs)
    if normalized in {"ollama"}:
        from app.providers.ollama.client import OllamaProvider  # noqa: PLC0415
        from app.settings.config import Config  # noqa: PLC0415

        base_url = kwargs.pop("base_url", Config.OLLAMA_BASE_URL)
        model = kwargs.pop("model", Config.OLLAMA_MODEL)
        return OllamaProvider(base_url, model)
    raise ValueError(
        f"Unsupported provider '{name}'. Supported: openai, anthropic, google, killo, xai, ollama."
    )
