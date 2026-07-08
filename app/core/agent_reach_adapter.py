"""Agent Reach Adapter — Bridges Agent Reach internet intelligence into unified context."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AgentReachAdapter:
    """Adapter for Agent Reach internet intelligence system."""
    
    def __init__(self) -> None:
        self._intel = None
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """Lazy initialization of Agent Reach."""
        if self._initialized:
            return
        try:
            from agent_reach.intelligence import FreeInternetIntel
            from agent_reach.config import Config as ReachConfig
            
            self._intel = FreeInternetIntel(ReachConfig())
            self._initialized = True
            logger.info("Agent Reach adapter initialized")
        except Exception as e:
            logger.warning("Agent Reach not available: %s", e)
            self._initialized = True  # Don't keep trying
            self._intel = None
    
    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search the internet using Agent Reach."""
        self._ensure_initialized()
        if not self._intel:
            return {"success": False, "results": [], "error": "Agent Reach not available"}
        
        try:
            result = self._intel.search(query, limit=limit)
            return result
        except Exception as e:
            logger.error("Agent Reach search failed: %s", e)
            return {"success": False, "results": [], "error": str(e)}
    
    def fetch(self, url: str) -> dict[str, Any]:
        """Fetch and extract content from a URL."""
        self._ensure_initialized()
        if not self._intel:
            return {"success": False, "content": "", "error": "Agent Reach not available"}
        
        try:
            result = self._intel.fetch(url)
            return result
        except Exception as e:
            logger.error("Agent Reach fetch failed: %s", e)
            return {"success": False, "content": "", "error": str(e)}
    
    def get_status(self) -> dict[str, Any]:
        """Get Agent Reach status."""
        self._ensure_initialized()
        if not self._intel:
            return {"success": False, "available": False}
        try:
            return self._intel.status()
        except Exception as e:
            return {"success": False, "available": False, "error": str(e)}


# Global instance
_agent_reach_adapter: AgentReachAdapter | None = None


def get_agent_reach_adapter() -> AgentReachAdapter:
    """Get global Agent Reach adapter instance."""
    global _agent_reach_adapter
    if _agent_reach_adapter is None:
        _agent_reach_adapter = AgentReachAdapter()
    return _agent_reach_adapter