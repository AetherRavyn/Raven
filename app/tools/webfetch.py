from __future__ import annotations

import ipaddress
import re
import socket
import warnings
from typing import Any, Dict, List, Tuple
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


class WebFetchTool(BaseTool):
    def __init__(self, google_api_key: str | None = None, model: Any | None = None):
        api_key = google_api_key or Config.GEMINI_API_KEY
        self._sdk_mode = "injected"
        self.model = None
        self._client = None
        self._model_name = "gemini-2.5-flash"

        if model is not None:
            self.model = model
        else:
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not configured.")
            try:
                from google import genai  # type: ignore

                self._client = genai.Client(api_key=api_key)
                self._sdk_mode = "new"
            except ImportError:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", FutureWarning)
                        import google.generativeai as genai  # type: ignore
                except ImportError as e:
                    raise ImportError(
                        "Install `google-genai` (preferred) or `google-generativeai` for WebFetchTool."
                    ) from e
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                self._sdk_mode = "legacy"

        self.MAX_CONTENT_LENGTH = 100_000
        self.URL_FETCH_TIMEOUT = 10
        self.USER_AGENT = "Mozilla/5.0 (compatible; AI-Agent/1.0)"

    def get_name(self) -> str:
        return "web_fetch"

    def get_description(self) -> str:
        return "Fetches content from URLs and processes it based on the user's prompt."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Prompt containing URL(s) and instructions",
                    required=True,
                )
            ],
        )

    def _extract_urls(self, text: str) -> Tuple[List[str], List[str]]:
        url_pattern = (
            r"(https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})+(?::\d+)?(?:/[^\s]*)?)"
        )
        found_urls = re.findall(url_pattern, text)
        valid_urls: list[str] = []
        errors: list[str] = []

        for url in found_urls:
            url = url.rstrip(".,;!?")
            try:
                result = urlparse(url)
                if result.scheme in ["http", "https"]:
                    valid_urls.append(url)
                else:
                    errors.append(f"Unsupported protocol in: {url}")
            except Exception:
                errors.append(f"Malformed URL: {url}")

        if not valid_urls and not errors and "http" in text:
            errors.append("Potential URL detected but could not be parsed.")
        return valid_urls, errors

    def _is_private_ip(self, url: str) -> bool:
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return True
            ip = socket.gethostbyname(hostname)
            return ipaddress.ip_address(ip).is_private
        except Exception:
            return True

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

    def _fetch_fallback(self, url: str, prompt: str) -> str:
        if requests is None:
            return "Error: requests package is not installed."

        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace(
                "/blob/", "/"
            )

        try:
            headers = {"User-Agent": self.USER_AGENT}
            response = requests.get(
                url, headers=headers, timeout=self.URL_FETCH_TIMEOUT
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()
            raw_text = ""

            if "text/html" in content_type:
                if BeautifulSoup is None:
                    return "Error: beautifulsoup4 package is not installed."
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(
                    ["script", "style", "nav", "footer", "iframe", "noscript"]
                ):
                    tag.decompose()
                raw_text = soup.get_text(separator=" ", strip=True)
            else:
                raw_text = response.text

            if len(raw_text) > self.MAX_CONTENT_LENGTH:
                raw_text = (
                    raw_text[: self.MAX_CONTENT_LENGTH] + "\n...[Content Truncated]"
                )

            rag_prompt = (
                f"User Request: '{prompt}'\n\n"
                f"I have fetched the website content below. "
                f"Answer the user's request using ONLY this content.\n\n"
                f"--- WEBSITE CONTENT ---\n{raw_text}\n--- END CONTENT ---"
            )
            text = self._generate_answer(rag_prompt)
            return text if text else "Error: Model generated empty response."

        except requests.exceptions.Timeout:
            return f"Error: Request to {url} timed out after {self.URL_FETCH_TIMEOUT}s."
        except requests.exceptions.HTTPError as e:
            return f"Error: HTTP {e.response.status_code} - {e.response.reason}."
        except requests.exceptions.RequestException as e:
            return f"Error: Network failure ({str(e)})."
        except Exception as e:
            return f"System Error during fetch: {str(e)}"

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        prompt = kwargs.get("prompt")
        if not prompt:
            return {"success": False, "output": "Error: 'prompt' argument is required."}

        valid_urls, errors = self._extract_urls(prompt)
        if errors:
            return {
                "success": False,
                "output": f"URL Parsing Errors: {'; '.join(errors)}",
            }
        if not valid_urls:
            return {
                "success": False,
                "output": "No valid HTTP/HTTPS URLs found in prompt.",
            }

        target_url = valid_urls[0]
        if self._is_private_ip(target_url):
            return {
                "success": False,
                "output": f"Security Error: Access to {target_url} is blocked (Private/Local IP detected).",
            }

        output_text = self._fetch_fallback(target_url, prompt)
        if output_text.startswith("Error:"):
            return {"success": False, "output": output_text}
        return {"success": True, "output": output_text}
