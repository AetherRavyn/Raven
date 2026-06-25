"""Environmental Sensor Context — Raven senses the physical environment.

Integrates with MQTT sensors, Home Assistant, and system sensors
to provide environmental context for smarter responses.

Sensors:
- Temperature / humidity (from MQTT or HA)
- Light level (from ambient light sensor or HA)
- Noise level (from microphone)
- Air quality (from AQI sensors)
- Presence detection (motion sensors)

This data helps Raven understand the user's physical context:
- "It's 28°C and humid" → suggest opening windows
- "It's dark outside" → offer to turn on lights
- "Noise level is high" → don't suggest voice interaction
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SensorReading:
    """A single sensor reading."""
    sensor_type: str  # temperature, humidity, light, noise, air_quality, presence
    value: float
    unit: str
    location: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class EnvironmentState:
    """Current environmental state."""
    temperature: float | None = None
    humidity: float | None = None
    light_level: float | None = None  # 0-100 (dark to bright)
    noise_level: float | None = None  # dB
    air_quality: int | None = None  # AQI
    presence: bool | None = None
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EnvironmentalSensor:
    """Collects and manages environmental sensor data."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "environment"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "environment.json"
        self._readings: list[SensorReading] = []

    def update(self, reading: SensorReading) -> None:
        """Add a sensor reading and update the environment state."""
        self._readings.append(reading)
        # Keep only last 100 readings
        if len(self._readings) > 100:
            self._readings = self._readings[-100:]
        self._update_state(reading)

    def _update_state(self, reading: SensorReading) -> None:
        """Update the persisted environment state."""
        state = self._load_state()
        if reading.sensor_type == "temperature":
            state.temperature = reading.value
        elif reading.sensor_type == "humidity":
            state.humidity = reading.value
        elif reading.sensor_type == "light":
            state.light_level = reading.value
        elif reading.sensor_type == "noise":
            state.noise_level = reading.value
        elif reading.sensor_type == "air_quality":
            state.air_quality = int(reading.value)
        elif reading.sensor_type == "presence":
            state.presence = reading.value > 0.5

        state.last_updated = datetime.now(timezone.utc).isoformat()
        self._save_state(state)

    def _load_state(self) -> EnvironmentState:
        if not self._file.exists():
            return EnvironmentState()
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return EnvironmentState(**{k: v for k, v in data.items() if k in EnvironmentState.__dataclass_fields__})
        except Exception:
            return EnvironmentState()

    def _save_state(self, state: EnvironmentState) -> None:
        from dataclasses import asdict
        self._file.write_text(
            json.dumps(asdict(state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_state(self) -> EnvironmentState:
        return self._load_state()

    def get_environment_context(self) -> str:
        """Build environment context string for prompts."""
        state = self._load_state()
        parts = []

        if state.temperature is not None:
            parts.append(f"Temperature: {state.temperature}°C")
        if state.humidity is not None:
            parts.append(f"Humidity: {state.humidity}%")
        if state.light_level is not None:
            level = "dark" if state.light_level < 20 else "dim" if state.light_level < 50 else "bright"
            parts.append(f"Light: {level} ({state.light_level}%)")
        if state.noise_level is not None:
            noise = "quiet" if state.noise_level < 30 else "moderate" if state.noise_level < 60 else "loud"
            parts.append(f"Noise: {noise} ({state.noise_level}dB)")
        if state.air_quality is not None:
            quality = "good" if state.air_quality < 50 else "moderate" if state.air_quality < 100 else "poor"
            parts.append(f"Air quality: {quality} (AQI {state.air_quality})")
        if state.presence is not None:
            parts.append(f"Presence: {'detected' if state.presence else 'none'}")

        if parts:
            return "Environment: " + " | ".join(parts)
        return ""

    def process_mqtt_reading(self, topic: str, payload: dict[str, Any]) -> SensorReading | None:
        """Process an MQTT sensor reading."""
        # Parse common MQTT sensor topics
        if "temperature" in topic.lower() or "temp" in topic.lower():
            value = float(payload.get("value", payload.get("temperature", 0)))
            reading = SensorReading(sensor_type="temperature", value=value, unit="°C", location=topic)
        elif "humidity" in topic.lower():
            value = float(payload.get("value", payload.get("humidity", 0)))
            reading = SensorReading(sensor_type="humidity", value=value, unit="%", location=topic)
        elif "light" in topic.lower() or "lux" in topic.lower():
            value = float(payload.get("value", payload.get("illuminance", 0)))
            reading = SensorReading(sensor_type="light", value=min(value / 10, 100), unit="lux", location=topic)
        elif "noise" in topic.lower() or "sound" in topic.lower():
            value = float(payload.get("value", payload.get("db", 0)))
            reading = SensorReading(sensor_type="noise", value=value, unit="dB", location=topic)
        elif "motion" in topic.lower() or "pir" in topic.lower():
            value = 1.0 if payload.get("value", payload.get("motion", False)) else 0.0
            reading = SensorReading(sensor_type="presence", value=value, unit="bool", location=topic)
        elif "aqi" in topic.lower() or "air" in topic.lower():
            value = float(payload.get("value", payload.get("aqi", 0)))
            reading = SensorReading(sensor_type="air_quality", value=value, unit="AQI", location=topic)
        else:
            return None

        self.update(reading)
        return reading
