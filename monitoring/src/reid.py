import onnxruntime as ort
from PIL import Image
import numpy as np
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from monitoring.src.db import initDB

logger = logging.getLogger(__name__)


class ReID:
    def __init__(
        self,
        db: initDB,
        model_path: Optional[str] = None,
        known_dir: Optional[str] = None,
        threshold: float = 1.2,  # Loosened ArcFace threshold to fix Swadhin orthogonal distance
        known_guard_threshold: float = 1.3,
    ):
        base = os.path.dirname(__file__)
        # Use the ArcFace model
        self.MODEL_PATH = model_path or os.path.abspath(
            os.path.join(base, "..", "models", "w600k_r50.onnx")
        )
        self.KNOWN_DIR = known_dir or os.path.join(base, "known")
        self.THRESHOLD = threshold
        self.KNOWN_GUARD_THRESHOLD = known_guard_threshold
        self.db = db

        self.known_db: Dict[str, np.ndarray] = {}
        self.unknown_db: Dict[str, dict] = {}
        self.session: Optional[ort.InferenceSession] = None
        self.input_name: Optional[str] = None

        os.makedirs(self.KNOWN_DIR, exist_ok=True)

        if os.path.exists(self.MODEL_PATH):
            self.session = ort.InferenceSession(
                self.MODEL_PATH, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            logger.info("ONNX session ready with model: %s", self.MODEL_PATH)
        else:
            logger.warning(
                "ReID running WITHOUT model – face matching disabled until "
                "model is placed at %s",
                self.MODEL_PATH,
            )

        self._load_persons_from_graph()
        self._backfill_known_from_disk()

    # ------------------------------------------------------------------
    # STARTUP: load all Person nodes from graph into memory
    # ------------------------------------------------------------------

    def _load_persons_from_graph(self):
        """Populate known_db + unknown_db from existing graph Person nodes."""
        if self.db.neo4j.driver is None:
            logger.warning("Graph storage unavailable – starting with empty caches")
            return
        try:
            import sqlite3 as _sqlite3
            db_path = self.db.neo4j._db_path
            conn = _sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT person_id, features, metadata FROM persons"
            ).fetchall()
            conn.close()
            for pid, features_json, meta_json in rows:
                features = json.loads(features_json) if features_json else []
                meta = json.loads(meta_json) if meta_json else {}
                if not features:
                    continue
                emb = np.array(features, dtype=np.float32)

                # Skip embeddings that don't match the current model's output size
                if self.session and emb.shape[0] != self.session.get_outputs()[0].shape[1]:
                    logger.warning(f"Skipping {pid} due to embedding size mismatch")
                    continue

                if meta.get("is_known"):
                    self.known_db[meta.get("label", pid)] = emb
                else:
                    self.unknown_db[pid] = {
                        "embedding": emb,
                        "first_seen": meta.get("first_seen", ""),
                        "last_seen": meta.get("last_seen", ""),
                        "visit_count": meta.get("visit_count", 1),
                        "label": meta.get("label", pid),
                    }
            logger.info(
                "Graph: loaded %d known + %d unknown persons",
                len(self.known_db),
                len(self.unknown_db),
            )
        except Exception as e:
            logger.error("Failed to load persons from graph: %s", e)

    def _backfill_known_from_disk(self):
        """Load/refresh face images from KNOWN_DIR into known_db and graph."""
        if self.session is None or not os.path.exists(self.KNOWN_DIR):
            return

        import mediapipe as mp
        BaseOptions = mp.tasks.BaseOptions
        FaceDetector = mp.tasks.vision.FaceDetector
        FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "blaze_face_short_range.tflite"))
        detector = None
        if os.path.exists(model_path):
            try:
                options = FaceDetectorOptions(
                    base_options=BaseOptions(model_asset_path=model_path),
                    running_mode=VisionRunningMode.IMAGE,
                    min_detection_confidence=0.5,
                )
                detector = FaceDetector.create_from_options(options)
            except Exception as e:
                logger.warning("Could not init face detector for backfill: %s", e)

        for fname in os.listdir(self.KNOWN_DIR):
            if not fname.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            try:
                name = os.path.splitext(fname)[0]
                existed = name in self.known_db
                img = Image.open(os.path.join(self.KNOWN_DIR, fname)).convert("RGB")

                if detector:
                    img_arr = np.asarray(img)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_arr)
                    results = detector.detect(mp_image)
                    if results.detections:
                        bbox = max(
                            results.detections,
                            key=lambda d: d.bounding_box.width * d.bounding_box.height,
                        ).bounding_box
                        w, h = img.size
                        # Match live pipeline crop padding for embedding consistency
                        pad = int(0.15 * max(bbox.width, bbox.height))
                        cx1 = max(0, bbox.origin_x - pad)
                        cy1 = max(0, bbox.origin_y - pad)
                        cx2 = min(w, bbox.origin_x + bbox.width + pad)
                        cy2 = min(h, bbox.origin_y + bbox.height + pad)
                        img = img.crop((cx1, cy1, cx2, cy2))
                    else:
                        logger.warning("No face detected in known image %s; using full image", fname)

                emb = self.embedding(img)
                if emb is None:
                    continue
                self.known_db[name] = emb
                now = datetime.now().isoformat()
                self._graph_upsert(
                    name,
                    emb,
                    {
                        "is_known": True,
                        "label": name,
                        "first_seen": now,
                        "last_seen": now,
                    },
                )
                if existed:
                    logger.info("Refreshed known identity from disk: %s", name)
                else:
                    logger.info("Back-filled known identity from disk: %s", name)
            except Exception as e:
                logger.warning("Could not load %s: %s", fname, e)

        logger.info("Known identities available after disk sync: %d", len(self.known_db))

    # ------------------------------------------------------------------
    # NEO4J HELPERS
    # ------------------------------------------------------------------

    def _graph_upsert(self, person_id: str, emb: np.ndarray, extra_meta: dict):
        """Upsert a Person node in the graph with fresh embedding + metadata."""
        now = datetime.now().isoformat()
        meta = {"last_seen": now, **extra_meta}
        if "first_seen" not in meta:
            meta["first_seen"] = now
        self.db.neo4j.add_person(
            person_id=person_id,
            features=emb.tolist(),
            metadata=meta,
        )

    def _graph_increment_visit(self, uid: str, emb: np.ndarray):
        """Update last_seen + visit_count for a returning unknown visitor."""
        now = datetime.now().isoformat()
        meta = self.unknown_db[uid]
        meta["last_seen"] = now
        meta["visit_count"] += 1
        self._graph_upsert(
            uid,
            emb,
            {
                "is_known": False,
                "label": meta["label"],
                "first_seen": meta["first_seen"],
                "last_seen": meta["last_seen"],
                "visit_count": meta["visit_count"],
            },
        )

    def _sqlite_log_sighting(self, person_id: str, camera_id: str, score: float):
        """Write a person_seen event to the SQLite events table."""
        try:
            self.db.sqlite.insert_event(
                {
                    "event_id": f"reid_{person_id}_{datetime.now().strftime('%Y%m%dT%H%M%S%f')}",
                    "event_type": "person_seen",
                    "camera_id": camera_id,
                    "timestamp": datetime.now(),
                    "risk_level": "low",
                    "description": f"{person_id} matched (dist={score:.4f})",
                    "metadata": {
                        "person_id": person_id,
                        "cosine_distance": round(score, 4),
                    },
                }
            )
        except Exception as e:
            logger.warning("Failed to log sighting event: %s", e)

    # ------------------------------------------------------------------
    # EMBEDDING  (MobileNetV2 via ONNX, 224x224 input)
    # ------------------------------------------------------------------

    def preprocess(self, img: Image.Image) -> np.ndarray:
        """Normalize a PIL image to the ArcFace input format (112x112)."""
        img = img.resize((112, 112))
        arr = np.asarray(img).astype(np.float32)
        # Convert RGB to BGR (ArcFace expects BGR)
        if arr.shape[-1] == 3:
            arr = arr[:, :, ::-1]
        # ArcFace normalization: (x - 127.5) / 127.5
        arr = (arr - 127.5) / 127.5
        arr = np.transpose(arr, (2, 0, 1))
        return np.expand_dims(arr, axis=0)

    def embedding(self, img: Image.Image) -> Optional[np.ndarray]:
        """Return an L2-normalized face embedding vector, or None if model not loaded."""
        if self.session is None:
            return None
        emb = self.session.run(None, {self.input_name: self.preprocess(img)})[0]
        # Flatten in case output is (1, 1000) or similar
        emb = emb.flatten()
        return emb / (np.linalg.norm(emb) + 1e-8)

    # ------------------------------------------------------------------
    # DISTANCE
    # ------------------------------------------------------------------

    def cosine_distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine distance ∈ [0, 2].  0 = identical."""
        return float(1.0 - np.dot(a, b))

    # ------------------------------------------------------------------
    # INTERNAL: find best match in any label->embedding dict
    # ------------------------------------------------------------------

    def _best_match(
        self, source: Dict[str, np.ndarray], emb: np.ndarray
    ) -> Tuple[Optional[str], float]:
        if not source:
            return None, float("inf")

        labels = list(source.keys())
        embeddings = np.array([source[l] for l in labels], dtype=np.float32)

        # GPU-batched cosine similarity — all identities in one shot
        from monitoring.src.gpu import gpu_cosine_similarity
        sims = gpu_cosine_similarity(emb, embeddings)  # (N,) similarities
        distances = 1.0 - sims  # cosine distance ∈ [0, 2]

        best_idx = int(np.argmin(distances))
        return labels[best_idx], float(distances[best_idx])

    # ------------------------------------------------------------------
    # MATCHING
    # ------------------------------------------------------------------

    def match(
        self, imagearry: np.ndarray, camera_id: str = "unknown_cam"
    ) -> Tuple[str, float]:
        """
        Identify a face image array.

        Priority:
          1. Named identity (known_db)      -> returns (name, distance)
          2. Returning unknown visitor      -> updates visit metadata, returns (unknown_XXXX, distance)
          3. Brand-new visitor              -> registers in graph + SQLite, returns (unknown_XXXX, distance)

        SEEN_IN relationship is updated in graph.
        """
        img = Image.fromarray(imagearry).convert("RGB")
        emb = self.embedding(img)
        if emb is None:
            return "no_model", 1.0
        now = datetime.utcnow().isoformat()

        # --- 1. Named identities ---
        best_name, best_score = self._best_match(self.known_db, emb)
        logger.debug(
            "Match diagnostics: known_count=%d best_known=%s best_known_score=%.4f threshold=%.4f",
            len(self.known_db),
            best_name,
            float(best_score),
            float(self.THRESHOLD),
        )
        if best_name:
            logger.debug("Best known match: %s, score: %f", best_name, best_score)
        if best_name and best_score <= self.THRESHOLD:
            self.db.neo4j.add_camera(camera_id)
            self.db.neo4j.add_relationship(best_name, camera_id, datetime.now())
            self._sqlite_log_sighting(best_name, camera_id, best_score)
            return best_name, best_score

        # Guard rail: if this face is still relatively close to a known identity,
        # do not create a brand-new unknown visitor record.
        if best_name and best_score <= self.KNOWN_GUARD_THRESHOLD:
            logger.debug(
                "Known-guard hit: best_known=%s score=%.4f guard=%.4f; suppressing unknown registration",
                best_name,
                float(best_score),
                float(self.KNOWN_GUARD_THRESHOLD),
            )
            self.db.neo4j.add_camera(camera_id)
            self.db.neo4j.add_relationship(best_name, camera_id, datetime.now())
            self._sqlite_log_sighting(best_name, camera_id, best_score)
            return best_name, best_score

        # --- 2. Returning unknown visitors ---
        uid_embs = {uid: m["embedding"] for uid, m in self.unknown_db.items()}
        best_uid, best_uscore = self._best_match(uid_embs, emb)
        if best_uid:
            logger.debug("Best unknown match: %s, score: %f", best_uid, best_uscore)
        if best_uid and best_uscore <= self.THRESHOLD:
            self._graph_increment_visit(best_uid, emb)
            self.db.neo4j.add_camera(camera_id)
            self.db.neo4j.add_relationship(best_uid, camera_id, datetime.now())
            self._sqlite_log_sighting(best_uid, camera_id, best_uscore)
            return self.unknown_db[best_uid]["label"], best_uscore

        # --- 3. New visitor ---
        uid = f"unknown_{len(self.unknown_db) + 1:04d}"
        self.unknown_db[uid] = {
            "embedding": emb,
            "first_seen": now,
            "last_seen": now,
            "visit_count": 1,
            "label": uid,
        }
        self._graph_upsert(
            uid,
            emb,
            {
                "is_known": False,
                "label": uid,
                "first_seen": now,
                "last_seen": now,
                "visit_count": 1,
            },
        )
        self.db.neo4j.add_camera(camera_id)
        self.db.neo4j.add_relationship(uid, camera_id, datetime.now())
        self._sqlite_log_sighting(uid, camera_id, best_uscore if best_uid else 1.0)
        logger.info("New visitor registered: %s", uid)
        return uid, best_uscore if best_uid else 1.0

    # ------------------------------------------------------------------
    # ADD / PROMOTE
    # ------------------------------------------------------------------

    def add_identity(self, imagearry: np.ndarray, name: str) -> str:
        """Register a face as a named known identity (disk image + graph)."""
        img = Image.fromarray(imagearry).convert("RGB")
        emb = self.embedding(img)
        self.known_db[name] = emb
        img.save(os.path.join(self.KNOWN_DIR, f"{name}.jpg"))
        now = datetime.now().isoformat()
        self._graph_upsert(
            name,
            emb,
            {
                "is_known": True,
                "label": name,
                "first_seen": now,
                "last_seen": now,
            },
        )
        logger.info("Added known identity: %s", name)
        return f"Added {name}"

    def promote_unknown(self, uid: str, name: str) -> str:
        """
        Give a real name to an auto-assigned unknown visitor.

        Updates in-memory caches and graph.  If you have a fresh face
        image available, call add_identity() instead (it also saves to disk).
        """
        if uid not in self.unknown_db:
            return f"{uid} not found in visitor DB"
        meta = self.unknown_db.pop(uid)
        emb = meta["embedding"]
        self.known_db[name] = emb
        self._graph_upsert(
            name,
            emb,
            {
                "is_known": True,
                "label": name,
                "first_seen": meta["first_seen"],
                "last_seen": meta["last_seen"],
                "visit_count": meta["visit_count"],
            },
        )
        logger.info("Promoted %s -> %s", uid, name)
        return f"Promoted {uid} to {name}"

    # ------------------------------------------------------------------
    # DEBUG
    # ------------------------------------------------------------------

    def debug_match(self, imagearry: np.ndarray) -> Dict[str, float]:
        """Return cosine distances to all known + unknown identities."""
        img = Image.fromarray(imagearry).convert("RGB")
        emb = self.embedding(img)
        scores: Dict[str, float] = {}
        for name, kemb in self.known_db.items():
            scores[name] = self.cosine_distance(emb, kemb)
        for uid, meta in self.unknown_db.items():
            scores[uid] = self.cosine_distance(emb, meta["embedding"])
        return {
            "scores": scores,
            "best_known": self._best_match(self.known_db, emb),
            "best_unknown": (
                self._best_match(self.unknown_db, emb) if self.unknown_db else None
            ),
        }

class ReIDService:
    """Microservice wrapper for ReID using MessageBus."""
    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.reid = ReID(config or {})
        self.bus.subscribe("tracked_objects", self.process_tracked_objects)

    def process_tracked_objects(self, payload):
        try:
            camera_id = payload.get("camera_id")
            if not camera_id:
                return

            tracked_objects = payload.get("tracked_objects", [])
            frame_b64 = payload.get("frame_b64")

            if not frame_b64 or not tracked_objects:
                return

            import base64
            import numpy as np
            from PIL import Image
            import io

            frame_bytes = base64.b64decode(frame_b64)
            image = Image.open(io.BytesIO(frame_bytes))
            frame = np.array(image)

            identities = []
            for obj in tracked_objects:
                if obj["class_name"] == "person":
                    bbox = obj["bbox"]
                    x1, y1, x2, y2 = map(int, bbox)
                    # Ensure bbox is within frame bounds
                    h, w = frame.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    if x2 > x1 and y2 > y1:
                        crop = frame[y1:y2, x1:x2]
                        identity, confidence = self.reid.identify(crop)
                        identities.append({
                            "track_id": obj["track_id"],
                            "identity": identity,
                            "confidence": confidence
                        })

            if identities:
                identity_payload = {
                    "camera_id": camera_id,
                    "camera_name": payload["camera_name"],
                    "location": payload["location"],
                    "timestamp": payload["timestamp"],
                    "identities": identities
                }
                self.bus.publish("identities", identity_payload)
                logger.info(f"Published {len(identities)} identities for {camera_id}")
        except Exception as e:
            logger.error(f"Error processing tracked objects: {e}")

    def start(self):
        import time
        logger.info("ReID Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("ReID Service stopped")

if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus
    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = ReIDService(bus)
    service.start()
