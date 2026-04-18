# -*- coding: utf-8 -*-
"""Reddit — check connectivity and proxy configuration."""

import os
import urllib.request
from .base import Channel

_UA = "agent-reach/1.0"
_TIMEOUT = 10


def _reddit_reachable() -> bool:
    """Return True if the Reddit JSON API responds with 200 (with User-Agent)."""
    url = "https://www.reddit.com/r/linux.json?limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


class RedditChannel(Channel):
    name = "reddit"
    description = "Reddit posts and comments"
    backends = ["JSON API", "Exa"]
    tier = 1

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "reddit.com" in d or "redd.it" in d

    def check(self, config=None):
        proxy = (config.get("reddit_proxy") if config else None) or os.environ.get(
            "REDDIT_PROXY"
        )
        if proxy:
            return "ok", "Proxy configured, can read posts. Search uses Exa"
        # Actual connectivity probe (with User-Agent, required by the Reddit API)
        if _reddit_reachable():
            return (
                "ok",
                "Direct access is available (JSON API responds normally). Search uses Exa",
            )
        return "warn", (
            "No proxy is configured and the Reddit JSON API is not responding. The server IP may be blocked. Configure a proxy:\n"
            "  agent-reach configure proxy http://user:pass@ip:port"
        )
