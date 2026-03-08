"""
Shared application state — all globals used by the route modules and processing loop.
Import from here instead of circular imports to main.py.
"""

import asyncio
import threading
from typing import Dict, Optional

from monitoring.src.db.initdb import initDB
from monitoring.src.reid import ReID
from monitoring.src.detection import YOLODetector
from monitoring.src.anomaly import AnomalyDetector
from monitoring.src.message_bus import MessageBus
from monitoring.src.vision_analytics import VisionAnalyticsEngine
from monitoring.src.semantic_search import SemanticSearchEngine

# ── Database & ML ─────────────────────────────────────────────────────────────
reid: Optional[ReID] = None
db: Optional[initDB] = None
bus: Optional[MessageBus] = None

# ── SSE & Shutdown ────────────────────────────────────────────────────────────
_sse_queue: Optional[asyncio.Queue] = None
_shutdown_event = threading.Event()

# ── Vision Engines ────────────────────────────────────────────────────────────
vision_engine: Optional[VisionAnalyticsEngine] = None
semantic_search_engine: Optional[SemanticSearchEngine] = None

# ── Object Detection + Tracking ──────────────────────────────────────────────
yolo_detector: Optional[YOLODetector] = None
anomaly_detector: Optional[AnomalyDetector] = None
_YOLO_FRAME_SKIP = 1
_FACE_FRAME_SKIP = 3
_TARGET_FPS_SLEEP = 0.08

# ── Camera Registry ──────────────────────────────────────────────────────────
# Import CameraStream class after the module is created
camera_registry: Dict = {}
_camera_lock = threading.Lock()

# ── ESP Registry ─────────────────────────────────────────────────────────────
esp_registry: Dict[str, dict] = {}
_esp_lock = threading.Lock()
