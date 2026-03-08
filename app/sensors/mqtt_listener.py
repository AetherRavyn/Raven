# app/sensors/mqtt_listener.py
"""Async MQTT subscriber that feeds sensor readings into SARAS.

Connects to the configured MQTT broker, subscribes to all configured topics,
stores the latest payload per topic in an in-memory dict, and fires BotSignal
alerts for anomalous conditions (motion, temperature extremes).

Usage:
    asyncio.create_task(
        run_mqtt_listener(broker_url="mqtt://localhost:1883", topics=["saras/#"])
    )

State access:
    from app.sensors.mqtt_listener import get_sensor_state
    state = get_sensor_state()  # {"saras/living_room/temp": {"temperature": 22.5}, ...}
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# In-memory state: latest value per topic
_sensor_state: dict[str, dict] = {}


def get_sensor_state() -> dict[str, dict]:
    """Return the in-memory snapshot of all known sensor topics."""
    return _sensor_state


async def run_mqtt_listener(
    broker_url: str,
    topics: list[str],
    username: str = "",
    password: str = "",
) -> None:
    """Run MQTT subscriber until cancelled. Stores readings in _sensor_state.

    Reconnects automatically on connection drops (10-second backoff).
    """
    import aiomqtt  # lazy — only imported when MQTT is actually enabled

    parsed = urlparse(broker_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 1883

    while True:
        try:
            client_kwargs: dict = dict(
                hostname=host,
                port=port,
            )
            if username:
                client_kwargs["username"] = username
            if password:
                client_kwargs["password"] = password

            async with aiomqtt.Client(**client_kwargs) as client:
                for topic in topics:
                    await client.subscribe(topic.strip())
                logger.info(
                    "MQTT connected to %s:%d, subscribed to: %s", host, port, topics
                )

                async for message in client.messages:
                    topic_str = str(message.topic)
                    raw = message.payload
                    try:
                        payload: dict = json.loads(
                            raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                        )
                        if not isinstance(payload, dict):
                            payload = {"value": payload}
                    except Exception:
                        payload = {
                            "raw": raw.decode(errors="replace")
                            if isinstance(raw, (bytes, bytearray))
                            else str(raw)
                        }

                    _sensor_state[topic_str] = payload
                    logger.debug("MQTT %s = %s", topic_str, payload)

                    # Fire alerts for anomalous readings
                    await _check_alerts(topic_str, payload)

        except asyncio.CancelledError:
            logger.info("MQTT listener cancelled.")
            break
        except Exception as exc:
            logger.error("MQTT connection error: %s — retrying in 10s", exc)
            await asyncio.sleep(10)


async def _check_alerts(topic: str, payload: dict) -> None:
    """Fire BotSignal alerts for anomalous sensor readings.

    Currently monitors:
    - Motion events (payload key "motion" == True)
    - Temperature extremes (>35°C or <5°C)
    """
    from app.core.botsignal import get_botsignal
    from app.core.models import ReplyTarget
    from app.settings.config import Config

    alerts: list[str] = []

    # Motion detection
    if "motion" in topic and payload.get("motion") is True:
        alerts.append(f"Motion detected: {topic}")

    # Temperature threshold
    temp = payload.get("temperature")
    if temp is not None:
        try:
            t = float(temp)
            if t > 35:
                alerts.append(f"High temperature on {topic}: {t}°C")
            elif t < 5:
                alerts.append(f"Low temperature on {topic}: {t}°C")
        except (TypeError, ValueError):
            pass

    if not alerts or not Config.ADMIN_USER_IDS:
        return

    botsignal = get_botsignal()
    for msg in alerts:
        for admin_id in Config.ADMIN_USER_IDS:
            platform = "telegram"
            chat_id = admin_id
            if ":" in admin_id:
                platform, chat_id = admin_id.split(":", 1)
            target = ReplyTarget(platform=platform, chat_id=chat_id)
            try:
                await botsignal.send_text(target, msg, source_kind="sensor")
            except Exception as exc:
                logger.error("MQTT alert send failed for %s: %s", admin_id, exc)
