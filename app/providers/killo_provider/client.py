from __future__ import annotations

import asyncio
import json as _json
from typing import Any, AsyncIterator, Dict, List

try:
    import requests
except ImportError:
    requests = None

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

from app.settings.config import Config


class KilloProviderClient:
    """Minimal Kilo provider helper for tools/agents."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or Config.KILLO_API_KEY or "not-needed-for-free-models"
        self.base_url = (base_url or Config.KILLO_BASE_URL).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, payload: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        if requests is None:
            return {"success": False, "error": "requests package is not installed"}

        url = f"{self.base_url}{path}"

        def _send():
            return requests.request(
                method=method.upper(),
                url=url,
                headers=self._headers(),
                json=payload,
                timeout=30,
            )

        try:
            response = await asyncio.to_thread(_send)
            data = response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

        if response.status_code >= 400:
            return {
                "success": False,
                "status_code": response.status_code,
                "error": data.get("error", data),
            }
        return {"success": True, "status_code": response.status_code, "data": data}

    @staticmethod
    def _normalize_error(error: Any) -> Dict[str, Any]:
        if isinstance(error, dict):
            return error
        return {"message": str(error)}

    @classmethod
    def _is_rate_limited(cls, error: Any, status_code: int | None = None) -> bool:
        if status_code == 429:
            return True
        e = cls._normalize_error(error)
        code = e.get("code")
        if code == 429:
            return True
        message = str(e.get("message", "")).lower()
        raw = str((e.get("metadata") or {}).get("raw", "")).lower()
        return "rate limit" in message or "rate-limited" in raw

    @staticmethod
    def _looks_free(model: Dict[str, Any]) -> bool:
        mid = str(model.get("id", ""))
        pricing = model.get("pricing", {}) or {}
        prompt = float(pricing.get("prompt", "0") or 0)
        completion = float(pricing.get("completion", "0") or 0)
        return (
            mid.endswith(":free")
            or mid in {"giga-potato", "corethink:free"}
            or (prompt == 0 and completion == 0)
        )

    async def list_models(self) -> Dict[str, Any]:
        res = await self._request("GET", "/models")
        if not res.get("success"):
            return res
        models = res.get("data", {}).get("data", []) or []
        return {"success": True, "models": models}

    async def list_free_models(self) -> Dict[str, Any]:
        res = await self.list_models()
        if not res.get("success"):
            return res
        free_ids = sorted(
            {m.get("id", "") for m in res.get("models", []) if self._looks_free(m)}
        )
        return {"success": True, "free_model_ids": free_ids}

    async def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        free_only_guard: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if free_only_guard:
            free = await self.list_free_models()
            if not free.get("success"):
                return free
            if model not in set(free.get("free_model_ids", [])):
                return {"success": False, "error": f"{model} is not free right now"}

        body = {"model": model, "messages": messages}
        body.update(kwargs)
        res = await self._request("POST", "/chat/completions", body)
        if not res.get("success"):
            return res
        data = res.get("data", {})
        choices = data.get("choices", []) or []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "")
        return {"success": True, "content": content, "raw": data}

    async def chat_completion_resilient(
        self,
        *,
        messages: List[Dict[str, str]],
        preferred_models: List[str] | None = None,
        free_only_guard: bool = True,
        max_retries_per_model: int = 2,
        initial_backoff_seconds: float = 1.0,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        free = await self.list_free_models()
        if not free.get("success"):
            return free
        free_ids = free.get("free_model_ids", []) or []
        if not free_ids:
            return {"success": False, "error": "No free models available right now"}

        ordered_models: list[str] = []
        for m in preferred_models or []:
            if m in free_ids and m not in ordered_models:
                ordered_models.append(m)
        for m in free_ids:
            if m not in ordered_models:
                ordered_models.append(m)

        attempts: list[Dict[str, Any]] = []
        for model in ordered_models:
            backoff = max(0.5, initial_backoff_seconds)
            for try_idx in range(max(1, max_retries_per_model)):
                res = await self.chat_completion(
                    model=model,
                    messages=messages,
                    free_only_guard=free_only_guard,
                    **kwargs,
                )
                if res.get("success"):
                    res["model_used"] = model
                    res["attempts"] = attempts
                    return res

                err = self._normalize_error(res.get("error"))
                status_code = res.get("status_code")
                attempts.append(
                    {
                        "model": model,
                        "try": try_idx + 1,
                        "status_code": status_code,
                        "error": err,
                    }
                )
                if self._is_rate_limited(err, status_code=status_code):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                break

        guidance = (
            "Provider returned repeated rate limits or errors across free models. "
            "Retry shortly or add your own provider key (BYOK) for higher limits."
        )
        return {
            "success": False,
            "error": guidance,
            "attempts": attempts,
        }

    async def chat_completion_stream(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield token chunks from a streaming chat completion via the Killo gateway.

        Uses httpx for async streaming.  Falls back to empty iterator if httpx is
        unavailable or the request fails.
        """
        if _httpx is None:
            return

        url = f"{self.base_url}/chat/completions"
        body = {"model": model, "messages": messages, "stream": True}
        body.update(kwargs)

        try:
            async with _httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", url, headers=self._headers(), json=body
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
        except Exception:
            return
