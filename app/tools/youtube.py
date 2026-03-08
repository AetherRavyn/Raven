from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import requests
from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class YouTubeTool(BaseTool):
    """YouTube operations: search videos, get transcripts, get channel info.
    Uses YouTube Data API v3 or scraping fallback."""

    def __init__(self, **cfg: Any):
        self._api_key = cfg.get("api_key") or os.environ.get("YOUTUBE_API_KEY")
        self.MAX_RESULTS = min(int(cfg.get("max_results", 10)), 20)

    def get_name(self) -> str:
        return "youtube_ops"

    def get_description(self) -> str:
        return (
            "YouTube operations: search videos, get video details, "
            "or fetch transcripts (if available). "
            "Returns video title, description, channel, view count, and transcript."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: search, details, or transcript",
                    required=True,
                    enum=["search", "details", "transcript"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query or video URL/ID",
                    required=True,
                ),
                ToolParameter(
                    name="count",
                    type="integer",
                    description=f"Number of results (1-{self.MAX_RESULTS}, default 10)",
                    required=False,
                ),
            ],
        )

    def _extract_video_id(self, query: str) -> Optional[str]:
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
            r"^([0-9A-Za-z_-]{11})$",
        ]
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)
        return None

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return self._error("query parameter is required")

        count = min(int(kwargs.get("count", 10)), self.MAX_RESULTS)

        try:
            if op == "search":
                return await asyncio.to_thread(self._search_videos, query, count)
            elif op == "details":
                return await asyncio.to_thread(self._get_details, query)
            elif op == "transcript":
                return await asyncio.to_thread(self._get_transcript, query)
            else:
                return self._error(f"Unknown operation: {op}")
        except Exception as e:
            return self._error(f"YouTube operation failed: {e}")

    def _search_videos(self, query: str, count: int) -> Dict[str, Any]:
        if not self._api_key:
            return self._error("YOUTUBE_API_KEY not configured")

        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": count,
            "key": self._api_key,
        }

        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return self._error(f"YouTube API error: {resp.status_code}")

        data = resp.json()
        results = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            results.append(
                {
                    "video_id": item.get("id", {}).get("videoId"),
                    "title": snippet.get("title"),
                    "description": snippet.get("description", "")[:200],
                    "channel_title": snippet.get("channelTitle"),
                    "published_at": snippet.get("publishedAt"),
                    "thumbnail": snippet.get("thumbnails", {})
                    .get("high", {})
                    .get("url"),
                }
            )

        return {
            "success": True,
            "operation": "search",
            "query": query,
            "count": len(results),
            "results": results,
        }

    def _get_details(self, query: str) -> Dict[str, Any]:
        if not self._api_key:
            return self._error("YOUTUBE_API_KEY not configured")

        video_id = self._extract_video_id(query)
        if not video_id:
            return self._error("Invalid video URL or ID")

        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": self._api_key,
        }

        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return self._error(f"YouTube API error: {resp.status_code}")

        data = resp.json()
        items = data.get("items", [])
        if not items:
            return self._error("Video not found")

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})

        return {
            "success": True,
            "operation": "details",
            "video_id": video_id,
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "channel_title": snippet.get("channelTitle"),
            "published_at": snippet.get("publishedAt"),
            "view_count": stats.get("viewCount"),
            "like_count": stats.get("likeCount"),
            "comment_count": stats.get("commentCount"),
            "duration": content.get("duration"),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
        }

    def _get_transcript(self, query: str) -> Dict[str, Any]:
        video_id = self._extract_video_id(query)
        if not video_id:
            return self._error("Invalid video URL or ID")

        # Use YouTube transcript API (unofficial but works)
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            text = " ".join([t["text"] for t in transcript])
            return {
                "success": True,
                "operation": "transcript",
                "video_id": video_id,
                "transcript": text[:5000],  # Limit to 5000 chars
            }
        except ImportError:
            return self._error("youtube-transcript-api not installed")
        except Exception as e:
            return self._error(f"Transcript unavailable: {e}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}
