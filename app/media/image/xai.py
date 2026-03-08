from __future__ import annotations

from typing import Any, Dict
from urllib.parse import urlparse

from app.provider.xai import XAIGrpcClient
from app.settings.config import Config


def is_valid_http_image_url(image_url: str) -> bool:
    try:
        parsed = urlparse(image_url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def understand_image(
    *,
    image_url: str,
    prompt: str = "Describe this image.",
    model: str | None = None,
    image_detail: str = "auto",
    client: XAIGrpcClient | None = None,
) -> Dict[str, Any]:
    image_url = str(image_url or "").strip()
    prompt = str(prompt or "").strip() or "Describe this image."
    model = str(model or "").strip() or Config.XAI_VISION_MODEL
    image_detail = str(image_detail or "auto").strip().lower()

    if not image_url:
        return {"success": False, "error": "image_url is required."}
    if not is_valid_http_image_url(image_url):
        return {"success": False, "error": "image_url must be a valid HTTP/HTTPS URL."}
    if image_detail not in {"auto", "low", "high"}:
        return {
            "success": False,
            "error": "image_detail must be one of: auto, low, high.",
        }

    xai_client = client or XAIGrpcClient()
    try:
        response = xai_client.chat_completion_with_image(
            model=model,
            prompt=prompt,
            image_url=image_url,
            image_detail=image_detail,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {
        "success": bool(response.get("success")),
        "model": model,
        "image_url": image_url,
        "output": response.get("content", ""),
        "raw": response.get("raw"),
    }
