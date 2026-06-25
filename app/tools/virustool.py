from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.settings.config import Config
from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema


class VirusTotalTool(BaseTool):
    """VirusTotal API v3 scanner and reputation lookup tool."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://www.virustotal.com/api/v3",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key or (Config.VIRUSTOTAL_API_KEY or "")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_name(self) -> str:
        return "virustotal_scanner"

    def get_description(self) -> str:
        return (
            "Scan and lookup indicators/files with VirusTotal API v3: URLs, file hashes, "
            "domains, IPs, analyses, and file submissions."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="VirusTotal operation to execute",
                    required=True,
                    enum=[
                        "scan_url",
                        "get_url_report",
                        "get_file_report",
                        "get_domain_report",
                        "get_ip_report",
                        "get_analysis",
                        "upload_file",
                        "scan_and_wait_url",
                        "scan_and_wait_file",
                        "auto_lookup",
                    ],
                ),
                ToolParameter(
                    name="indicator",
                    type="string",
                    description="IOC auto-detection input (url/hash/domain/ip) for auto_lookup",
                    required=False,
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to scan or lookup",
                    required=False,
                ),
                ToolParameter(
                    name="file_hash",
                    type="string",
                    description="File hash (sha256 preferred) for lookup",
                    required=False,
                ),
                ToolParameter(
                    name="domain",
                    type="string",
                    description="Domain for lookup",
                    required=False,
                ),
                ToolParameter(
                    name="ip_address",
                    type="string",
                    description="IP address for lookup",
                    required=False,
                ),
                ToolParameter(
                    name="analysis_id",
                    type="string",
                    description="Analysis ID for status/result lookup",
                    required=False,
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Local path to file for upload and scanning",
                    required=False,
                ),
                ToolParameter(
                    name="max_polls",
                    type="integer",
                    description="Max analysis polling rounds for scan_and_wait operations",
                    required=False,
                ),
                ToolParameter(
                    name="poll_interval_seconds",
                    type="integer",
                    description="Seconds between polling calls for scan_and_wait operations",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["security.scan"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="confirm",
            readonly=True,
        )

    def _require_api_key(self) -> None:
        if not self.api_key:
            raise ValueError(
                "VirusTotal API key is missing. Set VIRUSTOTAL_API_KEY environment variable."
            )

    def _headers(self) -> dict[str, str]:
        return {"x-apikey": self.api_key}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> Dict[str, Any]:
        self._require_api_key()
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        headers = self._headers().copy()
        body: bytes | None = None

        if files:
            boundary = "----raven_vt_boundary"
            parts: list[bytes] = []
            for field_name, (filename, content, content_type) in files.items():
                parts.extend(
                    [
                        f"--{boundary}\r\n".encode(),
                        (
                            f'Content-Disposition: form-data; name="{field_name}"; '
                            f'filename="{filename}"\r\n'
                        ).encode(),
                        f"Content-Type: {content_type}\r\n\r\n".encode(),
                        content,
                        b"\r\n",
                    ]
                )
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data:
            body = urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        def _send() -> Dict[str, Any]:
            req = Request(url=url, data=body, headers=headers, method=method.upper())
            try:
                with urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {"raw": raw}
                    return {
                        "success": True,
                        "status_code": getattr(resp, "status", 200),
                        "data": payload,
                    }
            except HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"raw": raw}
                return {
                    "success": False,
                    "status_code": e.code,
                    "error": payload.get("error", payload),
                }
            except URLError as e:
                return {"success": False, "error": f"Network error: {str(e)}"}

        return await asyncio.to_thread(_send)

    @staticmethod
    def _url_id(url: str) -> str:
        encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
        return encoded.rstrip("=")

    @staticmethod
    def _extract_stats(data: dict[str, Any]) -> Dict[str, Any]:
        attrs = data.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats") or attrs.get("stats") or {}
        return {
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "harmless": stats.get("harmless", 0),
            "undetected": stats.get("undetected", 0),
            "timeout": stats.get("timeout", 0),
        }

    async def _wait_analysis(
        self, analysis_id: str, max_polls: int, poll_interval_seconds: int
    ) -> Dict[str, Any]:
        max_polls = max(1, min(max_polls, 60))
        poll_interval_seconds = max(1, min(poll_interval_seconds, 30))
        for _ in range(max_polls):
            res = await self._request("GET", f"/analyses/{analysis_id}")
            if not res.get("success"):
                return res
            status = (
                res.get("data", {}).get("data", {}).get("attributes", {}).get("status")
            )
            if status == "completed":
                return res
            await asyncio.sleep(poll_interval_seconds)
        return {
            "success": False,
            "error": f"Analysis did not complete within {max_polls} polls",
            "analysis_id": analysis_id,
        }

    async def execute(
        self,
        operation: str,
        indicator: str | None = None,
        url: str | None = None,
        file_hash: str | None = None,
        domain: str | None = None,
        ip_address: str | None = None,
        analysis_id: str | None = None,
        file_path: str | None = None,
        max_polls: int = 12,
        poll_interval_seconds: int = 3,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            if operation == "scan_url":
                if not url:
                    return {"success": False, "error": "url is required"}
                res = await self._request("POST", "/urls", data={"url": url})
                if not res.get("success"):
                    return res
                analysis = res.get("data", {}).get("data", {})
                return {
                    "success": True,
                    "operation": operation,
                    "analysis_id": analysis.get("id"),
                    "analysis_type": analysis.get("type"),
                }

            if operation == "get_url_report":
                target = url or indicator
                if not target:
                    return {"success": False, "error": "url is required"}
                url_id = self._url_id(target)
                res = await self._request("GET", f"/urls/{url_id}")
                if not res.get("success"):
                    return res
                return {
                    "success": True,
                    "operation": operation,
                    "url": target,
                    "url_id": url_id,
                    "stats": self._extract_stats(res.get("data", {})),
                    "raw": res.get("data"),
                }

            if operation == "get_file_report":
                target_hash = file_hash or indicator
                if not target_hash:
                    return {"success": False, "error": "file_hash is required"}
                res = await self._request("GET", f"/files/{target_hash}")
                if not res.get("success"):
                    return res
                return {
                    "success": True,
                    "operation": operation,
                    "file_hash": target_hash,
                    "stats": self._extract_stats(res.get("data", {})),
                    "raw": res.get("data"),
                }

            if operation == "get_domain_report":
                target_domain = domain or indicator
                if not target_domain:
                    return {"success": False, "error": "domain is required"}
                res = await self._request("GET", f"/domains/{target_domain}")
                if not res.get("success"):
                    return res
                return {
                    "success": True,
                    "operation": operation,
                    "domain": target_domain,
                    "stats": self._extract_stats(res.get("data", {})),
                    "raw": res.get("data"),
                }

            if operation == "get_ip_report":
                target_ip = ip_address or indicator
                if not target_ip:
                    return {"success": False, "error": "ip_address is required"}
                res = await self._request("GET", f"/ip_addresses/{target_ip}")
                if not res.get("success"):
                    return res
                return {
                    "success": True,
                    "operation": operation,
                    "ip_address": target_ip,
                    "stats": self._extract_stats(res.get("data", {})),
                    "raw": res.get("data"),
                }

            if operation == "get_analysis":
                if not analysis_id:
                    return {"success": False, "error": "analysis_id is required"}
                res = await self._request("GET", f"/analyses/{analysis_id}")
                if not res.get("success"):
                    return res
                status = (
                    res.get("data", {})
                    .get("data", {})
                    .get("attributes", {})
                    .get("status")
                )
                return {
                    "success": True,
                    "operation": operation,
                    "analysis_id": analysis_id,
                    "status": status,
                    "raw": res.get("data"),
                }

            if operation == "upload_file":
                if not file_path:
                    return {"success": False, "error": "file_path is required"}
                file_obj = Path(file_path)
                if not file_obj.exists() or not file_obj.is_file():
                    return {"success": False, "error": f"File not found: {file_path}"}
                if file_obj.stat().st_size > 32 * 1024 * 1024:
                    return {
                        "success": False,
                        "error": "File >32MB. Use /files/upload_url flow for large files.",
                    }
                content = file_obj.read_bytes()
                files = {"file": (file_obj.name, content, "application/octet-stream")}
                res = await self._request("POST", "/files", files=files)
                if not res.get("success"):
                    return res
                analysis = res.get("data", {}).get("data", {})
                return {
                    "success": True,
                    "operation": operation,
                    "analysis_id": analysis.get("id"),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "filename": file_obj.name,
                }

            if operation == "scan_and_wait_url":
                submit = await self.execute(operation="scan_url", url=url)
                if not submit.get("success"):
                    return submit
                a_id = submit.get("analysis_id")
                if not a_id:
                    return {
                        "success": False,
                        "error": "Missing analysis_id in scan response",
                    }
                waited = await self._wait_analysis(
                    a_id, max_polls, poll_interval_seconds
                )
                if not waited.get("success"):
                    return waited
                return {
                    "success": True,
                    "operation": operation,
                    "analysis_id": a_id,
                    "status": "completed",
                    "raw": waited.get("data"),
                }

            if operation == "scan_and_wait_file":
                submit = await self.execute(
                    operation="upload_file", file_path=file_path
                )
                if not submit.get("success"):
                    return submit
                a_id = submit.get("analysis_id")
                if not a_id:
                    return {
                        "success": False,
                        "error": "Missing analysis_id in upload response",
                    }
                waited = await self._wait_analysis(
                    a_id, max_polls, poll_interval_seconds
                )
                if not waited.get("success"):
                    return waited
                return {
                    "success": True,
                    "operation": operation,
                    "analysis_id": a_id,
                    "status": "completed",
                    "raw": waited.get("data"),
                }

            if operation == "auto_lookup":
                value = (
                    indicator or url or file_hash or domain or ip_address or ""
                ).strip()
                if not value:
                    return {
                        "success": False,
                        "error": "indicator is required for auto_lookup",
                    }
                if value.startswith("http://") or value.startswith("https://"):
                    return await self.execute(operation="get_url_report", url=value)
                if "/" not in value and all(ch.isdigit() or ch == "." for ch in value):
                    return await self.execute(
                        operation="get_ip_report", ip_address=value
                    )
                if "." in value and all(c.isalnum() or c in ".-" for c in value):
                    return await self.execute(
                        operation="get_domain_report", domain=value
                    )
                if len(value) in {32, 40, 64} and all(
                    c in "0123456789abcdefABCDEF" for c in value
                ):
                    return await self.execute(
                        operation="get_file_report", file_hash=value
                    )
                return {"success": False, "error": "Could not infer indicator type"}

            return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            return {"success": False, "error": f"VirusTotal tool error: {str(e)}"}
