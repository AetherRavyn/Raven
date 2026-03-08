from __future__ import annotations

import asyncio
import re
import socket
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from dateutil import parser as dateparser

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class URLMetadataTool(BaseTool):
    """Fetch metadata from any URL: OpenGraph tags, favicon, title, description, images.
    Useful for link previews and content summarization."""

    def __init__(self, **cfg: Any):
        self._timeout = int(cfg.get("timeout_seconds", 10))
        self._user_agent = cfg.get("user_agent", "SARAS/1.0 (URL Metadata Fetcher)")

    def get_name(self) -> str:
        return "url_metadata"

    def get_description(self) -> str:
        return (
            "Fetch metadata from any URL: title, description, OpenGraph tags, "
            "favicon, preview images, and social media tags. "
            "Useful for link previews and content analysis."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="The URL to fetch metadata from",
                    required=True,
                ),
                ToolParameter(
                    name="include_content",
                    type="boolean",
                    description="Also fetch first 2000 characters of page content",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        url = kwargs.get("url", "").strip()
        if not url:
            return self._error("url parameter is required")

        include_content = kwargs.get("include_content", False)

        try:
            result = await asyncio.to_thread(self._fetch_metadata, url, include_content)
            return result
        except Exception as e:
            return self._error(f"Failed to fetch metadata: {e}")

    def _fetch_metadata(self, url: str, include_content: bool) -> Dict[str, Any]:
        headers = {"User-Agent": self._user_agent}

        try:
            resp = requests.get(
                url, headers=headers, timeout=self._timeout, allow_redirects=True
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            return self._error(f"Request failed: {e}")

        html = resp.text
        final_url = resp.url

        metadata = {
            "url": final_url,
            "status_code": resp.status_code,
            "content_type": resp.headers.get("Content-Type", ""),
            "server": resp.headers.get("Server", ""),
        }

        # Extract title
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if title_match:
            metadata["title"] = title_match.group(1).strip()

        # Extract meta tags
        og_tags = {}
        meta_pattern = r'<meta\s+(?:property|name)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']'
        for match in re.finditer(meta_pattern, html, re.IGNORECASE):
            key, value = match.groups()
            og_tags[key] = value

        if og_tags.get("og:title"):
            metadata["og_title"] = og_tags["og:title"]
        if og_tags.get("og:description"):
            metadata["og_description"] = og_tags["og:description"]
        if og_tags.get("og:image"):
            metadata["og_image"] = og_tags["og:image"]
        if og_tags.get("og:url"):
            metadata["og_url"] = og_tags["og:url"]
        if og_tags.get("og:type"):
            metadata["og_type"] = og_tags["og:type"]
        if og_tags.get("twitter:card"):
            metadata["twitter_card"] = og_tags["twitter:card"]
        if og_tags.get("twitter:image"):
            metadata["twitter_image"] = og_tags["twitter:image"]

        # Description from meta
        if not metadata.get("og_description"):
            desc = og_tags.get("description") or og_tags.get("twitter:description")
            if desc:
                metadata["description"] = desc

        # Extract favicon
        favicon_match = re.search(
            r'<link[^>]*rel=["\'](?:icon|favicon)["\'][^>]*href=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if not favicon_match:
            favicon_match = re.search(
                r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\'](?:icon|favicon)["\']',
                html,
                re.IGNORECASE,
            )

        if favicon_match:
            favicon_href = favicon_match.group(1)
            if favicon_href.startswith("//"):
                metadata["favicon"] = "https:" + favicon_href
            elif favicon_href.startswith("/"):
                parsed = urlparse(final_url)
                metadata["favicon"] = f"{parsed.scheme}://{parsed.netloc}{favicon_href}"
            else:
                metadata["favicon"] = favicon_href

        # Content snippet
        if include_content:
            # Remove scripts and styles
            cleaned = re.sub(
                r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
            )
            cleaned = re.sub(
                r"<style[^>]*>.*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE
            )
            # Get text
            text = re.sub(r"<[^>]+>", " ", cleaned)
            text = re.sub(r"\s+", " ", text).strip()
            metadata["content_snippet"] = text[:2000]

        return {"success": True, "metadata": metadata}

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class SSLMonitorTool(BaseTool):
    """Check SSL certificate status for domains: expiry date, issuer, days remaining.
    Useful for monitoring certificate expiration."""

    def __init__(self, **cfg: Any):
        self._timeout = int(cfg.get("timeout_seconds", 10))

    def get_name(self) -> str:
        return "ssl_check"

    def get_description(self) -> str:
        return (
            "Check SSL certificate status for a domain: expiry date, issuer, "
            "days remaining, and certificate chain info. "
            "Useful for monitoring certificate expiration."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="domain",
                    type="string",
                    description="Domain name to check (e.g., google.com)",
                    required=True,
                ),
                ToolParameter(
                    name="port",
                    type="integer",
                    description="Port to check (default 443)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        domain = kwargs.get("domain", "").strip()
        if not domain:
            return self._error("domain parameter is required")

        port = int(kwargs.get("port", 443))

        try:
            result = await asyncio.to_thread(self._check_ssl, domain, port)
            return result
        except Exception as e:
            return self._error(f"SSL check failed: {e}")

    def _check_ssl(self, domain: str, port: int) -> Dict[str, Any]:
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

        try:
            with socket.create_connection(
                (domain, port), timeout=self._timeout
            ) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
        except socket.timeout:
            return self._error(f"Connection timeout to {domain}:{port}")
        except socket.gaierror as e:
            return self._error(f"DNS resolution failed for {domain}: {e}")
        except ssl.SSLError as e:
            return self._error(f"SSL error for {domain}: {e}")
        except Exception as e:
            return self._error(f"Connection failed to {domain}:{port}: {e}")

        # Parse certificate
        not_after = cert.get("notAfter", "")
        try:
            expiry_date = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            try:
                expiry_date = dateparser.parse(not_after)
            except Exception:
                expiry_date = None

        days_remaining = None
        if expiry_date:
            days_remaining = (expiry_date - datetime.utcnow()).days

        # Get subject and issuer
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))

        return {
            "success": True,
            "domain": domain,
            "port": port,
            "valid": days_remaining is not None and days_remaining > 0,
            "expiry_date": not_after,
            "days_remaining": days_remaining,
            "subject_cn": subject.get("commonName", ""),
            "issuer_cn": issuer.get("commonName", ""),
            "issuer_org": issuer.get("organizationName", ""),
            "protocol": ssock.version(),
            "cipher": ssock.cipher()[0] if ssock.cipher() else None,
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}
