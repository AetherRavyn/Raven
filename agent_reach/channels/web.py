# -*- coding: utf-8 -*-
"""Web — any URL via Jina Reader. Always available."""

from .base import Channel


class WebChannel(Channel):
    name = "web"
    description = "Any web page"
    backends = ["Jina Reader"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        return True  # Fallback — handles any URL

    def check(self, config=None):
        return (
            "ok",
            "Read any web page through Jina Reader (curl https://r.jina.ai/URL)",
        )
