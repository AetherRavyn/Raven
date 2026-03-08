# app/tools/sensorreadtool.py
"""SensorReadTool — read live sensor/binary_sensor values from Home Assistant."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

# Domains considered "sensor-like" by default
_SENSOR_DOMAINS = frozenset(
    [
        "sensor",
        "binary_sensor",
        "weather",
        "climate",
        "air_quality",
        "humidifier",
        "sun",
    ]
)


class SensorReadTool(BaseTool):
    """Read live sensor and environment data from Home Assistant."""

    def get_name(self) -> str:
        return "read_sensor"

    def get_description(self) -> str:
        return (
            "Read live sensor values from Home Assistant: temperature, humidity, "
            "motion, door/window contact, air quality, and any other sensor entity. "
            "Can read a single sensor or list all sensors (optionally filtered by type)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="read — fetch one sensor | list — list all sensors.",
                    required=True,
                    enum=["read", "list"],
                ),
                ToolParameter(
                    name="entity_id",
                    type="string",
                    description=(
                        "HA entity ID of the sensor (e.g. 'sensor.living_room_temperature'). "
                        "Required for operation=read."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="domain_filter",
                    type="string",
                    description=(
                        "Restrict list results to a specific domain "
                        "(e.g. 'sensor', 'binary_sensor'). "
                        "If omitted, all sensor-like domains are returned."
                    ),
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        token = Config.HOME_ASSISTANT_TOKEN
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _base_url(self) -> str:
        return (Config.HOME_ASSISTANT_URL or "http://homeassistant.local:8123").rstrip(
            "/"
        )

    # ------------------------------------------------------------------ #
    #  execute                                                              #
    # ------------------------------------------------------------------ #

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not Config.HOME_ASSISTANT_URL or not Config.HOME_ASSISTANT_TOKEN:
            return {
                "success": False,
                "error": "HOME_ASSISTANT_URL or HOME_ASSISTANT_TOKEN not configured.",
            }

        operation: str = kwargs.get("operation", "read")
        entity_id: Optional[str] = kwargs.get("entity_id")
        domain_filter: Optional[str] = kwargs.get("domain_filter")

        base = self._base_url()
        headers = self._headers()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # ── read ──────────────────────────────────────────────── #
                if operation == "read":
                    if not entity_id:
                        return {
                            "success": False,
                            "error": "'entity_id' is required for read.",
                        }
                    resp = await client.get(
                        f"{base}/api/states/{entity_id}", headers=headers
                    )
                    if resp.status_code == 404:
                        return {
                            "success": False,
                            "error": f"Sensor '{entity_id}' not found.",
                        }
                    resp.raise_for_status()
                    data = resp.json()
                    attrs = data.get("attributes", {})
                    return {
                        "success": True,
                        "entity_id": entity_id,
                        "state": data.get("state"),
                        "unit": attrs.get("unit_of_measurement"),
                        "friendly_name": attrs.get("friendly_name"),
                        "attributes": attrs,
                        "last_changed": data.get("last_changed"),
                        "last_updated": data.get("last_updated"),
                    }

                # ── list ──────────────────────────────────────────────── #
                elif operation == "list":
                    resp = await client.get(f"{base}/api/states", headers=headers)
                    resp.raise_for_status()
                    all_states = resp.json()

                    allowed_domains: frozenset[str] = (
                        frozenset([domain_filter]) if domain_filter else _SENSOR_DOMAINS
                    )

                    sensors: List[Dict[str, Any]] = []
                    for s in all_states:
                        eid: str = s.get("entity_id", "")
                        dom = eid.split(".")[0]
                        if dom not in allowed_domains:
                            continue
                        attrs = s.get("attributes", {})
                        sensors.append(
                            {
                                "entity_id": eid,
                                "state": s.get("state"),
                                "unit": attrs.get("unit_of_measurement"),
                                "friendly_name": attrs.get("friendly_name"),
                                "last_updated": s.get("last_updated"),
                            }
                        )

                    return {
                        "success": True,
                        "operation": "list",
                        "count": len(sensors),
                        "sensors": sensors,
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"HA API error {exc.response.status_code}: {exc.response.text[:300]}",
            }
        except Exception as exc:
            logger.exception("SensorReadTool error")
            return {"success": False, "error": str(exc)}
