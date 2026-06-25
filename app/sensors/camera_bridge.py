# app/sensors/camera_bridge.py
"""Bridge between monitoring/ anomaly detection and RAVEN BotSignal.

The monitoring/ system runs as a separate process. This module provides
a simple HTTP webhook receiver that monitoring/ POSTs alerts to.

Endpoint: POST /internal/camera-alert
Body: {"event": "person_detected", "camera": "front_door", "confidence": 0.92, "snapshot_path": "/tmp/snap.jpg"}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def handle_camera_alert(event_data: dict) -> None:
    """Process a camera alert and notify admin users via BotSignal."""
    from app.core.event_digest import broadcast_event_digest
    from app.core.botsignal import get_botsignal
    from app.core.models import ReplyTarget, SignalPayload
    from app.settings.config import Config

    event = event_data.get("event", "unknown")
    camera = event_data.get("camera", "unknown")
    confidence = event_data.get("confidence", 0.0)
    snapshot_path = event_data.get("snapshot_path")

    text = f"\U0001f6a8 Camera Alert \u2014 {event} detected on {camera} (confidence: {confidence:.0%})"
    botsignal = get_botsignal()

    for admin_id in Config.ADMIN_USER_IDS:
        # Admin IDs are in format "platform:chat_id" e.g. "telegram:123456"
        # If plain number, assume Telegram
        if ":" in admin_id:
            platform, chat_id = admin_id.split(":", 1)
        else:
            platform, chat_id = "telegram", admin_id

        if not botsignal.has_sender(platform):
            continue

        target = ReplyTarget(platform=platform, chat_id=chat_id)
        if snapshot_path:
            payload = SignalPayload(
                text=text,
                file_path=snapshot_path,
                caption=text,
            )
        else:
            payload = SignalPayload(text=text)

        try:
            await botsignal.send(target, payload)
        except Exception as exc:
            logger.error("Camera alert notification failed for %s: %s", admin_id, exc)

    try:
        await broadcast_event_digest(event_data)
    except Exception as exc:
        logger.debug("Event digest broadcast failed: %s", exc)
