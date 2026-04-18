import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

_SARAS_WEBHOOK_URL = "http://127.0.0.1:8765/internal/camera-alert"


async def _notify_saras(event: dict) -> None:
    """POST a camera alert event to the SARAS webhook server (best-effort)."""
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            await client.post(_SARAS_WEBHOOK_URL, json=event, timeout=5)
    except Exception as exc:
        logger.debug("SARAS webhook notification failed: %s", exc)


async def _broadcast_proactive_digest(event: dict) -> None:
    try:
        from app.core.event_digest import broadcast_event_digest

        await broadcast_event_digest(event)
    except Exception as exc:
        logger.debug("Proactive digest broadcast failed: %s", exc)


@dataclass
class AnomalyEvent:
    event_id: str
    event_type: str
    track_id: Optional[int]
    camera_id: str
    zone_id: Optional[str]
    timestamp: datetime
    risk_level: str
    description: str
    metadata: Dict = field(default_factory=dict)
    processed: bool = False


class AnomalyDetector:
    def __init__(self, config: Dict, thresholds: Dict):
        self.config = config
        self.thresholds = thresholds
        self.anomaly_config = config.get("anomaly", {})

        self.track_history: Dict[int, Dict] = defaultdict(
            lambda: {
                "positions": [],
                "timestamps": [],
                "zones": [],
                "static_start": None,
                "loiter_start": None,
                "last_alert": None,
                "pose_history": [],
            }
        )

        self.events: List[AnomalyEvent] = []
        self._init_pose_model()

    def _init_pose_model(self):
        self.pose_model = None
        if self.anomaly_config.get("pose_estimation", {}).get("enabled", False):
            try:
                from ultralytics import YOLO

                pose_model_name = self.anomaly_config.get("pose_estimation", {}).get(
                    "model", "yolov8n-pose.pt"
                )
                self.pose_model = YOLO(pose_model_name)
                logger.info(f"Pose model loaded: {pose_model_name}")
            except Exception as e:
                logger.warning(f"Pose model not available: {e}")

    def analyze(
        self,
        tracks: List,
        camera_id: str,
        timestamp: datetime,
        frame: Optional[np.ndarray] = None,
    ) -> List[AnomalyEvent]:
        events = []

        for track in tracks:
            if track.class_name != "person":
                continue

            history = self.track_history[track.track_id]
            history["positions"].append(track.last_position)
            history["timestamps"].append(timestamp)

            if len(history["positions"]) > 300:
                history["positions"] = history["positions"][-300:]
                history["timestamps"] = history["timestamps"][-300:]

            if self.anomaly_config.get("loitering", {}).get("enabled", True):
                loiter_event = self._detect_loitering(
                    track, history, camera_id, timestamp
                )
                if loiter_event:
                    events.append(loiter_event)

            if self.anomaly_config.get("static_object", {}).get("enabled", True):
                static_event = self._detect_static_object(
                    track, history, camera_id, timestamp
                )
                if static_event:
                    events.append(static_event)

            if self.anomaly_config.get("abandoned_baggage", {}).get("enabled", True):
                bag_event = self._detect_abandoned_baggage(
                    track, history, camera_id, timestamp
                )
                if bag_event:
                    events.append(bag_event)

        if frame is not None and self.pose_model is not None:
            pose_events = self._analyze_poses(tracks, frame, camera_id, timestamp)
            events.extend(pose_events)

        if self.anomaly_config.get("unknown_person", {}).get("enabled", True):
            unknown_events = self._detect_unknown_person(tracks, camera_id, timestamp)
            events.extend(unknown_events)

        if self.anomaly_config.get("weapon_detection", {}).get("enabled", True):
            weapon_events = self._detect_weapon(tracks, camera_id, timestamp)
            events.extend(weapon_events)

        if self.anomaly_config.get("restricted_entry", {}).get("enabled", True):
            restricted_events = self._detect_restricted_entry(
                tracks, camera_id, timestamp
            )
            events.extend(restricted_events)

        if self.anomaly_config.get("pet_escape", {}).get("enabled", True):
            pet_events = self._detect_pet_escape(tracks, camera_id, timestamp)
            events.extend(pet_events)

        self.events.extend(events)
        return events

    def _detect_loitering(
        self, track, history: Dict, camera_id: str, timestamp: datetime
    ) -> Optional[AnomalyEvent]:
        config = self.anomaly_config.get("loitering", {})
        min_duration = timedelta(seconds=config.get("time_threshold_seconds", 60))
        max_distance = config.get("max_distance_moved_meters", 5)
        cooldown = timedelta(seconds=config.get("cooldown_seconds", 30))

        if len(history["positions"]) < 10:
            return None

        if history["loiter_start"] is None:
            positions = history["positions"][-30:]
            if len(positions) >= 2:
                max_disp = max(
                    np.sqrt(
                        (p[0] - positions[0][0]) ** 2 + (p[1] - positions[0][1]) ** 2
                    )
                    for p in positions
                )
                if max_disp < max_distance * 50:
                    history["loiter_start"] = timestamp

        if history["loiter_start"] is not None:
            duration = timestamp - history["loiter_start"]
            if duration >= min_duration:
                if (
                    history["last_alert"] is None
                    or (timestamp - history["last_alert"]) > cooldown
                ):
                    history["last_alert"] = timestamp
                    return AnomalyEvent(
                        event_id=f"loiter_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                        event_type="loitering",
                        track_id=track.track_id,
                        camera_id=camera_id,
                        zone_id=None,
                        timestamp=timestamp,
                        risk_level="medium",
                        description=f"Person {track.track_id} loitering for {duration.seconds}s",
                        metadata={
                            "track_id": track.track_id,
                            "duration_seconds": duration.seconds,
                        },
                    )

        return None

    def _detect_static_object(
        self, track, history: Dict, camera_id: str, timestamp: datetime
    ) -> Optional[AnomalyEvent]:
        config = self.anomaly_config.get("static_object", {})
        min_duration = timedelta(seconds=config.get("time_threshold_seconds", 300))
        cooldown = timedelta(seconds=config.get("cooldown_seconds", 60))

        if len(history["positions"]) < 10:
            return None

        positions = history["positions"][-60:]
        if len(positions) >= 2:
            max_disp = max(
                np.sqrt((p[0] - positions[0][0]) ** 2 + (p[1] - positions[0][1]) ** 2)
                for p in positions
            )

            if max_disp < 10:
                if history["static_start"] is None:
                    history["static_start"] = timestamp

                duration = timestamp - history["static_start"]
                if duration >= min_duration:
                    if (
                        history["last_alert"] is None
                        or (timestamp - history["last_alert"]) > cooldown
                    ):
                        history["last_alert"] = timestamp
                        return AnomalyEvent(
                            event_id=f"static_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                            event_type="static_object",
                            track_id=track.track_id,
                            camera_id=camera_id,
                            zone_id=None,
                            timestamp=timestamp,
                            risk_level="low",
                            description=f"Static object/person detected for {duration.seconds}s",
                            metadata={
                                "track_id": track.track_id,
                                "duration_seconds": duration.seconds,
                            },
                        )
            else:
                history["static_start"] = None

        return None

    def _detect_abandoned_baggage(
        self, track, history: Dict, camera_id: str, timestamp: datetime
    ) -> Optional[AnomalyEvent]:
        config = self.anomaly_config.get("abandoned_baggage", {})

        if track.class_name not in ["bag", "suitcase", "backpack"]:
            return None

        min_duration = timedelta(seconds=config.get("time_threshold_seconds", 120))

        if history.get("baggage_start") is None:
            history["baggage_start"] = timestamp

        duration = timestamp - history["baggage_start"]
        if duration >= min_duration:
            return AnomalyEvent(
                event_id=f"abandoned_{camera_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                event_type="abandoned_baggage",
                track_id=track.track_id,
                camera_id=camera_id,
                zone_id=None,
                timestamp=timestamp,
                risk_level="medium",
                description=f"Abandoned baggage detected for {duration.seconds}s",
                metadata={
                    "track_id": track.track_id,
                    "duration_seconds": duration.seconds,
                },
            )

        return None

    def _analyze_poses(
        self, tracks: List, frame: np.ndarray, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        events = []

        if self.pose_model is None:
            return events

        try:
            results = self.pose_model(frame, verbose=False)

            for result in results:
                if result.keypoints is None:
                    continue

                keypoints = result.keypoints.data.cpu().numpy()

                for kp_idx, kp in enumerate(keypoints):
                    pose_events = self._analyze_single_pose(
                        kp, tracks, camera_id, timestamp
                    )
                    events.extend(pose_events)

        except Exception as e:
            logger.error(f"Pose analysis error: {e}")

        return events

    def _analyze_single_pose(
        self, keypoints: np.ndarray, tracks: List, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        events = []

        pose_config = self.anomaly_config.get("pose_estimation", {})
        fall_threshold = self.thresholds.get("pose", {}).get("fall_angle_threshold", 45)
        fall_confidence = self.thresholds.get("pose", {}).get(
            "fall_confidence_threshold", 0.6
        )

        if len(keypoints) < 17:
            return events

        try:
            left_shoulder = keypoints[5]
            right_shoulder = keypoints[6]
            left_hip = keypoints[11]
            right_hip = keypoints[12]

            if left_shoulder[2] < 0.3 or right_shoulder[2] < 0.3:
                return events

            shoulder_y = (left_shoulder[1] + right_shoulder[1]) / 2
            hip_y = (left_hip[1] + right_hip[1]) / 2

            body_angle = abs(shoulder_y - hip_y)

            if pose_config.get("fall_detection", True) and body_angle < fall_threshold:
                events.append(
                    AnomalyEvent(
                        event_id=f"fall_{camera_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                        event_type="fall",
                        track_id=None,
                        camera_id=camera_id,
                        zone_id=None,
                        timestamp=timestamp,
                        risk_level="high",
                        description="Fall detected - person may be unconscious",
                        metadata={
                            "confidence": float(fall_confidence),
                            "angle": float(body_angle),
                        },
                    )
                )

            if pose_config.get("fight_detection", True):
                left_wrist = keypoints[9]
                right_wrist = keypoints[10]

                wrist_movement = 0
                if len(keypoints) > 20:
                    right_wrist_2 = keypoints[16]
                    wrist_movement = abs(right_wrist[0] - right_wrist_2[0])

                if wrist_movement > 50:
                    events.append(
                        AnomalyEvent(
                            event_id=f"fight_{camera_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                            event_type="fight",
                            track_id=None,
                            camera_id=camera_id,
                            zone_id=None,
                            timestamp=timestamp,
                            risk_level="high",
                            description="Potential fight detected - aggressive arm movement",
                            metadata={"wrist_movement": float(wrist_movement)},
                        )
                    )

        except Exception as e:
            logger.debug(f"Single pose analysis error: {e}")

        return events

    def _detect_unknown_person(
        self, tracks: List, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        events = []
        for track in tracks:
            # Requires tracking logic to provide identity; we check if identity starts with unknown_
            if (
                hasattr(track, "identity")
                and track.identity
                and str(track.identity).startswith("unknown_")
            ):
                # We need tracking history or state to not spam alerts
                history = self.track_history[track.track_id]
                cooldown = timedelta(
                    seconds=self.anomaly_config.get("unknown_person", {}).get(
                        "cooldown_seconds", 300
                    )
                )

                if (
                    history.get("last_unknown_alert") is None
                    or (timestamp - history["last_unknown_alert"]) > cooldown
                ):
                    history["last_unknown_alert"] = timestamp
                    events.append(
                        AnomalyEvent(
                            event_id=f"unknown_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                            event_type="unknown_person",
                            track_id=track.track_id,
                            camera_id=camera_id,
                            zone_id=None,
                            timestamp=timestamp,
                            risk_level="medium",
                            description=f"Unknown person ({track.identity}) detected",
                            metadata={
                                "track_id": track.track_id,
                                "identity": track.identity,
                            },
                        )
                    )
        return events

    def _detect_weapon(
        self, tracks: List, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        events = []
        weapon_classes = ["knife", "scissors", "baseball bat", "gun", "rifle"]
        for track in tracks:
            if track.class_name in weapon_classes:
                history = self.track_history[track.track_id]
                cooldown = timedelta(
                    seconds=self.anomaly_config.get("weapon_detection", {}).get(
                        "cooldown_seconds", 60
                    )
                )

                if (
                    history.get("last_weapon_alert") is None
                    or (timestamp - history["last_weapon_alert"]) > cooldown
                ):
                    history["last_weapon_alert"] = timestamp
                    events.append(
                        AnomalyEvent(
                            event_id=f"weapon_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                            event_type="weapon_detected",
                            track_id=track.track_id,
                            camera_id=camera_id,
                            zone_id=None,
                            timestamp=timestamp,
                            risk_level="critical",
                            description=f"Weapon ({track.class_name}) detected",
                            metadata={
                                "track_id": track.track_id,
                                "weapon_type": track.class_name,
                                "confidence": track.confidence,
                            },
                        )
                    )
        return events

    def _detect_restricted_entry(
        self, tracks: List, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        # Typically requires zone mapping. We mock behavior based on anomaly_config zones.
        events = []
        restricted_zones = self.anomaly_config.get("restricted_zones", {}).get(
            camera_id, []
        )
        if not restricted_zones:
            return events

        for track in tracks:
            if track.class_name == "person":
                # Assuming track has current zone or we calculate it (mocked here through config)
                # In real scenario we check track.last_position against polygon
                history = self.track_history[track.track_id]
                cooldown = timedelta(seconds=60)

                # Mock: logic would go here to check intersection of track.bbox and restricted_zones
                # For placeholder functionality, we assume it's provided via `track.zone_id`
                if getattr(track, "zone_id", None) in restricted_zones:
                    if (
                        history.get("last_restricted_alert") is None
                        or (timestamp - history["last_restricted_alert"]) > cooldown
                    ):
                        history["last_restricted_alert"] = timestamp
                        events.append(
                            AnomalyEvent(
                                event_id=f"restricted_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                                event_type="restricted_entry",
                                track_id=track.track_id,
                                camera_id=camera_id,
                                zone_id=track.zone_id,
                                timestamp=timestamp,
                                risk_level="high",
                                description=f"Restricted entry in zone {track.zone_id}",
                                metadata={
                                    "track_id": track.track_id,
                                    "zone": track.zone_id,
                                },
                            )
                        )
        return events

    def _detect_pet_escape(
        self, tracks: List, camera_id: str, timestamp: datetime
    ) -> List[AnomalyEvent]:
        events = []
        door_zones = self.anomaly_config.get("door_zones", {}).get(camera_id, [])
        for track in tracks:
            if track.class_name in ["dog", "cat", "bird"]:
                history = self.track_history[track.track_id]
                cooldown = timedelta(seconds=120)

                # Simplified proximity check: if pet is near door zone
                if getattr(track, "zone_id", None) in door_zones:
                    if (
                        history.get("last_pet_alert") is None
                        or (timestamp - history["last_pet_alert"]) > cooldown
                    ):
                        history["last_pet_alert"] = timestamp
                        events.append(
                            AnomalyEvent(
                                event_id=f"pet_escape_{camera_id}_{track.track_id}_{timestamp.strftime('%Y%m%d%H%M%S')}",
                                event_type="pet_escape",
                                track_id=track.track_id,
                                camera_id=camera_id,
                                zone_id=track.zone_id,
                                timestamp=timestamp,
                                risk_level="high",
                                description=f"Pet ({track.class_name}) escape attempt near door",
                                metadata={
                                    "track_id": track.track_id,
                                    "pet_type": track.class_name,
                                    "zone": track.zone_id,
                                },
                            )
                        )
        return events

    def get_events_by_risk(self, risk_level: str) -> List[AnomalyEvent]:
        return [e for e in self.events if e.risk_level == risk_level]

    def get_recent_events(self, minutes: int = 60) -> List[AnomalyEvent]:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [e for e in self.events if e.timestamp > cutoff]

    def clear_old_events(self, hours: int = 24):
        cutoff = datetime.now() - timedelta(hours=hours)
        self.events = [e for e in self.events if e.timestamp > cutoff]


class EventService:
    """Microservice wrapper for AnomalyDetector using Redis MessageBus."""

    def __init__(self, bus, config: Dict | None = None, thresholds: Dict | None = None):
        self.bus = bus
        self.anomaly_detector = AnomalyDetector(config or {}, thresholds or {})
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
            import time

            camera_id = payload.get("camera_id")
            if not camera_id:
                return

            tracked_objects = payload.get("tracked_objects", [])

            for obj in tracked_objects:
                track_id = obj["track_id"]
                identity_info = self.current_identities.get(camera_id, {}).get(
                    track_id, {}
                )
                identity = identity_info.get("identity", "unknown")
                confidence = identity_info.get("confidence", 0.0)

                # Check for anomalies
                from monitoring.src.tracker import Track

                track = Track(
                    track_id=track_id,
                    class_id=obj["class_id"],
                    class_name=obj["class_name"],
                    bbox=obj["bbox"],
                    confidence=obj["confidence"],
                )

                # Inject identity into track for unknown_person detection
                track.identity = identity
                track.zone_id = payload.get("zone_id")

                # Note: AnomalyDetector.check_anomaly expects a Track object and identity
                # We need to adapt this to the actual AnomalyDetector methods
                # The current AnomalyDetector has analyze_track, analyze_zone_intrusion, etc.
                # For simplicity, we'll just call analyze_track
                events = self.anomaly_detector.analyze(
                    [track],
                    camera_id,
                    datetime.fromtimestamp(payload.get("timestamp", time.time())),
                )

                for event in events:
                    event_payload = {
                        "event_id": event.event_id,
                        "timestamp": payload["timestamp"],
                        "camera_id": camera_id,
                        "camera_name": payload["camera_name"],
                        "location": payload["location"],
                        "track_id": track_id,
                        "identity": identity,
                        "confidence": confidence,
                        "anomaly_type": event.event_type,
                        "severity": event.risk_level,
                        "description": event.description,
                        "frame_b64": payload.get("frame_b64"),
                    }
                    self.bus.publish("events.detected", event_payload)
                    logger.info(f"Published event: {event.event_type} for {camera_id}")

                    # Notify SARAS via webhook for high/critical events
                    if event.risk_level in ("high", "critical"):
                        import asyncio

                        saras_payload = {
                            "event": event.event_type,
                            "camera": camera_id,
                            "confidence": confidence,
                        }
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(_notify_saras(saras_payload))
                            else:
                                loop.run_until_complete(_notify_saras(saras_payload))
                        except Exception as exc:
                            logger.debug("SARAS webhook dispatch error: %s", exc)

                        try:
                            from app.core.event_digest import broadcast_event_digest

                            if loop.is_running():
                                asyncio.create_task(
                                    broadcast_event_digest(
                                        {
                                            "event_type": event.event_type,
                                            "camera_id": camera_id,
                                            "risk_level": event.risk_level,
                                            "description": event.description,
                                        }
                                    )
                                )
                            else:
                                loop.run_until_complete(
                                    broadcast_event_digest(
                                        {
                                            "event_type": event.event_type,
                                            "camera_id": camera_id,
                                            "risk_level": event.risk_level,
                                            "description": event.description,
                                        }
                                    )
                                )
                        except Exception as exc:
                            logger.debug("Proactive digest dispatch error: %s", exc)
        except Exception as e:
            logger.error(f"Error processing tracked objects: {e}")

    def start(self):
        import time

        logger.info("Event Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Event Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus

    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = EventService(bus)
    service.start()
