"""IoT Bridge — adapter layer between raven_iot module and main app.

This module provides thin wrappers that make raven_iot tools
compatible with the main app's BaseTool system and Config class.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class SmartHomeToolAdapter(BaseTool):
    """Adapter: wraps raven_iot.SmartHomeTool as a BaseTool."""

    def __init__(self) -> None:
        from raven_iot.config import IoTConfig
        from raven_iot.tools.smart_home import SmartHomeTool

        self._inner = SmartHomeTool(config=IoTConfig(
            home_assistant_url=Config.HOME_ASSISTANT_URL,
            home_assistant_token=Config.HOME_ASSISTANT_TOKEN,
        ))

    def get_name(self) -> str:
        return self._inner.get_name()

    def get_description(self) -> str:
        return self._inner.get_description()

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="operation", type="string", required=True,
                             description="Action: get_state, turn_on, turn_off, toggle, call_service, "
                                        "list_entities, group_control, list_groups",
                             enum=["get_state", "turn_on", "turn_off", "toggle", "call_service",
                                   "list_entities", "group_control", "list_groups"]),
                ToolParameter(name="entity_id", type="string", required=False,
                             description="HA entity ID (e.g. 'light.living_room')"),
                ToolParameter(name="group_name", type="string", required=False,
                             description="Group name for group_control"),
                ToolParameter(name="action", type="string", required=False,
                             description="Action for group_control (turn_on, turn_off, toggle)"),
                ToolParameter(name="domain", type="string", required=False,
                             description="HA domain for call_service"),
                ToolParameter(name="service", type="string", required=False,
                             description="HA service name for call_service"),
                ToolParameter(name="service_data", type="object", required=False,
                             description="Extra service data for call_service"),
                ToolParameter(name="domain_filter", type="string", required=False,
                             description="Filter list_entities by domain prefix"),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        return await self._inner.execute(**kwargs)
