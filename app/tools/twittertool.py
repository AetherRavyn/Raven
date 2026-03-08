from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import requests

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class TwitterTool(BaseTool):
    """Twitter/X operations: trending topics, user tweets, hashtag search.
    Uses the free X API v2 (limited) or scraping fallback."""

    def __init__(self, **cfg: Any):
        self._bearer_token = cfg.get("bearer_token") or os.environ.get(
            "TWITTER_BEARER_TOKEN"
        )
        self._api_key = cfg.get("api_key") or os.environ.get("TWITTER_API_KEY")
        self._api_secret = cfg.get("api_secret") or os.environ.get("TWITTER_API_SECRET")
        self.MAX_RESULTS = min(int(cfg.get("max_results", 10)), 20)

    def get_name(self) -> str:
        return "twitter_ops"

    def get_description(self) -> str:
        return (
            "Twitter/X operations: search tweets, get user tweets, "
            "search hashtags, or get trending topics. "
            "Returns tweet text, author, metrics, and URLs."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: search_tweets, user_tweets, hashtag, or trending",
                    required=True,
                    enum=["search_tweets", "user_tweets", "hashtag", "trending"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query, username (without @), or hashtag (without #)",
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

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return self._error("query parameter is required")

        count = min(int(kwargs.get("count", 10)), self.MAX_RESULTS)

        try:
            if op == "trending":
                return await asyncio.to_thread(self._get_trending, count)
            elif op == "hashtag":
                return await asyncio.to_thread(self._search_hashtag, query, count)
            elif op == "user_tweets":
                return await asyncio.to_thread(self._get_user_tweets, query, count)
            else:  # search_tweets
                return await asyncio.to_thread(self._search_tweets, query, count)
        except Exception as e:
            return self._error(f"Twitter operation failed: {e}")

    def _get_bearer_token(self) -> Optional[str]:
        if self._bearer_token:
            return self._bearer_token
        return os.environ.get("TWITTER_BEARER_TOKEN")

    def _search_tweets(self, query: str, count: int) -> Dict[str, Any]:
        bearer = self._get_bearer_token()
        if not bearer:
            return self._error("TWITTER_BEARER_TOKEN not configured")

        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": query,
            "max_results": count,
            "tweet.fields": "created_at,public_metrics,author_id",
        }
        headers = {"Authorization": f"Bearer {bearer}"}

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return self._error(f"Twitter API error: {resp.status_code} {resp.text}")

        data = resp.json()
        tweets = []
        for item in data.get("data", []):
            tweets.append(
                {
                    "id": item.get("id"),
                    "text": item.get("text", ""),
                    "author_id": item.get("author_id"),
                    "created_at": item.get("created_at"),
                    "metrics": item.get("public_metrics", {}),
                }
            )

        return {
            "success": True,
            "operation": "search_tweets",
            "count": len(tweets),
            "results": tweets,
        }

    def _get_user_tweets(self, username: str, count: int) -> Dict[str, Any]:
        bearer = self._get_bearer_token()
        if not bearer:
            return self._error("TWITTER_BEARER_TOKEN not configured")

        # First get user ID
        user_url = f"https://api.twitter.com/2/users/by/username/{username}"
        headers = {"Authorization": f"Bearer {bearer}"}
        user_resp = requests.get(user_url, headers=headers, timeout=15)
        if user_resp.status_code != 200:
            return self._error(f"User not found: {username}")
        user_id = user_resp.json().get("data", {}).get("id")
        if not user_id:
            return self._error(f"Could not resolve user: {username}")

        # Then get tweets
        tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
        params = {"max_results": count, "tweet.fields": "created_at,public_metrics"}
        resp = requests.get(tweets_url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return self._error(f"Twitter API error: {resp.status_code}")

        data = resp.json()
        tweets = []
        for item in data.get("data", []):
            tweets.append(
                {
                    "id": item.get("id"),
                    "text": item.get("text", ""),
                    "created_at": item.get("created_at"),
                    "metrics": item.get("public_metrics", {}),
                }
            )

        return {
            "success": True,
            "operation": "user_tweets",
            "username": username,
            "count": len(tweets),
            "results": tweets,
        }

    def _search_hashtag(self, hashtag: str, count: int) -> Dict[str, Any]:
        # Remove # if present
        hashtag = hashtag.lstrip("#")
        return self._search_tweets(f"#{hashtag}", count)

    def _get_trending(self, count: int) -> Dict[str, Any]:
        bearer = self._get_bearer_token()
        if not bearer:
            return self._error("TWITTER_BEARER_TOKEN not configured")

        # Use Twitter's search/recent for trending approximation
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": "trending OR viral OR breaking -is:retweet",
            "max_results": min(count, 20),
            "tweet.fields": "created_at,public_metrics",
        }
        headers = {"Authorization": f"Bearer {bearer}"}

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return self._error(f"Twitter API error: {resp.status_code}")

        data = resp.json()
        tweets = []
        for item in data.get("data", []):
            tweets.append(
                {
                    "id": item.get("id"),
                    "text": item.get("text", ""),
                    "created_at": item.get("created_at"),
                    "metrics": item.get("public_metrics", {}),
                }
            )

        return {
            "success": True,
            "operation": "trending",
            "count": len(tweets),
            "results": tweets,
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "results": []}
