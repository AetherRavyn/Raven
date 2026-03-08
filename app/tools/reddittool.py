from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import requests
from praw import Reddit
from praw.models import Submission

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class RedditTool(BaseTool):
    """Reddit operations: hot posts, search subreddits, get post comments.
    Uses PRAW (Reddit API) with client_id/secret fallback to scraping."""

    def __init__(self, **cfg: Any):
        self._client_id = cfg.get("client_id") or os.environ.get("REDDIT_CLIENT_ID")
        self._client_secret = cfg.get("client_secret") or os.environ.get(
            "REDDIT_CLIENT_SECRET"
        )
        self._user_agent = cfg.get("user_agent", "SARAS/1.0")
        self._username = cfg.get("username") or os.environ.get("REDDIT_USERNAME")
        self._password = cfg.get("password") or os.environ.get("REDDIT_PASSWORD")
        self.MAX_RESULTS = min(int(cfg.get("max_results", 10)), 25)

    def get_name(self) -> str:
        return "reddit_ops"

    def get_description(self) -> str:
        return (
            "Reddit operations: get hot posts from a subreddit, "
            "search posts, or get comments from a specific post. "
            "Returns post title, content, score, and comments."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: hot, search, or comments",
                    required=True,
                    enum=["hot", "search", "comments"],
                ),
                ToolParameter(
                    name="subreddit",
                    type="string",
                    description="Subreddit name (without r/), or full post URL for comments",
                    required=True,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (only for search operation)",
                    required=False,
                ),
                ToolParameter(
                    name="count",
                    type="integer",
                    description=f"Number of results (1-{self.MAX_RESULTS}, default 10)",
                    required=False,
                ),
            ],
        )

    def _get_reddit(self) -> Optional[Reddit]:
        if self._client_id and self._client_secret:
            try:
                return Reddit(
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                    user_agent=self._user_agent,
                    username=self._username,
                    password=self._password,
                )
            except Exception:
                pass
        return None

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        subreddit = str(kwargs.get("subreddit", "")).strip()
        if not subreddit:
            return self._error("subreddit parameter is required")

        count = min(int(kwargs.get("count", 10)), self.MAX_RESULTS)
        query = kwargs.get("query", "")

        reddit = self._get_reddit()

        try:
            if op == "hot":
                return await asyncio.to_thread(self._get_hot, reddit, subreddit, count)
            elif op == "search":
                return await asyncio.to_thread(
                    self._search, reddit, subreddit, query, count
                )
            elif op == "comments":
                return await asyncio.to_thread(
                    self._get_comments, reddit, subreddit, count
                )
            else:
                return self._error(f"Unknown operation: {op}")
        except Exception as e:
            return self._error(f"Reddit operation failed: {e}")

    def _get_hot(
        self, reddit: Optional[Reddit], subreddit: str, count: int
    ) -> Dict[str, Any]:
        if not reddit:
            return self._error(
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not configured"
            )

        try:
            sub = reddit.subreddit(subreddit)
            posts = []
            for post in sub.hot(limit=count):
                posts.append(self._format_post(post))
            return {
                "success": True,
                "operation": "hot",
                "subreddit": subreddit,
                "count": len(posts),
                "results": posts,
            }
        except Exception as e:
            return self._error(f"Failed to get hot posts: {e}")

    def _search(
        self, reddit: Optional[Reddit], subreddit: str, query: str, count: int
    ) -> Dict[str, Any]:
        if not reddit:
            return self._error(
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not configured"
            )

        if not query:
            return self._error("query parameter required for search operation")

        try:
            sub = reddit.subreddit(subreddit)
            posts = []
            for post in sub.search(query, limit=count):
                posts.append(self._format_post(post))
            return {
                "success": True,
                "operation": "search",
                "subreddit": subreddit,
                "query": query,
                "count": len(posts),
                "results": posts,
            }
        except Exception as e:
            return self._error(f"Failed to search: {e}")

    def _get_comments(
        self, reddit: Optional[Reddit], post_url: str, count: int
    ) -> Dict[str, Any]:
        if not reddit:
            return self._error(
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not configured"
            )

        try:
            submission = reddit.submission(url=post_url)
            submission.comments.replace_more(limit=0)
            comments = []
            for comment in submission.comments[:count]:
                comments.append(
                    {
                        "author": str(comment.author)
                        if comment.author
                        else "[deleted]",
                        "body": comment.body[:500],
                        "score": comment.score,
                        "created_utc": comment.created_utc,
                    }
                )
            return {
                "success": True,
                "operation": "comments",
                "post_url": post_url,
                "count": len(comments),
                "results": comments,
            }
        except Exception as e:
            return self._error(f"Failed to get comments: {e}")

    def _format_post(self, post: Submission) -> Dict[str, Any]:
        return {
            "id": post.id,
            "title": post.title,
            "selftext": post.selftext[:500] if post.is_self else "",
            "url": post.url,
            "score": post.score,
            "num_comments": post.num_comments,
            "created_utc": post.created_utc,
            "permalink": post.permalink,
            "author": str(post.author) if post.author else "[deleted]",
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "results": []}
