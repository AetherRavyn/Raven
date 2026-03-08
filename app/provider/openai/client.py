from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from app.provider.base import BaseLLMProvider
from app.settings.config import Config


class OpenAIProviderClient(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 30,
        request_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key or Config.OPENAI_API_KEY
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._request_fn = request_fn

    @property
    def name(self) -> str:
        return "openai"

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._request_fn is not None:
            response = await asyncio.to_thread(
                self._request_fn,
                "POST",
                f"{self._base_url}/chat/completions",
                self._headers(),
                payload,
                self._timeout,
            )
            return response

        if requests is None:
            return {"success": False, "error": "requests package is not installed"}

        def _send() -> Any:
            return requests.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
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
        body: Dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = float(temperature)
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)
        body.update(kwargs)

        result = await self._request(body)
        if not result.get("success"):
            return result

        data = result.get("data", {})
        choices = data.get("choices", []) or []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
        return {
            "success": True,
            "provider": self.name,
            "model_used": data.get("model", model),
            "content": content,
            "raw": data,
        }
