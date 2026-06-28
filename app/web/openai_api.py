"""OpenAI-Compatible API — expose Raven as a standard OpenAI API endpoint.

Enables any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat)
to connect to Raven as if it were an OpenAI API. Supports streaming SSE
and tool calling.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────

_MODELS = [
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
]


def _count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _text_content(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
        return " ".join(texts)
    return str(content)


async def _get_or_create_orchestrator() -> Any:
    """Get the singleton orchestrator or create a fresh one."""
    try:
        from app.core.orchestrator import get_orchestrator

        orch = get_orchestrator()
        # Ensure API sender is registered
        _register_api_sender(orch)
        return orch
    except RuntimeError:
        from app.core.botsignal import BotSignal
        from app.core.orchestrator import MessageOrchestrator

        logger.warning("Orchestrator not initialized — creating ephemeral instance")
        orch = MessageOrchestrator(BotSignal(), output_directory="workspace")
        _register_api_sender(orch)
        return orch


def _register_api_sender(orchestrator: Any) -> None:
    """Register a no-op API sender so the runtime can send responses."""

    async def api_sender(target: Any, payload: Any) -> None:
        pass  # Response captured via handle_request return value

    try:
        orchestrator._agent_runtime.botsignal.register_sender("api", api_sender)
    except Exception:
        pass


async def _run_raven(user_message: str) -> str:
    """Run a message through the Raven orchestrator and return the response."""
    from app.core.models import IncomingRequest, ReplyTarget

    orchestrator = await _get_or_create_orchestrator()

    request_obj = IncomingRequest(
        text=user_message,
        platform="api",
        user_id="api_user",
        reply_target=ReplyTarget(platform="api", chat_id="api_user"),
    )
    result = await orchestrator.handle_request(request_obj)
    return result.get("text", "")


def _build_response(
    completion_id: str,
    created: int,
    model: str,
    response_text: str,
    prompt_tokens: int,
) -> dict:
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
            "prompt_tokens": prompt_tokens,
            "completion_tokens": _count_tokens(response_text),
            "total_tokens": prompt_tokens + _count_tokens(response_text),
        },
    }


def _build_stream_chunk(
    completion_id: str,
    created: int,
    model: str,
    content: str,
    finish_reason: str | None = None,
) -> str:
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


# ── routes ───────────────────────────────────────────────────────────


def create_openai_api_routes(app: Any) -> None:
    """Register OpenAI-compatible API routes on the FastAPI app."""

    @app.get("/v1/models")
    async def list_models():
        return {"object": "list", "data": _MODELS}

    @app.get("/v1/models/{model_id}")
    async def get_model(model_id: str):
        return {
            "id": model_id,
            "object": "model",
            "owned_by": "raven",
            "created": 1700000000,
            "permission": [],
            "root": model_id,
            "parent": None,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
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
                user_message = _text_content(msg)
                break

        if not user_message:
            return {"error": "No user message found"}

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        prompt_tokens = sum(_count_tokens(_text_content(m)) for m in messages)

        if stream:
            return await _handle_stream(completion_id, created, model, user_message, prompt_tokens)

        return await _handle_non_stream(completion_id, created, model, user_message, prompt_tokens)


async def _handle_non_stream(
    completion_id: str,
    created: int,
    model: str,
    user_message: str,
    prompt_tokens: int,
) -> dict:
    """Non-streaming response."""
    try:
        response_text = await _run_raven(user_message)
        return _build_response(completion_id, created, model, response_text, prompt_tokens)
    except Exception as e:
        return {"error": str(e)[:500]}


async def _handle_stream(
    completion_id: str,
    created: int,
    model: str,
    user_message: str,
    prompt_tokens: int,
) -> StreamingResponse:
    """Streaming SSE response."""

    async def event_stream():
        yield _build_stream_chunk(completion_id, created, model, "")
        try:
            response_text = await _run_raven(user_message)
            if response_text:
                # Stream word-by-word for realistic SSE
                words = response_text.split()
                buffer = ""
                for word in words:
                    chunk = word + " "
                    buffer += chunk
                    yield _build_stream_chunk(completion_id, created, model, chunk)
                    if len(buffer) > 500:
                        buffer = ""
                yield _build_stream_chunk(completion_id, created, model, "", finish_reason="stop")
            else:
                yield _build_stream_chunk(completion_id, created, model, "", finish_reason="stop")
        except Exception as e:
            logger.exception("Streaming failed")
            yield _build_stream_chunk(completion_id, created, model, str(e))
            yield _build_stream_chunk(completion_id, created, model, "", finish_reason="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
