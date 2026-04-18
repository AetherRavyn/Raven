# -*- coding: utf-8 -*-
"""
Agent Reach - internet health, discovery, and configuration helpers.

Agent Reach helps AI agents install and configure upstream platform tools
(bird CLI, yt-dlp, mcporter, gh CLI, etc.) and provides a free-first internet
intelligence layer for search, reading, and discovery.

Usage:
    from agent_reach.core import AgentReach

    reach = AgentReach()
    print(reach.doctor_report())
    results = reach.search("latest open source AI agents")
"""

from typing import Any, Dict, Iterable, Optional

from agent_reach.config import Config
from agent_reach.intelligence import FreeInternetIntel


class AgentReach:
    """Give your AI agent eyes to see the entire internet.

    This class provides health-check functionality and a free-first internet
    intelligence API built on public sites, Jina Reader, and local tools.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._intel = FreeInternetIntel(self.config)

    def doctor(self) -> Dict[str, dict]:
        """Check all channel availability."""
        from agent_reach.doctor import check_all

        return check_all(self.config)

    def doctor_report(self) -> str:
        """Get formatted health report."""
        from agent_reach.doctor import check_all, format_report

        return format_report(check_all(self.config))

    def status(self) -> dict[str, Any]:
        """Return the full internet coverage status."""
        return self._intel.status()

    def search(
        self,
        query: str,
        limit: int = 8,
        sources: str | Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Search the internet using free-first sources."""
        return self._intel.search(query=query, limit=limit, sources=sources)

    def discover(
        self,
        query: str,
        limit: int = 8,
        sources: str | Iterable[str] | None = None,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """Search and deep-read the most relevant sources."""
        return self._intel.discover(
            query=query,
            limit=limit,
            sources=sources,
            max_chars=max_chars,
        )

    def read(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        """Read a web page or supported platform URL."""
        return self._intel.read(url, max_chars=max_chars)

    def coverage_report(self) -> str:
        """Return a human-readable coverage report."""
        return self._intel.coverage_report()
