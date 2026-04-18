from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.models import IncomingRequest, SignalPayload


@dataclass(slots=True)
class MultimodalEvent:
    modality: str
    content: str
    priority: int = 0
    source: str = "request"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class MultimodalContext:
    platform: str
    user_id: str
    conversation_id: str | None
    request_text: str
    modality: str
    events: list[MultimodalEvent] = field(default_factory=list)
    max_chars: int = 2400

    def has_signal(self) -> bool:
        return any(
            event.modality != "text" or event.source != "request"
            for event in self.events
        )

    def render(self) -> str:
        lines = ["--- [Multimodal Context] ---"]
        lines.append(f"platform: {self.platform}")
        lines.append(f"user_id: {self.user_id}")
        if self.conversation_id:
            lines.append(f"conversation_id: {self.conversation_id}")
        lines.append(f"modality: {self.modality}")
        lines.append("priority_rules:")
        lines.append("- user text and transcripts first")
        lines.append("- images and video next")
        lines.append("- live sensor and surveillance events next")
        lines.append("- memory snippets last")
        lines.append("evidence:")

        packed = MultimodalContextBuilder.pack_events(self.events, self.max_chars)
        for event in packed:
            label = f"[{event.modality}]"
            if event.source != "request":
                label = f"[{event.source}:{event.modality}]"
            line = f"- {label} {event.content}"
            lines.append(line)

        return "\n".join(lines).strip()


class MultimodalContextBuilder:
    def __init__(self, max_chars: int = 2400) -> None:
        self.max_chars = max_chars

    @staticmethod
    def pack_events(
        events: list[MultimodalEvent], max_chars: int
    ) -> list[MultimodalEvent]:
        packed: list[MultimodalEvent] = []
        used = 0
        for event in sorted(events, key=lambda e: (-e.priority, e.timestamp)):
            block = f"[{event.modality}] {event.content}"
            size = len(block) + 3
            if packed and used + size > max_chars:
                break
            packed.append(event)
            used += size
        return packed

    @staticmethod
    def _compact_value(value: Any, limit: int = 180) -> str:
        if isinstance(value, str):
            return value[:limit]
        try:
            return json.dumps(value, ensure_ascii=True, sort_keys=True)[:limit]
        except Exception:
            return str(value)[:limit]

    def from_request(
        self,
        request: IncomingRequest,
        *,
        sensor_state: dict[str, Any] | None = None,
        memory_snippets: list[str] | None = None,
        event_payloads: list[dict[str, Any]] | None = None,
    ) -> MultimodalContext:
        modality = "image" if request.image_urls else "text"
        events: list[MultimodalEvent] = []

        request_text = request.text.strip() or "[empty]"
        events.append(
            MultimodalEvent(
                modality="voice" if modality in {"voice", "audio"} else "text",
                content=request_text,
                priority=100,
                source="request",
                metadata={"platform": request.platform},
            )
        )

        for index, url in enumerate(request.image_urls or [], start=1):
            events.append(
                MultimodalEvent(
                    modality="image",
                    content=f"image[{index}] {url}",
                    priority=95,
                    source="attachment",
                    metadata={"url": url, "index": index},
                )
            )

        if request.image_urls:
            events.append(
                MultimodalEvent(
                    modality="attachment",
                    content=f"{len(request.image_urls)} image attachment(s) available in monitoring only",
                    priority=92,
                    source="request",
                )
            )

        if sensor_state:
            for idx, (topic, payload) in enumerate(sorted(sensor_state.items())):
                if idx >= 5:
                    break
                events.append(
                    MultimodalEvent(
                        modality="sensor",
                        content=f"{topic} = {self._compact_value(payload)}",
                        priority=70,
                        source="mqtt",
                        metadata={"topic": topic},
                    )
                )

        for idx, snippet in enumerate(memory_snippets or []):
            if idx >= 5:
                break
            events.append(
                MultimodalEvent(
                    modality="memory",
                    content=snippet[:220],
                    priority=60,
                    source="memory",
                )
            )

        for payload in event_payloads or []:
            events.append(self.from_event_payload(payload))

        return MultimodalContext(
            platform=request.platform,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            request_text=request_text,
            modality=modality,
            events=events,
            max_chars=self.max_chars,
        )

    @staticmethod
    def from_event_payload(payload: dict[str, Any]) -> MultimodalEvent:
        modality = "surveillance"
        if payload.get("topic") or payload.get("sensor"):
            modality = "sensor"
        elif payload.get("video_path"):
            modality = "video"
        elif payload.get("image_path") or payload.get("frame_b64"):
            modality = "image"
        elif payload.get("text"):
            modality = "text"

        content = (
            payload.get("description")
            or payload.get("message")
            or payload.get("event_type")
            or payload.get("anomaly_type")
            or payload.get("text")
            or "event"
        )
        priority_map = {"critical": 100, "high": 90, "medium": 75, "low": 60}
        risk = str(
            payload.get("risk_level") or payload.get("severity") or "low"
        ).lower()
        priority = priority_map.get(risk, 70)
        source = payload.get("source") or payload.get("origin") or modality
        return MultimodalEvent(
            modality=modality,
            content=str(content)[:260],
            priority=priority,
            source=str(source),
            metadata=payload,
        )

    @staticmethod
    def from_signal_payload(payload: SignalPayload) -> list[MultimodalEvent]:
        events: list[MultimodalEvent] = []
        text = payload.text or payload.caption or ""
        if text:
            events.append(
                MultimodalEvent(
                    modality="text",
                    content=text[:260],
                    priority=90,
                    source=payload.source_kind or "message",
                )
            )
        if payload.audio_path:
            events.append(
                MultimodalEvent(
                    modality="audio",
                    content=payload.audio_path,
                    priority=95,
                    source=payload.source_kind or "message",
                )
            )
        if payload.video_path:
            events.append(
                MultimodalEvent(
                    modality="video",
                    content=payload.video_path,
                    priority=95,
                    source=payload.source_kind or "message",
                )
            )
        if payload.file_path:
            events.append(
                MultimodalEvent(
                    modality="file",
                    content=payload.file_path,
                    priority=80,
                    source=payload.source_kind or "message",
                )
            )
        return events
