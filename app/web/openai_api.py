"""OpenAI-Compatible API — expose Raven as a standard OpenAI API endpoint.

Enables any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat)
to connect to Raven as if it were an OpenAI API.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def create_openai_api_routes(app: Any) -> None:
    """Register OpenAI-compatible API routes on the FastAPI app."""

    @app.get("/v1/models")
    async def list_models():
        """List available models (OpenAI compatible)."""
        return {
            "object": "list",
            "data": [
                {
                    "id": "raven-default",
                    "object": "model",
                    "owned_by": "raven",
                    "created": 1700000000,
                },
                {
                    "id": "raven-fast",
                    "object": "model",
                    "owned_by": "raven",
                    "created": 1700000000,
                },
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Any):
        """OpenAI-compatible chat completions endpoint."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        messages = body.get("messages", [])
        model = body.get("model", "raven-default")
        stream = body.get("stream", False)

        # Extract the last user message
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            return {"error": "No user message found"}

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        try:
            from app.core.orchestrator import MessageOrchestrator
            from app.core.botsignal import BotSignal
            from app.core.models import IncomingRequest, ReplyTarget

            signal = BotSignal()
            response_text = ""

            async def capture_sender(target, payload):
                nonlocal response_text
                if hasattr(payload, "text"):
                    response_text = payload.text

            signal.register_sender("api", capture_sender)
            orchestrator = MessageOrchestrator(signal, output_directory="workspace")

            request_obj = IncomingRequest(
                text=user_message,
                platform="api",
                user_id="api_user",
                reply_target=ReplyTarget(platform="api", chat_id="api_user"),
            )
            await orchestrator.handle_request(request_obj)

            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": sum(len(m.get("content", "")) // 4 for m in messages),
                    "completion_tokens": len(response_text) // 4,
                    "total_tokens": sum(len(m.get("content", "")) // 4 for m in messages) + len(response_text) // 4,
                },
            }

        except Exception as e:
            return {"error": str(e)[:500]}

    @app.get("/v1/models/{model_id}")
    async def get_model(model_id: str):
        """Get model info (OpenAI compatible)."""
        return {
            "id": model_id,
            "object": "model",
            "owned_by": "raven",
            "created": 1700000000,
            "permission": [],
            "root": model_id,
            "parent": None,
        }
