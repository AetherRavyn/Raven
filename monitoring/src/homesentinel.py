import io
import importlib
import json
import logging
import os
import threading
import time
import urllib.request
import queue
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple, Callable, Any

import cv2
import numpy as np
from PIL import Image

from monitoring.src.alert import AlertManager
from monitoring.src.anomaly import AnomalyDetector
from monitoring.src.db.initdb import initDB
from monitoring.src.detection import YOLODetector
from monitoring.src.reid import ReID
from monitoring.src.tracker import ByteTrackTracker

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    camera_id: str
    camera_name: str
    location: str
    protocol: str
    stream_url: str
    enabled: bool = True

    @staticmethod
    def from_dict(raw: Dict) -> "CameraConfig":
        protocol = str(raw.get("protocol") or "rtsp").lower()
        stream_url = (
            raw.get("stream_url")
            or raw.get("rtsp_url")
            or raw.get("http_url")
            or raw.get("url")
            or ""
        )
        return CameraConfig(
            camera_id=str(raw.get("camera_id") or raw.get("id") or ""),
            camera_name=str(raw.get("camera_name") or raw.get("name") or "Camera"),
            location=str(raw.get("location") or "unknown"),
            protocol=protocol,
            stream_url=str(stream_url),
            enabled=bool(raw.get("enabled", True)),
        )


class CameraStream:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_jpeg: Optional[bytes] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "Camera stream started: %s (%s)", self.cfg.camera_id, self.cfg.protocol
        )

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def _set_frame(self, frame: np.ndarray):
        ok, enc = cv2.imencode(".jpg", frame)
        with self._lock:
            self._latest_frame = frame
            self._latest_jpeg = enc.tobytes() if ok else None

    def _run(self):
        protocol = self.cfg.protocol.lower()
        if protocol in {"rtsp", "http", "usb", "file"}:
            self._run_opencv_capture()
        elif protocol in {"mjpeg", "http_mjpeg"}:
            self._run_mjpeg_capture()
        elif protocol in {"websocket", "ws"}:
            self._run_ws_capture()
        else:
            logger.error(
                "Unsupported protocol for %s: %s", self.cfg.camera_id, protocol
            )

    def _opencv_source(self):
        if self.cfg.protocol.lower() == "usb":
            url = self.cfg.stream_url.strip()
            if url.startswith("/dev/video"):
                suffix = url.replace("/dev/video", "")
                if suffix.isdigit():
                    return int(suffix)
            if url.isdigit():
                return int(url)
        return self.cfg.stream_url

    def _run_opencv_capture(self):
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self._opencv_source())
            if not cap.isOpened():
                logger.warning("Could not open %s; retrying", self.cfg.camera_id)
                time.sleep(2)
                continue
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        break
                    self._set_frame(frame)
            finally:
                cap.release()
            time.sleep(0.5)

    def _run_mjpeg_capture(self):
        while not self._stop.is_set():
            try:
                req = urllib.request.urlopen(self.cfg.stream_url, timeout=10)
                content_type = req.headers.get("Content-Type", "")
                boundary = None
                if "boundary=" in content_type:
                    boundary = content_type.split("boundary=")[-1].encode()
                    if boundary.startswith(b"--"):
                        boundary = boundary[2:]

                buf = b""
                while not self._stop.is_set():
                    chunk = req.read(8192)
                    if not chunk:
                        break
                    buf += chunk

                    if boundary and boundary in buf:
                        parts = buf.split(boundary)
                        for part in parts[:-1]:
                            start = part.find(b"\xff\xd8")
                            end = part.rfind(b"\xff\xd9")
                            if start != -1 and end > start:
                                jpg = part[start : end + 2]
                                arr = np.frombuffer(jpg, dtype=np.uint8)
                                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                                if frame is not None:
                                    self._set_frame(frame)
                        buf = parts[-1]
            except Exception as exc:
                logger.warning("MJPEG error on %s: %s", self.cfg.camera_id, exc)
                time.sleep(2)

    def _run_ws_capture(self):
        try:
            websocket = importlib.import_module("websocket")
        except Exception:
            logger.error("websocket-client not installed; cannot use WS protocol")
            return

        while not self._stop.is_set():
            try:
                ws = websocket.create_connection(self.cfg.stream_url, timeout=5)
                while not self._stop.is_set():
                    payload = ws.recv()
                    if isinstance(payload, str):
                        payload = payload.encode()
                    arr = np.frombuffer(payload, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self._set_frame(frame)
                ws.close()
            except Exception as exc:
                logger.warning("WS error on %s: %s", self.cfg.camera_id, exc)
                time.sleep(2)


@dataclass
class RuntimeEvent:
    event_id: str
    timestamp: str
    camera_id: str
    camera_name: str
    location: str
    track_id: Optional[int]
    identity: str
    confidence: float
    anomaly_type: str
    severity: str
    description: str
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    metadata: Optional[Dict] = None


class CameraIngestionService:
    """Microservice wrapper for CameraStream using Redis MessageBus."""

    def __init__(self, config: CameraConfig, bus):
        self.config = config
        self.bus = bus
        self.stream = CameraStream(config)

    def start(self):
        import base64
        import io
        from PIL import Image

        self.stream.start()
        logger.info(f"Camera Ingestion Service started for {self.config.camera_id}")
        try:
            while True:
                frame = self.stream.get_frame()
                if frame is not None:
                    # Encode frame to base64 for Redis using PIL
                    image = Image.fromarray(frame[..., ::-1])  # Convert BGR to RGB
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG")
                    frame_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

                    payload = {
                        "camera_id": self.config.camera_id,
                        "camera_name": self.config.camera_name,
                        "location": self.config.location,
                        "timestamp": time.time(),
                        "frame_b64": frame_b64,
                    }
                    self.bus.publish("raw_frames", payload)
                time.sleep(0.1)  # 10 FPS
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.stream.stop()
        self.bus.stop()
        logger.info(f"Camera Ingestion Service stopped for {self.config.camera_id}")


from monitoring.src.message_bus import MessageBus


class HouseMappingEngine:
    """Maintains a 3D spatial model of the house."""

    def __init__(self):
        # Simple adjacency graph for rooms
        self.adjacency = {
            "Gate": ["Yard"],
            "Yard": ["Gate", "LivingRoom", "Kitchen"],
            "LivingRoom": ["Yard", "Kitchen", "ServerRoom"],
            "Kitchen": ["Yard", "LivingRoom"],
            "ServerRoom": ["LivingRoom"],
        }
        self.restricted_areas = {"ServerRoom"}

    def get_adjacent_rooms(self, location: str) -> List[str]:
        return self.adjacency.get(location, [])

    def is_restricted(self, location: str) -> bool:
        return location in self.restricted_areas


class PathPredictionAI:
    """Predicts where a person is likely to go based on room adjacency."""

    def __init__(self, mapping_engine: HouseMappingEngine):
        self.mapping = mapping_engine

    def predict_next(self, current_location: str) -> Dict[str, float]:
        adjacent = self.mapping.get_adjacent_rooms(current_location)
        if not adjacent:
            return {}
        # Simple uniform probability for now
        prob = 1.0 / len(adjacent)
        return {room: prob for room in adjacent}


class SuspicionScoringAI:
    """Calculates a dynamic suspicion score (0.0 to 1.0)."""

    def __init__(self, mapping_engine: HouseMappingEngine):
        self.mapping = mapping_engine

    def calculate_score(
        self, identity: str, location: str, is_night: bool, has_weapon: bool
    ) -> Tuple[float, str]:
        score = 0.1  # Base score

        if identity.lower().startswith("unknown"):
            score += 0.4
            if is_night:
                score += 0.3

        if self.mapping.is_restricted(location):
            score += 0.5

        if has_weapon:
            score += 0.8

        score = min(1.0, score)

        if score < 0.2:
            severity = "LOW"
        elif score < 0.5:
            severity = "MEDIUM"
        elif score < 0.8:
            severity = "HIGH"
        else:
            severity = "CRITICAL"

        return score, severity


class EdgeAIScheduler:
    """Controls CPU usage and FPS dynamically."""

    def __init__(self):
        self.base_fps = 5
        self.max_fps = 15
        self.current_fps = self.base_fps
        self.last_activity = time.time()

    def register_activity(self):
        self.last_activity = time.time()
        self.current_fps = self.max_fps

    def get_sleep_time(self) -> float:
        # Decay FPS if no activity for 10 seconds
        if time.time() - self.last_activity > 10:
            self.current_fps = self.base_fps
        return 1.0 / self.current_fps


class MultiObjectReasoningEngine:
    """Reasons about relationships between objects and people."""

    def __init__(self):
        self.person_holdings: Dict[int, str] = {}  # track_id -> object_class
        self.recent_disappearances: Deque[Tuple[str, str, datetime]] = deque(
            maxlen=50
        )  # (camera_id, object_class, time)

    def analyze_frame(
        self, tracks: List, camera_id: str, ts: datetime
    ) -> List[RuntimeEvent]:
        events = []
        persons = [t for t in tracks if t.class_name == "person"]
        objects = [t for t in tracks if t.class_name != "person"]

        # 1. Check for objects near people (Holding/Carrying)
        for p in persons:
            px1, py1, px2, py2 = p.bbox
            for o in objects:
                ox1, oy1, ox2, oy2 = o.bbox
                # Simple intersection over union or proximity check
                # If object is inside or very close to person bounding box
                if (
                    ox1 >= px1 - 20
                    and ox2 <= px2 + 20
                    and oy1 >= py1 - 20
                    and oy2 <= py2 + 20
                ):

                    self.person_holdings[p.track_id] = o.class_name

                    # If it's a dangerous object, we flag it immediately
                    if o.class_name in {"knife", "scissors", "gun"}:
                        events.append(
                            RuntimeEvent(
                                event_id=f"reason_wpn_{camera_id}_{int(ts.timestamp()*1000)}",
                                timestamp=ts.isoformat(),
                                camera_id=camera_id,
                                camera_name="Camera",  # Will be filled by caller
                                location="Unknown",  # Will be filled by caller
                                track_id=p.track_id,
                                identity="Unknown",  # Will be filled by caller
                                confidence=0.8,
                                anomaly_type="person_holding_weapon",
                                severity="CRITICAL",
                                description=f"Person {p.track_id} is holding a {o.class_name}",
                                metadata={"object": o.class_name},
                            )
                        )

        # 2. Check for theft/removal (Person was holding X, now X is gone)
        # This requires cross-referencing with object disappearances
        # We will handle this in the ingest method of CorrelationEngine for cross-frame logic

        return events

    def register_disappearance(self, camera_id: str, object_class: str, ts: datetime):
        self.recent_disappearances.append((camera_id, object_class, ts))

    def check_for_removal(self, camera_id: str, ts: datetime) -> List[RuntimeEvent]:
        events = []
        # If an object disappeared recently, and a person was seen holding it recently
        for cam, obj, dis_ts in list(self.recent_disappearances):
            if (ts - dis_ts).total_seconds() < 10:  # Within 10 seconds
                for track_id, held_obj in list(self.person_holdings.items()):
                    if held_obj == obj:
                        events.append(
                            RuntimeEvent(
                                event_id=f"reason_rmv_{camera_id}_{int(ts.timestamp()*1000)}",
                                timestamp=ts.isoformat(),
                                camera_id=camera_id,
                                camera_name="Camera",
                                location="Unknown",
                                track_id=track_id,
                                identity="Unknown",
                                confidence=0.7,
                                anomaly_type="possible_object_removal",
                                severity="HIGH",
                                description=f"Object '{obj}' disappeared while Person {track_id} was nearby",
                                metadata={"object": obj},
                            )
                        )
                        # Clear to prevent duplicate alerts
                        self.recent_disappearances.remove((cam, obj, dis_ts))
                        del self.person_holdings[track_id]
                        break
        return events


class SelfLearningBehaviorModel:
    """Learns normal patterns using lightweight time histograms and transition matrices."""

    def __init__(self):
        # location -> hour -> count
        self.location_time_histogram: Dict[str, Dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # (from_loc, to_loc) -> count
        self.transition_matrix: Dict[Tuple[str, str], int] = defaultdict(int)
        self.last_seen_location: Dict[str, Tuple[str, datetime]] = (
            {}
        )  # identity -> (location, time)

    def observe(self, identity: str, location: str, ts: datetime):
        if identity.lower().startswith("unknown"):
            return  # Don't learn from unknowns

        # Update time histogram
        self.location_time_histogram[location][ts.hour] += 1

        # Update transition matrix
        if identity in self.last_seen_location:
            last_loc, last_ts = self.last_seen_location[identity]
            if (
                last_loc != location and (ts - last_ts).total_seconds() < 300
            ):  # Moved within 5 mins
                self.transition_matrix[(last_loc, location)] += 1

        self.last_seen_location[identity] = (location, ts)

    def is_unusual_time(self, location: str, hour: int) -> bool:
        """Returns True if this location is rarely visited at this hour."""
        if not self.location_time_histogram[location]:
            return False  # Not enough data

        total_visits = sum(self.location_time_histogram[location].values())
        if total_visits < 20:
            return False  # Need baseline data

        hour_visits = self.location_time_histogram[location].get(hour, 0)
        probability = hour_visits / total_visits

        return probability < 0.05  # Less than 5% of visits happen at this hour


class EdgeToEdgeNetwork:
    """Simulates P2P communication between edge nodes for sharing intelligence."""

    def __init__(self, message_bus: MessageBus):
        self.bus = message_bus
        self.known_embeddings: Dict[str, np.ndarray] = {}
        self.active_tracks: Dict[int, Dict] = {}

        # Subscribe to local events to broadcast them
        self.bus.subscribe("tracking.objects", self._broadcast_track)
        self.bus.subscribe("faces.detected", self._broadcast_face)

    def _broadcast_track(self, payload: Dict):
        # In a real distributed system, this would send a UDP/TCP packet to other nodes
        # For now, we simulate it by updating the shared state
        self.active_tracks[payload["track_id"]] = payload

    def _broadcast_face(self, payload: Dict):
        if payload.get("identity") and not payload["identity"].lower().startswith(
            "unknown"
        ):
            self.known_embeddings[payload["identity"]] = payload.get("embedding")

    def get_global_track(self, track_id: int) -> Optional[Dict]:
        return self.active_tracks.get(track_id)


class SmartCachingSystem:
    """Caches detection results and embeddings to avoid repeated computation."""

    def __init__(self):
        self.detection_cache: Dict[str, Tuple[float, List]] = (
            {}
        )  # frame_hash -> (timestamp, detections)
        self.embedding_cache: Dict[str, Tuple[float, str, float]] = (
            {}
        )  # crop_hash -> (timestamp, identity, score)
        self.ttl_seconds = 2.0

    def _hash_frame(self, frame: np.ndarray) -> str:
        # Fast hash using center pixels and shape
        h, w = frame.shape[:2]
        center = frame[h // 2 - 10 : h // 2 + 10, w // 2 - 10 : w // 2 + 10]
        return f"{h}x{w}_{hash(center.tobytes())}"

    def get_cached_detections(self, frame: np.ndarray) -> Optional[List]:
        f_hash = self._hash_frame(frame)
        if f_hash in self.detection_cache:
            ts, dets = self.detection_cache[f_hash]
            if time.time() - ts < self.ttl_seconds:
                return dets
        return None

    def set_cached_detections(self, frame: np.ndarray, detections: List):
        f_hash = self._hash_frame(frame)
        self.detection_cache[f_hash] = (time.time(), detections)

    def get_cached_identity(self, crop: np.ndarray) -> Optional[Tuple[str, float]]:
        c_hash = self._hash_frame(crop)
        if c_hash in self.embedding_cache:
            ts, ident, score = self.embedding_cache[c_hash]
            if time.time() - ts < self.ttl_seconds:
                return ident, score
        return None

    def set_cached_identity(self, crop: np.ndarray, identity: str, score: float):
        c_hash = self._hash_frame(crop)
        self.embedding_cache[c_hash] = (time.time(), identity, score)


class CorrelationEngine:
    def __init__(self):
        self.history: Deque[RuntimeEvent] = deque(maxlen=1500)

    def ingest(self, event: RuntimeEvent) -> List[RuntimeEvent]:
        self.history.append(event)
        now = datetime.fromisoformat(event.timestamp)
        correlated: List[RuntimeEvent] = []

        if event.identity.lower().startswith("unknown"):
            recent_unknown = [
                e
                for e in self.history
                if e.identity == event.identity
                and e.camera_id != event.camera_id
                and datetime.fromisoformat(e.timestamp) >= now - timedelta(minutes=5)
            ]
            if recent_unknown:
                correlated.append(
                    RuntimeEvent(
                        event_id=f"corr_{int(time.time()*1000)}",
                        timestamp=event.timestamp,
                        camera_id=event.camera_id,
                        camera_name=event.camera_name,
                        location=event.location,
                        track_id=event.track_id,
                        identity=event.identity,
                        confidence=event.confidence,
                        anomaly_type="cross_camera_movement",
                        severity="HIGH",
                        description=f"{event.identity} moved across multiple cameras",
                        metadata={
                            "camera_path": list(
                                {e.camera_id for e in recent_unknown}
                                | {event.camera_id}
                            )
                        },
                    )
                )

        if event.anomaly_type == "dangerous_object_near_child":
            correlated.append(event)

        return correlated


class IntelligenceService:
    """Microservice wrapper for v4 Advanced AI logic using Redis MessageBus."""

    def __init__(self, bus):
        self.bus = bus
        self.house_mapping = HouseMappingEngine()
        self.path_prediction = PathPredictionAI(self.house_mapping)
        self.suspicion_scoring = SuspicionScoringAI(self.house_mapping)
        self.reasoning_engine = MultiObjectReasoningEngine()
        self.behavior_model = SelfLearningBehaviorModel()
        self.edge_network = EdgeToEdgeNetwork(self.bus)

        self.bus.subscribe("tracked_objects", self.process_tracked_objects)
        self.bus.subscribe("identities", self.process_identities)
        self.current_identities = {}

    def process_identities(self, payload):
        camera_id = payload.get("camera_id")
        if not camera_id:
            return
        if camera_id not in self.current_identities:
            self.current_identities[camera_id] = {}
        for identity in payload.get("identities", []):
            self.current_identities[camera_id][identity["track_id"]] = identity

    def process_tracked_objects(self, payload):
        try:
            camera_id = payload.get("camera_id")
            if not camera_id:
                return

            tracked_objects = payload.get("tracked_objects", [])
            timestamp = datetime.fromtimestamp(payload.get("timestamp", time.time()))
            location = payload.get("location", "unknown")

            for obj in tracked_objects:
                track_id = obj["track_id"]
                identity_info = self.current_identities.get(camera_id, {}).get(
                    track_id, {}
                )
                identity = identity_info.get("identity", "Unknown")

                if obj["class_name"] == "person":
                    # Self-Learning Behavior Model
                    self.behavior_model.observe(identity, location, timestamp)
                    is_unusual_time = self.behavior_model.is_unusual_time(
                        location, timestamp.hour
                    )

                    # Suspicion Scoring
                    has_weapon = False  # Would come from reasoning engine
                    is_night = timestamp.hour < 6 or timestamp.hour > 20
                    score, reason = self.suspicion_scoring.calculate_score(
                        identity, location, is_night, has_weapon
                    )

                    if is_unusual_time:
                        score += 0.2
                        reason += " | Unusual time for this person"

                    if score > 0.7:
                        event_payload = {
                            "event_id": f"suspicion_{int(time.time())}_{track_id}",
                            "timestamp": payload["timestamp"],
                            "camera_id": camera_id,
                            "camera_name": payload["camera_name"],
                            "location": location,
                            "track_id": track_id,
                            "identity": identity,
                            "confidence": score,
                            "anomaly_type": "high_suspicion",
                            "severity": "high",
                            "description": reason,
                            "frame_b64": payload.get("frame_b64"),
                        }
                        self.bus.publish("events", event_payload)
                        logger.info(
                            f"Published high suspicion event for {identity} at {location}"
                        )

                    # Path Prediction
                    predictions = self.path_prediction.predict_next(location)
                    if predictions:
                        logger.debug(
                            f"Predicted next locations for {identity}: {predictions}"
                        )

        except Exception as e:
            logger.error(f"Error in IntelligenceService: {e}")

    def start(self):
        logger.info("Intelligence Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Intelligence Service stopped")


class HomeSentinelSystem:
    def __init__(self, config: Dict):
        self.config = config or {}
        self.db = initDB()

        monitoring_dir = Path(__file__).resolve().parent.parent
        model_path = monitoring_dir / "models" / "w600k_r50.onnx"
        known_dir = Path(__file__).resolve().parent / "known"

        self.reid = ReID(
            db=self.db,
            model_path=str(model_path),
            known_dir=str(known_dir),
            threshold=float(self.config.get("identity", {}).get("threshold", 0.6)),
            known_guard_threshold=float(
                self.config.get("identity", {}).get("known_guard_threshold", 0.9)
            ),
        )

        detection_cfg = self.config.get("detection", {})
        tracking_cfg = self.config.get("tracking", {})
        thresholds_cfg = self.config.get("thresholds", {})

        self.detector = YOLODetector(detection_cfg)
        self.anomaly_detector = AnomalyDetector(self.config, thresholds_cfg)
        self.alert_manager = AlertManager(self.config)
        self.correlation = CorrelationEngine()

        # v4 Architecture Components
        self.message_bus = MessageBus()
        self.house_mapping = HouseMappingEngine()
        self.path_prediction = PathPredictionAI(self.house_mapping)
        self.suspicion_scoring = SuspicionScoringAI(self.house_mapping)
        self.edge_scheduler = EdgeAIScheduler()
        self.reasoning_engine = MultiObjectReasoningEngine()
        self.behavior_model = SelfLearningBehaviorModel()
        self.edge_network = EdgeToEdgeNetwork(self.message_bus)
        self.smart_cache = SmartCachingSystem()

        self.capture_dir = Path(self.config.get("captures_dir", "captures"))
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self._cameras: Dict[str, CameraConfig] = {}
        self._streams: Dict[str, CameraStream] = {}
        self._trackers: Dict[str, ByteTrackTracker] = {}
        self._workers: Dict[str, threading.Thread] = {}
        self._stop = threading.Event()

        self._last_jpeg: Dict[str, bytes] = {}
        self._events: Deque[RuntimeEvent] = deque(maxlen=5000)
        self._object_memory: Dict[str, Dict[str, List[Tuple[float, float]]]] = (
            defaultdict(dict)
        )

        for raw in self.config.get("cameras", []):
            cam = CameraConfig.from_dict(raw)
            if cam.enabled:
                self.add_camera(cam)

    def start(self):
        self._stop.clear()

        import multiprocessing
        from monitoring.src.detection import YOLODetectionService
        from monitoring.src.tracker import TrackingService
        from monitoring.src.reid import ReIDService
        from monitoring.src.anomaly import EventService
        from monitoring.src.alert import AlertService
        from monitoring.src.storage import StorageService

        def run_service(service_class, *args):
            bus = MessageBus()
            service = service_class(bus, *args)
            service.start()

        self.processes = [
            multiprocessing.Process(
                target=run_service,
                args=(YOLODetectionService, self.config.get("detection", {})),
            ),
            multiprocessing.Process(
                target=run_service,
                args=(TrackingService, self.config.get("tracking", {})),
            ),
            multiprocessing.Process(
                target=run_service, args=(ReIDService, self.config)
            ),
            multiprocessing.Process(
                target=run_service, args=(EventService, self.config)
            ),
            multiprocessing.Process(
                target=run_service, args=(AlertService, self.config)
            ),
            multiprocessing.Process(
                target=run_service, args=(StorageService, self.config)
            ),
            multiprocessing.Process(target=run_service, args=(IntelligenceService,)),
        ]

        for p in self.processes:
            p.start()

        for camera_id in list(self._streams.keys()):
            self._start_camera_runtime(camera_id)

    def stop(self):
        self._stop.set()
        for s in self._streams.values():
            s.stop()
        if hasattr(self, "processes"):
            for p in self.processes:
                p.terminate()
                p.join()
        self.message_bus.stop()
        self.db.close()

    def add_camera(self, cam: CameraConfig):
        self._cameras[cam.camera_id] = cam
        if not self._stop.is_set():
            self._start_camera_runtime(cam.camera_id)

    def remove_camera(self, camera_id: str):
        self._cameras.pop(camera_id, None)
        self._workers.pop(camera_id, None)

    def list_cameras(self) -> List[Dict]:
        return [asdict(c) for c in self._cameras.values()]

    def get_latest_jpeg(self, camera_id: str) -> Optional[bytes]:
        # In microservices, we'd get this from Redis, but for now we can just return None or fetch from a cache
        return None

    def get_recent_events(self, limit: int = 100) -> List[Dict]:
        items = list(self._events)[-limit:]
        return [asdict(e) for e in reversed(items)]

    def _start_camera_runtime(self, camera_id: str):
        if camera_id in self._workers and self._workers[camera_id].is_alive():
            return

        cam = self._cameras[camera_id]

        def run_camera():
            bus = MessageBus()
            service = CameraIngestionService(cam, bus)
            service.start()

        import multiprocessing

        p = multiprocessing.Process(target=run_camera)
        self._workers[camera_id] = p
        p.start()
