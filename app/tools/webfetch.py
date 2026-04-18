from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ---------------------------------------------------------------------------
# Simple in-process cache (thread-safe enough for single-process use)
# ---------------------------------------------------------------------------
_FETCH_CACHE: Dict[str, Tuple[float, Any]] = {}


def _cache_get(key: str, ttl_minutes: float) -> Optional[Any]:
    entry = _FETCH_CACHE.get(key)
    if entry and (time.time() - entry[0]) < ttl_minutes * 60:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _FETCH_CACHE[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Unified WebFetchOperationTool — FULL enum style (exactly like git_ops / web_ops / obsidian_ops)
# ---------------------------------------------------------------------------
class WebFetchOperationTool(BaseTool):
    """Unified web fetch tool with FULL operation enum.
    Exactly matches your GitOperationTool / ObsidianOperationTool / SpotifyOperationTool / WebOperationTool style.
    Supports SSRF-safe fetching, readability, Firecrawl fallback, and AI synthesis.
    Works on all devices (Windows/macOS/Linux)."""

    def __init__(
        self,
        google_api_key: str | None = None,
        model: Any | None = None,
        **cfg: Any,
    ):
        # Gemini setup for optional AI synthesis (exactly as you wrote)
        api_key = google_api_key or getattr(Config, "GEMINI_API_KEY", None)
        self._sdk_mode = "injected"
        self.model = None
        self._client = None
        self._model_name = "gemini-2.5-flash"
        if model is not None:
            self.model = model
        else:
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not configured for AI synthesis.")
            try:
                from google import genai  # type: ignore

                self._client = genai.Client(api_key=api_key)
                self._sdk_mode = "new"
            except ImportError:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", FutureWarning)
                        import google.generativeai as genai  # type: ignore
                    genai.configure(api_key=api_key)
                    self.model = genai.GenerativeModel("gemini-1.5-flash")
                    self._sdk_mode = "legacy"
                except ImportError as e:
                    raise ImportError(
                        "Install `google-genai` (preferred) or `google-generativeai` for AI synthesis."
                    ) from e

        # Configurable limits (exactly as you wrote)
        self.MAX_CHARS: int = int(cfg.get("max_chars", 50_000))
        self.MAX_CHARS_CAP: int = int(cfg.get("max_chars_cap", 50_000))
        self.MAX_RESPONSE_BYTES: int = int(cfg.get("max_response_bytes", 2_000_000))
        self.TIMEOUT: int = int(cfg.get("timeout_seconds", 30))
        self.CACHE_TTL: float = float(cfg.get("cache_ttl_minutes", 15))
        self.MAX_REDIRECTS: int = int(cfg.get("max_redirects", 3))
        self.USER_AGENT: str = cfg.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        self.READABILITY: bool = bool(cfg.get("readability", True))

        # Firecrawl fallback
        self.FIRECRAWL_ENABLED: bool = bool(cfg.get("firecrawl_enabled", False))
        self.FIRECRAWL_API_KEY: str | None = cfg.get("firecrawl_api_key") or getattr(
            Config, "FIRECRAWL_API_KEY", None
        )
        self.FIRECRAWL_BASE_URL: str = cfg.get(
            "firecrawl_base_url", "https://api.firecrawl.dev"
        )
        self.FIRECRAWL_ONLY_MAIN: bool = bool(
            cfg.get("firecrawl_only_main_content", True)
        )
        self.FIRECRAWL_MAX_AGE_MS: int = int(
            cfg.get("firecrawl_max_age_ms", 86_400_000)
        )
        self.FIRECRAWL_TIMEOUT: int = int(cfg.get("firecrawl_timeout_seconds", 60))

    def get_name(self) -> str:
        return "web_fetch_ops"

    def get_description(self) -> str:
        return (
            "Unified web fetch operations with full enum: fetch, summarize, extract_links, metadata. "
            "SSRF-safe, readability, Firecrawl fallback, AI synthesis. Works on all devices."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The fetch operation to perform.",
                    required=True,
                    enum=[
                        "fetch",  # Full readable content (markdown/text)
                        "summarize",  # AI-powered summary of the page
                        "extract_links",  # Extract all hyperlinks from the page
                        "metadata",  # Page title, description, meta tags, etc.
                    ],
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    description="The http/https URL to fetch.",
                    required=True,
                ),
                ToolParameter(
                    name="extractMode",
                    type="string",
                    description="For 'fetch' only: 'markdown' (default) or 'text'.",
                    required=False,
                ),
                ToolParameter(
                    name="maxChars",
                    type="integer",
                    description=f"Truncate content (default {self.MAX_CHARS}, max {self.MAX_CHARS_CAP}).",
                    required=False,
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="For 'summarize' only: custom summary instruction.",
                    required=False,
                ),
            ],
        )

    # -------------------------------------------------- private helpers (exactly as you wrote)
    def _is_private_ip(self, url: str) -> bool:
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return True
            ip = socket.gethostbyname(hostname)
            addr = ipaddress.ip_address(ip)
            return addr.is_private or addr.is_loopback or addr.is_link_local
        except Exception:
            return True  # fail closed

    def _validate_url(self, url: str) -> Optional[str]:
        url = url.rstrip(".,;!?")
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return f"Unsupported scheme '{parsed.scheme}' in URL: {url}"
        except Exception:
            return f"Malformed URL: {url}"
        if self._is_private_ip(url):
            return f"Security Error: Access to {url} is blocked (private/local IP)."
        return None

    def _html_to_text(self, html: str, mode: str) -> str:
        if BeautifulSoup is None:
            text = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s{2,}", " ", text).strip()
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(
            ["script", "style", "nav", "footer", "iframe", "noscript", "head"]
        ):
            tag.decompose()
        if mode == "markdown" and self.READABILITY:
            return self._readability_markdown(soup)
        return soup.get_text(separator=" ", strip=True)

    def _readability_markdown(self, soup: "BeautifulSoup") -> str:
        lines: List[str] = []
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup
        for el in main.descendants:  # type: ignore[union-attr]
            if not hasattr(el, "name"):
                continue
            tag = el.name
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                lines.append(f"\n{'#' * level} {el.get_text(strip=True)}\n")
            elif tag == "p":
                text = el.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"\n{text}\n")
            elif tag == "li":
                text = el.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"- {text}")
            elif tag == "a":
                href = el.get("href", "")
                text = el.get_text(strip=True)
                if href and text:
                    lines.append(f"[{text}]({href})")
            elif tag == "code":
                lines.append(f"`{el.get_text(strip=True)}`")
            elif tag == "pre":
                lines.append(f"\n```\n{el.get_text()}\n```\n")
        return "\n".join(lines).strip()

    def _firecrawl_fetch(self, url: str) -> Optional[str]:
        if requests is None or not self.FIRECRAWL_API_KEY:
            return None
        try:
            endpoint = f"{self.FIRECRAWL_BASE_URL.rstrip('/')}/v1/scrape"
            payload: Dict[str, Any] = {
                "url": url,
                "onlyMainContent": self.FIRECRAWL_ONLY_MAIN,
                "formats": ["markdown"],
                "maxAge": self.FIRECRAWL_MAX_AGE_MS,
            }
            resp = requests.post(
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.FIRECRAWL_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=self.FIRECRAWL_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("markdown") or data.get("data", {}).get(
                "content"
            )
        except Exception:
            return None

    def _http_fetch(self, url: str, mode: str, max_chars: int) -> Tuple[bool, str]:
        if requests is None:
            return False, "Error: 'requests' package is not installed."
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace(
                "/blob/", "/"
            )
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=self.TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            redirect_count = 0
            while resp.is_redirect and redirect_count < self.MAX_REDIRECTS:
                redirect_url = resp.headers.get("Location", "")
                if not redirect_url:
                    break
                err = self._validate_url(redirect_url)
                if err:
                    return False, f"Redirect blocked: {err}"
                resp = requests.get(
                    redirect_url,
                    headers=headers,
                    timeout=self.TIMEOUT,
                    allow_redirects=False,
                    stream=True,
                )
                redirect_count += 1
            resp.raise_for_status()
            chunks: List[bytes] = []
            downloaded = 0
            truncated = False
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > self.MAX_RESPONSE_BYTES:
                    chunks.append(
                        chunk[: self.MAX_RESPONSE_BYTES - (downloaded - len(chunk))]
                    )
                    truncated = True
                    break
                chunks.append(chunk)
            raw_bytes = b"".join(chunks)
            content_type = resp.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raw_text = self._html_to_text(
                    raw_bytes.decode("utf-8", errors="replace"), mode
                )
            else:
                raw_text = raw_bytes.decode("utf-8", errors="replace")
            if truncated:
                raw_text += (
                    "\n\n...[Response truncated: exceeded maxResponseBytes limit]"
                )
            if len(raw_text) > max_chars:
                raw_text = raw_text[:max_chars] + "\n\n...[Content truncated]"
            return True, raw_text
        except Exception as e:
            return False, f"Fetch error: {e}"

    def _generate_answer(self, rag_prompt: str) -> str:
        if self._sdk_mode == "new":
            result = self._client.models.generate_content(
                model=self._model_name, contents=rag_prompt
            )
            text = getattr(result, "text", None)
            if text:
                return text
            candidates = getattr(result, "candidates", None) or []
            if candidates:
                parts = (
                    getattr(getattr(candidates[0], "content", None), "parts", []) or []
                )
                if parts:
                    return getattr(parts[0], "text", "") or ""
            return ""
        result = self.model.generate_content(rag_prompt)
        return getattr(result, "text", "") or ""

    # ---------------------------------------------------------------- execute with FULL enum handling
    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        url: str = str(kwargs.get("url", "")).strip()
        if not url:
            return self._error("'url' parameter is required.")
        err = self._validate_url(url)
        if err:
            return self._error(err)

        # Common params
        mode: str = str(kwargs.get("extractMode", "markdown")).lower()
        if mode not in ("markdown", "text"):
            mode = "markdown"
        requested_max = int(kwargs.get("maxChars", self.MAX_CHARS))
        max_chars = min(requested_max, self.MAX_CHARS_CAP)
        prompt: Optional[str] = kwargs.get("prompt")

        cache_key = f"fetch_ops:{op}:{url}:{mode}:{max_chars}"
        cached = _cache_get(cache_key, self.CACHE_TTL)
        if cached is not None:
            result_text = cached
        else:
            # Run sync HTTP work in a thread to avoid blocking the event loop
            success, result_text = await asyncio.to_thread(
                self._http_fetch, url, mode, max_chars
            )
            if not success and self.FIRECRAWL_ENABLED:
                fc_content = await asyncio.to_thread(self._firecrawl_fetch, url)
                if fc_content:
                    if len(fc_content) > max_chars:
                        fc_content = (
                            fc_content[:max_chars] + "\n\n...[Content truncated]"
                        )
                    result_text = fc_content
                    success = True
            if not success:
                return self._error(result_text)
            _cache_set(cache_key, result_text)

        # Operation-specific handling
        if op == "fetch":
            return {
                "success": True,
                "operation": op,
                "output": result_text,
                "url": url,
            }

        elif op == "summarize":
            summary_prompt = (
                prompt or "Provide a concise, high-quality summary of the page content."
            )
            rag = (
                f"{summary_prompt}\n\n"
                f"--- CONTENT FROM {url} ---\n{result_text}\n--- END CONTENT ---"
            )
            answer = self._generate_answer(rag)
            if not answer:
                return self._error("Model generated empty summary.")
            return {
                "success": True,
                "operation": op,
                "output": answer,
                "url": url,
                "synthesized": True,
            }

        elif op == "extract_links":
            if BeautifulSoup is None:
                return self._error(
                    "BeautifulSoup not installed — cannot extract links."
                )
            soup = BeautifulSoup(
                result_text if "<" in result_text else "<html>" + result_text,
                "html.parser",
            )
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True) or ""
                links.append({"text": text, "url": href})
            return {
                "success": True,
                "operation": op,
                "output": links,
                "count": len(links),
                "url": url,
            }

        elif op == "metadata":
            if BeautifulSoup is None:
                return self._error(
                    "BeautifulSoup not installed — cannot extract metadata."
                )
            soup = BeautifulSoup(
                result_text if "<" in result_text else "<html>" + result_text,
                "html.parser",
            )
            meta = {
                "title": soup.find("title").get_text(strip=True)
                if soup.find("title")
                else "",
                "description": soup.find("meta", attrs={"name": "description"}).get(
                    "content", ""
                )
                if soup.find("meta", attrs={"name": "description"})
                else "",
                "og_title": soup.find("meta", attrs={"property": "og:title"}).get(
                    "content", ""
                )
                if soup.find("meta", attrs={"property": "og:title"})
                else "",
                "og_description": soup.find(
                    "meta", attrs={"property": "og:description"}
                ).get("content", "")
                if soup.find("meta", attrs={"property": "og:description"})
                else "",
            }
            return {
                "success": True,
                "operation": op,
                "output": meta,
                "url": url,
            }

        else:
            return self._error(f"Unknown operation: {op}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "output": f"Error: {msg}"}


# Backwards-compatible alias used by older tests/imports.
class WebFetchTool(WebFetchOperationTool):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @staticmethod
    def _extract_url_from_prompt(prompt: str) -> str:
        match = re.search(r"https?://[^\s)\]]+", prompt)
        return match.group(0).rstrip(".,;!?") if match else ""

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        prompt = str(kwargs.get("prompt", "")).strip()
        url = str(kwargs.get("url", "")).strip()

        if not prompt and not url:
            return self._error("prompt is required")

        if not url and prompt:
            url = self._extract_url_from_prompt(prompt)
            if not url:
                return self._error("No valid HTTP/HTTPS URLs found in prompt")

        err = self._validate_url(url)
        if err:
            return self._error(err)

        fallback = getattr(self, "_fetch_fallback", None)
        if callable(fallback):
            result = fallback(url, prompt)
            if asyncio.iscoroutine(result):
                result = await result
            return {
                "success": True,
                "operation": kwargs.get("operation", "fetch"),
                "output": result,
                "url": url,
            }

        operation = kwargs.get("operation", "fetch")
        if operation == "summarize" and prompt:
            return await super().execute(operation="summarize", url=url, prompt=prompt)
        return await super().execute(operation="fetch", url=url)
