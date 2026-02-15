import re
import requests
import ipaddress
import socket
import google.generativeai as genai
from urllib.parse import urlparse
from typing import Any, Dict, List, Tuple
from bs4 import BeautifulSoup
from app.tools.base import BaseTool, ToolParameter, ToolSchema
# Assuming BaseTool, ToolSchema, ToolParameter are defined in your 'base_tool.py'


class WebFetchTool(BaseTool):
    def __init__(self, google_api_key: str):
        """
        Args:
            google_api_key: API key for Gemini to perform the analysis.
        """
        genai.configure(api_key=google_api_key)
        # Using 'gemini-1.5-flash' for speed, or switch to 'gemini-1.5-pro' for complex reasoning
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.MAX_CONTENT_LENGTH = 100_000
        self.URL_FETCH_TIMEOUT = 10
        self.USER_AGENT = 'Mozilla/5.0 (compatible; AI-Agent/1.0)'

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
                    description="The prompt containing URL(s) and instructions.",
                    required=True
                )
            ]
        )

    def _extract_urls(self, text: str) -> Tuple[List[str], List[str]]:
        """
        Robustly extracts valid HTTP/HTTPS URLs from the text.
        """
        # Regex is safer than split() for URLs adjacent to punctuation
        url_pattern = r'(https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})+(?::\d+)?(?:/[^\s]*)?)'
        
        found_urls = re.findall(url_pattern, text)
        valid_urls = []
        errors = []

        for url in found_urls:
            # Clean trailing punctuation often caught by regex (e.g., "http://site.com.")
            url = url.rstrip('.,;!?')
            
            try:
                result = urlparse(url)
                if result.scheme in ['http', 'https']:
                    valid_urls.append(url)
                else:
                    errors.append(f"Unsupported protocol in: {url}")
            except Exception:
                errors.append(f"Malformed URL: {url}")

        if not valid_urls and not errors and "http" in text:
             # Fallback for messy inputs
             errors.append("Potential URL detected but could not be parsed.")

        return valid_urls, errors

    def _is_private_ip(self, url: str) -> bool:
        """
        SSRF Protection: Checks if a URL resolves to a private/local IP.
        Returns True if private/unsafe, False if public/safe.
        """
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return True # Block invalid hostnames
            
            # Resolve DNS
            ip = socket.gethostbyname(hostname)
            
            # Check for private IP ranges (127.0.0.1, 192.168.x.x, etc.)
            return ipaddress.ip_address(ip).is_private
        except socket.gaierror:
            # DNS resolution failed - treat as unsafe/unreachable
            return True
        except Exception:
            return True

    def _fetch_fallback(self, url: str, prompt: str) -> str:
        """
        Manual Fetch Strategy:
        1. GET request
        2. Clean HTML -> Text
        3. Feed Text -> LLM for answer
        """
        # Handle GitHub blob URLs (convert to raw)
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

        try:
            headers = {'User-Agent': self.USER_AGENT}
            response = requests.get(url, headers=headers, timeout=self.URL_FETCH_TIMEOUT)
            response.raise_for_status() # Raises HTTPError for 4xx/5xx

            # Parse Content
            content_type = response.headers.get('Content-Type', '').lower()
            raw_text = ""

            if 'text/html' in content_type:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Remove junk tags
                for tag in soup(["script", "style", "nav", "footer", "iframe", "noscript"]):
                    tag.decompose()
                raw_text = soup.get_text(separator=' ', strip=True)
            else:
                # JSON, Raw Text, Code
                raw_text = response.text

            # Safety Truncation
            if len(raw_text) > self.MAX_CONTENT_LENGTH:
                raw_text = raw_text[:self.MAX_CONTENT_LENGTH] + "\n...[Content Truncated]"

            # RAG Step: Feed content to Gemini
            rag_prompt = (
                f"User Request: '{prompt}'\n\n"
                f"I have fetched the website content below. "
                f"Answer the user's request using ONLY this content.\n\n"
                f"--- WEBSITE CONTENT ---\n{raw_text}\n--- END CONTENT ---"
            )
            
            result = self.model.generate_content(rag_prompt)
            return result.text if result.text else "Error: Model generated empty response."

        except requests.exceptions.Timeout:
            return f"Error: Request to {url} timed out after {self.URL_FETCH_TIMEOUT}s."
        except requests.exceptions.HTTPError as e:
            return f"Error: HTTP {e.response.status_code} - {e.response.reason}."
        except requests.exceptions.RequestException as e:
            return f"Error: Network failure ({str(e)})."
        except Exception as e:
            return f"System Error during fetch: {str(e)}"

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Main execution logic.
        """
        prompt = kwargs.get("prompt")
        if not prompt:
            return {"success": False, "output": "Error: 'prompt' argument is required."}

        # 1. Parse URLs
        valid_urls, errors = self._extract_urls(prompt)
        if errors:
            return {"success": False, "output": f"URL Parsing Errors: {'; '.join(errors)}"}
        if not valid_urls:
            return {"success": False, "output": "No valid HTTP/HTTPS URLs found in prompt."}

        target_url = valid_urls[0]

        # 2. Security Check
        if self._is_private_ip(target_url):
            return {
                "success": False, 
                "output": f"Security Error: Access to {target_url} is blocked (Private/Local IP detected)."
            }

        # 3. Strategy: Fallback (Manual Fetch)
        # Note: We skip direct model web-fetch (Google Search Grounding) here as it requires 
        # complex specific configuration. We default to the robust Manual Fetch strategy.
        
        print(f"[WebFetch] Fetching: {target_url}")
        output_text = self._fetch_fallback(target_url, prompt)
        
        # Check if the output indicates an error caught inside _fetch_fallback
        if output_text.startswith("Error:"):
             return {"success": False, "output": output_text}

        return {
            "success": True,
            "output": output_text
        }