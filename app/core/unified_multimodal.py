"""Unified Multimodal Context — Friday-style holistic perception.

Merges text, voice, vision, sensors, calendar, email, files, and surveillance
into a single coherent context for the reasoning engine.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.models import IncomingRequest, SignalPayload

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModalityEvent:
    """A single event from any modality."""
    event_id: str
    modality: str  # text, voice, image, video, sensor, calendar, email, file, surveillance, memory, web
    content: str
    priority: int = 0
    source: str = "request"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    token_estimate: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UnifiedContext:
    """Complete unified multimodal context for reasoning."""
    context_id: str
    platform: str
    user_id: str
    conversation_id: str | None
    request_text: str
    primary_modality: str
    events: list[ModalityEvent] = field(default_factory=list)
    max_tokens: int = 8000
    token_budget: dict[str, int] = field(default_factory=dict)  # modality -> allocated tokens
    rendered: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TokenBudgetAllocator:
    """Allocates token budget across modalities based on priority and relevance."""
    
    DEFAULT_BUDGETS = {
        "text": 2000,      # User request, transcripts
        "voice": 1500,     # Voice transcripts, audio descriptions
        "image": 1500,     # Image descriptions, OCR
        "video": 1000,     # Video summaries, key frames
        "sensor": 500,     # Sensor readings
        "calendar": 500,   # Upcoming events
        "email": 500,      # Recent emails
        "file": 500,       # File contents/summaries
        "surveillance": 500,  # Camera alerts, anomalies
        "memory": 500,     # Relevant memories
        "web": 500,        # Web search results
    }
    
    PRIORITY_WEIGHTS = {
        "request": 1.0,      # Direct user request
        "attachment": 0.9,   # User attachments
        "voice": 0.85,       # Voice transcripts
        "calendar": 0.7,     # Calendar events
        "email": 0.6,        # Email content
        "sensor": 0.5,       # Sensor data
        "surveillance": 0.7, # Security events
        "memory": 0.4,       # Retrieved memories
        "web": 0.4,          # Web results
        "mqtt": 0.5,         # MQTT sensor data
    }

    def __init__(self, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens
        self.budgets = self.DEFAULT_BUDGETS.copy()

    def allocate(self, events: list[ModalityEvent]) -> dict[str, int]:
        """Allocate token budget based on events present."""
        # Count events per modality
        modality_counts = defaultdict(int)
        modality_priorities = defaultdict(int)
        
        for event in events:
            modality_counts[event.modality] += 1
            modality_priorities[event.modality] = max(
                modality_priorities[event.modality], event.priority
            )
        
        # Calculate weights
        weights = {}
        total_weight = 0
        for modality, count in modality_counts.items():
            priority = modality_priorities[modality]
            source_weight = self.PRIORITY_WEIGHTS.get(
                next((e.source for e in events if e.modality == modality), "memory"), 0.3
            )
            weight = count * (priority / 100) * source_weight
            weights[modality] = weight
            total_weight += weight
        
        # Allocate proportionally
        allocated = {}
        for modality, weight in weights.items():
            if total_weight > 0:
                allocated[modality] = int(self.max_tokens * weight / total_weight)
            else:
                allocated[modality] = self.budgets.get(modality, 500)
        
        # Ensure minimums
        for modality in modality_counts:
            if allocated.get(modality, 0) < 100:
                allocated[modality] = 100
        
        return allocated


class UnifiedMultimodalContextBuilder:
    """Builds unified context from all available modalities."""
    
    def __init__(self, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens
        self.budget_allocator = TokenBudgetAllocator(max_tokens)
        self._memory_store = None
        self._calendar_store = None
        self._email_store = None
        self._file_store = None
        self._sensor_state = {}
        self._surveillance_events = []
        self._web_results = []

    def set_stores(
        self,
        memory_store: Any = None,
        calendar_store: Any = None,
        email_store: Any = None,
        file_store: Any = None
    ) -> None:
        """Set external data stores for context enrichment."""
        self._memory_store = memory_store
        self._calendar_store = calendar_store
        self._email_store = email_store
        self._file_store = file_store

    def update_sensor_state(self, sensor_state: dict[str, Any]) -> None:
        """Update current sensor state."""
        self._sensor_state = sensor_state

    def add_surveillance_event(self, event: dict[str, Any]) -> None:
        """Add a surveillance/camera event."""
        self._surveillance_events.append(event)
        # Keep only recent events
        if len(self._surveillance_events) > 50:
            self._surveillance_events = self._surveillance_events[-50:]

    def add_web_results(self, results: list[dict[str, Any]]) -> None:
        """Add web search results."""
        self._web_results = results

    def build(
        self,
        request: IncomingRequest,
        *,
        sensor_state: dict[str, Any] | None = None,
        memory_snippets: list[str] | None = None,
        event_payloads: list[dict[str, Any]] | None = None,
        calendar_events: list[dict[str, Any]] | None = None,
        emails: list[dict[str, Any]] | None = None,
        file_contents: list[dict[str, Any]] | None = None,
        voice_transcript: str | None = None,
    ) -> UnifiedContext:
        """Build complete unified context from all sources."""
        
        events: list[ModalityEvent] = []
        
        # 1. Primary request (text or voice)
        request_text = request.text.strip() or "[empty]"
        primary_modality = "text"
        
        if voice_transcript:
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="voice",
                content=f"Voice transcript: {voice_transcript}",
                priority=100,
                source="request",
                metadata={"platform": request.platform, "original_text": request_text},
                token_estimate=len(voice_transcript) // 4
            ))
            primary_modality = "voice"
        else:
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="text",
                content=request_text,
                priority=100,
                source="request",
                metadata={"platform": request.platform},
                token_estimate=len(request_text) // 4
            ))
        
        # 2. Image attachments
        for index, url in enumerate(request.image_urls or [], start=1):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="image",
                content=f"Image attachment {index}: {url}",
                priority=95,
                source="attachment",
                metadata={"url": url, "index": index},
                token_estimate=500  # Estimated tokens for image description
            ))
        
        # 3. Sensor data (MQTT, IoT)
        sensors = sensor_state or self._sensor_state
        if sensors:
            for idx, (topic, payload) in enumerate(sorted(sensors.items())):
                if idx >= 10:  # Limit sensor events
                    break
                events.append(ModalityEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    modality="sensor",
                    content=f"Sensor {topic}: {json.dumps(payload)[:200]}",
                    priority=70,
                    source="mqtt",
                    metadata={"topic": topic, "payload": payload},
                    token_estimate=50
                ))
        
        # 4. Surveillance/Camera events
        for idx, event in enumerate(self._surveillance_events[-5:]):  # Last 5
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="surveillance",
                content=self._format_surveillance_event(event),
                priority=event.get("risk_level", "low") == "critical" and 95 or 80,
                source="camera",
                metadata=event,
                token_estimate=100
            ))
        
        # 5. Calendar events
        cal_events = calendar_events or []
        if self._calendar_store and not cal_events:
            # Would fetch from calendar store
            pass
        for idx, event in enumerate(cal_events[:5]):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="calendar",
                content=f"Calendar: {event.get('title', 'Event')} at {event.get('start', 'unknown')}",
                priority=60,
                source="calendar",
                metadata=event,
                token_estimate=50
            ))
        
        # 6. Emails
        for idx, email in enumerate((emails or [])[:3]):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="email",
                content=f"Email from {email.get('from', 'unknown')}: {email.get('subject', 'No subject')}",
                priority=50,
                source="email",
                metadata=email,
                token_estimate=100
            ))
        
        # 7. File contents
        for idx, file_info in enumerate((file_contents or [])[:3]):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="file",
                content=f"File {file_info.get('name', 'unknown')}: {file_info.get('summary', file_info.get('content', '')[:300])}",
                priority=50,
                source="file",
                metadata=file_info,
                token_estimate=200
            ))
        
        # 8. Memory snippets
        for idx, snippet in enumerate((memory_snippets or [])[:5]):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="memory",
                content=f"Memory: {snippet[:250]}",
                priority=40,
                source="memory",
                metadata={"index": idx},
                token_estimate=50
            ))
        
        # 9. Web search results
        for idx, result in enumerate(self._web_results[:3]):
            events.append(ModalityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                modality="web",
                content=f"Web: {result.get('title', 'Result')} - {result.get('snippet', '')[:200]}",
                priority=40,
                source="web_search",
                metadata=result,
                token_estimate=100
            ))
        
        # 10. Additional event payloads (from SignalPayload, etc.)
        for payload in (event_payloads or []):
            events.append(self._event_from_payload(payload))
        
        # Allocate token budget
        token_budget = self.budget_allocator.allocate(events)
        
        # Pack events within budget
        packed_events = self._pack_events(events, token_budget)
        
        # Render final context
        rendered = self._render_context(packed_events, request.platform, request.user_id)
        
        return UnifiedContext(
            context_id=f"ctx_{uuid.uuid4().hex[:12]}",
            platform=request.platform,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            request_text=request_text,
            primary_modality=primary_modality,
            events=packed_events,
            max_tokens=self.max_tokens,
            token_budget=token_budget,
            rendered=rendered
        )

    def _event_from_payload(self, payload: dict[str, Any]) -> ModalityEvent:
        """Convert a generic event payload to ModalityEvent."""
        modality = "surveillance"
        if payload.get("topic") or payload.get("sensor"):
            modality = "sensor"
        elif payload.get("video_path"):
            modality = "video"
        elif payload.get("image_path") or payload.get("frame_b64"):
            modality = "image"
        elif payload.get("text"):
            modality = "text"
        elif payload.get("calendar"):
            modality = "calendar"
        elif payload.get("email"):
            modality = "email"
        
        content = (
            payload.get("description")
            or payload.get("message")
            or payload.get("event_type")
            or payload.get("anomaly_type")
            or payload.get("text")
            or "event"
        )
        priority_map = {"critical": 100, "high": 90, "medium": 75, "low": 60}
        risk = str(payload.get("risk_level") or payload.get("severity") or "low").lower()
        priority = priority_map.get(risk, 70)
        source = payload.get("source") or payload.get("origin") or modality
        
        return ModalityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            modality=modality,
            content=str(content)[:300],
            priority=priority,
            source=str(source),
            metadata=payload,
            token_estimate=len(str(content)) // 4
        )

    def _format_surveillance_event(self, event: dict[str, Any]) -> str:
        """Format surveillance event for context."""
        parts = []
        if event.get("anomaly_type"):
            parts.append(f"Anomaly: {event['anomaly_type']}")
        if event.get("camera_id"):
            parts.append(f"Camera: {event['camera_id']}")
        if event.get("location"):
            parts.append(f"Location: {event['location']}")
        if event.get("description"):
            parts.append(event["description"])
        if event.get("track_id"):
            parts.append(f"Track: {event['track_id']}")
        return " | ".join(parts) if parts else "Surveillance event"

    def _pack_events(
        self,
        events: list[ModalityEvent],
        budget: dict[str, int]
    ) -> list[ModalityEvent]:
        """Pack events within token budget per modality."""
        # Group by modality
        by_modality = defaultdict(list)
        for event in events:
            by_modality[event.modality].append(event)
        
        packed = []
        for modality, modality_events in by_modality.items():
            modality_budget = budget.get(modality, 500)
            used = 0
            
            # Sort by priority
            for event in sorted(modality_events, key=lambda e: (-e.priority, e.timestamp)):
                if used + event.token_estimate <= modality_budget:
                    packed.append(event)
                    used += event.token_estimate
                elif used == 0:
                    # Always include at least one event per modality
                    packed.append(event)
                    used += event.token_estimate
        
        # Global budget check
        total_tokens = sum(e.token_estimate for e in packed)
        if total_tokens > self.max_tokens:
            # Trim lowest priority events
            packed.sort(key=lambda e: (e.priority, e.token_estimate))
            while total_tokens > self.max_tokens and packed:
                removed = packed.pop(0)
                total_tokens -= removed.token_estimate
            packed.sort(key=lambda e: (-e.priority, e.timestamp))
        
        return packed

    def _render_context(
        self,
        events: list[ModalityEvent],
        platform: str,
        user_id: str
    ) -> str:
        """Render unified context as structured text for LLM."""
        lines = [
            "=== UNIFIED MULTIMODAL CONTEXT ===",
            f"Platform: {platform}",
            f"User: {user_id}",
            f"Total Events: {len(events)}",
            "",
            "TOKEN BUDGET ALLOCATION:",
        ]
        
        # Show budget
        by_modality = defaultdict(list)
        for e in events:
            by_modality[e.modality].append(e)
        for mod, evs in sorted(by_modality.items()):
            tokens = sum(e.token_estimate for e in evs)
            lines.append(f"  {mod}: {len(evs)} events, ~{tokens} tokens")
        
        lines.append("")
        lines.append("EVENTS (priority ordered):")
        
        for event in sorted(events, key=lambda e: (-e.priority, e.timestamp)):
            label = f"[{event.modality}]"
            if event.source != "request":
                label = f"[{event.source}:{event.modality}]"
            lines.append(f"  {label} (p={event.priority}) {event.content}")
        
        return "\n".join(lines)


class CrossModalFusion:
    """Fuses information across modalities for higher-level understanding."""
    
    def __init__(self) -> None:
        pass
    
    def fuse_image_and_text(self, image_event: ModalityEvent, text_event: ModalityEvent) -> ModalityEvent:
        """Fuse image and text into a single understanding."""
        return ModalityEvent(
            event_id=f"fused_{uuid.uuid4().hex[:8]}",
            modality="fused_image_text",
            content=f"Image context: {image_event.content}. User query: {text_event.content}",
            priority=max(image_event.priority, text_event.priority),
            source="fusion",
            metadata={
                "image_event": image_event.metadata,
                "text_event": text_event.metadata
            },
            token_estimate=image_event.token_estimate + text_event.token_estimate
        )
    
    def fuse_sensor_and_surveillance(self, sensor_event: ModalityEvent, surv_event: ModalityEvent) -> ModalityEvent:
        """Fuse sensor data with surveillance for richer context."""
        return ModalityEvent(
            event_id=f"fused_{uuid.uuid4().hex[:8]}",
            modality="fused_sensor_surveillance",
            content=f"Sensor reading: {sensor_event.content}. Surveillance: {surv_event.content}",
            priority=max(sensor_event.priority, surv_event.priority),
            source="fusion",
            metadata={
                "sensor": sensor_event.metadata,
                "surveillance": surv_event.metadata
            },
            token_estimate=sensor_event.token_estimate + surv_event.token_estimate
        )
    
    def fuse_calendar_and_communication(
        self, 
        cal_event: ModalityEvent, 
        email_event: ModalityEvent
    ) -> ModalityEvent:
        """Fuse calendar event with related email."""
        return ModalityEvent(
            event_id=f"fused_{uuid.uuid4().hex[:8]}",
            modality="fused_calendar_email",
            content=f"Calendar: {cal_event.content}. Related email: {email_event.content}",
            priority=max(cal_event.priority, email_event.priority),
            source="fusion",
            metadata={
                "calendar": cal_event.metadata,
                "email": email_event.metadata
            },
            token_estimate=cal_event.token_estimate + email_event.token_estimate
        )


# Global instance
_unified_builder: UnifiedMultimodalContextBuilder | None = None


def get_unified_context_builder() -> UnifiedMultimodalContextBuilder:
    """Get global unified context builder instance."""
    global _unified_builder
    if _unified_builder is None:
        _unified_builder = UnifiedMultimodalContextBuilder()
    return _unified_builder