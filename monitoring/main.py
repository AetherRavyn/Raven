"""
SARAS Central Node — Main Application
Clean entry point: lifespan, camera processing, and router includes.
All API routes live in monitoring/routes/.
"""

import asyncio
import io
import logging
import os
import signal
import sys
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont

import mediapipe as mp

# ── Python path ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Internal imports ──────────────────────────────────────────────────────────
from monitoring.src import state
from monitoring.src.db.initdb import initDB
from monitoring.src.reid import ReID
from monitoring.src.detection import YOLODetector, Detection
from monitoring.src.tracker import ByteTrackTracker, Track
from monitoring.src.anomaly import AnomalyDetector, AnomalyEvent, EventService
from monitoring.config.settings import config, threshold_config, camera_config
from monitoring.src.message_bus import MessageBus
from monitoring.src.risk_analysis import RiskAnalysisService
from monitoring.src.storage import StorageService
from monitoring.src.alert import AlertService
from monitoring.src.scheduler import EdgeAIScheduler
from monitoring.src.p2p import P2PNetworkNode
from monitoring.src.llm import init_llm_uplink
from monitoring.src.vision_analytics import VisionAnalyticsEngine, VisionService
from monitoring.src.semantic_search import SemanticSearchService, SemanticSearchEngine

# ── Route modules ─────────────────────────────────────────────────────────────
from monitoring.routes import cameras as cam_routes
from monitoring.routes import esps as esp_routes
from monitoring.routes import events as event_routes
from monitoring.routes import identities as identity_routes
from monitoring.routes import analytics as analytics_routes

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ── Config paths ──────────────────────────────────────────────────────────────
SRC_DIR = Path(__file__).parent / "src"
KNOWN_DIR = SRC_DIR / "known"
MODEL_PATH = Path(__file__).parent / "models" / "w600k_r50.onnx"


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-CAMERA REGISTRY
# ══════════════════════════════════════════════════════════════════════════════
class CameraStream:
    def __init__(self, cam_id: str, url: str, location: str = "unknown"):
        self.cam_id = cam_id
        self.url = url
        self.location = location
        self.lock = threading.Lock()
        self.raw_frame: Optional[bytes] = None
        self.annotated_frame: Optional[bytes] = None
        self.active = True
        self.reader_thread: Optional[threading.Thread] = None
        self.processor_thread: Optional[threading.Thread] = None

    def to_dict(self):
        return {"id": self.cam_id, "url": self.url, "location": self.location, "active": self.active}


# ══════════════════════════════════════════════════════════════════════════════
# STREAM READER — RTSP (PyAV + NVDEC GPU) or MJPEG HTTP fallback
# ══════════════════════════════════════════════════════════════════════════════

def _is_rtsp(url: str) -> bool:
    return url.lower().startswith("rtsp://")


def _iter_rtsp_frames(url: str):
    """Read frames from an RTSP stream using PyAV. Tries NVDEC GPU decode first."""
    import av
    while not state._shutdown_event.is_set():
        container = None
        try:
            options = {
                "rtsp_transport": "tcp",
                "stimeout": "5000000",
                "max_delay": "500000",
                "fflags": "nobuffer",
                "flags": "low_delay",
            }
            container = av.open(url, options=options, timeout=10.0)
            stream = container.streams.video[0]
            try:
                stream.codec_context.options = {"hwaccel": "cuda"}
                logger.info("RTSP using GPU decode (NVDEC) for %s", url)
            except Exception:
                logger.info("RTSP GPU decode unavailable, using CPU for %s", url)
            stream.thread_type = "AUTO"

            for frame in container.decode(video=0):
                if state._shutdown_event.is_set():
                    break
                rgb = frame.to_ndarray(format="rgb24")
                pil_img = Image.fromarray(rgb)
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=80)
                yield buf.getvalue()
        except Exception as e:
            if state._shutdown_event.is_set():
                break
            logger.warning("RTSP reconnecting %s: %s", url, e)
            time.sleep(3)
        finally:
            if container:
                try:
                    container.close()
                except Exception:
                    pass


def _iter_mjpeg_frames(url: str, timeout: int = 10):
    """Read frames from an MJPEG HTTP stream."""
    while not state._shutdown_event.is_set():
        try:
            req = urllib.request.urlopen(url, timeout=timeout)
            boundary = None
            content_type = req.headers.get("Content-Type", "")
            if "boundary=" in content_type:
                boundary = content_type.split("boundary=")[1].encode()
                if boundary.startswith(b"--"):
                    boundary = boundary[2:]

            buf = b""
            while not state._shutdown_event.is_set():
                chunk = req.read(8192)
                if not chunk:
                    break
                buf += chunk
                if boundary and boundary in buf:
                    parts = buf.split(boundary)
                    for part in parts[:-1]:
                        start = part.find(b"\xff\xd8")
                        end = part.rfind(b"\xff\xd9")
                        if start != -1 and end != -1 and end > start:
                            yield part[start : end + 2]
                    buf = parts[-1]
                elif not boundary:
                    start = buf.find(b"\xff\xd8")
                    end = buf.rfind(b"\xff\xd9")
                    if start != -1 and end != -1 and end > start:
                        yield buf[start : end + 2]
                        buf = buf[end + 2 :]
        except Exception as e:
            if state._shutdown_event.is_set():
                break
            time.sleep(3)


def _camera_reader_loop(cam: CameraStream):
    """Auto-detect RTSP vs MJPEG and use the right reader."""
    logger.info("Reader started for camera %s -> %s", cam.cam_id, cam.url)
    frame_iter = _iter_rtsp_frames(cam.url) if _is_rtsp(cam.url) else _iter_mjpeg_frames(cam.url)
    for jpg_bytes in frame_iter:
        if state._shutdown_event.is_set() or not cam.active:
            break
        with cam.lock:
            cam.raw_frame = jpg_bytes


# ══════════════════════════════════════════════════════════════════════════════
# CAMERA PROCESSING LOOP
# ══════════════════════════════════════════════════════════════════════════════

_ABSENCE_THRESHOLD_SEC = 30

_CLASS_COLORS = {
    "person": "#3b82f6",
    "car": "#22c55e",
    "truck": "#f97316",
    "bus": "#eab308",
    "motorcycle": "#8b5cf6",
    "bicycle": "#06b6d4",
    "dog": "#ec4899",
    "cat": "#ec4899",
    "backpack": "#f59e0b",
    "suitcase": "#f59e0b",
    "handbag": "#f59e0b",
}
_DEFAULT_OBJ_COLOR = "#6b7280"


def _camera_processing_loop(cam: CameraStream):
    """Per-camera processing: detection, tracking, ReID, anomaly, annotation."""
    logger.info("Processor started for camera %s", cam.cam_id)

    det_config = camera_config.get("detection", {})
    track_config = camera_config.get("tracking", {})

    cam_tracker = ByteTrackTracker(track_config)
    last_detections: List[Detection] = []
    frame_counter = 0
    presence: Dict[str, dict] = {}

    # MediaPipe face detector
    BaseOptions = mp.tasks.BaseOptions
    FaceDetector = mp.tasks.vision.FaceDetector
    FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(Path(__file__).parent / "models" / "blaze_face_short_range.tflite")),
        running_mode=VisionRunningMode.IMAGE,
        min_detection_confidence=0.5,
    )

    with FaceDetector.create_from_options(options) as face_detector:
        while not state._shutdown_event.is_set() and cam.active:
            with cam.lock:
                raw = cam.raw_frame
            if not raw:
                time.sleep(0.05)
                continue
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                w, h = img.size
                img_arr = np.asarray(img)
                draw = ImageDraw.Draw(img)
                frame_counter += 1
                now_mono = time.monotonic()
                now_ts = datetime.utcnow()
                events = []

                # ── YOLO Object Detection (every frame to feed Kalman Filter correctly) ──
                if state.yolo_detector and frame_counter % state._YOLO_FRAME_SKIP == 0:
                    try:
                        current_detections = state.yolo_detector.detect(img_arr)
                    except Exception as e:
                        logger.error("YOLO detect error cam %s: %s", cam.cam_id, e)
                        current_detections = []

                    # ── ByteTrack Update ──────────────────────────────────
                    try:
                        all_tracks = cam_tracker.update(current_detections, img_arr, time.time())
                        active_tracks = cam_tracker.get_active_tracks()
                    except Exception as e:
                        logger.error("Tracker error cam %s: %s", cam.cam_id, e)

                # ── Draw Object Bounding Boxes + Track IDs ────────────
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
                except Exception:
                    font = ImageFont.load_default()

                for track in active_tracks:
                    if track.state != "tracked" or track.hits < 3: # Hide 1-frame hallucinations
                        continue
                    x1, y1, x2, y2 = [int(v) for v in track.bbox]
                    color = _CLASS_COLORS.get(track.class_name, _DEFAULT_OBJ_COLOR)
                    
                    # Bold thick bounding box
                    draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
                    
                    label_text = f"{track.class_name} (ID: {track.track_id})"
                    
                    # Text background for maximum visibility
                    left, top, right, bottom = draw.textbbox((x1 + 2, y1 - 32), label_text, font=font)
                    draw.rectangle([left - 2, top - 2, right + 2, bottom + 2], fill=color)
                    draw.text((x1 + 2, y1 - 32), label_text, fill=(255, 255, 255), font=font)

                    if len(track.trajectory) > 1:
                        pts = track.trajectory[-20:]
                        for i in range(1, len(pts)):
                            px, py = int(pts[i-1][0]), int(pts[i-1][1])
                            cx, cy = int(pts[i][0]), int(pts[i][1])
                            draw.line([(px, py), (cx, cy)], fill=color, width=1)

                # ── Anomaly Detection ─────────────────────────────────
                if state.anomaly_detector and active_tracks:
                    try:
                        anomaly_events = state.anomaly_detector.analyze(
                            active_tracks, cam.cam_id, now_ts, img_arr
                        )
                        for aev in anomaly_events:
                            events.append({
                                "ts": aev.timestamp.isoformat(),
                                "label": f"\u26a0 {aev.event_type}",
                                "score": 0,
                                "known": False,
                                "camera": cam.cam_id,
                                "type": "anomaly",
                                "risk": aev.risk_level,
                                "description": aev.description,
                            })
                            if state.bus:
                                try:
                                    state.bus.publish("events", {
                                        "event_id": aev.event_id,
                                        "event_type": aev.event_type,
                                        "camera_id": cam.cam_id,
                                        "risk_level": aev.risk_level,
                                        "description": aev.description,
                                        "timestamp": aev.timestamp.isoformat(),
                                    })
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.error("Anomaly analysis error cam %s: %s", cam.cam_id, e)

                # ── Face Detection + ReID (every Nth frame) ───────────
                face_results = None
                if frame_counter % state._FACE_FRAME_SKIP == 0:
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_arr)
                    face_results = face_detector.detect(mp_image)

                if face_results and face_results.detections:
                    for detection in face_results.detections:
                        bbox = detection.bounding_box
                        xmin, ymin = bbox.origin_x, bbox.origin_y
                        bw, bh = bbox.width, bbox.height
                        pad = int(0.15 * max(bw, bh))
                        cx1, cy1 = max(0, xmin - pad), max(0, ymin - pad)
                        cx2, cy2 = min(w, xmin + bw + pad), min(h, ymin + bh + pad)
                        crop_arr = np.asarray(img.crop((cx1, cy1, cx2, cy2)))
                        try:
                            label, score = state.reid.match(crop_arr, camera_id=cam.cam_id)
                        except Exception:
                            label, score = "error", 1.0
                        is_known = not label.startswith("unknown_")
                        fcolor = "#00dc00" if is_known else "#ff8c00"
                        draw.rectangle([cx1, cy1, cx2, cy2], outline=fcolor, width=3)
                        draw.text((cx1 + 4, cy1 - 14), f"{label} {score:.2f}", fill=fcolor)

                        pkey = f"{cam.cam_id}:{label}"
                        if pkey in presence:
                            presence[pkey]["last_seen"] = now_mono
                        else:
                            presence[pkey] = {"last_seen": now_mono}
                            events.append({"ts": now_ts.isoformat(), "label": label, "score": round(float(score), 4), "known": is_known, "camera": cam.cam_id, "type": "identity"})

                # Expire stale presence
                expired = [k for k, v in presence.items() if now_mono - v["last_seen"] > _ABSENCE_THRESHOLD_SEC]
                for k in expired:
                    del presence[k]

                # ── Timestamp overlay ─────────────────────────────────
                now_str = now_ts.strftime("%Y-%m-%d %H:%M:%S UTC")
                obj_count = len(active_tracks)
                draw.text((8, h - 20), f"{cam.cam_id} | {now_str} | {obj_count} objects", fill="#cccccc")

                # ── Vision Analytics overlay ──────────────────────────
                if state.vision_engine and state.vision_engine.active_tool:
                    from monitoring.src.gpu import gpu_rgb_to_bgr, gpu_bgr_to_rgb
                    bgr = gpu_rgb_to_bgr(np.asarray(img))
                    bgr = state.vision_engine.process_frame(bgr, active_tracks)
                    img = Image.fromarray(gpu_bgr_to_rgb(bgr))

                # ── Encode + store ────────────────────────────────────
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                with cam.lock:
                    cam.annotated_frame = buf.getvalue()

                # ── Push SSE events ───────────────────────────────────
                if events and state._sse_queue:
                    for ev in events:
                        try:
                            state._sse_queue.put_nowait(ev)
                        except asyncio.QueueFull:
                            pass
            except Exception as e:
                logger.error("Processing error cam %s: %s", cam.cam_id, e)
                time.sleep(0.5)
            time.sleep(state._TARGET_FPS_SLEEP)


# ══════════════════════════════════════════════════════════════════════════════
# CAMERA START / STOP
# ══════════════════════════════════════════════════════════════════════════════

def _start_camera(cam_id: str, url: str, location: str = "unknown"):
    cam = CameraStream(cam_id, url, location)
    cam.reader_thread = threading.Thread(target=_camera_reader_loop, args=(cam,), daemon=True)
    cam.processor_thread = threading.Thread(target=_camera_processing_loop, args=(cam,), daemon=True)
    cam.reader_thread.start()
    cam.processor_thread.start()
    with state._camera_lock:
        state.camera_registry[cam_id] = cam
    logger.info("Camera %s started: %s (%s)", cam_id, url, location)


def _stop_camera(cam_id: str):
    with state._camera_lock:
        cam = state.camera_registry.pop(cam_id, None)
    if cam:
        cam.active = False
        logger.info("Camera %s stopped", cam_id)


# ══════════════════════════════════════════════════════════════════════════════
# LIFESPAN
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Database ──────────────────────────────────────────────────────────
    state.db = initDB()
    logger.info("Database initialized")

    # ── ReID ──────────────────────────────────────────────────────────────
    state.reid = ReID(db=state.db, model_path=str(MODEL_PATH), known_dir=str(KNOWN_DIR))
    logger.info("ReID ready (%d known identities)", len(state.reid.known_db))

    # ── SSE Queue ─────────────────────────────────────────────────────────
    state._sse_queue = asyncio.Queue(maxsize=200)

    # ── YOLO Detector ─────────────────────────────────────────────────────
    det_config = camera_config.get("detection", {})
    state.yolo_detector = YOLODetector(det_config)
    logger.info("YOLO Detector ready (device=%s)", det_config.get("device", "cpu"))

    # ── Anomaly Detector ──────────────────────────────────────────────────
    anomaly_config = camera_config.get("anomaly", {})
    state.anomaly_detector = AnomalyDetector(config={"anomaly": anomaly_config}, thresholds=threshold_config)
    logger.info("Anomaly Detector ready")

    # ── Load saved cameras from cameras.yaml ──────────────────────────────
    saved_cams = camera_config.get("cameras", [])
    if saved_cams:
        for cam_cfg in saved_cams:
            cid = cam_cfg.get("id", "")
            curl = cam_cfg.get("url", cam_cfg.get("stream_url", ""))
            cloc = cam_cfg.get("location", "unknown")
            if cid and curl:
                try:
                    _start_camera(cid, curl, cloc)
                    logger.info("Loaded saved camera: %s -> %s", cid, curl)
                except Exception as e:
                    logger.warning("Failed to start saved camera %s: %s", cid, e)
        logger.info("Loaded %d cameras from cameras.yaml", len(saved_cams))
    else:
        logger.info("No saved cameras - add cameras from the Dashboard.")

    # ── Microservices ─────────────────────────────────────────────────────
    state.bus = MessageBus()
    master_config = {"anomaly": threshold_config, "storage": {"output_dir": "clips"}, "alerts": {}}

    event_service = EventService(state.bus, master_config, threshold_config)
    storage_service = StorageService(state.bus, master_config)
    alert_service = AlertService(state.bus, master_config)
    risk_service = RiskAnalysisService(state.bus)
    scheduler = EdgeAIScheduler(state.bus)
    p2p_node = P2PNetworkNode("master_node_01", state.bus)

    scheduler.start()
    p2p_node.start()

    state.vision_engine = VisionAnalyticsEngine(
        config={"vision_analytics": {"model": det_config.get("model_path", "yolov8n.pt")}}
    )
    vision_svc = VisionService(state.bus, state.vision_engine)

    semantic_svc = SemanticSearchService(state.bus)
    state.semantic_search_engine = semantic_svc.engine

    init_llm_uplink(state.bus)
    logger.info("All microservices initialized.")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    state._shutdown_event.set()
    with state._camera_lock:
        for cam in state.camera_registry.values():
            cam.active = False
    scheduler.stop()
    p2p_node.stop()
    state.db.close()
    logger.info("SARAS shutdown complete.")


# ══════════════════════════════════════════════════════════════════════════════
# APP CREATION & ROUTER INCLUDES
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="SARAS Central Node", version="2.0", lifespan=lifespan)

# Signal handlers
def _force_exit(signum, frame):
    logger.info("Force quitting application...")
    state._shutdown_event.set()
    with state._camera_lock:
        for c in state.camera_registry.values():
            c.active = False
    if state.db:
        state.db.close()
    os._exit(0)

signal.signal(signal.SIGINT, _force_exit)
signal.signal(signal.SIGTERM, _force_exit)

# Static files & templates
_base_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_base_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_base_dir / "templates"))

# Dashboard page (only route in main)
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

# Include all route modules
app.include_router(cam_routes.router)
app.include_router(esp_routes.router)
app.include_router(event_routes.router)
app.include_router(identity_routes.router)
app.include_router(analytics_routes.router)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "monitoring.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        timeout_graceful_shutdown=1,
    )
