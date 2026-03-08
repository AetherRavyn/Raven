from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Tuple

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from app.provider.base import BaseLLMProvider
from app.settings.config import Config


class AnthropicProviderClient(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: int = 30,
        anthropic_version: str = "2023-06-01",
        request_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key or Config.ANTHROPIC_API_KEY
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._anthropic_version = anthropic_version
        self._request_fn = request_fn

    @property
    def name(self) -> str:
        return "anthropic"

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return {
            "x-api-key": self._api_key,
            "anthropic-version": self._anthropic_version,
            "content-type": "application/json",
        }

    @staticmethod
    def _to_anthropic_messages(
        messages: List[Dict[str, str]],
    ) -> Tuple[str | None, List[Dict[str, Any]]]:
        system_parts: List[str] = []
        out: List[Dict[str, Any]] = []
        for m in messages:
            role = (m.get("role") or "user").strip().lower()
            content = m.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            mapped_role = "assistant" if role == "assistant" else "user"
            out.append({"role": mapped_role, "content": content})
        return ("\n".join(system_parts).strip() or None, out)

    async def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._request_fn is not None:
            response = await asyncio.to_thread(
                self._request_fn,
                "POST",
                f"{self._base_url}/messages",
                self._headers(),
                payload,
                self._timeout,
            )
            return response

        if requests is None:
            return {"success": False, "error": "requests package is not installed"}

        def _send() -> Any:
            return requests.post(
                f"{self._base_url}/messages",
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
        system_prompt, converted = self._to_anthropic_messages(messages)
        body: Dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": int(max_tokens or 1024),
        }
        if system_prompt:
            body["system"] = system_prompt
        if temperature is not None:
            body["temperature"] = float(temperature)
        body.update(kwargs)

        result = await self._request(body)
        if not result.get("success"):
            return result

        data = result.get("data", {})
        content_blocks = data.get("content", []) or []
        text_parts: List[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        return {
            "success": True,
            "provider": self.name,
            "model_used": data.get("model", model),
            "content": "\n".join(t for t in text_parts if t).strip(),
            "raw": data,
        }
