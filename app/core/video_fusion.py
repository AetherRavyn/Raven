from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VideoFusionBundle:
    clip_path: str
    camera_id: str
    event_payloads: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    clip_metadata: dict[str, Any] = field(default_factory=dict)


class VideoEventFusion:
    def __init__(self, clips_root: str = "clips") -> None:
        self.clips_root = Path(clips_root)

    @staticmethod
    def _clip_sidecar(clip_path: str) -> Path:
        return Path(clip_path).with_suffix(".json")

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def load_clip_metadata(self, clip_path: str) -> dict[str, Any]:
        sidecar = self._clip_sidecar(clip_path)
        if not sidecar.exists():
            return {}
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to load clip sidecar for %s: %s", clip_path, exc)
            return {}

    def _nearby_events_from_db(
        self,
        clip_metadata: dict[str, Any],
        db: Any | None = None,
        window_minutes: int = 5,
    ) -> list[dict[str, Any]]:
        if db is None:
            return []

        camera_id = clip_metadata.get("camera_id")
        start = self._parse_iso(clip_metadata.get("start_time"))
        end = self._parse_iso(clip_metadata.get("end_time"))
        if not camera_id or not start or not end:
            return []

        try:
            from monitoring.src.db.postgres import SQLiteDB

            if not isinstance(db, SQLiteDB):
                return []
            nearby = db.get_events(
                camera_id=camera_id,
                from_time=start.replace(tzinfo=None),
                to_time=end.replace(tzinfo=None),
                limit=20,
            )
            return nearby
        except Exception as exc:
            logger.debug("Nearby event lookup failed: %s", exc)
            return []

    @staticmethod
    def _event_to_payload(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "video_fusion",
            "event_type": event.get("anomaly_type")
            or event.get("event_type")
            or "video_event",
            "risk_level": event.get("severity") or event.get("risk_level") or "low",
            "event_id": f"video_{event.get('event_id')}",
            "description": event.get("description") or "Nearby clip event",
            "camera_id": event.get("camera_id") or "unknown",
            "video_path": event.get("video_path"),
            "image_path": event.get("image_path"),
            "metadata": event,
        }

    def fuse(
        self,
        clip_path: str,
        *,
        db: Any | None = None,
        event_payloads: list[dict[str, Any]] | None = None,
    ) -> VideoFusionBundle:
        metadata = self.load_clip_metadata(clip_path)
        camera_id = str(metadata.get("camera_id") or Path(clip_path).stem.split("_")[0])
        bundle = VideoFusionBundle(
            clip_path=clip_path,
            camera_id=camera_id,
            clip_metadata=metadata,
        )

        if event_payloads:
            bundle.event_payloads.extend(event_payloads)

        if metadata:
            bundle.event_payloads.append(
                {
                    "source": "clip_metadata",
                    "event_type": "clip_context",
                    "risk_level": "low",
                    "event_id": f"clip_{Path(clip_path).stem}",
                    "description": f"Clip {Path(clip_path).name} lasting {metadata.get('duration_seconds', 'unknown')} seconds",
                    "camera_id": camera_id,
                    "video_path": clip_path,
                    "metadata": metadata,
                }
            )

        nearby_events = self._nearby_events_from_db(metadata, db=db)
        if nearby_events:
            for event in nearby_events[:5]:
                bundle.event_payloads.append(self._event_to_payload(event))
            bundle.notes.append(
                f"Fused {len(nearby_events[:5])} nearby monitoring events."
            )

        if not metadata and not bundle.event_payloads:
            bundle.notes.append("No clip metadata found; using raw video path only.")

        return bundle
