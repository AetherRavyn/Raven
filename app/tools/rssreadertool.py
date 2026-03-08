# app/tools/rssreadertool.py
"""RSSReaderTool — read and summarize RSS feeds."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    import feedparser
except ImportError:
    feedparser = None


class RSSReaderTool(BaseTool):
    """Read and parse RSS/Atom feeds, get headlines, and summarize content."""

    def get_name(self) -> str:
        return "rss_reader"

    def get_description(self) -> str:
        return (
            "Read RSS and Atom feeds, get latest headlines, "
            "fetch full article content, and list available feeds."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=["fetch", "headlines", "list_feeds", "summarize"],
                ),
                ToolParameter(
                    name="feed_url",
                    type="string",
                    description="URL of the RSS/Atom feed",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of items to return",
                    required=False,
                ),
                ToolParameter(
                    name="feed_urls",
                    type="string",
                    description="Comma-separated list of feed URLs (for headlines operation)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if feedparser is None:
            return {
                "success": False,
                "error": "feedparser not installed. pip install feedparser",
            }

        operation = kwargs.get("operation", "fetch")
        feed_url = kwargs.get("feed_url", "")
        limit = kwargs.get("limit", 5)
        feed_urls_str = kwargs.get("feed_urls", "")

        try:
            if operation == "fetch":
                if not feed_url:
                    return {"success": False, "error": "feed_url required"}
                feed = feedparser.parse(feed_url)
                entries = feed.entries[:limit]
                items = []
                for entry in entries:
                    items.append(
                        {
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "summary": entry.get("summary", "")[:500],
                            "author": entry.get("author", ""),
                        }
                    )
                return {
                    "success": True,
                    "feed_title": feed.feed.get("title", ""),
                    "feed_description": feed.feed.get("description", ""),
                    "items": items,
                }

            if operation == "headlines":
                if not feed_urls_str:
                    return {
                        "success": False,
                        "error": "feed_urls (comma-separated) required",
                    }
                feed_urls = [u.strip() for u in feed_urls_str.split(",")]
                all_headlines = []
                async with httpx.AsyncClient(timeout=30) as client:
                    for url in feed_urls[:5]:
                        try:
                            feed = feedparser.parse(url)
                            for entry in feed.entries[:3]:
                                all_headlines.append(
                                    {
                                        "feed": feed.feed.get("title", url),
                                        "title": entry.get("title", ""),
                                        "link": entry.get("link", ""),
                                        "published": entry.get("published", "")[:22],
                                    }
                                )
                        except Exception:
                            continue
                return {
                    "success": True,
                    "headlines": all_headlines[: limit * 3],
                }

            if operation == "list_feeds":
                default_feeds = [
                    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
                    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
                    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/rss.xml"},
                    {
                        "name": "NASA",
                        "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
                    },
                ]
                return {"success": True, "feeds": default_feeds}

            if operation == "summarize":
                if not feed_url:
                    return {"success": False, "error": "feed_url required"}
                feed = feedparser.parse(feed_url)
                entries = feed.entries[:limit]
                items = []
                for entry in entries:
                    items.append(
                        {
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "summary": entry.get("summary", "")[:300] + "...",
                        }
                    )
                return {
                    "success": True,
                    "feed_title": feed.feed.get("title", ""),
                    "articles": items,
                    "note": "For full summaries, use web_fetch tool on article links",
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.exception("RSSReaderTool error")
            return {"success": False, "error": str(exc)}
