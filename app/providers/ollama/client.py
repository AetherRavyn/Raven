# app/providers/ollama/client.py
"""Ollama provider — OpenAI-compatible local LLM server.

Uses the /v1/chat/completions endpoint exposed by Ollama, which is
API-compatible with OpenAI, so the same message format works as with
all other providers.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Minimal Ollama client wrapping the /v1/chat/completions endpoint.

    Ollama exposes an OpenAI-compatible endpoint at /v1/chat/completions.
    We use that to reuse the same message format as the existing providers.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def chat_completion(
        self,
        messages: list,
        model: str | None = None,
        **kwargs,
    ) -> dict:
        """Send a chat completion request to Ollama.

        Returns a dict with ``{"success": True, "raw": <openai-style response>}``
        or ``{"success": False, "error": "<message>"}`` on failure.
        """
        effective_model = model or self._model
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json={"model": effective_model, "messages": messages, **kwargs},
                )
                resp.raise_for_status()
                data = resp.json()
                return {"success": True, "raw": data}
        except Exception as exc:
            logger.error("Ollama chat_completion error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def chat_completion_stream(
        self,
        messages: list,
        model: str | None = None,
        **kwargs,
    ):
        """Yield token chunks from a streaming Ollama completion.

        Yields ``str`` delta chunks.  Intended for Task 6.5.
        """
        import json as _json

        effective_model = model or self._model
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/v1/chat/completions",
                    json={
                        "model": effective_model,
                        "messages": messages,
                        "stream": True,
                        **kwargs,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = _json.loads(payload)
                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except Exception:
                            continue
        except Exception as exc:
            logger.error("Ollama stream error: %s", exc)

    async def health(self) -> bool:
        """Return True if the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/version")
                return resp.status_code == 200
        except Exception:
            return False
