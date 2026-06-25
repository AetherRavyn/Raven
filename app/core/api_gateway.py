"""Universal API Gateway — FRIDAY-style access to any public API.

Like FRIDAY accessing Stark Industries' systems, Raven can now
call any public API through a unified gateway.

Features:
- Register API endpoints with auth, rate limits, schemas
- Auto-discover available APIs
- Execute API calls with automatic error handling
- Cache responses for performance
- Track API usage for cost optimization

Usage:
    gateway = APIGateway()
    gateway.register("github", GitHubAPI(token="..."))
    result = await gateway.call("github", "repos.list", {"user": "swadhin"})
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class APIDefinition:
    """Definition of a public API."""
    name: str
    base_url: str
    auth_type: str = "none"  # none, api_key, bearer, oauth
    auth_config: dict[str, str] = field(default_factory=dict)
    rate_limit: int = 60  # requests per minute
    timeout: int = 30
    headers: dict[str, str] = field(default_factory=dict)
    endpoints: dict[str, dict[str, Any]] = field(default_factory=dict)  # name → {method, path, params}


@dataclass(slots=True)
class APICallResult:
    """Result of an API call."""
    success: bool
    status_code: int = 0
    data: Any = None
    error: str = ""
    cached: bool = False
    latency_ms: float = 0.0


class APIGateway:
    """FRIDAY-style universal API gateway.

    Registers public APIs and provides a unified interface
    for calling them. Like FRIDAY accessing any system Tony
    needs, Raven can call any registered API.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._apis: dict[str, APIDefinition] = {}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._usage_log: list[dict[str, Any]] = []
        self._dir = Path(workspace_dir) / "api_gateway"
        self._dir.mkdir(parents=True, exist_ok=True)

    def register(self, name: str, api: APIDefinition) -> None:
        """Register a public API."""
        self._apis[name] = api
        logger.info("API registered: %s (%s)", name, api.base_url)

    def register_preset(self, name: str) -> None:
        """Register a preset API configuration."""
        presets = {
            "github": APIDefinition(
                name="github",
                base_url="https://api.github.com",
                auth_type="bearer",
                rate_limit=60,
                endpoints={
                    "repos.list": {"method": "GET", "path": "/user/repos"},
                    "repos.get": {"method": "GET", "path": "/repos/{owner}/{repo}"},
                    "issues.list": {"method": "GET", "path": "/repos/{owner}/{repo}/issues"},
                    "issues.create": {"method": "POST", "path": "/repos/{owner}/{repo}/issues"},
                    "search.repos": {"method": "GET", "path": "/search/repositories"},
                    "user.profile": {"method": "GET", "path": "/user"},
                },
            ),
            "openweather": APIDefinition(
                name="openweather",
                base_url="https://api.openweathermap.org/data/2.5",
                auth_type="api_key",
                endpoints={
                    "weather.current": {"method": "GET", "path": "/weather"},
                    "weather.forecast": {"method": "GET", "path": "/forecast"},
                },
            ),
            "newsapi": APIDefinition(
                name="newsapi",
                base_url="https://newsapi.org/v2",
                auth_type="api_key",
                endpoints={
                    "headlines": {"method": "GET", "path": "/top-headlines"},
                    "search": {"method": "GET", "path": "/everything"},
                },
            ),
            "spotify": APIDefinition(
                name="spotify",
                base_url="https://api.spotify.com/v1",
                auth_type="bearer",
                endpoints={
                    "player.current": {"method": "GET", "path": "/me/player/currently-playing"},
                    "search": {"method": "GET", "path": "/search"},
                    "playlists.list": {"method": "GET", "path": "/me/playlists"},
                },
            ),
            "twitter": APIDefinition(
                name="twitter",
                base_url="https://api.twitter.com/2",
                auth_type="bearer",
                endpoints={
                    "tweets.search": {"method": "GET", "path": "/tweets/search/recent"},
                    "tweets.create": {"method": "POST", "path": "/tweets"},
                    "user.profile": {"method": "GET", "path": "/users/me"},
                },
            ),
        }

        if name in presets:
            self.register(name, presets[name])
        else:
            logger.warning("Unknown preset: %s", name)

    async def call(
        self,
        api_name: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> APICallResult:
        """Call an API endpoint."""
        api = self._apis.get(api_name)
        if not api:
            return APICallResult(success=False, error=f"API '{api_name}' not registered")

        ep = api.endpoints.get(endpoint)
        if not ep:
            return APICallResult(success=False, error=f"Endpoint '{endpoint}' not found in {api_name}")

        # Check cache
        cache_key = f"{api_name}:{endpoint}:{json.dumps(params or {}, sort_keys=True)}"
        if use_cache and cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return APICallResult(success=True, data=cached_data, cached=True)

        # Build request
        method = ep.get("method", "GET")
        path = ep.get("path", "")
        url = api.base_url + path

        # Substitute path parameters
        if params:
            for key, value in params.items():
                url = url.replace(f"{{{key}}}", str(value))

        # Build headers
        headers = dict(api.headers)
        if api.auth_type == "bearer" and api.auth_config.get("token"):
            headers["Authorization"] = f"Bearer {api.auth_config['token']}"
        elif api.auth_type == "api_key" and api.auth_config.get("key"):
            headers["X-API-Key"] = api.auth_config["key"]

        # Make request
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=api.timeout) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    resp = await client.post(url, headers=headers, json=params)
                elif method == "PUT":
                    resp = await client.put(url, headers=headers, json=params)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    return APICallResult(success=False, error=f"Unsupported method: {method}")

                latency = (time.time() - start) * 1000

                if resp.status_code < 400:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                    # Cache successful responses
                    if use_cache:
                        self._cache[cache_key] = (time.time(), data)
                    # Log usage
                    self._log_usage(api_name, endpoint, resp.status_code, latency)
                    return APICallResult(success=True, status_code=resp.status_code, data=data, latency_ms=latency)
                else:
                    return APICallResult(success=False, status_code=resp.status_code, error=resp.text[:500])

        except httpx.TimeoutException:
            return APICallResult(success=False, error="Request timed out")
        except Exception as exc:
            return APICallResult(success=False, error=str(exc))

    def _log_usage(self, api: str, endpoint: str, status: int, latency: float) -> None:
        self._usage_log.append({
            "api": api,
            "endpoint": endpoint,
            "status": status,
            "latency_ms": latency,
            "timestamp": time.time(),
        })

    def list_apis(self) -> list[dict[str, Any]]:
        return [
            {"name": api.name, "base_url": api.base_url, "endpoints": list(api.endpoints.keys())}
            for api in self._apis.values()
        ]

    def get_usage_stats(self) -> dict[str, Any]:
        if not self._usage_log:
            return {"total_calls": 0}
        by_api = {}
        for entry in self._usage_log:
            api = entry["api"]
            by_api.setdefault(api, {"calls": 0, "errors": 0, "avg_latency": 0})
            by_api[api]["calls"] += 1
            if entry["status"] >= 400:
                by_api[api]["errors"] += 1
            by_api[api]["avg_latency"] = (
                by_api[api]["avg_latency"] * (by_api[api]["calls"] - 1) + entry["latency_ms"]
            ) / by_api[api]["calls"]
        return {"total_calls": len(self._usage_log), "by_api": by_api}


# Singleton
_gateway: APIGateway | None = None


def get_api_gateway() -> APIGateway:
    global _gateway
    if _gateway is None:
        _gateway = APIGateway()
        # Register common presets
        for preset in ["github", "openweather", "newsapi", "spotify", "twitter"]:
            _gateway.register_preset(preset)
    return _gateway
