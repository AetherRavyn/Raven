"""VideoStreamTool — continuous camera feed via WebSocket.

FRIDAY-style: real-time video monitoring with motion detection,
recording, and streaming to dashboard.

Unlike CameraSnapshotTool (single frame), this provides:
- Continuous frame capture at configurable FPS
- WebSocket streaming to web dashboard
- Motion detection alerts
- Recording to disk with retention
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VideoStreamConfig:
    """Configuration for a video stream."""
    camera_id: str
    source: str  # "local" or "ha_entity"
    fps: int = 5
    resolution: tuple[int, int] = (640, 480)
    motion_detection: bool = True
    recording: bool = False
    retention_hours: int = 24


@dataclass(slots=True)
class MotionEvent:
    """A detected motion event."""
    camera_id: str
    timestamp: str
    frame_base64: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VideoStreamManager:
    """Manages continuous video streams from multiple cameras.

    FRIDAY-style: monitors cameras, detects motion, records events,
    and streams to the dashboard.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._workspace = Path(workspace_dir or Config.MEMORY_ROOT)
        self._streams: dict[str, VideoStreamConfig] = {}
        self._running: dict[str, bool] = {}
        self._motion_callbacks: list[Callable] = []
        self._frame_buffer: dict[str, bytes] = {}
        self._recording_dir = self._workspace / "recordings"
        self._recording_dir.mkdir(parents=True, exist_ok=True)

    def register_camera(self, config: VideoStreamConfig) -> None:
        """Register a camera for streaming."""
        self._streams[config.camera_id] = config
        logger.info("Registered camera: %s (source=%s, fps=%d)", config.camera_id, config.source, config.fps)

    def on_motion(self, callback: Callable) -> None:
        """Register a callback for motion events."""
        self._motion_callbacks.append(callback)

    async def start_stream(self, camera_id: str) -> bool:
        """Start capturing frames from a camera."""
        config = self._streams.get(camera_id)
        if not config:
            logger.warning("Camera %s not registered", camera_id)
            return False

        self._running[camera_id] = True
        asyncio.create_task(self._capture_loop(config))
        logger.info("Started stream for camera %s", camera_id)
        return True

    async def stop_stream(self, camera_id: str) -> None:
        """Stop capturing frames from a camera."""
        self._running[camera_id] = False
        logger.info("Stopped stream for camera %s", camera_id)

    async def _capture_loop(self, config: VideoStreamConfig) -> None:
        """Main capture loop for a camera."""
        import cv2

        cap = None
        try:
            if config.source == "local":
                cap = cv2.VideoCapture(0)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.resolution[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.resolution[1])
            # HA camera sources would use HTTP polling

            prev_frame = None
            frame_interval = 1.0 / config.fps

            while self._running.get(config.camera_id, False):
                start = time.time()

                if cap and cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        # Encode frame
                        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        frame_bytes = buffer.tobytes()
                        self._frame_buffer[config.camera_id] = frame_bytes

                        # Motion detection (frame differencing)
                        if config.motion_detection and prev_frame is not None:
                            motion_score = self._compute_motion(prev_frame, frame)
                            if motion_score > 0.02:  # Threshold
                                event = MotionEvent(
                                    camera_id=config.camera_id,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    frame_base64=base64.b64encode(frame_bytes).decode(),
                                    confidence=min(motion_score * 10, 1.0),
                                )
                                for cb in self._motion_callbacks:
                                    try:
                                        cb(event)
                                    except Exception:
                                        pass

                        prev_frame = frame.copy()

                        # Recording
                        if config.recording:
                            self._record_frame(config.camera_id, frame_bytes)

                # Maintain frame rate
                elapsed = time.time() - start
                sleep_time = max(0, frame_interval - elapsed)
                await asyncio.sleep(sleep_time)

        except Exception as exc:
            logger.error("Video capture loop error for %s: %s", config.camera_id, exc)
        finally:
            if cap:
                cap.release()

    def _compute_motion(self, prev_frame: Any, curr_frame: Any) -> float:
        """Compute motion score between two frames using frame differencing."""
        try:
            import cv2
            import numpy as np

            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(prev_gray, curr_gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            return np.sum(thresh) / (thresh.shape[0] * thresh.shape[1] * 255)
        except Exception:
            return 0.0

    def _record_frame(self, camera_id: str, frame_bytes: bytes) -> None:
        """Save a frame to the recording directory."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            cam_dir = self._recording_dir / camera_id / today
            cam_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%H%M%S_%f")
            path = cam_dir / f"{ts}.jpg"
            path.write_bytes(frame_bytes)
        except Exception:
            pass

    def get_latest_frame(self, camera_id: str) -> bytes | None:
        """Get the latest frame from a camera."""
        return self._frame_buffer.get(camera_id)

    def get_latest_frame_base64(self, camera_id: str) -> str | None:
        """Get the latest frame as base64."""
        frame = self.get_latest_frame(camera_id)
        if frame:
            return base64.b64encode(frame).decode()
        return None

    def list_cameras(self) -> list[dict[str, Any]]:
        """List all registered cameras."""
        return [
            {
                "camera_id": c.camera_id,
                "source": c.source,
                "fps": c.fps,
                "running": self._running.get(c.camera_id, False),
                "has_frame": c.camera_id in self._frame_buffer,
            }
            for c in self._streams.values()
        ]

    def cleanup_old_recordings(self, hours: int = 24) -> int:
        """Remove recordings older than retention_hours."""
        cutoff = time.time() - (hours * 3600)
        removed = 0
        for cam_dir in self._recording_dir.iterdir():
            if not cam_dir.is_dir():
                continue
            for date_dir in cam_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                for frame_file in date_dir.glob("*.jpg"):
                    if frame_file.stat().st_mtime < cutoff:
                        frame_file.unlink()
                        removed += 1
                # Remove empty date dirs
                if not any(date_dir.iterdir()):
                    date_dir.rmdir()
        return removed


# Singleton
_video_manager: VideoStreamManager | None = None


def get_video_manager() -> VideoStreamManager:
    global _video_manager
    if _video_manager is None:
        _video_manager = VideoStreamManager()
    return _video_manager
