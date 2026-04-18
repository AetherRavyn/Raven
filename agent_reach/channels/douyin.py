# -*- coding: utf-8 -*-
"""Douyin — check whether mcporter + douyin-mcp-server is available."""

import shutil
import subprocess
from .base import Channel


class DouyinChannel(Channel):
    name = "douyin"
    description = "Douyin short videos"
    backends = ["douyin-mcp-server"]
    tier = 2

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "douyin.com" in d or "iesdouyin.com" in d

    def check(self, config=None):
        mcporter = shutil.which("mcporter")
        if not mcporter:
            return "off", (
                "Requires mcporter + douyin-mcp-server. Install steps:\n"
                "  1. npm install -g mcporter\n"
                "  2. pip install douyin-mcp-server\n"
                "  3. Start the service (see the instructions below)\n"
                "  4. mcporter config add douyin http://localhost:18070/mcp\n"
                "  See https://github.com/yzfly/douyin-mcp-server"
            )
        try:
            r = subprocess.run(
                [mcporter, "config", "list"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if "douyin" not in r.stdout:
                return "off", (
                    "mcporter is installed but the Douyin MCP is not configured. Run:\n"
                    "  pip install douyin-mcp-server\n"
                    "  # After starting the service:\n"
                    "  mcporter config add douyin http://localhost:18070/mcp"
                )
        except Exception:
            return "off", "mcporter connection error"
        # Verify MCP connectivity by listing available tools instead of
        # calling with a hardcoded (invalid) share link that always fails.
        try:
            r = subprocess.run(
                [mcporter, "list", "douyin"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                return "ok", "Fully available (video parsing, download link retrieval)"
            return (
                "warn",
                "MCP is connected but the tool list is empty. Check whether the douyin-mcp-server service is running",
            )
        except Exception:
            return (
                "warn",
                "MCP connection error. Check whether the douyin-mcp-server service is running",
            )
