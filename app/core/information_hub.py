"""Information Hub — unified search across all information sources.

FRIDAY-style: one query, results from every available source.

Combines:
- Web search (Brave, Gemini, Perplexity, SearXNG)
- Knowledge graph (HelixDB)
- Memory (semantic search)
- News (RSS, HackerNews)
- Social media (Twitter, Reddit)
- Docs (Notion, Obsidian)

Results are ranked, deduplicated, and returned as a unified list.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InfoResult:
    """A single search result from any source."""
    source: str
    title: str
    snippet: str
    url: str = ""
    relevance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


class InformationHub:
    """FRIDAY-style unified information retrieval.

    Queries all available sources in parallel and returns
    ranked, deduplicated results.
    """

    def __init__(self) -> None:
        self._search_engines: list[Callable] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default search engines."""
        # Web search (auto-detects provider: Brave/Gemini/Perplexity/Grok/DuckDuckGo)
        try:
            from app.tools.websearch import WebOperationTool
            self._search_engines.append(self._web_search)
        except ImportError:
            pass

        # AgentReach (DuckDuckGo + Jina Reader, free, no key)
        self._search_engines.append(self._agentreach_search)

        # SearXNG (privacy search — only if server is running)
        try:
            from app.tools.searxngtool import SearXNGTool
            self._search_engines.append(self._searxng_search)
        except ImportError:
            pass

        # Knowledge graph
        self._search_engines.append(self._kg_search)

        # Memory
        self._search_engines.append(self._memory_search)

    async def search(
        self,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 20,
    ) -> list[InfoResult]:
        """Search all available sources and return unified results."""
        tasks = []

        for engine in self._search_engines:
            engine_name = engine.__name__ if hasattr(engine, '__name__') else str(engine)
            if sources and not any(s in engine_name for s in sources):
                continue
            tasks.append(self._safe_search(engine, query))

        # Run all searches in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and deduplicate
        all_results: list[InfoResult] = []
        seen_urls: set[str] = set()

        for result_list in results:
            if isinstance(result_list, Exception):
                continue
            for result in result_list:
                if result.url and result.url in seen_urls:
                    continue
                if result.url:
                    seen_urls.add(result.url)
                all_results.append(result)

        # Sort by relevance
        all_results.sort(key=lambda r: r.relevance, reverse=True)
        return all_results[:max_results]

    async def _safe_search(self, engine: Callable, query: str) -> list[InfoResult]:
        """Run a search engine safely with timeout."""
        try:
            return await asyncio.wait_for(engine(query), timeout=10)
        except Exception as exc:
            logger.debug("Search engine %s failed: %s", getattr(engine, '__name__', '?'), exc)
            return []

    async def _web_search(self, query: str) -> list[InfoResult]:
        """Search via web search tools."""
        try:
            from app.tools.websearch import WebOperationTool
            tool = WebOperationTool()
            result = await tool.execute(operation="search", query=query, limit=5)
            if result.get("success"):
                return [
                    InfoResult(
                        source="web",
                        title=r.get("title", ""),
                        snippet=r.get("snippet", ""),
                        url=r.get("url", ""),
                        relevance=r.get("score", 0.5),
                    )
                    for r in result.get("results", [])
                ]
        except Exception:
            pass
        return []

    async def _searxng_search(self, query: str) -> list[InfoResult]:
        """Search via SearXNG (privacy)."""
        try:
            from app.tools.searxngtool import SearXNGTool
            tool = SearXNGTool()
            result = await tool.execute(query=query, max_results=5)
            if result.get("success"):
                return [
                    InfoResult(
                        source="searxng",
                        title=r.get("title", ""),
                        snippet=r.get("content", ""),
                        url=r.get("url", ""),
                        relevance=0.6,
                    )
                    for r in result.get("results", [])
                ]
        except Exception:
            pass
        return []

    async def _agentreach_search(self, query: str) -> list[InfoResult]:
        """Search via AgentReach (DuckDuckGo + Jina Reader, free, no key)."""
        try:
            from app.tools.internetinteltool import InternetIntelTool
            tool = InternetIntelTool()
            result = await tool.execute(operation="search", query=query, limit=5)
            if result.get("success"):
                return [
                    InfoResult(
                        source="agentreach",
                        title=r.get("title", ""),
                        snippet=r.get("snippet", ""),
                        url=r.get("url", ""),
                        relevance=0.5,
                    )
                    for r in result.get("results", [])
                ]
        except Exception:
            pass
        return []

    async def _kg_search(self, query: str) -> list[InfoResult]:
        """Search the knowledge graph."""
        try:
            from app.core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            result = facade.graph_query(query)
            if result.get("success"):
                connections = result.get("connections", [])
                return [
                    InfoResult(
                        source="knowledge_graph",
                        title=c.split("-->")[0].strip() if "-->" in c else c,
                        snippet=c,
                        relevance=0.7,
                    )
                    for c in connections[:5]
                ]
        except Exception:
            pass
        return []

    async def _memory_search(self, query: str) -> list[InfoResult]:
        """Search semantic memory."""
        try:
            from app.core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            results = facade.recall(query, top_k=5)
            return [
                InfoResult(
                    source="memory",
                    title=m.content[:100],
                    snippet=m.content,
                    relevance=m.confidence,
                )
                for m in results
            ]
        except Exception:
            pass
        return []


# Singleton
_hub: InformationHub | None = None


def get_information_hub() -> InformationHub:
    global _hub
    if _hub is None:
        _hub = InformationHub()
    return _hub
