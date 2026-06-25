"""9Router Provider — connect Raven to 9Router's smart AI routing.

9Router provides:
- 40+ providers (Kiro free, OpenCode free, Vertex $300 credits, GLM cheap)
- Auto-fallback: Subscription → Cheap → Free
- Token savings via RTK compression (-20-40%)
- Format translation (OpenAI ↔ Claude ↔ Gemini)

This client wraps 9Router's OpenAI-compatible API endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.provider.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class NineRouterProvider(BaseLLMProvider):
    """9Router AI routing provider.

    Connects to a local 9Router instance (default: localhost:20128)
    which routes to 40+ providers with auto-fallback and token savings.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:20128",
        api_key: str = "sk_9router",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "9router"

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request via 9Router.

        9Router handles:
        - Provider selection (auto or specified)
        - Format translation (OpenAI ↔ Claude ↔ Gemini)
        - Token compression (RTK)
        - Auto-fallback on failure
        """
        url = f"{self._base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 200:
                    return resp.json()
                else:
                    error_text = resp.text[:500]
                    logger.warning("9Router error %d: %s", resp.status_code, error_text)
                    return {
                        "success": False,
                        "error": f"9Router returned {resp.status_code}: {error_text}",
                        "choices": [{"message": {"content": ""}}],
                    }

        except httpx.TimeoutException:
            return {"success": False, "error": "9Router request timed out"}
        except httpx.ConnectError:
            return {"success": False, "error": f"Cannot connect to 9Router at {self._base_url}. Is it running?"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_models(self) -> list[dict[str, Any]]:
        """List all available models from 9Router."""
        url = f"{self._base_url}/v1/models"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", [])
                return []
        except Exception:
            return []

    def get_available_models(self) -> list[dict[str, str]]:
        """Get commonly used 9Router models."""
        return [
            # Free tier
            {"id": "kr/claude-sonnet-4.5", "name": "Claude Sonnet 4.5 (Kiro Free)", "tier": "free"},
            {"id": "kr/claude-haiku-4.5", "name": "Claude Haiku 4.5 (Kiro Free)", "tier": "free"},
            {"id": "kr/glm-5", "name": "GLM-5 (Kiro Free)", "tier": "free"},
            {"id": "kr/deepseek-3.2", "name": "DeepSeek 3.2 (Kiro Free)", "tier": "free"},
            {"id": "oc/autonomous", "name": "OpenCode Free (No Auth)", "tier": "free"},
            # Cheap tier
            {"id": "glm/glm-5.1", "name": "GLM-5.1", "tier": "cheap", "cost": "$0.6/1M"},
            {"id": "glm/glm-4.7", "name": "GLM-4.7", "tier": "cheap", "cost": "$0.6/1M"},
            {"id": "minimax/MiniMax-M2.7", "name": "MiniMax M2.7", "tier": "cheap", "cost": "$0.2/1M"},
            # Subscription tier
            {"id": "cc/claude-opus-4-7", "name": "Claude Opus 4.7 (Claude Code)", "tier": "subscription"},
            {"id": "cc/claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Claude Code)", "tier": "subscription"},
            {"id": "cx/gpt-5.5", "name": "GPT-5.5 (Codex)", "tier": "subscription"},
            {"id": "gh/gpt-5.4", "name": "GPT-5.4 (GitHub Copilot)", "tier": "subscription"},
        ]
