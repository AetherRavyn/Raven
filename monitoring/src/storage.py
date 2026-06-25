import os
import subprocess
import logging
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class ClipStorage:
    def __init__(self, config: Dict):
        self.config = config.get("storage", {})
        self.output_dir = Path(self.config.get("output_dir", "clips"))
        self.clip_duration = self.config.get("clip_duration_seconds", 30)
        self.buffer_before = self.config.get("buffer_before_seconds", 10)
        self.retention_days = self.config.get("retention_days", 30)
        self.format = self.config.get("format", "mp4")
        self.video_codec = self.config.get("video_codec", "libx264")
        self.quality = self.config.get("quality", 23)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.frame_buffer: Dict[str, List[bytes]] = {}
        self.ffmpeg_processes: Dict[str, subprocess.Popen] = {}

    def add_frame(self, camera_id: str, frame_data: bytes, timestamp: datetime):
        if camera_id not in self.frame_buffer:
            self.frame_buffer[camera_id] = []

        self.frame_buffer[camera_id].append(frame_data)

        max_buffer_frames = self.clip_duration * 25
        if len(self.frame_buffer[camera_id]) > max_buffer_frames:
            self.frame_buffer[camera_id] = self.frame_buffer[camera_id][
                -max_buffer_frames:
            ]

    def save_clip(
        self,
        camera_id: str,
        start_time: datetime,
        end_time: datetime,
        frames: Optional[List[bytes]] = None,
        metadata: Optional[Dict] = None,
    ) -> Optional[str]:
        if frames is None:
            frames = self.frame_buffer.get(camera_id, [])

        if not frames:
            logger.warning(f"No frames to save for camera {camera_id}")
            return None

        clip_filename = (
            f"{camera_id}_{start_time.strftime('%Y%m%d_%H%M%S')}.{self.format}"
        )
        clip_path = self.output_dir / clip_filename

        try:
            self._write_frames_to_clip(frames, str(clip_path))

            metadata_path = clip_path.with_suffix(".json")
            clip_metadata = {
                "camera_id": camera_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": (end_time - start_time).total_seconds(),
                "frame_count": len(frames),
                "format": self.format,
                "additional": metadata or {},
            }

            with open(metadata_path, "w") as f:
                json.dump(clip_metadata, f, indent=2)

            logger.info(f"Saved clip: {clip_path}")
            return str(clip_path)

        except Exception as e:
            logger.error(f"Failed to save clip for {camera_id}: {e}")
            return None

    def _write_frames_to_clip(self, frames: List[bytes], output_path: str):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".raw"
        ) as raw_file:
            for frame in frames:
                raw_file.write(frame)
            raw_path = raw_file.name

        try:
            width, height = 1920, 1080
            pix_fmt = "rgb24"

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-s",
                f"{width}x{height}",
                "-pix_fmt",
                pix_fmt,
                "-r",
                "25",
                "-i",
                raw_path,
                "-c:v",
                self.video_codec,
                "-preset",
                "ultrafast",
                "-crf",
                str(self.quality),
                "-pix_fmt",
                "yuv420p",
                output_path,
            ]

            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr.decode()}")
                raise Exception(f"FFmpeg failed with code {result.returncode}")

        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)

    def start_continuous_recording(self, camera_id: str, stream_url: str):
        clip_filename = f"{camera_id}_continuous_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self.format}"
        clip_path = self.output_dir / clip_filename

        cmd = [
            "ffmpeg",
            "-i",
            stream_url,
            "-c:v",
            self.video_codec,
            "-preset",
            "ultrafast",
            "-crf",
            str(self.quality),
            "-segment_time",
            str(self.clip_duration),
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            str(self.output_dir / f"{camera_id}_%Y%m%d_%H%M%S.{self.format}"),
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.ffmpeg_processes[camera_id] = process
        logger.info(f"Started continuous recording for {camera_id}")

        return process

    def stop_continuous_recording(self, camera_id: str):
        if camera_id in self.ffmpeg_processes:
            self.ffmpeg_processes[camera_id].terminate()
            del self.ffmpeg_processes[camera_id]
            logger.info(f"Stopped continuous recording for {camera_id}")

    def cleanup_old_clips(self):
        if self.retention_days <= 0:
            return

        cutoff = datetime.now().timestamp() - (self.retention_days * 86400)

        for clip_file in self.output_dir.glob(f"*.{self.format}"):
            if clip_file.stat().st_mtime < cutoff:
                clip_file.unlink()

                metadata_file = clip_file.with_suffix(".json")
                if metadata_file.exists():
                    metadata_file.unlink()

                logger.info(f"Deleted old clip: {clip_file}")

    def get_clips(
        self, camera_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        pattern = f"{camera_id}_*.{self.format}" if camera_id else f"*.{self.format}"

        clips = []
        for clip_file in sorted(
            self.output_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True
        )[:limit]:
            metadata_file = clip_file.with_suffix(".json")

            clip_info = {
                "path": str(clip_file),
                "filename": clip_file.name,
                "size_bytes": clip_file.stat().st_size,
                "created": datetime.fromtimestamp(
                    clip_file.stat().st_mtime
                ).isoformat(),
            }

            if metadata_file.exists():
                with open(metadata_file) as f:
                    clip_info["metadata"] = json.load(f)

            clips.append(clip_info)

        return clips


class StorageService:
    """Microservice wrapper for ClipStorage using MessageBus."""

    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.storage_manager = ClipStorage(config or {})
        self.bus.subscribe("events", self.process_events)

    def process_events(self, payload):
        try:
            event_id = payload.get("event_id")
            if not event_id:
                return

            anomaly_type = payload.get("anomaly_type")
            severity = payload.get("severity")
            description = payload.get("description")
            frame_b64 = payload.get("frame_b64")

            if not anomaly_type:
                return

            import base64
            import numpy as np
            from PIL import Image
            import io

            frame = None
            if frame_b64:
                frame_bytes = base64.b64decode(frame_b64)
                image = Image.open(io.BytesIO(frame_bytes))
                frame = np.array(image)

            # Save event
            from monitoring.src.db.initdb import initDB
            from datetime import datetime

            if not hasattr(self, "db"):
                self.db = initDB()

            try:
                # Save image to disk if we have a frame
                image_path = None
                if frame is not None:
                    # e.g., /var/lib/raven/clips/event_{event_id}.jpg
                    image_filename = f"event_{event_id}.jpg"
                    image_file_path = self.storage_manager.output_dir / image_filename
                    image.save(image_file_path, format="JPEG", quality=85)
                    image_path = str(image_file_path)

                self.db.sqlite.insert_event(
                    {
                        "event_id": event_id,
                        "event_type": anomaly_type,
                        "camera_id": payload.get("camera_id", "unknown"),
                        "location": payload.get("location", "unknown"),
                        "timestamp": datetime.fromtimestamp(
                            payload.get("timestamp", time.time())
                        ),
                        "identity": payload.get("identity", "Unknown"),
                        "confidence": payload.get("confidence", 0.0),
                        "anomaly_type": anomaly_type,
                        "severity": severity.lower() if severity else "low",
                        "risk_level": severity.lower() if severity else "low",
                        "description": description,
                        "image_path": image_path,
                        "video_path": None,  # Will be updated by clip saver if applicable
                        "metadata": {
                            "track_id": payload.get("track_id")
                        },
                    }
                )

                person_id = payload.get("identity", "Unknown")
                self.db.neo4j.add_person(
                    person_id=person_id,
                    features=[],
                    metadata={
                        "label": person_id,
                        "is_known": not person_id.lower().startswith("unknown"),
                        "last_seen": datetime.fromtimestamp(
                            payload.get("timestamp", time.time())
                        ).isoformat(),
                    },
                )
                self.db.neo4j.add_camera(
                    payload.get("camera_id", "unknown"),
                    location=payload.get("location", "unknown"),
                )
                self.db.neo4j.add_relationship(
                    person_id,
                    payload.get("camera_id", "unknown"),
                    datetime.utcnow(),
                    metadata={
                        "event_type": anomaly_type,
                        "severity": severity,
                    },
                )
            except Exception as exc:
                logger.warning("DB store failed: %s", exc)

            logger.info(f"Saved event {event_id}")
        except Exception as e:
            logger.error(f"Error processing events: {e}")

    def start(self):
        import time

        logger.info("Storage Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Storage Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus

    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = StorageService(bus)
    service.start()
