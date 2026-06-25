"""SmartHomeTool — control Home Assistant devices via REST API.

Decoupled from main app: uses IoTConfig instead of Config.
Can be used standalone or via the adapter layer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from raven_iot.config import IoTConfig, get_iot_config

logger = logging.getLogger(__name__)


class SmartHomeTool:
    """Control smart home devices and automations via Home Assistant REST API."""

    def __init__(self, config: IoTConfig | None = None) -> None:
        self._config = config or get_iot_config()

    def get_name(self) -> str:
        return "smart_home"

    def get_description(self) -> str:
        return (
            "Control smart home devices via Home Assistant. "
            "Turn lights/switches on or off, toggle devices, call any HA service, "
            "list all entities, get state, create scenes and automations, "
            "control device groups."
        )

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._config.home_assistant_token:
            headers["Authorization"] = f"Bearer {self._config.home_assistant_token}"
        return headers

    def _base_url(self) -> str:
        return (self._config.home_assistant_url or "http://homeassistant.local:8123").rstrip("/")

    def _unavailable(self) -> Dict[str, Any]:
        return {"success": False, "error": "Home Assistant not configured."}

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not self._config.home_assistant_url or not self._config.home_assistant_token:
            return self._unavailable()

        operation = kwargs.get("operation", "")
        entity_id = kwargs.get("entity_id")
        domain = kwargs.get("domain")
        service = kwargs.get("service")
        service_data = kwargs.get("service_data") or {}
        domain_filter = kwargs.get("domain_filter")

        base = self._base_url()
        headers = self._headers()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if operation == "get_state":
                    if not entity_id:
                        return {"success": False, "error": "'entity_id' is required."}
                    resp = await client.get(f"{base}/api/states/{entity_id}", headers=headers)
                    if resp.status_code == 404:
                        return {"success": False, "error": f"Entity '{entity_id}' not found."}
                    resp.raise_for_status()
                    data = resp.json()
                    return {"success": True, "entity_id": entity_id, "state": data.get("state"),
                            "attributes": data.get("attributes", {}), "last_changed": data.get("last_changed")}

                elif operation in ("turn_on", "turn_off", "toggle"):
                    if not entity_id:
                        return {"success": False, "error": "'entity_id' is required."}
                    ent_domain = entity_id.split(".")[0]
                    resp = await client.post(f"{base}/api/services/{ent_domain}/{operation}",
                                            headers=headers, json={"entity_id": entity_id})
                    resp.raise_for_status()
                    return {"success": True, "operation": operation, "entity_id": entity_id}

                elif operation == "call_service":
                    if not domain or not service:
                        return {"success": False, "error": "'domain' and 'service' are required."}
                    if entity_id:
                        service_data["entity_id"] = entity_id
                    resp = await client.post(f"{base}/api/services/{domain}/{service}",
                                            headers=headers, json=service_data)
                    resp.raise_for_status()
                    return {"success": True, "operation": "call_service", "domain": domain, "service": service}

                elif operation == "list_entities":
                    resp = await client.get(f"{base}/api/states", headers=headers)
                    resp.raise_for_status()
                    states = resp.json()
                    if domain_filter:
                        states = [s for s in states if s.get("entity_id", "").startswith(f"{domain_filter}.")]
                    entities = [{"entity_id": s["entity_id"], "state": s.get("state"),
                                "friendly_name": s.get("attributes", {}).get("friendly_name")} for s in states]
                    return {"success": True, "operation": "list_entities", "count": len(entities), "entities": entities}

                elif operation == "group_control":
                    group_name = kwargs.get("group_name", "")
                    action = kwargs.get("action", "turn_on")
                    if not group_name:
                        return {"success": False, "error": "'group_name' is required."}
                    body = {"entity_id": f"group.{group_name}"}
                    body.update(service_data)
                    resp = await client.post(f"{base}/api/services/group/{action}", headers=headers, json=body)
                    resp.raise_for_status()
                    return {"success": True, "operation": "group_control", "group": group_name, "action": action}

                elif operation == "list_groups":
                    resp = await client.get(f"{base}/api/states", headers=headers)
                    resp.raise_for_status()
                    groups = [{"entity_id": s["entity_id"], "state": s.get("state"),
                               "friendly_name": s.get("attributes", {}).get("friendly_name"),
                               "members": s.get("attributes", {}).get("entity_id", [])}
                              for s in resp.json() if s.get("entity_id", "").startswith("group.")]
                    return {"success": True, "operation": "list_groups", "count": len(groups), "groups": groups}

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"HA API error {exc.response.status_code}: {exc.response.text[:300]}"}
        except Exception as exc:
            logger.exception("SmartHomeTool error")
            return {"success": False, "error": str(exc)}
