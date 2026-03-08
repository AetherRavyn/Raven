import numpy as np
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ZoomCropAnalyzer:
    def __init__(self, config: Dict):
        self.config = config.get("zoom_crop", {})
        self.enabled = self.config.get("enabled", True)
        self.target_fps = self.config.get("target_fps", 5)
        self.max_zoom = self.config.get("max_zoom", 4)
        self.min_object_area = self.config.get("min_object_area", 2000)
        self.overlap_threshold = self.config.get("overlap_threshold", 0.3)
        self.analysis_interval = self.config.get("analysis_interval", 30)

        self.frame_buffer: List[Tuple[np.ndarray, datetime]] = []
        self.last_analysis_time: Optional[datetime] = None
        self.analysis_results: Dict = {}

    def add_frame(self, frame: np.ndarray, timestamp: datetime):
        if not self.enabled:
            return

        self.frame_buffer.append((frame.copy(), timestamp))

        max_frames = self.target_fps * self.analysis_interval
        if len(self.frame_buffer) > max_frames:
            self.frame_buffer = self.frame_buffer[-max_frames:]

    def should_analyze(self, current_time: datetime) -> bool:
        if not self.enabled:
            return False

        if self.last_analysis_time is None:
            return True

        elapsed = (current_time - self.last_analysis_time).total_seconds()
        return elapsed >= self.analysis_interval

    def analyze_roi(
        self, tracks: List, frame: np.ndarray, camera_id: str
    ) -> List[Dict]:
        if not self.enabled or not tracks:
            return []

        results = []
        tracked_objects = [t for t in tracks if t.class_name == "person"]

        for track in tracked_objects:
            bbox = track.bbox
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

            if area < self.min_object_area:
                continue

            zoom_level = self._calculate_zoom(area, frame.shape)
            crop_coords = self._calculate_crop(bbox, frame.shape, zoom_level)

            if crop_coords is None:
                continue

            cropped_frame = self._crop_frame(frame, crop_coords)

            result = {
                "track_id": track.track_id,
                "camera_id": camera_id,
                "zoom_level": zoom_level,
                "crop_coords": crop_coords,
                "timestamp": datetime.now(),
                "cropped_frame": cropped_frame,
                "original_bbox": bbox,
            }
            results.append(result)

        return results

    def _calculate_zoom(self, object_area: int, frame_shape: Tuple) -> float:
        h, w = frame_shape[:2]
        frame_area = h * w

        area_ratio = frame_area / (object_area + 1)
        zoom = min(self.max_zoom, max(1.0, np.sqrt(area_ratio) / 2))

        return zoom

    def _calculate_crop(
        self, bbox: List[float], frame_shape: Tuple, zoom: float
    ) -> Optional[Tuple[int, int, int, int]]:
        h, w = frame_shape[:2]
        x1, y1, x2, y2 = bbox

        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        crop_w = (x2 - x1) * zoom
        crop_h = (y2 - y1) * zoom

        crop_x1 = int(center_x - crop_w / 2)
        crop_y1 = int(center_y - crop_h / 2)
        crop_x2 = int(center_x + crop_w / 2)
        crop_y2 = int(center_y + crop_h / 2)

        if crop_x1 < 0 or crop_y1 < 0 or crop_x2 > w or crop_y2 > h:
            padding_x = max(0, -crop_x1) + max(0, crop_x2 - w)
            padding_y = max(0, -crop_y1) + max(0, crop_y2 - h)

            if padding_x > crop_w * 0.5 or padding_y > crop_h * 0.5:
                return None

            crop_x1 = max(0, crop_x1)
            crop_y1 = max(0, crop_y1)
            crop_x2 = min(w, crop_x2)
            crop_y2 = min(h, crop_y2)

        return (crop_x1, crop_y1, crop_x2, crop_y2)

    def _crop_frame(
        self, frame: np.ndarray, crop_coords: Tuple[int, int, int, int]
    ) -> np.ndarray:
        x1, y1, x2, y2 = crop_coords
        return frame[y1:y2, x1:x2]

    def get_buffer_frames(self, count: int = 30) -> List[Tuple[np.ndarray, datetime]]:
        if not self.frame_buffer:
            return []

        return self.frame_buffer[-count:]

    def clear_buffer(self):
        self.frame_buffer.clear()
        self.analysis_results.clear()
