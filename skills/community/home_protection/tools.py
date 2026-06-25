"""Snapshot tool for the Home Protection module.

``SnapshotTool`` is the ``tool`` contribution declared in ``module.yaml``
(``tools.py:SnapshotTool``). It extends :class:`~app.tools.base.BaseTool` and is
the tool the ``intruder_response`` proactive reaction invokes when a stranger is
detected. The Module_Loader instantiates it with no constructor arguments.

This reference implementation returns a synthetic snapshot descriptor rather than
opening the camera stream, so the worked example runs without hardware. A
production tool would read ``CAMERA_RTSP_URL`` and grab a real frame.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.tools.base import (
    BaseTool,
    ToolCapability,
    ToolParameter,
    ToolSchema,
)

logger = logging.getLogger(__name__)


class SnapshotTool(BaseTool):
    """Capture a still image from a home-protection camera."""

    group = "security"

    def get_name(self) -> str:
        return "snapshot_tool"

    def get_description(self) -> str:
        return (
            "Capture a still snapshot from a home-protection camera. "
            "Invoked automatically when a stranger is detected at the door."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="camera_id",
                    type="string",
                    description="Identifier of the camera to snapshot.",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["camera.read"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="none",
            readonly=True,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Capture a snapshot and return a descriptor of the captured frame."""
        camera_id = str(kwargs.get("camera_id") or "front_door")
        captured_at = datetime.now(UTC).isoformat()
        logger.info("Capturing snapshot from camera %s", camera_id)
        return {
            "success": True,
            "camera_id": camera_id,
            "captured_at": captured_at,
            "image_ref": f"snapshot://{camera_id}/{captured_at}",
        }
