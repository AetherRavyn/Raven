from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from app.provider.base import BaseLLMProvider
from app.settings.config import Config


class GoogleProviderClient(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: int = 30,
        request_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key or Config.GOOGLE_API_KEY or Config.GEMINI_API_KEY
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._request_fn = request_fn

    @property
    def name(self) -> str:
        return "google"

    @staticmethod
    def _to_google_contents(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            role = (m.get("role") or "user").strip().lower()
            content = m.get("content", "")
            if role == "system":
                content = f"System instruction: {content}"
                mapped = "user"
            elif role == "assistant":
                mapped = "model"
            else:
                mapped = "user"
            out.append({"role": mapped, "parts": [{"text": content}]})
        return out

    async def _request(self, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._api_key:
            return {
                "success": False,
                "error": "GOOGLE_API_KEY/GEMINI_API_KEY is not configured",
            }

        url = f"{self._base_url}/models/{model}:generateContent?key={self._api_key}"
        if self._request_fn is not None:
            response = await asyncio.to_thread(
                self._request_fn,
                "POST",
                url,
                {"Content-Type": "application/json"},
                payload,
                self._timeout,
            )
            return response

        if requests is None:
            return {"success": False, "error": "requests package is not installed"}

        def _send() -> Any:
            return requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self._timeout,
            )

        try:
            res = await asyncio.to_thread(_send)
            data = res.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

        if res.status_code >= 400:
            return {
                "success": False,
                "status_code": res.status_code,
                "error": data.get("error", data),
            }
        return {"success": True, "status_code": res.status_code, "data": data}

    async def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = float(temperature)
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = int(max_tokens)
        generation_config.update(kwargs.pop("generation_config", {}))

        body: Dict[str, Any] = {
            "contents": self._to_google_contents(messages),
        }
        if generation_config:
            body["generationConfig"] = generation_config
        body.update(kwargs)

        result = await self._request(model, body)
        if not result.get("success"):
            return result

        data = result.get("data", {})
        candidates = data.get("candidates", []) or []
        text_parts: List[str] = []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", []) or []
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    text_parts.append(part["text"])

        return {
            "success": True,
            "provider": self.name,
            "model_used": model,
            "content": "\n".join(text_parts).strip(),
            "raw": data,
        }
