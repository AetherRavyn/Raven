"""Raven IoT Configuration — decoupled from main app Config.

Provides IoT-specific settings that don't require importing
the main app's Config class. Can be configured via environment
variables or constructor injection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class IoTConfig:
    """IoT-specific configuration."""

    # Home Assistant
    home_assistant_url: str = ""
    home_assistant_token: str = ""

    # MQTT
    mqtt_broker_url: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topics: list[str] = field(default_factory=lambda: ["#"])

    # Camera
    camera_default_fps: int = 5
    camera_default_resolution: tuple[int, int] = (640, 480)
    camera_motion_threshold: float = 0.02

    # Recording
    recording_retention_hours: int = 24

    # Alert routing
    admin_user_ids: list[str] = field(default_factory=list)

    # Workspace
    workspace_root: str = "workspace"

    @classmethod
    def from_env(cls) -> IoTConfig:
        """Load config from environment variables."""
        return cls(
            home_assistant_url=os.getenv("HOME_ASSISTANT_URL", ""),
            home_assistant_token=os.getenv("HOME_ASSISTANT_TOKEN", ""),
            mqtt_broker_url=os.getenv("MQTT_BROKER_URL", ""),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_username=os.getenv("MQTT_USERNAME", ""),
            mqtt_password=os.getenv("MQTT_PASSWORD", ""),
            mqtt_topics=os.getenv("MQTT_TOPICS", "#").split(","),
            admin_user_ids=[
                uid.strip()
                for uid in os.getenv("ADMIN_USER_IDS", "").split(",")
                if uid.strip()
            ],
            workspace_root=os.getenv("MEMORY_ROOT", "workspace"),
        )


# Singleton
_iot_config: IoTConfig | None = None


def get_iot_config() -> IoTConfig:
    global _iot_config
    if _iot_config is None:
        _iot_config = IoTConfig.from_env()
    return _iot_config
