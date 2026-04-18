from __future__ import annotations

import asyncio
import os
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ---------------------------------------------------------------------------
# In-process cache (shared across all calls)
# ---------------------------------------------------------------------------
_SEARCH_CACHE: Dict[str, Tuple[float, Any]] = {}


def _cache_get(key: str, ttl_minutes: float) -> Optional[Any]:
    entry = _SEARCH_CACHE.get(key)
    if entry and (time.time() - entry[0]) < ttl_minutes * 60:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _SEARCH_CACHE[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Brave generic helper (supports web / news / images)
# ---------------------------------------------------------------------------
def _search_brave(
    endpoint: str,  # "web" | "news" | "images"
    query: str,
    api_key: str,
    count: int,
    country: Optional[str] = None,
    search_lang: Optional[str] = None,
    freshness: Optional[str] = None,
    timeout: int = 30,
) -> List[Dict[str, Any]]:
    """Call Brave Search API (web, news, or images)."""
    try:
        import requests
    except ImportError:
        raise ImportError("Install 'requests' to use the Brave search provider.")

    params: Dict[str, Any] = {"q": query, "count": min(count, 20)}
    if country:
        params["country"] = country
    if search_lang:
        params["search_lang"] = search_lang
    if freshness:
        params["freshness"] = freshness

    resp = requests.get(
        f"https://api.search.brave.com/res/v1/{endpoint}/search",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        },
        params=params,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    results: List[Dict[str, Any]] = []
    section = data.get(endpoint, {}) if endpoint != "images" else data
    items = section.get("results", [])[:count]

    for item in items:
        if endpoint == "images":
            results.append(
                {
                    "title": item.get("title", ""),
                    "image_url": item.get("image", {}).get("src", item.get("url", "")),
                    "source_url": item.get("url", ""),
                    "thumbnail": item.get("thumbnail", {}).get("src", ""),
                    "width": item.get("width"),
                    "height": item.get("height"),
                }
            )
        else:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", "") or item.get("snippet", ""),
                }
            )
    return results


# ---------------------------------------------------------------------------
# Original AI providers (exactly as you provided)
# ---------------------------------------------------------------------------
def _search_perplexity(
    query: str,
    api_key: str,
    base_url: str,
    model: str,
    count: int,
    freshness: Optional[str],
    search_lang: Optional[str],
    timeout: int,
) -> List[Dict[str, str]]:
    """Call Perplexity/OpenRouter Sonar model and return AI-synthesized result + citations."""
    try:
        import requests
    except ImportError:
        raise ImportError("Install 'requests' to use the Perplexity search provider.")
    messages = [{"role": "user", "content": query}]
    if freshness:
        messages[0]["content"] += f"\n\n[Freshness filter: {freshness}]"
    if search_lang:
        messages[0]["content"] += f"\n\n[Respond in language: {search_lang}]"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": 1024,
    }
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    citations = data.get("citations", [])
    results = [{"title": "AI Answer", "url": "", "snippet": answer}]
    for i, cite in enumerate(citations[:count], 1):
        if isinstance(cite, str):
            results.append({"title": f"Source {i}", "url": cite, "snippet": ""})
        elif isinstance(cite, dict):
            results.append(
                {
                    "title": cite.get("title", f"Source {i}"),
                    "url": cite.get("url", ""),
                    "snippet": cite.get("snippet", ""),
                }
            )
    return results


def _search_gemini(
    query: str,
    api_key: str,
    model: str,
    count: int,
    timeout: int,
) -> List[Dict[str, str]]:
    """Use Gemini with Google Search grounding and resolve redirect URLs."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        client = genai.Client(api_key=api_key)
        tool = types.Tool(google_search=types.GoogleSearch())
        resp = client.models.generate_content(
            model=model,
            contents=query,
            config=types.GenerateContentConfig(tools=[tool]),
        )
    except ImportError:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)
            gmodel = genai.GenerativeModel(model)
            resp = gmodel.generate_content(query)
        except ImportError as e:
            raise ImportError(
                "Install 'google-genai' to use the Gemini search provider."
            ) from e
    answer = getattr(resp, "text", "") or ""
    results = [{"title": "AI Answer", "url": "", "snippet": answer}]
    # Extract grounding citations and resolve Google redirect URLs
    try:
        import requests

        candidates = getattr(resp, "candidates", []) or []
        if candidates:
            grounding = getattr(candidates[0], "grounding_metadata", None)
            chunks = getattr(grounding, "grounding_chunks", []) or []
            for chunk in chunks[:count]:
                web = getattr(chunk, "web", None)
                if not web:
                    continue
                raw_url = getattr(web, "uri", "") or ""
                title = getattr(web, "title", "") or ""
                # Resolve Google redirect → direct URL
                final_url = _resolve_redirect(raw_url, timeout)
                results.append({"title": title, "url": final_url, "snippet": ""})
    except Exception:
        pass
    return results


def _search_grok(
    query: str,
    api_key: str,
    count: int,
    timeout: int,
) -> List[Dict[str, str]]:
    """Call xAI Grok via its OpenAI-compatible API."""
    try:
        import requests
    except ImportError:
        raise ImportError("Install 'requests' to use the Grok search provider.")
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        json={
            "model": "grok-3-latest",
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 1024,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return [{"title": "AI Answer", "url": "", "snippet": answer}]


def _resolve_redirect(url: str, timeout: int = 10) -> str:
    """Follow HTTP redirects (HEAD) and return the final URL. SSRF-safe."""
    if not url:
        return url
    try:
        import ipaddress
        import socket
        from urllib.parse import urlparse

        import requests

        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        final = resp.url
        # SSRF guard on final destination
        hostname = urlparse(final).hostname or ""
        try:
            ip = socket.gethostbyname(hostname)
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return url  # fall back to original
        except Exception:
            pass
        return final
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Provider auto-detection
# ---------------------------------------------------------------------------
def _detect_provider() -> Tuple[str, str]:
    """
    Return (provider_name, api_key) by checking env vars in documented order:
    Brave → Gemini → Perplexity → Grok
    """
    brave_key = os.environ.get("BRAVE_API_KEY") or getattr(
        Config, "BRAVE_API_KEY", None
    )
    if brave_key:
        return "brave", brave_key
    gemini_key = os.environ.get("GEMINI_API_KEY") or getattr(
        Config, "GEMINI_API_KEY", None
    )
    if gemini_key:
        return "gemini", gemini_key
    perp_key = (
        os.environ.get("PERPLEXITY_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or getattr(Config, "PERPLEXITY_API_KEY", None)
        or getattr(Config, "OPENROUTER_API_KEY", None)
    )
    if perp_key:
        return "perplexity", perp_key
    grok_key = os.environ.get("XAI_API_KEY") or getattr(Config, "XAI_API_KEY", None)
    if grok_key:
        return "grok", grok_key
    raise ValueError(
        "No search API key found. Configure BRAVE_API_KEY, GEMINI_API_KEY, "
        "PERPLEXITY_API_KEY, OPENROUTER_API_KEY, or XAI_API_KEY."
    )


def _perplexity_base_url(api_key: str) -> str:
    """Infer Perplexity base URL from key format (as documented)."""
    if api_key.startswith("pplx-"):
        return "https://api.perplexity.ai"
    if api_key.startswith("sk-or-"):
        return "https://openrouter.ai/api/v1"
    return "https://openrouter.ai/api/v1"  # safe fallback


# ---------------------------------------------------------------------------
# Unified WebOperationTool (FULL enum + all operations)
# ---------------------------------------------------------------------------
class WebOperationTool(BaseTool):
    """Unified web operations tool — exactly matches your GitOperationTool / ObsidianOperationTool / SpotifyOperationTool style.
    Supports: search, news, image_search, scholar.
    Brave preferred for structured results. Works on all devices (Windows/macOS/Linux)."""

    VALID_FRESHNESS = {"pd", "pw", "pm", "py"}

    def __init__(self, **cfg: Any):
        # Provider selection
        self._explicit_provider: Optional[str] = cfg.get("provider")
        self._explicit_key: Optional[str] = cfg.get("api_key")
        self.MAX_RESULTS: int = min(int(cfg.get("max_results", 8)), 15)
        self.TIMEOUT: int = int(cfg.get("timeout_seconds", 30))
        self.CACHE_TTL: float = float(cfg.get("cache_ttl_minutes", 15))
        # Perplexity
        self._perp_base_url: Optional[str] = cfg.get("perplexity_base_url")
        self._perp_model: str = cfg.get("perplexity_model", "perplexity/sonar-pro")
        # Gemini
        self._gemini_model: str = cfg.get("gemini_model", "gemini-2.5-flash")

    def get_name(self) -> str:
        return "web_ops"

    def get_description(self) -> str:
        return (
            "Unified web operations: general search, latest news, image search, "
            "and academic scholar search. Auto-detects provider. Full enum support."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The web operation to perform.",
                    required=True,
                    enum=[
                        "search",  # General web search
                        "news",  # Real-time news
                        "image_search",  # Images with direct URLs + thumbnails
                        "scholar",  # Academic papers / research (scholar bias)
                    ],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="The search query.",
                    required=True,
                ),
                ToolParameter(
                    name="count",
                    type="integer",
                    description=f"Number of results (1–15; default {self.MAX_RESULTS}).",
                    required=False,
                ),
                ToolParameter(
                    name="country",
                    type="string",
                    description="2-letter country code (Brave).",
                    required=False,
                ),
                ToolParameter(
                    name="freshness",
                    type="string",
                    description=(
                        "Filter results by discovery time. "
                        "Options: 'pd' (past day), 'pw' (past week), 'pm' (past month), "
                        "'py' (past year), or 'YYYY-MM-DDtoYYYY-MM-DD'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="provider",
                    type="string",
                    description="Force provider: brave | perplexity | gemini | grok",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        query: str = str(kwargs.get("query", "")).strip()
        if not query:
            return self._error("query parameter is required.")

        count: int = min(int(kwargs.get("count", self.MAX_RESULTS)), 15)
        country: Optional[str] = kwargs.get("country")
        freshness: Optional[str] = kwargs.get("freshness")

        if (
            freshness
            and freshness not in self.VALID_FRESHNESS
            and "to" not in freshness
        ):
            return self._error(
                f"Invalid freshness '{freshness}'. "
                f"Use one of: {', '.join(sorted(self.VALID_FRESHNESS))} "
                "or YYYY-MM-DDtoYYYY-MM-DD."
            )

        # Resolve provider + key
        try:
            if self._explicit_provider:
                provider = self._explicit_provider.lower()
                api_key = self._explicit_key or _detect_provider()[1]
            else:
                provider, api_key = _detect_provider()
        except ValueError as e:
            setup_hint = (
                "Run: openclaw configure --section web\n"
                "Or set one of: BRAVE_API_KEY, GEMINI_API_KEY, "
                "PERPLEXITY_API_KEY, OPENROUTER_API_KEY, XAI_API_KEY"
            )
            return self._error(f"{e}\n\n{setup_hint}")

        # Cache key (includes operation)
        cache_key = f"web_ops:{op}:{provider}:{query}:{count}:{country}:{freshness}"
        cached = _cache_get(cache_key, self.CACHE_TTL)
        if cached is not None:
            return {
                "success": True,
                "operation": op,
                "output": cached,
                "cached": True,
                "provider": provider,
            }

        # Dispatch — run sync HTTP work in a thread to avoid blocking the event loop
        def _sync_dispatch() -> List[Dict[str, Any]]:
            if provider == "brave":
                if op == "search":
                    return _search_brave(
                        "web",
                        query,
                        api_key,
                        count,
                        country,
                        freshness=freshness,
                        timeout=self.TIMEOUT,
                    )
                elif op == "news":
                    return _search_brave(
                        "news",
                        query,
                        api_key,
                        count,
                        country,
                        freshness=freshness,
                        timeout=self.TIMEOUT,
                    )
                elif op == "image_search":
                    return _search_brave(
                        "images",
                        query,
                        api_key,
                        count,
                        country,
                        freshness=freshness,
                        timeout=self.TIMEOUT,
                    )
                elif op == "scholar":
                    # Academic bias
                    scholar_query = f"{query} scholar OR pdf OR academic OR research OR doi OR filetype:pdf"
                    return _search_brave(
                        "web",
                        scholar_query,
                        api_key,
                        count,
                        country,
                        freshness=freshness,
                        timeout=self.TIMEOUT,
                    )
                else:
                    raise ValueError(f"Unknown operation: {op}")
            else:
                # Non-Brave providers → enhance prompt based on operation
                enhanced_query = query
                if op == "news":
                    enhanced_query = f"Latest news about: {query}"
                elif op == "image_search":
                    enhanced_query = f"Find and describe images of: {query}"
                elif op == "scholar":
                    enhanced_query = (
                        f"Academic papers, authors, abstracts, DOIs on: {query}"
                    )

                if provider == "perplexity":
                    base_url = self._perp_base_url or _perplexity_base_url(api_key)
                    return _search_perplexity(
                        query=enhanced_query,
                        api_key=api_key,
                        base_url=base_url,
                        model=self._perp_model,
                        count=count,
                        freshness=freshness,
                        search_lang=None,
                        timeout=self.TIMEOUT,
                    )
                elif provider == "gemini":
                    return _search_gemini(
                        query=enhanced_query,
                        api_key=api_key,
                        model=self._gemini_model,
                        count=count,
                        timeout=self.TIMEOUT,
                    )
                elif provider == "grok":
                    return _search_grok(
                        query=enhanced_query,
                        api_key=api_key,
                        count=count,
                        timeout=self.TIMEOUT,
                    )
                else:
                    raise ValueError(f"Unknown provider: '{provider}'.")

        try:
            results: List[Dict[str, Any]] = await asyncio.to_thread(_sync_dispatch)
        except Exception as e:
            return self._error(f"{op} failed with {provider}: {e}")

        _cache_set(cache_key, results)
        return {
            "success": True,
            "operation": op,
            "provider": provider,
            "output": results,
            "count": len(results),
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "output": f"Error: {msg}"}


# Backwards-compatible alias used by older tests/imports.
class WebSearchTool(WebOperationTool):
    def __init__(self, *args: Any, model: Any | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.model = model

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return {
                "llmContent": "Error: query is required.",
                "returnDisplay": {"error": "query is required"},
            }

        if self.model is None:
            return await super().execute(**kwargs)

        try:
            response = self.model.generate_content(contents=query, tools=None)
        except TypeError:
            response = self.model.generate_content(query)

        if response is None:
            return {
                "llmContent": "No search results",
                "returnDisplay": {"results": []},
            }

        candidates = getattr(response, "candidates", []) or []
        if not candidates:
            return {
                "llmContent": "No search results",
                "returnDisplay": {"results": []},
            }

        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", []) or []
        text = "\n".join(
            getattr(part, "text", "") for part in parts if getattr(part, "text", "")
        )
        if not text:
            text = "No search results"

        grounding = getattr(candidates[0], "grounding_metadata", None)
        results: list[dict[str, Any]] = []
        if grounding and getattr(grounding, "grounding_chunks", None):
            for chunk in getattr(grounding, "grounding_chunks", []) or []:
                web = getattr(chunk, "web", None)
                if web:
                    results.append(
                        {
                            "title": getattr(web, "title", ""),
                            "uri": getattr(web, "uri", ""),
                        }
                    )

        return {
            "llmContent": text,
            "returnDisplay": {"results": results},
        }
