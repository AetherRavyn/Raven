# app/tools/smarthometool.py
"""SmartHomeTool — control Home Assistant devices via REST API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class SmartHomeTool(BaseTool):
    """Control smart home devices and automations via Home Assistant REST API."""

    def get_name(self) -> str:
        return "smart_home"

    def get_description(self) -> str:
        return (
            "Control smart home devices via Home Assistant. "
            "Turn lights/switches on or off, toggle devices, call any HA service, "
            "list all entities, and get the current state of any entity."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Action to perform.",
                    required=True,
                    enum=[
                        "get_state",
                        "turn_on",
                        "turn_off",
                        "toggle",
                        "call_service",
                        "list_entities",
                        "create_scene",
                        "activate_scene",
                        "create_automation",
                        "group_control",
                        "list_groups",
                    ],
                ),
                ToolParameter(
                    name="entity_id",
                    type="string",
                    description=(
                        "Home Assistant entity ID (e.g. 'light.living_room', "
                        "'switch.fan'). Required for get_state, turn_on, turn_off, toggle."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="domain",
                    type="string",
                    description=(
                        "HA domain for call_service (e.g. 'light', 'switch', "
                        "'media_player', 'script'). Required for call_service."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="service",
                    type="string",
                    description=(
                        "HA service name within the domain for call_service "
                        "(e.g. 'turn_on', 'set_brightness'). Required for call_service."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="service_data",
                    type="object",
                    description=(
                        "Optional dict of extra service data for call_service "
                        "(e.g. {'brightness': 128, 'color_temp': 300})."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="domain_filter",
                    type="string",
                    description=(
                        "Filter list_entities by domain prefix "
                        "(e.g. 'light', 'switch', 'sensor'). "
                        "If omitted all entities are returned."
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

    def _unavailable(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "HOME_ASSISTANT_URL or HOME_ASSISTANT_TOKEN not configured.",
        }

    # ------------------------------------------------------------------ #
    #  execute                                                              #
    # ------------------------------------------------------------------ #

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not Config.HOME_ASSISTANT_URL or not Config.HOME_ASSISTANT_TOKEN:
            return self._unavailable()

        operation: str = kwargs.get("operation", "")
        entity_id: Optional[str] = kwargs.get("entity_id")
        domain: Optional[str] = kwargs.get("domain")
        service: Optional[str] = kwargs.get("service")
        service_data: Dict[str, Any] = kwargs.get("service_data") or {}
        domain_filter: Optional[str] = kwargs.get("domain_filter")

        base = self._base_url()
        headers = self._headers()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # ── get_state ──────────────────────────────────────────── #
                if operation == "get_state":
                    if not entity_id:
                        return {"success": False, "error": "'entity_id' is required."}
                    resp = await client.get(
                        f"{base}/api/states/{entity_id}", headers=headers
                    )
                    if resp.status_code == 404:
                        return {
                            "success": False,
                            "error": f"Entity '{entity_id}' not found.",
                        }
                    resp.raise_for_status()
                    data = resp.json()
                    return {
                        "success": True,
                        "entity_id": entity_id,
                        "state": data.get("state"),
                        "attributes": data.get("attributes", {}),
                        "last_changed": data.get("last_changed"),
                    }

                # ── turn_on / turn_off / toggle ────────────────────────── #
                elif operation in ("turn_on", "turn_off", "toggle"):
                    if not entity_id:
                        return {"success": False, "error": "'entity_id' is required."}
                    ent_domain = entity_id.split(".")[0]
                    body: Dict[str, Any] = {"entity_id": entity_id}
                    resp = await client.post(
                        f"{base}/api/services/{ent_domain}/{operation}",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": operation,
                        "entity_id": entity_id,
                        "result": resp.json() if resp.content else [],
                    }

                # ── call_service ───────────────────────────────────────── #
                elif operation == "call_service":
                    if not domain or not service:
                        return {
                            "success": False,
                            "error": "'domain' and 'service' are required for call_service.",
                        }
                    if entity_id:
                        service_data["entity_id"] = entity_id
                    resp = await client.post(
                        f"{base}/api/services/{domain}/{service}",
                        headers=headers,
                        json=service_data,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": "call_service",
                        "domain": domain,
                        "service": service,
                        "result": resp.json() if resp.content else [],
                    }

                # ── list_entities ──────────────────────────────────────── #
                elif operation == "list_entities":
                    resp = await client.get(f"{base}/api/states", headers=headers)
                    resp.raise_for_status()
                    states = resp.json()
                    if domain_filter:
                        states = [
                            s
                            for s in states
                            if s.get("entity_id", "").startswith(f"{domain_filter}.")
                        ]
                    entities = [
                        {
                            "entity_id": s["entity_id"],
                            "state": s.get("state"),
                            "friendly_name": s.get("attributes", {}).get(
                                "friendly_name"
                            ),
                        }
                        for s in states
                    ]
                    return {
                        "success": True,
                        "operation": "list_entities",
                        "count": len(entities),
                        "entities": entities,
                    }

                # ── create_scene ──────────────────────────────────────── #
                elif operation == "create_scene":
                    scene_name = kwargs.get("scene_name", "")
                    entity_states = kwargs.get("entity_states", {})
                    if not scene_name or not entity_states:
                        return {
                            "success": False,
                            "error": "'scene_name' and 'entity_states' are required for create_scene.",
                        }
                    # Create scene via HA API
                    body = {
                        "name": scene_name,
                        "entities": {
                            eid: {"state": state}
                            for eid, state in entity_states.items()
                        },
                    }
                    resp = await client.post(
                        f"{base}/api/states/scene.{scene_name}",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": "create_scene",
                        "scene_name": scene_name,
                        "entities": list(entity_states.keys()),
                    }

                # ── activate_scene ────────────────────────────────────── #
                elif operation == "activate_scene":
                    scene_name = kwargs.get("scene_name", "")
                    if not scene_name:
                        return {"success": False, "error": "'scene_name' is required."}
                    resp = await client.post(
                        f"{base}/api/services/scene/turn_on",
                        headers=headers,
                        json={"entity_id": f"scene.{scene_name}"},
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": "activate_scene",
                        "scene_name": scene_name,
                    }

                # ── create_automation ─────────────────────────────────── #
                elif operation == "create_automation":
                    trigger = kwargs.get("trigger", {})
                    actions = kwargs.get("actions", [])
                    alias = kwargs.get("alias", "Raven Automation")
                    if not trigger or not actions:
                        return {
                            "success": False,
                            "error": "'trigger' and 'actions' are required for create_automation.",
                        }
                    # Create automation via HA REST API
                    body = {
                        "alias": alias,
                        "trigger": trigger,
                        "action": actions,
                        "mode": "single",
                    }
                    resp = await client.post(
                        f"{base}/api/config/automation/config/{alias}",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": "create_automation",
                        "alias": alias,
                        "trigger": trigger,
                        "actions_count": len(actions),
                    }

                # ── group_control ─────────────────────────────────────── #
                elif operation == "group_control":
                    group_name = kwargs.get("group_name", "")
                    action = kwargs.get("action", "turn_on")
                    service_data = kwargs.get("service_data", {})
                    if not group_name:
                        return {"success": False, "error": "'group_name' is required."}
                    # Control all entities in a group via HA group service
                    body = {"entity_id": f"group.{group_name}"}
                    body.update(service_data)
                    resp = await client.post(
                        f"{base}/api/services/group/{action}",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "operation": "group_control",
                        "group": group_name,
                        "action": action,
                    }

                # ── list_groups ──────────────────────────────────────── #
                elif operation == "list_groups":
                    resp = await client.get(f"{base}/api/states", headers=headers)
                    resp.raise_for_status()
                    states = resp.json()
                    groups = [
                        {
                            "entity_id": s["entity_id"],
                            "state": s.get("state"),
                            "friendly_name": s.get("attributes", {}).get("friendly_name"),
                            "members": s.get("attributes", {}).get("entity_id", []),
                        }
                        for s in states
                        if s.get("entity_id", "").startswith("group.")
                    ]
                    return {
                        "success": True,
                        "operation": "list_groups",
                        "count": len(groups),
                        "groups": groups,
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"HA API error {exc.response.status_code}: {exc.response.text[:300]}",
            }
        except Exception as exc:
            logger.exception("SmartHomeTool error")
            return {"success": False, "error": str(exc)}
