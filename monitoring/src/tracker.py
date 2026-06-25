import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import torch

logger = logging.getLogger(__name__)


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    bbox: List[float]
    confidence: float
    feature: Optional[np.ndarray] = None
    timestamp: float = 0.0
    frame_id: int = 0
    hits: int = 0
    age: int = 0
    time_since_update: int = 0
    last_seen: float = 0.0
    state: str = "tracked"
    zones_visited: List[str] = field(default_factory=list)
    total_distance: float = 0.0
    last_position: Optional[Tuple[float, float]] = None
    trajectory: List[Tuple[float, float]] = field(default_factory=list)


class ByteTrackTracker:
    def __init__(self, config: Dict):
        self.config = config
        self.track_thresh = config.get("track_thresh", 0.5)
        self.track_buffer = config.get("track_buffer", 30)
        self.match_thresh = config.get("match_thresh", 0.8)
        self.min_box_area = config.get("min_box_area", 10)
        self.max_time_lost = config.get("max_time_lost", 30)
        self.min_kalman_interval = config.get("min_kalman_interval", 2)
        self.use_byte = config.get("use_byte", True)

        self.tracks: Dict[int, Track] = {}
        self.track_id_count = 0
        self.frame_count = 0
        self._init_kalman()

        self.use_reid = config.get("with_reid", True)
        self.reid_model = None
        if self.use_reid:
            self._init_reid(config)

    def _init_kalman(self):
        try:
            from scipy.linalg import block_diag

            self.kalman_filter = self._KalmanFilter()
            logger.info("Kalman filter initialized")
        except ImportError:
            logger.warning("Scipy not available, using simple tracking")
            self.kalman_filter = None

    def _init_reid(self, config: Dict):
        try:
            import torchreid

            reid_model_name = config.get("reid_model", "osnet_x0_25")
            reid_device = config.get(
                "reid_device", "cuda" if torch.cuda.is_available() else "cpu"
            )

            self.reid_model = torchreid.models.build_model(
                name=reid_model_name, num_classes=1, pretrained=True
            )
            self.reid_model.to(reid_device)
            self.reid_model.eval()
            self.reid_device = reid_device
            logger.info(f"ReID model ({reid_model_name}) loaded on {reid_device}")
        except ImportError:
            logger.warning("Torchreid not available, disabling ReID")
            self.reid_model = None

    class _KalmanFilter:
        def __init__(self):
            self._motion_mat = np.eye(8, 8)
            self._motion_mat[:4, 4:] = np.eye(4) * 0.01

        def predict(self, mean, covariance):
            return mean, covariance

        def update(self, mean, covariance, measurement):
            return mean, covariance

    def update(
        self, detections: List, frame: np.ndarray, timestamp: float
    ) -> List[Track]:
        self.frame_count += 1

        if not detections:
            self._mark_lost()
            return list(self.tracks.values())

        dets_for_tracking = []
        for det in detections:
            if (det.bbox[2] - det.bbox[0]) * (
                det.bbox[3] - det.bbox[1]
            ) >= self.min_box_area:
                dets_for_tracking.append(det)

        if not dets_for_tracking:
            self._mark_lost()
            return list(self.tracks.values())

        det_bboxes = np.array([d.bbox for d in dets_for_tracking])
        det_scores = np.array([d.confidence for d in dets_for_tracking])

        features = None
        if self.reid_model is not None:
            features = self._extract_reid_features(frame, det_bboxes)

        matched, unmatched_dets, unmatched_tracks = self._associate(
            det_bboxes, det_scores, features
        )

        for det_idx, track_id in matched:
            self._update_track(
                track_id,
                dets_for_tracking[det_idx],
                features[det_idx] if features is not None else None,
                timestamp,
            )

        for det_idx in unmatched_dets:
            new_track = self._create_track(
                dets_for_tracking[det_idx],
                features[det_idx] if features is not None else None,
                timestamp,
            )
            self.tracks[new_track.track_id] = new_track

        for track_id in unmatched_tracks:
            self.tracks[track_id].state = "lost"
            self.tracks[track_id].time_since_update += 1

        return list(self.tracks.values())

    def _extract_reid_features(
        self, frame: np.ndarray, bboxes: np.ndarray
    ) -> List[np.ndarray]:
        import torch
        from torchvision import transforms

        features = []
        h, w = frame.shape[:2]
        transform = transforms.Compose(
            [
                transforms.ToPILImage(),
                transforms.Resize((256, 128)),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

        for bbox in bboxes:
            x1, y1, x2, y2 = map(int, bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
                if crop.size > 0:
                    try:
                        tensor = transform(crop).unsqueeze(0).to(self.reid_device)
                        with torch.no_grad():
                            feat = self.reid_model(tensor)
                        features.append(feat.cpu().numpy().flatten())
                        continue
                    except Exception as e:
                        logger.debug(f"ReID feature extraction failed: {e}")

            features.append(np.zeros(512))

        return features

    def _associate(
        self,
        det_bboxes: np.ndarray,
        det_scores: np.ndarray,
        features: Optional[List[np.ndarray]],
    ):
        if not self.tracks:
            return [], list(range(len(det_bboxes))), []

        track_ids = list(self.tracks.keys())
        track_bboxes = np.array([self.tracks[tid].bbox for tid in track_ids])
        track_features = np.array(
            [
                (
                    self.tracks[tid].feature
                    if self.tracks[tid].feature is not None
                    else np.zeros(512)
                )
                for tid in track_ids
            ]
        )

        iou_matrix = self._compute_iou_matrix(det_bboxes, track_bboxes)

        matched = []
        unmatched_dets = list(range(len(det_bboxes)))
        unmatched_tracks = track_ids.copy()

        if self.use_reid and features is not None:
            feature_matrix = self._compute_feature_distance(features, track_features)
            cost_matrix = (1 - iou_matrix) * 0.5 + feature_matrix * 0.5
        else:
            cost_matrix = 1 - iou_matrix

        for _ in range(min(len(det_bboxes), len(track_ids))):
            if cost_matrix.size == 0:
                break

            min_idx = np.unravel_index(np.argmin(cost_matrix), cost_matrix.shape)
            det_idx, track_idx = min_idx

            if cost_matrix[det_idx, track_idx] > (1 - self.match_thresh):
                break

            matched.append((det_idx, track_ids[track_idx]))
            cost_matrix[det_idx, :] = float("inf")
            cost_matrix[:, track_idx] = float("inf")
            unmatched_dets.remove(det_idx)
            if track_ids[track_idx] in unmatched_tracks:
                unmatched_tracks.remove(track_ids[track_idx])

        return matched, unmatched_dets, unmatched_tracks

    def _compute_iou_matrix(self, boxes1: np.ndarray, boxes2: np.ndarray) -> np.ndarray:
        from monitoring.src.gpu import gpu_iou_matrix
        return gpu_iou_matrix(boxes1, boxes2)

    def _compute_feature_distance(
        self, features1: List[np.ndarray], features2: np.ndarray
    ) -> np.ndarray:
        features1 = np.array(features1)
        if features1.ndim == 1:
            features1 = features1.reshape(1, -1)

        distances = np.zeros((len(features1), len(features2)))

        for i, f1 in enumerate(features1):
            for j, f2 in enumerate(features2):
                distances[i, j] = 1 - np.dot(f1, f2) / (
                    np.linalg.norm(f1) * np.linalg.norm(f2) + 1e-6
                )

        return distances

    def _box_iou(self, box1: np.ndarray, box2: np.ndarray) -> float:
        x1_min, y1_min, x1_max, y1_max = box1
        x2_min, y2_min, x2_max, y2_max = box2

        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)

        if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
            return 0.0

        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
        box1_area = (x1_max - x1_min) * (y1_max - y1_min)
        box2_area = (x2_max - x2_min) * (y2_max - y2_min)

        return inter_area / (box1_area + box2_area - inter_area + 1e-6)

    def _create_track(
        self, detection, feature: Optional[np.ndarray], timestamp: float
    ) -> Track:
        self.track_id_count += 1
        bbox = detection.bbox
        center_x, center_y = (bbox[0] + bbox[2]) / 2, (bbox[3] + bbox[1]) / 2

        return Track(
            track_id=self.track_id_count,
            class_id=detection.class_id,
            class_name=detection.class_name,
            bbox=bbox,
            confidence=detection.confidence,
            feature=feature,
            timestamp=timestamp,
            frame_id=self.frame_count,
            hits=1,
            age=0,
            time_since_update=0,
            last_seen=timestamp,
            state="tracked",
            trajectory=[(center_x, center_y)],
            last_position=(center_x, center_y),
        )

    def _update_track(
        self, track_id: int, detection, feature: Optional[np.ndarray], timestamp: float
    ):
        track = self.tracks[track_id]

        old_center = track.last_position
        new_bbox = detection.bbox
        center_x, center_y = (
            (new_bbox[0] + new_bbox[2]) / 2,
            (new_bbox[3] + new_bbox[1]) / 2,
        )

        if old_center:
            distance = np.sqrt(
                (center_x - old_center[0]) ** 2 + (center_y - old_center[1]) ** 2
            )
            track.total_distance += distance

        track.bbox = new_bbox
        track.confidence = detection.confidence
        track.timestamp = timestamp
        track.frame_id = self.frame_count
        track.hits += 1
        track.age += 1
        track.time_since_update = 0
        track.last_seen = timestamp
        track.state = "tracked"

        if feature is not None:
            if track.feature is not None:
                track.feature = 0.9 * track.feature + 0.1 * feature
            else:
                track.feature = feature

        track.trajectory.append((center_x, center_y))
        track.last_position = (center_x, center_y)

    def _mark_lost(self):
        for track in self.tracks.values():
            if track.state == "tracked":
                track.state = "lost"
            track.time_since_update += 1
            if track.time_since_update > self.max_time_lost:
                track.state = "removed"

    def get_active_tracks(self) -> List[Track]:
        return [t for t in self.tracks.values() if t.state == "tracked"]

    def get_track_by_id(self, track_id: int) -> Optional[Track]:
        return self.tracks.get(track_id)

    def reset(self):
        self.tracks.clear()
        self.track_id_count = 0
        self.frame_count = 0


class TrackingService:
    """Microservice wrapper for ByteTrackTracker using MessageBus."""

    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.trackers = {}
        self.config = config or {"track_thresh": 0.5}
        self.bus.subscribe("detections", self.process_detections)

    def process_detections(self, payload):
        try:
            camera_id = payload.get("camera_id")
            if not camera_id:
                return

            if camera_id not in self.trackers:
                self.trackers[camera_id] = ByteTrackTracker(self.config)

            tracker = self.trackers[camera_id]
            detections = payload.get("detections", [])
            frame_b64 = payload.get("frame_b64")

            import time

            timestamp = payload.get("timestamp", time.time())

            if not frame_b64:
                return

            import base64
            import numpy as np
            from PIL import Image
            import io

            frame_bytes = base64.b64decode(frame_b64)
            image = Image.open(io.BytesIO(frame_bytes))
            frame = np.array(image)

            from monitoring.src.detection import Detection

            det_objs = [
                Detection(
                    class_id=d["class_id"],
                    class_name=d["class_name"],
                    confidence=d["confidence"],
                    bbox=d["bbox"],
                )
                for d in detections
            ]

            tracked_objects = tracker.update(det_objs, frame, timestamp)

            # Publish tracked objects
            tracked_payload = {
                "camera_id": camera_id,
                "camera_name": payload["camera_name"],
                "location": payload["location"],
                "timestamp": timestamp,
                "frame_b64": frame_b64,
                "tracked_objects": [
                    {
                        "track_id": t.track_id,
                        "class_id": t.class_id,
                        "class_name": t.class_name,
                        "confidence": t.confidence,
                        "bbox": t.bbox,
                    }
                    for t in tracked_objects
                ],
            }
            self.bus.publish("tracked_objects", tracked_payload)
            logger.info(
                f"Published {len(tracked_objects)} tracked objects for {camera_id}"
            )
        except Exception as e:
            logger.error(f"Error processing detections: {e}")

    def start(self):
        import time

        logger.info("Tracking Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Tracking Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus

    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = TrackingService(bus)
    service.start()
