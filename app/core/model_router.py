from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.provider.factory import create_provider
from app.settings.config import Config


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
            self._local_health = bool(await health())
        except Exception:
            self._local_health = False
        return self._local_health

    async def resolve(self, text: str) -> RouteDecision:
        route_kind = self.classify(text)
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
