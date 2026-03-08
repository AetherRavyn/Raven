# app/tools/imagegentool.py
"""ImageGenerationTool — generate images via xAI Aurora REST API."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

_XAI_IMAGE_URL = "https://api.x.ai/v1/images/generations"
_DEFAULT_MODEL = "aurora"


class ImageGenerationTool(BaseTool):
    """Generate images using xAI's Aurora model."""

    def get_name(self) -> str:
        return "generate_image"

    def get_description(self) -> str:
        return (
            "Generate images from a text prompt using the xAI Aurora image generation model. "
            "Returns URLs to the generated image(s)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Text description of the image to generate.",
                    required=True,
                ),
                ToolParameter(
                    name="n",
                    type="integer",
                    description="Number of images to generate (1–4). Defaults to 1.",
                    required=False,
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    description=(
                        f"xAI image model to use. Defaults to '{_DEFAULT_MODEL}'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="response_format",
                    type="string",
                    description="Return 'url' (default) or 'b64_json'.",
                    required=False,
                    enum=["url", "b64_json"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        api_key = Config.XAI_API_KEY
        if not api_key:
            return {"success": False, "error": "XAI_API_KEY not configured."}

        prompt: str = kwargs.get("prompt", "")
        if not prompt:
            return {"success": False, "error": "'prompt' is required."}

        n: int = max(1, min(int(kwargs.get("n", 1)), 4))
        model: str = kwargs.get("model") or _DEFAULT_MODEL
        response_format: str = kwargs.get("response_format", "url")

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "response_format": response_format,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(_XAI_IMAGE_URL, headers=headers, json=payload)

            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"xAI API error {resp.status_code}: {resp.text[:400]}",
                }

            data = resp.json()
            images: List[Dict[str, str]] = data.get("data", [])

            if response_format == "url":
                urls = [img.get("url", "") for img in images]
                return {
                    "success": True,
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                    "urls": urls,
                }
            else:
                return {
                    "success": True,
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                    "images_b64": [img.get("b64_json", "") for img in images],
                }

        except Exception as exc:
            logger.exception("ImageGenerationTool error")
            return {"success": False, "error": str(exc)}
