"""Unified Multimodal Context Integration for AgentRuntime.

This module provides the integration layer that connects the unified multimodal
context builder with the AgentRuntime, pulling data from all connectors
(calendar, email, files, sensors, surveillance, web, memory) into a single
coherent context for reasoning.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.multimodal_connectors import (
    MultimodalConnectorHub,
    get_connector_hub,
)
from app.core.unified_multimodal import (
    UnifiedMultimodalContextBuilder,
    get_unified_context_builder,
)
from app.core.memory_facade import get_memory_facade
from app.core.agent_reach_adapter import get_agent_reach_adapter

logger = logging.getLogger(__name__)


class UnifiedMultimodalIntegration:
    """Integrates all multimodal data sources into the unified context builder."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.workspace_dir = workspace_dir
        self.connector_hub = get_connector_hub()
        self.unified_builder = get_unified_context_builder()
        self.memory_facade = get_memory_facade()
        self.agent_reach = get_agent_reach_adapter()
        
        # Inject connector data into unified builder
        self.connector_hub.inject_into_builder(self.unified_builder)
        
        # Setup sensor state callback
        self._setup_sensor_callback()
        
        logger.info("UnifiedMultimodalIntegration initialized")

    def _setup_sensor_callback(self) -> None:
        """Setup callback for real-time sensor updates."""
        # This would connect to MQTT or monitoring system
        pass

    async def enrich_request_context(
        self,
        request: Any,  # IncomingRequest
        session_id: str,
        user_id: str
    ) -> dict[str, Any]:
        """Enrich a request with all available multimodal context."""
        
        context_data = {}
        
        # 1. Get memory snippets relevant to the request
        try:
            memory_results = await self.memory_facade.retrieve_relevant(
                query=request.text,
                user_id=user_id,
                session_id=session_id,
                limit=5
            )
            context_data["memory_snippets"] = [r.get("content", "") for r in memory_results]
        except Exception as e:
            logger.debug("Memory retrieval failed: %s", e)
            context_data["memory_snippets"] = []
        
        # 2. Get calendar events (upcoming)
        try:
            cal_events = self.connector_hub.calendar.get_events_for_context()
            context_data["calendar_events"] = cal_events
        except Exception as e:
            logger.debug("Calendar fetch failed: %s", e)
            context_data["calendar_events"] = []
        
        # 3. Get recent emails
        try:
            emails = self.connector_hub.email.get_messages_for_context()
            context_data["emails"] = emails
        except Exception as e:
            logger.debug("Email fetch failed: %s", e)
            context_data["emails"] = []
        
        # 4. Get relevant files
        try:
            files = self.connector_hub.files.get_files_for_context()
            context_data["file_contents"] = files
        except Exception as e:
            logger.debug("File fetch failed: %s", e)
            context_data["file_contents"] = []
        
        # 4.5 Get web search results if query looks like it needs them
        try:
            if self._needs_web_search(request.text):
                web_results = await self.agent_reach.search(request.text, limit=3)
                context_data["web_results"] = web_results.get("results", [])
            else:
                context_data["web_results"] = []
        except Exception as e:
            logger.debug("Web search failed: %s", e)
            context_data["web_results"] = []
        
        # 5. Get sensor state (already injected into builder)
        context_data["sensor_state"] = self.connector_hub.sensors.get_state_for_context()
        
        # 6. Get surveillance events (from monitoring)
        context_data["surveillance_events"] = []
        # This would come from monitoring stack
        
        # 7. Voice transcript if available
        context_data["voice_transcript"] = getattr(request, "voice_transcript", None)
        
        return context_data

    def _needs_web_search(self, query: str) -> bool:
        """Determine if query needs web search."""
        search_triggers = [
            "what is", "who is", "latest", "news", "current", "today",
            "price", "weather", "stock", "crypto", "how to", "tutorial",
            "compare", "review", "best", "recent", "2024", "2025"
        ]
        query_lower = query.lower()
        return any(trigger in query_lower for trigger in search_triggers)

    def build_unified_context(self, request: Any, session_id: str, user_id: str) -> Any:
        """Build the complete unified multimodal context."""
        
        # Get enriched context data
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await in sync context, use cached/sync data
                context_data = {
                    "memory_snippets": [],
                    "calendar_events": self.connector_hub.calendar.get_events_for_context(),
                    "emails": self.connector_hub.email.get_messages_for_context(),
                    "file_contents": self.connector_hub.files.get_files_for_context(),
                    "web_results": [],
                    "sensor_state": self.connector_hub.sensors.get_state_for_context(),
                    "surveillance_events": [],
                    "voice_transcript": getattr(request, "voice_transcript", None),
                }
            else:
                context_data = loop.run_until_complete(
                    self.enrich_request_context(request, session_id, user_id)
                )
        except Exception:
            context_data = {
                "memory_snippets": [],
                "calendar_events": [],
                "emails": [],
                "file_contents": [],
                "web_results": [],
                "sensor_state": {},
                "surveillance_events": [],
                "voice_transcript": None,
            }
        
        # Build unified context
        unified_context = self.unified_builder.build(
            request=request,
            calendar_events=context_data.get("calendar_events"),
            emails=context_data.get("emails"),
            file_contents=context_data.get("file_contents"),
            voice_transcript=context_data.get("voice_transcript"),
        )
        
        return unified_context


# Global instance
_unified_integration: UnifiedMultimodalIntegration | None = None


def get_unified_multimodal_integration(workspace_dir: str = "workspace") -> UnifiedMultimodalIntegration:
    """Get global unified multimodal integration instance."""
    global _unified_integration
    if _unified_integration is None:
        _unified_integration = UnifiedMultimodalIntegration(workspace_dir)
    return _unified_integration