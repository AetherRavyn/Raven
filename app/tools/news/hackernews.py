from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, List

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

_TIMEOUT = httpx.Timeout(10.0)


class HackerNewsTool(BaseTool):
    FIREBASE_URL = "https://hacker-news.firebaseio.com/v0"
    SEARCH_URL = "https://hn.algolia.com/api/v1/search"

    def get_name(self) -> str:
        return "hacker_news"

    def get_description(self) -> str:
        return (
            "Advanced Hacker News tool for technology intelligence: "
            "retrieve top/new/best stories, search discussions, analyze "
            "trends, summarize stories, retrieve comments, inspect users, "
            "rank stories, and analyze popular domains."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    required=True,
                    description="Operation name",
                    enum=[
                        "top",
                        "new",
                        "best",
                        "ask",
                        "jobs",
                        "search",
                        "get_story",
                        "get_comments",
                        "get_user",
                        "trending_domains",
                        "keyword_filter",
                        "story_summary",
                        "ranked_stories",
                    ],
                ),
                ToolParameter(
                    name="story_id",
                    type="integer",
                    required=False,
                    description="Story ID",
                ),
                ToolParameter(
                    name="user_id",
                    type="string",
                    required=False,
                    description="User ID",
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    required=False,
                    description="Search query",
                ),
                ToolParameter(
                    name="keyword",
                    type="string",
                    required=False,
                    description="Keyword filter",
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    required=False,
                    description="Max results",
                ),
                ToolParameter(
                    name="detailed",
                    type="boolean",
                    required=False,
                    description="Include full details",
                ),
            ],
        )

    async def execute(
        self,
        operation: str,
        story_id: int | None = None,
        user_id: str | None = None,
        query: str | None = None,
        keyword: str | None = None,
        max_results: int = 10,
        detailed: bool = False,
        **_: Any,
    ) -> Dict[str, Any]:

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                if operation in ["top", "new", "best", "ask", "jobs"]:
                    endpoint_map = {
                        "top": "topstories",
                        "new": "newstories",
                        "best": "beststories",
                        "ask": "askstories",
                        "jobs": "jobstories",
                    }

                    stories = await self._story_list(
                        client,
                        endpoint_map[operation],
                        max_results,
                        detailed,
                    )

                    return {
                        "success": True,
                        "operation": operation,
                        "count": len(stories),
                        "stories": stories,
                    }

                elif operation == "search":
                    if not query:
                        return {"success": False, "error": "query required"}

                    stories = await self._search(client, query, max_results)

                    return {
                        "success": True,
                        "operation": operation,
                        "query": query,
                        "count": len(stories),
                        "stories": stories,
                    }

                elif operation == "get_story":
                    if not story_id:
                        return {"success": False, "error": "story_id required"}

                    return {
                        "success": True,
                        "story": await self._get_item(client, story_id),
                    }

                elif operation == "get_comments":
                    if not story_id:
                        return {"success": False, "error": "story_id required"}

                    comments = await self._get_comments(client, story_id)

                    return {
                        "success": True,
                        "count": len(comments),
                        "comments": comments,
                    }

                elif operation == "get_user":
                    if not user_id:
                        return {"success": False, "error": "user_id required"}

                    return {
                        "success": True,
                        "user": await self._get_user(client, user_id),
                    }

                elif operation == "trending_domains":
                    stories = await self._story_list(client, "topstories", 50, True)

                    domains = []

                    for s in stories:
                        if s.get("url"):
                            domain = s["url"].split("/")[2]
                            domains.append(domain)

                    ranking = Counter(domains).most_common(10)

                    return {
                        "success": True,
                        "domains": ranking,
                    }

                elif operation == "keyword_filter":
                    if not keyword:
                        return {"success": False, "error": "keyword required"}

                    stories = await self._story_list(client, "topstories", 50, True)

                    filtered = [
                        s for s in stories if keyword.lower() in s["title"].lower()
                    ]

                    return {
                        "success": True,
                        "keyword": keyword,
                        "count": len(filtered),
                        "stories": filtered[:max_results],
                    }

                elif operation == "story_summary":
                    if not story_id:
                        return {"success": False, "error": "story_id required"}

                    story = await self._get_item(client, story_id)

                    summary = {
                        "title": story.get("title"),
                        "author": story.get("by"),
                        "score": story.get("score"),
                        "comments": story.get("descendants"),
                        "url": story.get("url"),
                        "summary": f"{story.get('title')} by {story.get('by')} "
                        f"has {story.get('score')} points and "
                        f"{story.get('descendants')} comments.",
                    }

                    return {
                        "success": True,
                        "summary": summary,
                    }

                elif operation == "ranked_stories":
                    stories = await self._story_list(client, "topstories", 50, True)

                    ranked = sorted(
                        stories, key=lambda x: x.get("score", 0), reverse=True
                    )[:max_results]

                    return {
                        "success": True,
                        "stories": ranked,
                    }

                return {
                    "success": False,
                    "error": f"Unknown operation {operation}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # ---------- Async API Methods ----------

    async def _get_item(
        self, client: httpx.AsyncClient, item_id: int
    ) -> Dict[str, Any]:
        resp = await client.get(f"{self.FIREBASE_URL}/item/{item_id}.json")
        return resp.json()

    async def _story_list(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        max_results: int,
        detailed: bool,
    ) -> List[Dict[str, Any]]:
        resp = await client.get(f"{self.FIREBASE_URL}/{endpoint}.json")
        ids: List[int] = resp.json()[:max_results]

        # Fetch all items in parallel
        items = await asyncio.gather(
            *[self._get_item(client, sid) for sid in ids],
            return_exceptions=True,
        )

        stories = []
        for s in items:
            if isinstance(s, Exception) or not s:
                continue

            if detailed:
                stories.append(s)
            else:
                stories.append(
                    {
                        "id": s.get("id"),
                        "title": s.get("title"),
                        "score": s.get("score"),
                        "by": s.get("by"),
                        "comments": s.get("descendants", 0),
                        "url": s.get("url"),
                    }
                )

        return stories

    async def _get_comments(
        self, client: httpx.AsyncClient, story_id: int
    ) -> List[Dict[str, Any]]:
        story = await self._get_item(client, story_id)

        if "kids" not in story:
            return []

        # Fetch all top-level comments in parallel
        comment_items = await asyncio.gather(
            *[self._get_item(client, cid) for cid in story["kids"][:30]],
            return_exceptions=True,
        )

        comments = []
        for c in comment_items:
            if isinstance(c, Exception) or not c:
                continue
            if c.get("text"):
                comments.append(
                    {
                        "by": c.get("by"),
                        "text": c.get("text"),
                        "time": c.get("time"),
                    }
                )

        return comments

    async def _get_user(
        self, client: httpx.AsyncClient, user_id: str
    ) -> Dict[str, Any]:
        resp = await client.get(f"{self.FIREBASE_URL}/user/{user_id}.json")
        return resp.json()

    async def _search(
        self, client: httpx.AsyncClient, query: str, max_results: int
    ) -> List[Dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={"query": query})
        r = resp.json()

        hits = r.get("hits", [])[:max_results]

        return [
            {
                "title": h.get("title"),
                "url": h.get("url"),
                "author": h.get("author"),
                "points": h.get("points"),
                "story_id": h.get("objectID"),
            }
            for h in hits
        ]
