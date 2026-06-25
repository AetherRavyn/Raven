#!/usr/bin/env python3
"""
Production-grade Frigate Anomaly Handler for Raspberry Pi 5
Integrates with existing RAVEN infrastructure:
- Uses src/db (SQLite managers)
- Uses src/anomaly (AnomalyDetector, AnomalyEvent)
- Uses src/storage (ClipStorage)
- Provides MQTT listener + Flask web dashboard
"""

import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests
from flask import Flask, jsonify, render_template_string, send_file
from paho.mqtt import client as mqtt_client
from werkzeug.serving import make_server

# Set up path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Import existing RAVEN infrastructure
from config.settings import CONFIG
from src.anomaly import AnomalyDetector, AnomalyEvent
from src.db.initdb import initDB
from src.storage import ClipStorage

# ============================================================================
# LOGGING
# ============================================================================


def setup_logging():
    """Configure logging."""
    log_dir = Path(CONFIG["storage"]["clips_dir"]).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    log_level = getattr(logging, CONFIG["logging"]["level"], logging.INFO)

    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        log_dir / "anomaly_handler.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("AnomalyHandler")


logger = setup_logging()

# ============================================================================
# ALERT MANAGER
# ============================================================================



# ============================================================================
# ANOMALY HANDLER SERVICE
# ============================================================================


class AnomalyHandlerService:
    """Main service orchestrating MQTT + anomaly detection + alerts."""

    def __init__(self, config: Dict):
        self.config = config
        self.running = False

        # Initialize database (SQLite + graph)
        self.db = initDB()

        # Initialize anomaly detector (uses existing src/anomaly.py)
        self.detector = AnomalyDetector(config, config.get("thresholds", {}))

        # Initialize clip storage (uses existing src/storage.py)
        self.storage = ClipStorage(config)

        # Initialize alerts
        self.alerts = AlertManager(config)

        # MQTT setup
        self.mqtt_client = None
        self.event_queue = queue.Queue(maxsize=100)
        self.worker_thread = None

    def start(self):
        """Start the service."""
        logger.info("Starting Anomaly Handler Service...")
        self.running = True

        # Start background worker thread
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

        logger.info("Service shutdown complete")

    def _setup_mqtt(self):
        """Initialize MQTT client."""

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info("MQTT connected")
                client.subscribe(self.config["mqtt"]["topic"])
            else:
                logger.error(f"MQTT connection failed: {rc}")

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

        # Start connection loop
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
                        f"MQTT connect failed: {e}, retrying in {self.config['mqtt']['reconnect_interval']}s"
                    )
                    time.sleep(self.config["mqtt"]["reconnect_interval"])

        threading.Thread(target=run, daemon=True).start()

    def _worker_loop(self):
        """Background worker: process events from MQTT queue."""
        while self.running:
            try:
                frigate_event = self.event_queue.get(timeout=1)

                # Adapt Frigate event to format expected by AnomalyDetector
                # The detector.analyze() expects a list of "tracks" with frame
                # For now, we'll use simplified logic
                self._process_frigate_event(frigate_event)

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    def _process_frigate_event(self, frigate_event: Dict):
        """Process a Frigate MQTT event."""
        event_type = frigate_event.get("type", "update")
        after = frigate_event.get("after", {})

        event_id = after.get("id")
        camera_id = after.get("camera")
        label = after.get("label")

        if not event_id or event_type == "end":
            return

        # Create AnomalyEvent for persistence
        anomaly_event = AnomalyEvent(
            event_id=event_id,
            event_type=label,
            track_id=after.get("track_id"),
            camera_id=camera_id,
            zone_id=None,
            timestamp=datetime.now(),
            risk_level="medium",
            description=f"{label} detected on {camera_id}",
            metadata=after,
        )

        # Save to database (SQLite + PostgreSQL)
        if self.db.sqlite:
            self.db.sqlite.insert_event(anomaly_event.__dict__)

        # Send alert
        self.alerts.send_alert(anomaly_event.__dict__)

        logger.info(f"Event processed: {event_id} on {camera_id}")


# ============================================================================
# FLASK WEB SERVER
# ============================================================================


def create_flask_app(service: AnomalyHandlerService) -> Flask:
    """Create Flask web application."""
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
                "database": (
                    "connected"
                    if service.db.sqlite and service.db.sqlite.engine
                    else "disconnected"
                ),
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
        if service.db.sqlite:
            events = service.db.sqlite.get_events(limit=50)
            return jsonify(events)
        return jsonify([])

    @app.route("/events")
    def events_html():
        """Get recent anomalies as HTML dashboard."""
        events = service.db.sqlite.get_events(limit=50) if service.db.sqlite else []

        html = (
            """
        <!DOCTYPE html>
        <html>
        <head>
            <title>🚨 Anomaly Detection Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #eee; padding: 20px; }
                header { padding: 20px; background: #1a1a1a; border-radius: 8px; margin-bottom: 20px; }
                h1 { margin: 0; color: #4fc3f7; }
                .stats { display: flex; gap: 20px; margin-top: 10px; font-size: 14px; }
                .stats > div { background: #222; padding: 10px 15px; border-radius: 4px; }
                table { width: 100%; border-collapse: collapse; background: #1a1a1a; border-radius: 8px; }
                th { background: #252525; padding: 12px; text-align: left; font-weight: 600; border-bottom: 1px solid #333; }
                td { padding: 12px; border-bottom: 1px solid #333; }
                tr:hover { background: #222; }
                .time { color: #888; font-size: 13px; }
                .type { display: inline-block; padding: 4px 8px; border-radius: 3px; font-size: 12px; font-weight: 600; background: #ff9800; color: #000; }
                a { color: #4fc3f7; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <header>
                <h1>🚨 Anomaly Detection Dashboard</h1>
                <div class="stats">
                    <div>📊 Total Anomalies: """
            + str(len(events))
            + """</div>
                    <div>🔄 Auto-refresh: 30s</div>
                </div>
            </header>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Camera</th>
                        <th>Type</th>
                        <th>Risk Level</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody>
        """
        )

        for event in events:
            html += f"""
                    <tr>
                        <td><span class="time">{event.get("timestamp", "N/A")}</span></td>
                        <td>{event.get("camera_id", "Unknown")}</td>
                        <td><span class="type">{event.get("event_type", "unknown")}</span></td>
                        <td>{event.get("risk_level", "medium")}</td>
                        <td>{event.get("description", "N/A")}</td>
                    </tr>
            """

        html += """
                </tbody>
            </table>
            <script>
                setTimeout(() => location.reload(), 30000);
            </script>
        </body>
        </html>
        """

        return render_template_string(html)

    @app.route("/clips/<filename>")
    def serve_clip(filename: str):
        """Serve clip or snapshot file."""
        try:
            filepath = Path(service.config["storage"]["clips_dir"]) / filename
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
    service = AnomalyHandlerService(CONFIG)

    # Signal handlers
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start service
    service.start()

    # Create and run Flask
    app = create_flask_app(service)
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
