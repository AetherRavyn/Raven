from __future__ import annotations

from typing import Any, Dict

from app.media.image.xai import understand_image
from app.provider.xai import XAIGrpcClient
from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class XAIImageUnderstandTool(BaseTool):
    """Image understanding tool backed by xAI gRPC chat multimodal input."""

    def __init__(
        self,
        client: XAIGrpcClient | None = None,
        default_model: str | None = None,
    ) -> None:
        self._client = client or XAIGrpcClient()
        self._default_model = default_model or Config.XAI_VISION_MODEL

    def get_name(self) -> str:
        return "xai_image_understand"

    def get_description(self) -> str:
        return "Understands an image from URL and returns model analysis."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="Public HTTP/HTTPS image URL to analyze.",
                    required=True,
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="What to analyze in the image.",
                    required=False,
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    description="Optional xAI vision model override.",
                    required=False,
                ),
                ToolParameter(
                    name="image_detail",
                    type="string",
                    description="Image detail level: auto, low, or high.",
                    required=False,
                    enum=["auto", "low", "high"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        image_url = str(kwargs.get("image_url", "")).strip()
        prompt = str(kwargs.get("prompt", "")).strip() or "Describe this image."
        model = str(kwargs.get("model", "")).strip() or self._default_model
        image_detail = str(kwargs.get("image_detail", "auto")).strip().lower()
        return understand_image(
            image_url=image_url,
            prompt=prompt,
            model=model,
            image_detail=image_detail,
            client=self._client,
        )
