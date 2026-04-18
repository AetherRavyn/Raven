# -*- coding: utf-8 -*-
"""WeChat Official Account articles — read and search.

Read:   wechat-article-for-ai (Camoufox stealth browser)
Search: miku_ai (Sogou WeChat search)
"""

import shutil
import subprocess
from .base import Channel


class WeChatChannel(Channel):
    name = "wechat"
    description = "WeChat Official Account articles"
    backends = ["wechat-article-for-ai (Camoufox)", "miku_ai (Sogou search)"]
    tier = 2

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "mp.weixin.qq.com" in d or "weixin.qq.com" in d

    def check(self, config=None):
        has_read = False
        has_search = False

        try:
            import camoufox  # noqa: F401

            has_read = True
        except ImportError:
            pass

        try:
            import miku_ai  # noqa: F401

            has_search = True
        except ImportError:
            pass

        if has_read and has_search:
            return "ok", "Fully available (search + read WeChat articles)"
        elif has_read:
            return (
                "ok",
                "Can read WeChat articles (URL -> Markdown). Install miku_ai to unlock search: pip install miku_ai",
            )
        elif has_search:
            return "warn", (
                "Can search WeChat articles but cannot read full articles. Install the reader tool:\n"
                "  pip install camoufox[geoip] markdownify beautifulsoup4 httpx mcp"
            )
        else:
            return "off", (
                "WeChat article tools are required:\n"
                "  # Read (URL -> Markdown):\n"
                "  pip install camoufox[geoip] markdownify beautifulsoup4 httpx mcp\n"
                "  # Search (keyword -> article list):\n"
                "  pip install miku_ai\n"
                "  See https://github.com/bzd6661/wechat-article-for-ai"
            )
