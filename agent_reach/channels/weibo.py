# -*- coding: utf-8 -*-
"""Weibo — check whether mcporter + mcp-server-weibo is available."""

import shutil
import subprocess
from .base import Channel


class WeiboChannel(Channel):
    name = "weibo"
    description = "Weibo posts and trending topics"
    backends = ["mcp-server-weibo"]
    tier = 1

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "weibo.com" in d or "weibo.cn" in d

    def check(self, config=None):
        mcporter = shutil.which("mcporter")
        if not mcporter:
            return "off", (
                "Requires mcporter + mcp-server-weibo. Install steps:\n"
                "  1. npm install -g mcporter\n"
                "  2. pip install git+https://github.com/Panniantong/mcp-server-weibo.git\n"
                "  3. mcporter config add weibo --command 'mcp-server-weibo'\n"
                "  See https://github.com/Panniantong/mcp-server-weibo"
            )
        try:
            r = subprocess.run(
                [mcporter, "config", "list"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if "weibo" not in r.stdout:
                return "off", (
                    "mcporter is installed but the Weibo MCP is not configured. Run:\n"
                    "  pip install git+https://github.com/Panniantong/mcp-server-weibo.git\n"
                    "  mcporter config add weibo --command 'mcp-server-weibo'"
                )
        except Exception:
            return "off", "mcporter connection error"
        try:
            r = subprocess.run(
                [mcporter, "list", "weibo"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if r.returncode == 0 and "search_users" in r.stdout:
                return (
                    "ok",
                    "Fully available (trending topics, search, user feeds, comments)",
                )
            return (
                "warn",
                "MCP is configured but tool loading failed. Check the mcp-server-weibo version",
            )
        except Exception:
            return (
                "warn",
                "MCP connection error. Check whether mcp-server-weibo is available",
            )
