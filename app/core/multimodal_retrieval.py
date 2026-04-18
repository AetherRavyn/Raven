from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.models import IncomingRequest
from app.core.video_fusion import VideoEventFusion

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MultimodalRetrievalBundle:
    event_payloads: list[dict[str, Any]] = field(default_factory=list)
    semantic_hits: list[dict[str, Any]] = field(default_factory=list)
    graph_hits: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class MultimodalRetriever:
    def __init__(
        self,
        *,
        graph_tool: Any | None = None,
    ) -> None:
        self.graph_tool = graph_tool

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        candidates: list[str] = []
        patterns = [
            r"\b(?:[A-Z][a-z0-9_-]+(?:\s+[A-Z][a-z0-9_-]+)*)\b",
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text):
                value = match.strip()
                if value and value not in candidates:
                    candidates.append(value)
        return candidates[:5]

    @staticmethod
    def _semantic_hit_to_payload(hit: dict[str, Any]) -> dict[str, Any]:
        similarity = hit.get("similarity", 0.0)
        description = hit.get("description") or "similar event"
        camera_id = hit.get("camera_id") or "unknown"
        event_id = hit.get("event_id") or "unknown"
        return {
            "source": "semantic_search",
            "event_type": "similar_event",
            "risk_level": "low",
            "event_id": f"semantic_{hashlib.sha1(str(event_id).encode('utf-8')).hexdigest()[:8]}",
            "description": f"{similarity:.2f} match: {description}",
            "camera_id": camera_id,
            "similarity": similarity,
            "matched_event_id": event_id,
        }

    @staticmethod
    def _graph_result_to_payload(entity: str, result: dict[str, Any]) -> dict[str, Any]:
        connections = result.get("connections") or []
        path = result.get("path") or []
        detail = connections[:3]
        if path:
            detail = [" -> ".join(path)]
        if not detail:
            detail = ["No known relationships"]
        return {
            "source": "knowledge_graph",
            "event_type": "graph_connection",
            "risk_level": "low",
            "event_id": f"graph_{hashlib.sha1(entity.encode('utf-8')).hexdigest()[:8]}",
            "description": f"{entity}: {'; '.join(detail)}",
            "entity": entity,
            "connections": connections,
            "path": path,
        }

    async def collect(self, request: IncomingRequest) -> MultimodalRetrievalBundle:
        bundle = MultimodalRetrievalBundle()

        if request.image_urls:
            bundle.notes.append(
                "Image attachments are available, but SARAS stays DB-only and does not run semantic image retrieval."
            )

        if getattr(request, "video_path", None):
            bundle.notes.append(
                "Video evidence stays inside monitoring; SARAS only consumes the stored metadata and anomaly summary."
            )

        entities = self._extract_entities(request.text)
        if self.graph_tool is None:
            try:
                from app.tools.kgtool import KnowledgeGraphTool

                self.graph_tool = KnowledgeGraphTool()
            except Exception:
                self.graph_tool = None

        if self.graph_tool is not None:
            for entity in entities[:3]:
                try:
                    result = await self.graph_tool.execute(
                        operation="query_entity",
                        query=entity,
                    )
                except Exception as exc:
                    logger.debug(
                        "Knowledge graph lookup failed for %s: %s", entity, exc
                    )
                    continue

                if result.get("success"):
                    bundle.graph_hits.append({"entity": entity, **result})
                    bundle.event_payloads.append(
                        self._graph_result_to_payload(entity, result)
                    )

        if not bundle.event_payloads:
            bundle.notes.append("No additional multimodal evidence found.")
        return bundle
