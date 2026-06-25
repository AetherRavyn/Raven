"""Raven IoT Module — standalone IoT and environmental intelligence.

Separated from the main app for clean architecture:
- raven_iot.tools/ — smart home, camera, sensor tools
- raven_iot.sensors/ — MQTT, webhook, camera bridge
- raven_iot.core/ — environmental sensors, video streaming
- raven_iot.config/ — IoT-specific configuration

The main app imports from raven_iot via the adapter layer in app/iot_bridge.py.
"""

__version__ = "1.0.0"
