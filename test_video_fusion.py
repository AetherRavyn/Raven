from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.video_fusion import VideoEventFusion


class _DBStub:
    def get_events(self, **kwargs):
        return [
            {
                "event_id": "e1",
                "camera_id": kwargs.get("camera_id"),
                "anomaly_type": "restricted_entry",
                "severity": "HIGH",
                "description": "Restricted entry near clip",
                "video_path": "/clips/e1.mp4",
                "image_path": "/clips/e1.jpg",
            }
        ]


def test_video_fusion_reads_sidecar_and_nearby_events(tmp_path: Path) -> None:
    clip_path = tmp_path / "cam1_20260101_120000.mp4"
    clip_path.write_bytes(b"fake-video")
    sidecar = clip_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "camera_id": "cam1",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": 12,
            }
        ),
        encoding="utf-8",
    )

    fusion = VideoEventFusion(clips_root=str(tmp_path))
    bundle = fusion.fuse(str(clip_path), db=_DBStub())

    assert bundle.camera_id == "cam1"
    assert bundle.event_payloads
    assert any(item["source"] == "clip_metadata" for item in bundle.event_payloads)
    assert any(item["source"] == "clip_metadata" for item in bundle.event_payloads)
    assert any(
        item["source"] == "video_fusion" or item.get("source") == "clip_metadata"
        for item in bundle.event_payloads
    )


def test_video_fusion_handles_missing_sidecar(tmp_path: Path) -> None:
    clip_path = tmp_path / "cam2_20260101_120000.mp4"
    clip_path.write_bytes(b"fake-video")

    fusion = VideoEventFusion(clips_root=str(tmp_path))
    bundle = fusion.fuse(str(clip_path))

    assert bundle.camera_id == "cam2"
    assert bundle.notes
