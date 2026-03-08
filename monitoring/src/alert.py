import logging
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


class AlertManager:
    """Send alerts via webhook and Telegram."""

    def __init__(self, config: Dict):
        self.config = config or {}
        self.alerts_cfg = self.config.get("alerts", {})

    def send_alert(self, anomaly_data: Dict):
        """Dispatch alert to all configured channels."""
        webhook_url = self.alerts_cfg.get("webhook_url")
        telegram_token = self.alerts_cfg.get("telegram_token")
        telegram_chat_id = self.alerts_cfg.get("telegram_chat_id")

        if webhook_url:
            self._send_webhook(anomaly_data)

        if telegram_token and telegram_chat_id:
            self._send_telegram(anomaly_data)

    def _send_webhook(self, data: Dict):
        """POST to webhook endpoint."""
        try:
            payload = {
                "event": "anomaly_detected",
                "camera": data.get("camera_name") or data.get("camera_id"),
                "identity": data.get("identity", "Unknown"),
                "severity": data.get("severity")
                or data.get("risk_level", "LOW").upper(),
                "time": data.get("timestamp"),
                "image": data.get("image_path"),
                "anomaly_type": data.get("anomaly_type") or data.get("event_type"),
                "description": data.get("description"),
                "track_id": data.get("track_id"),
                "event_id": data.get("event_id"),
            }

            response = requests.post(
                self.alerts_cfg.get("webhook_url"), json=payload, timeout=5
            )

            if response.status_code < 300:
                logger.info("Webhook alert sent: %s", data.get("event_id"))
            else:
                logger.error("Webhook returned %s", response.status_code)
        except Exception as e:
            logger.error("Webhook send failed: %s", e)

    def _send_telegram(self, data: Dict):
        """Send message and optional image to Telegram."""
        try:
            token = self.alerts_cfg.get("telegram_token")
            chat_id = self.alerts_cfg.get("telegram_chat_id")

            severity = (data.get("severity") or data.get("risk_level", "LOW")).upper()
            event_name = (
                data.get("anomaly_type") or data.get("event_type") or "Anomaly Detected"
            )
            msg = (
                "🚨 *ALERT*\n\n"
                f"Event: {event_name}\n"
                f"Camera: {data.get('camera_name') or data.get('camera_id')}\n"
                f"Identity: {data.get('identity', 'Unknown')}\n"
                f"Severity: {severity}\n"
                f"Time: {data.get('timestamp')}"
            )

            send_message_url = f"https://api.telegram.org/bot{token}/sendMessage"
            response = requests.post(
                send_message_url,
                data={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=5,
            )

            if response.status_code != 200:
                logger.error("Telegram message failed: %s", response.status_code)
                return

            image_path = data.get("image_path")
            if image_path:
                self._send_telegram_photo(token, chat_id, image_path)

            logger.info("Telegram alert sent: %s", data.get("event_id"))
        except Exception as e:
            logger.error("Telegram send failed: %s", e)

    def _send_telegram_photo(self, token: str, chat_id: str, image_path: str):
        try:
            with open(image_path, "rb") as image_file:
                send_photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
                response = requests.post(
                    send_photo_url,
                    data={"chat_id": chat_id},
                    files={"photo": image_file},
                    timeout=8,
                )
            if response.status_code != 200:
                logger.error("Telegram photo failed: %s", response.status_code)
        except Exception as e:
            logger.warning("Telegram photo skipped: %s", e)


class AlertService:
    """Microservice wrapper for AlertManager using Redis MessageBus."""

    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.alert_manager = AlertManager(config or {})
        self.bus.subscribe("alerts.generated", self.process_events)

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

            # Send alert
            self.alert_manager.send_alert(payload)
            logger.info(f"Sent alert for event {event_id}")
        except Exception as e:
            logger.error(f"Error processing events: {e}")

    def start(self):
        import time

        logger.info("Alert Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("Alert Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus

    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = AlertService(bus)
    service.start()
