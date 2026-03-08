#!/usr/bin/env python3
"""
Production-grade Frigate Anomaly Handler for Raspberry Pi 5
- Lightweight MQTT-driven anomaly detection
- Flask web server (not FastAPI for RPi efficiency)
- PostgreSQL + Neo4j persistence via existing database modules
- Webhook + Telegram alerts
- Memory footprint optimized for ARM
"""

import os
import sys
import json
import time
import logging
import threading
import queue
import signal
import cv2
import numpy as np
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from paho.mqtt import client as mqtt_client
from flask import Flask, render_template_string, send_file, jsonify
from werkzeug.serving import make_server

# Import existing monitoring infrastructure
sys.path.insert(0, os.path.dirname(__file__))
from config.settings import config
from src.db.initdb import initDB
from src.anomaly import AnomalyDetector, AnomalyEvent
from src.storage import ClipStorage
from src.alert import AlertManager  # If exists, else we'll create minimal version

# Try to import YOLO (optional for weapon detection)
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

# ============================================================================
# CONFIGURATION - Load from existing config modules
# ============================================================================


def load_config():
    """Load config from existing YAML configs + environment variables."""
    try:
        db_config = config.get("dbconfig.yaml")
        camera_config = config.get("cameras.yaml")
        threshold_config = config.get("thresholds.yaml")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not load YAML configs: {e}, using defaults")
        db_config = {}
        camera_config = {}
        threshold_config = {}
    
    return {
        "mqtt": {
            "host": os.getenv("FRIGATE_MQTT_HOST", "localhost"),
            "port": int(os.getenv("FRIGATE_MQTT_PORT", "1883")),
            "topic": "frigate/events",
            "client_id": "anomaly_handler",
            "reconnect_interval": 5,
        },
        "frigate": {
            "api_url": os.getenv("FRIGATE_API_URL", "http://localhost:5000"),
            "rtsp_url": os.getenv("FRIGATE_RTSP_URL", "rtsp://localhost:8554"),
        },
        "database": db_config,
        "cameras": camera_config,
        "storage": {
            "clips_dir": os.getenv("CLIPS_DIR", "/var/lib/saras/anomalies"),
            "retention_days": 7,
        },
        "alerts": {
            "webhook_url": os.getenv("ANOMALY_WEBHOOK_URL", ""),
            "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "alert_cooldown": 60,
        },
        "thresholds": threshold_config,
        "yolo": {
            "model_path": "yolo26n.pt",
            "enabled": YOLO_AVAILABLE,
        },
        "flask": {
            "port": int(os.getenv("FLASK_PORT", "8080")),
            "host": "0.0.0.0",
            "debug": False,
        },
        "logging": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
        },
    }


CONFIG = load_config()

# ============================================================================
# LOGGING SETUP
# ============================================================================


def setup_logging():
    """Configure logging with rotation and file output."""
    log_dir = Path(CONFIG["storage"]["clips_dir"]).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    log_level = getattr(logging, CONFIG["logging"]["level"], logging.INFO)

    # File handler with rotation
    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        log_dir / "anomaly_handler.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("AnomalyHandler")


logger = setup_logging()

# ============================================================================
# DATABASE HELPER
# ============================================================================


class DatabaseManager:
    """PostgreSQL connection manager with minimal overhead."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn = None
        self.connect()

    def connect(self):
        """Establish connection and initialize schema."""
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = True
            self._init_schema()
            logger.info("Database connected")
        except psycopg2.Error as e:
            logger.error(f"Database connection failed: {e}")
            self.conn = None

    def _init_schema(self):
        """Create tables if they don't exist."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS anomalies (
                    id SERIAL PRIMARY KEY,
                    event_id TEXT UNIQUE,
                    timestamp TIMESTAMP DEFAULT NOW(),
                    camera TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    confidence REAL,
                    track_id TEXT,
                    metadata JSONB,
                    snapshot_path TEXT,
                    clip_path TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_anomalies_timestamp ON anomalies(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_anomalies_camera ON anomalies(camera);
            """
            )
            logger.info("Database schema initialized")

    def save_anomaly(self, data: Dict) -> bool:
        """Insert anomaly record."""
        if not self.conn:
            return False

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO anomalies
                    (event_id, timestamp, camera, anomaly_type, confidence, track_id, metadata, snapshot_path, clip_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO UPDATE SET metadata = EXCLUDED.metadata
                """,
                    (
                        data.get("event_id"),
                        datetime.fromisoformat(
                            data.get("timestamp", datetime.now().isoformat())
                        ),
                        data.get("camera"),
                        data.get("anomaly_type"),
                        data.get("confidence", 0.0),
                        data.get("track_id"),
                        json.dumps(data.get("metadata", {})),
                        data.get("snapshot_path"),
                        data.get("clip_path"),
                    ),
                )
            return True
        except psycopg2.Error as e:
            logger.error(f"Database insert failed: {e}")
            return False

    def get_recent_anomalies(self, limit: int = 50) -> List[Dict]:
        """Fetch last N anomalies."""
        if not self.conn:
            return []

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, event_id, timestamp, camera, anomaly_type, confidence, track_id, snapshot_path, clip_path
                    FROM anomalies
                    ORDER BY timestamp DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Database query failed: {e}")
            return []

    def close(self):
        """Close connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")


# ============================================================================
# ANOMALY DETECTION ENGINE
# ============================================================================


class AnomalyDetector:
    """Lightweight anomaly detection rules engine."""

    def __init__(self, config: Dict):
        self.config = config
        self.active_tracks = (
            {}
        )  # {track_id: {"first_seen": ts, "last_seen": ts, "camera": "", "bbox": []}}
        self.last_alert_time = {}  # {event_key: ts} for cooldown
        self.yolo_model = None

        if config["yolo"]["enabled"] and YOLO_AVAILABLE:
            try:
                self.yolo_model = YOLO(config["yolo"]["model_path"])
                logger.info(f"YOLO model loaded: {config['yolo']['model_path']}")
            except Exception as e:
                logger.warning(f"YOLO model load failed: {e}")

    def process_event(self, frigate_event: Dict) -> Optional[Dict]:
        """
        Analyze Frigate MQTT event and return anomaly if detected.
        Returns: Dict with anomaly details or None
        """
        event_type = frigate_event.get("type", "update")
        after = frigate_event.get("after", {})

        event_id = after.get("id")
        camera = after.get("camera")
        label = after.get("label")
        track_id = after.get("track_id")
        bbox = after.get("box", [])

        if not event_id or event_type == "end":
            # Clean up track
            if event_id in self.active_tracks:
                del self.active_tracks[event_id]
            return None

        now = time.time()

        # Update tracking state
        if event_id not in self.active_tracks:
            self.active_tracks[event_id] = {
                "first_seen": now,
                "last_seen": now,
                "camera": camera,
                "label": label,
                "track_id": track_id,
                "bbox": bbox,
            }
        else:
            self.active_tracks[event_id]["last_seen"] = now
            self.active_tracks[event_id]["bbox"] = bbox

        track = self.active_tracks[event_id]
        duration = now - track["first_seen"]

        # Anomaly Detection Rules
        anomaly_type = None
        confidence = 0.0

        # Rule 1: Loitering (person in zone > LOITER_THRESHOLD)
        if label == "person" and duration > self.config["thresholds"]["loiter_seconds"]:
            anomaly_key = f"{event_id}_loiter"
            last_alert = self.last_alert_time.get(anomaly_key, 0)
            if now - last_alert > self.config["alerts"]["alert_cooldown"]:
                anomaly_type = "loitering"
                confidence = min(duration / 60.0, 1.0)  # Max confidence at 60s
                self.last_alert_time[anomaly_key] = now

        # Rule 2: Static object (bag, suitcase, etc. for > STATIC_OBJECT_THRESHOLD)
        elif (
            label in ["backpack", "handbag", "suitcase", "bag"]
            and duration > self.config["thresholds"]["static_object_seconds"]
        ):
            anomaly_key = f"{event_id}_static"
            last_alert = self.last_alert_time.get(anomaly_key, 0)
            if now - last_alert > self.config["alerts"]["alert_cooldown"]:
                anomaly_type = "static_object"
                confidence = 0.85
                self.last_alert_time[anomaly_key] = now

        # Rule 3: Potential weapon (via YOLO secondary check if available)
        elif label in ["person"] and self.yolo_model:
            # Could check for high confidence + specific pose/behavior
            # Placeholder for secondary weapon detection
            pass

        if anomaly_type:
            return {
                "event_id": event_id,
                "timestamp": datetime.now().isoformat(),
                "camera": camera,
                "anomaly_type": anomaly_type,
                "confidence": confidence,
                "track_id": track_id,
                "bbox": bbox,
                "label": label,
                "duration": duration,
                "metadata": {
                    "label": label,
                    "track_id": track_id,
                    "duration_seconds": int(duration),
                },
            }

        return None


# ============================================================================
# MEDIA PROCESSING (Snapshots, Clips, Zoom/Crop)
# ============================================================================


class MediaProcessor:
    """Handle snapshot fetching, zooming, cropping, and clip retrieval."""

    def __init__(self, config: Dict):
        self.config = config
        self.clips_dir = Path(config["storage"]["clips_dir"])
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def fetch_and_process_snapshot(
        self, event_id: str, camera: str, bbox: List
    ) -> Optional[str]:
        """
        Fetch snapshot from Frigate, apply digital zoom/crop, save to disk.
        Returns path to saved zoomed snapshot.
        """
        try:
            snap_url = f"{self.config['frigate']['api_url']}/api/events/{event_id}/snapshot.jpg"
            resp = requests.get(snap_url, timeout=10)

            if resp.status_code != 200:
                logger.warning(
                    f"Snapshot fetch failed for {event_id}: {resp.status_code}"
                )
                return None

            # Decode image
            img_array = np.frombuffer(resp.content, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if img is None:
                logger.warning(f"Failed to decode image for {event_id}")
                return None

            # Apply digital zoom + crop on subject
            zoomed = self._apply_zoom_crop(img, bbox)

            # Save cropped image
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{camera}_{timestamp_str}_snap.jpg"
            filepath = self.clips_dir / filename

            cv2.imwrite(str(filepath), zoomed, [cv2.IMWRITE_JPEG_QUALITY, 85])
            logger.info(f"Snapshot saved: {filepath}")

            return str(filepath)

        except Exception as e:
            logger.error(f"Snapshot processing failed: {e}")
            return None

    def _apply_zoom_crop(self, img: np.ndarray, bbox: List) -> np.ndarray:
        """
        Apply digital zoom centered on bbox.
        bbox format: [x1, y1, x2, y2] or [x, y, w, h]
        """
        h, w = img.shape[:2]

        # Assume [x, y, w, h] normalized (Frigate format)
        try:
            if len(bbox) == 4:
                x, y, bw, bh = bbox
                # Convert to absolute if normalized
                if x < 1.0 and y < 1.0 and bw < 1.0 and bh < 1.0:
                    x1, y1, x2, y2 = (
                        int(x * w),
                        int(y * h),
                        int((x + bw) * w),
                        int((y + bh) * h),
                    )
                else:
                    x1, y1, x2, y2 = int(x), int(y), int(x + bw), int(y + bh)
            else:
                # Fallback: use full image
                return img

            # Center crop with zoom factor
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            crop_size = max(x2 - x1, y2 - y1)
            zoom = self.config["thresholds"]["zoom_factor"]
            crop_w, crop_h = int(crop_size * zoom), int(crop_size * zoom)

            nx1 = max(0, cx - crop_w // 2)
            ny1 = max(0, cy - crop_h // 2)
            nx2 = min(w, nx1 + crop_w)
            ny2 = min(h, ny1 + crop_h)

            return img[ny1:ny2, nx1:nx2]

        except Exception as e:
            logger.warning(f"Zoom/crop failed: {e}, returning original")
            return img

    def fetch_clip(self, event_id: str, camera: str) -> Optional[str]:
        """
        Download clip from Frigate API (async in background).
        Returns path to saved clip.
        """
        try:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{camera}_{timestamp_str}_clip.mp4"
            filepath = self.clips_dir / filename

            clip_url = (
                f"{self.config['frigate']['api_url']}/api/events/{event_id}/clip.mp4"
            )

            # Download with timeout
            resp = requests.get(clip_url, stream=True, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Clip fetch failed: {resp.status_code}")
                return None

            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Clip saved: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"Clip fetch failed: {e}")
            return None


# ============================================================================
# ALERTING ENGINE
# ============================================================================


class AlertManager:
    """Send alerts via webhook and Telegram."""

    def __init__(self, config: Dict):
        self.config = config

    def send_alert(self, anomaly_data: Dict):
        """Dispatch alert to all configured channels."""
        # Webhook alert
        if self.config["alerts"]["webhook_url"]:
            self._send_webhook(anomaly_data)

        # Telegram alert
        if (
            self.config["alerts"]["telegram_token"]
            and self.config["alerts"]["telegram_chat_id"]
        ):
            self._send_telegram(anomaly_data)

    def _send_webhook(self, data: Dict):
        """POST to webhook endpoint."""
        try:
            payload = {
                "event_id": data.get("event_id"),
                "timestamp": data.get("timestamp"),
                "camera": data.get("camera"),
                "anomaly_type": data.get("anomaly_type"),
                "confidence": data.get("confidence"),
                "message": f"{data.get('anomaly_type').replace('_', ' ').title()} detected on {data.get('camera')}",
            }

            response = requests.post(
                self.config["alerts"]["webhook_url"], json=payload, timeout=5
            )

            if response.status_code < 300:
                logger.info(f"Webhook alert sent: {data.get('event_id')}")
            else:
                logger.error(f"Webhook returned {response.status_code}")

        except Exception as e:
            logger.error(f"Webhook send failed: {e}")

    def _send_telegram(self, data: Dict):
        """Send message to Telegram."""
        try:
            token = self.config["alerts"]["telegram_token"]
            chat_id = self.config["alerts"]["telegram_chat_id"]

            msg = f"""
🚨 *ANOMALY DETECTED*
Type: `{data.get('anomaly_type').replace('_', ' ').title()}`
Camera: `{data.get('camera')}`
Time: `{data.get('timestamp')}`
Confidence: `{data.get('confidence'):.2%}`
Track ID: `{data.get('track_id', 'N/A')}`
            """.strip()

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=5,
            )

            if response.status_code == 200:
                logger.info(f"Telegram alert sent: {data.get('event_id')}")
            else:
                logger.error(f"Telegram returned {response.status_code}")

        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


# ============================================================================
# MAIN ANOMALY HANDLER ORCHESTRATOR
# ============================================================================


class AnomalyHandlerService:
    """Main service that ties everything together."""

    def __init__(self, config: Dict):
        self.config = config
        self.db = DatabaseManager(config["database"]["url"])
        self.detector = AnomalyDetector(config)
        self.media = MediaProcessor(config)
        self.alerts = AlertManager(config)

        self.mqtt_client = None
        self.event_queue = queue.Queue(maxsize=100)
        self.running = False
        self.worker_thread = None

    def start(self):
        """Start the service."""
        logger.info("Starting Anomaly Handler Service...")
        self.running = True

        # Start background worker thread for media processing
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=False)
        self.worker_thread.start()

        # Connect to MQTT
        self._setup_mqtt()
        logger.info("Service started successfully")

    def stop(self):
        """Gracefully shutdown."""
        logger.info("Shutting down Anomaly Handler Service...")
        self.running = False

        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()

        if self.worker_thread:
            self.worker_thread.join(timeout=5)

        self.db.close()
        logger.info("Service shutdown complete")

    def _setup_mqtt(self):
        """Initialize and connect MQTT client."""

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info("MQTT connected")
                client.subscribe(self.config["mqtt"]["topic"])
            else:
                logger.error(f"MQTT connection failed with code {rc}")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                self.event_queue.put(payload, block=False)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in MQTT message")
            except queue.Full:
                logger.warning("Event queue full, dropping message")
            except Exception as e:
                logger.error(f"MQTT message error: {e}")

        def on_disconnect(client, userdata, rc):
            if rc != 0:
                logger.warning(f"Unexpected disconnect: {rc}")

        self.mqtt_client = mqtt_client.Client(self.config["mqtt"]["client_id"])
        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_message = on_message
        self.mqtt_client.on_disconnect = on_disconnect

        # Start connection loop in background
        self._mqtt_connect_loop()

    def _mqtt_connect_loop(self):
        """Reconnection loop for MQTT."""

        def run():
            while self.running:
                try:
                    self.mqtt_client.connect(
                        self.config["mqtt"]["host"],
                        self.config["mqtt"]["port"],
                        keepalive=60,
                    )
                    self.mqtt_client.loop_start()
                    return
                except Exception as e:
                    logger.error(
                        f"MQTT connect failed: {e}, retry in {self.config['mqtt']['reconnect_interval']}s"
                    )
                    time.sleep(self.config["mqtt"]["reconnect_interval"])

        threading.Thread(target=run, daemon=True).start()

    def _worker_loop(self):
        """Background worker: process events from queue."""
        while self.running:
            try:
                # Get event with timeout
                frigate_event = self.event_queue.get(timeout=1)

                # Analyze event
                anomaly = self.detector.process_event(frigate_event)

                if anomaly:
                    logger.info(
                        f"Anomaly detected: {anomaly.get('anomaly_type')} on {anomaly.get('camera')}"
                    )

                    # Fetch snapshot (sync)
                    snap_path = self.media.fetch_and_process_snapshot(
                        anomaly.get("event_id"),
                        anomaly.get("camera"),
                        anomaly.get("bbox"),
                    )
                    anomaly["snapshot_path"] = snap_path

                    # Fetch clip (async in thread)
                    def fetch_clip_async():
                        clip_path = self.media.fetch_clip(
                            anomaly.get("event_id"), anomaly.get("camera")
                        )
                        anomaly["clip_path"] = clip_path

                        # Save to DB
                        self.db.save_anomaly(anomaly)

                    clip_thread = threading.Thread(target=fetch_clip_async, daemon=True)
                    clip_thread.start()

                    # Send alerts immediately
                    self.alerts.send_alert(anomaly)

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")


# ============================================================================
# FLASK WEB SERVER
# ============================================================================


def create_flask_app(service: AnomalyHandlerService) -> Flask:
    """Create Flask application."""
    app = Flask(__name__)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.route("/")
    def index():
        """Home page."""
        return jsonify(
            {
                "status": "ok",
                "service": "Frigate Anomaly Handler",
                "endpoints": [
                    "/events - Recent anomalies (HTML)",
                    "/api/events - Recent anomalies (JSON)",
                    "/clips/<filename> - Download clip/snapshot",
                    "/live/<camera> - MJPEG stream",
                    "/health - Health check",
                ],
            }
        )

    @app.route("/health")
    def health():
        """Health check."""
        return jsonify(
            {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "database": "connected" if service.db.conn else "disconnected",
                "mqtt": (
                    "connected"
                    if service.mqtt_client and service.mqtt_client.is_connected()
                    else "disconnected"
                ),
            }
        )

    @app.route("/api/events")
    def api_events():
        """Get recent anomalies as JSON."""
        anomalies = service.db.get_recent_anomalies(limit=50)
        return jsonify(anomalies)

    @app.route("/events")
    def events_html():
        """Get recent anomalies as HTML page."""
        anomalies = service.db.get_recent_anomalies(limit=50)

        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Anomaly Detection Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #eee; padding: 20px; }
                header { padding: 20px; background: #1a1a1a; border-radius: 8px; margin-bottom: 20px; }
                h1 { margin: 0; color: #4fc3f7; }
                .stats { display: flex; gap: 20px; margin-top: 10px; font-size: 14px; }
                .stats > div { background: #222; padding: 10px 15px; border-radius: 4px; }
                table { width: 100%; border-collapse: collapse; background: #1a1a1a; border-radius: 8px; overflow: hidden; }
                th { background: #252525; padding: 12px; text-align: left; font-weight: 600; border-bottom: 1px solid #333; }
                td { padding: 12px; border-bottom: 1px solid #333; }
                tr:last-child td { border-bottom: none; }
                tr:hover { background: #222; }
                .time { color: #888; font-size: 14px; }
                .type { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
                .loitering { background: #ff9800; color: #000; }
                .static_object { background: #2196f3; color: #fff; }
                .potential_weapon { background: #f44336; color: #fff; }
                img { height: 60px; border-radius: 4px; cursor: pointer; }
                .conf { font-weight: 600; }
                a { color: #4fc3f7; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <header>
                <h1>🚨 Anomaly Detection Dashboard</h1>
                <div class="stats">
                    <div>Last 50 anomalies</div>
                    <div>Auto-refresh: 30s</div>
                </div>
            </header>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Camera</th>
                        <th>Type</th>
                        <th>Confidence</th>
                        <th>Snapshot</th>
                        <th>Clip</th>
                    </tr>
                </thead>
                <tbody>
        """

        for a in anomalies:
            timestamp = a.get("timestamp", "N/A")
            camera = a.get("camera", "Unknown")
            atype = a.get("anomaly_type", "unknown")
            conf = a.get("confidence", 0)
            snap = a.get("snapshot_path")
            clip = a.get("clip_path")

            snap_filename = snap.split("/")[-1] if snap else None
            clip_filename = clip.split("/")[-1] if clip else None

            html_template += f"""
                    <tr>
                        <td><span class="time">{timestamp}</span></td>
                        <td>{camera}</td>
                        <td><span class="type {atype}">{atype.replace("_", " ").title()}</span></td>
                        <td><span class="conf">{conf*100:.0f}%</span></td>
                        <td>
            """
            if snap_filename:
                html_template += f'<a href="/clips/{snap_filename}" target="_blank"><img src="/clips/{snap_filename}" alt="snap"></a>'
            else:
                html_template += "—"

            html_template += """
                        </td>
                        <td>
            """
            if clip_filename:
                html_template += f'<a href="/clips/{clip_filename}">📹 Watch</a>'
            else:
                html_template += "—"

            html_template += """
                        </td>
                    </tr>
            """

        html_template += """
                </tbody>
            </table>
            <script>
                setTimeout(() => location.reload(), 30000);
            </script>
        </body>
        </html>
        """

        return render_template_string(html_template)

    @app.route("/clips/<filename>")
    def serve_clip(filename: str):
        """Serve clip or snapshot file."""
        try:
            filepath = service.config["storage"]["clips_dir"] / filename
            if filepath.exists():
                return send_file(str(filepath))
        except Exception as e:
            logger.error(f"File serve error: {e}")

        return jsonify({"error": "File not found"}), 404

    @app.route("/live/<camera>")
    def live_stream(camera: str):
        """Proxy MJPEG stream from Frigate."""
        try:
            url = f"{service.config['frigate']['api_url']}/api/cameras/{camera}/mjpeg"

            def generate():
                resp = requests.get(url, stream=True, timeout=30)
                for chunk in resp.iter_content(chunk_size=1024):
                    yield chunk

            return (
                generate(),
                200,
                {"Content-Type": "multipart/x-mixed-replace; boundary=frame"},
            )

        except Exception as e:
            logger.error(f"Live stream error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": str(e)}), 500

    return app


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main():
    """Main entry point."""
    # Global service instance
    service = AnomalyHandlerService(CONFIG)

    # Signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start service
    service.start()

    # Create Flask app
    app = create_flask_app(service)

    # Run Flask in main thread
    logger.info(
        f"Starting Flask server on {service.config['flask']['host']}:{service.config['flask']['port']}"
    )

    try:
        server = make_server(
            service.config["flask"]["host"],
            service.config["flask"]["port"],
            app,
            threaded=True,
        )
        server.serve_forever()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, shutting down...")
        service.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        service.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
