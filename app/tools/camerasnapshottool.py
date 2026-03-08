# app/tools/camerasnapshottool.py
"""CameraSnapshotTool — capture a frame from a local camera or HA camera entity."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class CameraSnapshotTool(BaseTool):
    """Capture camera snapshots from a local USB/webcam or a Home Assistant camera entity."""

    def get_name(self) -> str:
        return "camera_snapshot"

    def get_description(self) -> str:
        return (
            "Capture a still image from a local camera (USB/webcam via OpenCV) or "
            "from a Home Assistant camera entity. Saves the image to disk and returns "
            "the file path so it can be analysed with xai_image_understand."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="source",
                    type="string",
                    description=(
                        "'local' — capture from a USB/webcam using OpenCV. "
                        "'ha' — fetch a snapshot from a Home Assistant camera entity."
                    ),
                    required=True,
                    enum=["local", "ha"],
                ),
                ToolParameter(
                    name="camera_index",
                    type="integer",
                    description="Camera device index for source=local (default: 0).",
                    required=False,
                ),
                ToolParameter(
                    name="entity_id",
                    type="string",
                    description=(
                        "Home Assistant camera entity ID for source=ha "
                        "(e.g. 'camera.front_door')."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="output_path",
                    type="string",
                    description=(
                        "File path where the snapshot will be saved. "
                        "Defaults to 'workspace/snapshot.jpg'."
                    ),
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  execute                                                              #
    # ------------------------------------------------------------------ #

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        source: str = kwargs.get("source", "local")
        output_path: str = kwargs.get("output_path") or "workspace/snapshot.jpg"
        camera_index: int = int(kwargs.get("camera_index", 0))
        entity_id: Optional[str] = kwargs.get("entity_id")

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if source == "local":
            return await asyncio.get_event_loop().run_in_executor(
                None, self._capture_local, camera_index, output_path
            )
        elif source == "ha":
            return await self._capture_ha(entity_id, output_path)

        return {"success": False, "error": f"Unknown source: {source}"}

    # ------------------------------------------------------------------ #
    #  Local capture (OpenCV)                                              #
    # ------------------------------------------------------------------ #

    def _capture_local(self, camera_index: int, output_path: str) -> Dict[str, Any]:
        try:
            import cv2  # type: ignore
        except ImportError:
            return {
                "success": False,
                "error": (
                    "OpenCV (cv2) is not installed. "
                    "Install it with: pip install opencv-python-headless"
                ),
            }

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return {
                "success": False,
                "error": f"Cannot open camera at index {camera_index}.",
            }
        try:
            ret, frame = cap.read()
            if not ret or frame is None:
                return {
                    "success": False,
                    "error": "Failed to capture frame from camera.",
                }
            cv2.imwrite(output_path, frame)
            abs_path = os.path.abspath(output_path)
            h, w = frame.shape[:2]
            return {
                "success": True,
                "source": "local",
                "camera_index": camera_index,
                "path": abs_path,
                "width": w,
                "height": h,
            }
        finally:
            cap.release()

    # ------------------------------------------------------------------ #
    #  HA camera snapshot                                                  #
    # ------------------------------------------------------------------ #

    async def _capture_ha(
        self, entity_id: Optional[str], output_path: str
    ) -> Dict[str, Any]:
        if not Config.HOME_ASSISTANT_URL or not Config.HOME_ASSISTANT_TOKEN:
            return {
                "success": False,
                "error": "HOME_ASSISTANT_URL or HOME_ASSISTANT_TOKEN not configured.",
            }
        if not entity_id:
            return {"success": False, "error": "'entity_id' is required for source=ha."}

        base = Config.HOME_ASSISTANT_URL.rstrip("/")
        url = f"{base}/api/camera_proxy/{entity_id}"
        headers = {
            "Authorization": f"Bearer {Config.HOME_ASSISTANT_TOKEN}",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return {
                    "success": False,
                    "error": f"Camera entity '{entity_id}' not found in HA.",
                }
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(resp.content)
            abs_path = os.path.abspath(output_path)
            return {
                "success": True,
                "source": "ha",
                "entity_id": entity_id,
                "path": abs_path,
                "size_bytes": len(resp.content),
            }
        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"HA camera error {exc.response.status_code}: {exc.response.text[:200]}",
            }
        except Exception as exc:
            logger.exception("CameraSnapshotTool HA capture error")
            return {"success": False, "error": str(exc)}
