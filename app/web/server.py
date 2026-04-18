# app/web/server.py
"""Web dashboard — FastAPI server with REST API and WebSocket chat UI.

Runs on port 8080 (configurable via WEB_DASHBOARD_PORT).
Provides:
  POST /message                — send a message, returns response (polling mode)
  GET  /status                 — which platforms are active
  GET  /sessions/{user_id}     — view conversation history for a user
  GET  /sessions               — list all sessions
  WebSocket /chat/{user_id}    — real-time chat with streaming responses
  GET  /                       — serve app/web/static/index.html
  GET  /metrics                — Prometheus metrics (if available)
  POST /internal/camera-alert  — camera alert webhook
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload

if TYPE_CHECKING:
    from app.core.orchestrator import MessageOrchestrator

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# ──────────────────────────────────────────────
# Connection registry: user_id → active WebSocket
# ──────────────────────────────────────────────
_WS_CONNECTIONS: dict[str, WebSocket] = {}


class WebDashboard:
    """FastAPI-based web dashboard that acts as a SARAS platform connector."""

    def __init__(self, orchestrator: "MessageOrchestrator") -> None:
        self._orchestrator = orchestrator
        self._app = self._build_app()

    # ─── BotSignal sender ───────────────────────────────────────────────────

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Push a reply back to the WebSocket connection for that user."""
        ws = _WS_CONNECTIONS.get(target.chat_id)
        if ws is None:
            logger.debug(
                "Web: no active WS for chat_id=%s, dropping reply", target.chat_id
            )
            return
        text = payload.text or payload.caption or ""
        try:
            await ws.send_json({"type": "chunk", "text": text})
            await ws.send_json({"type": "done"})
        except Exception as exc:
            logger.warning("Web WS send error for %s: %s", target.chat_id, exc)

    def register_output_sender(self, botsignal: BotSignal) -> None:
        botsignal.register_sender("web", self.send_to_target)

    # ─── App factory ────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="SARAS Web Dashboard")

        # Mount Prometheus /metrics if available
        try:
            from prometheus_client import make_asgi_app as _make_asgi_app

            app.mount("/metrics", _make_asgi_app())
        except ImportError:
            pass

        # Mount static files directory
        if _STATIC_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        # ── Routes ──────────────────────────────────────────────────────────

        @app.get("/")
        async def serve_index() -> FileResponse:
            index = _STATIC_DIR / "index.html"
            if not index.exists():
                raise HTTPException(status_code=404, detail="index.html not found")
            return FileResponse(str(index))

        class MessageRequest(BaseModel):
            user_id: str
            text: str
            platform: str = "web"

        @app.post("/message")
        async def post_message(req: MessageRequest) -> JSONResponse:
            """Send a message and wait for a reply (polling mode, max 30s)."""
            reply_holder: list[str] = []
            reply_event = asyncio.Event()

            reply_target = ReplyTarget(
                platform="web",
                chat_id=req.user_id,
            )

            # Temporarily hook the sender to capture the reply
            original_sender = self._orchestrator._botsignal._senders.get("web")

            async def _capture(target: ReplyTarget, payload: SignalPayload) -> None:
                reply_holder.append(payload.text or payload.caption or "")
                reply_event.set()

            self._orchestrator._botsignal.register_sender("web", _capture)

            incoming = IncomingRequest(
                platform=req.platform,
                user_id=req.user_id,
                text=req.text,
                reply_target=reply_target,
                conversation_id=req.user_id,
            )

            process_task = asyncio.create_task(
                self._orchestrator.handle(incoming), name="web-handle"
            )
            try:
                await asyncio.wait_for(reply_event.wait(), timeout=30.0)
                reply_text = reply_holder[0] if reply_holder else ""
            except asyncio.TimeoutError:
                reply_text = "Request timed out."
            finally:
                # Restore the original WebSocket sender
                if original_sender is not None:
                    self._orchestrator._botsignal.register_sender(
                        "web", original_sender
                    )
                else:
                    self._orchestrator._botsignal.register_sender(
                        "web", self.send_to_target
                    )
                process_task.cancel()

            return JSONResponse({"reply": reply_text})

        @app.get("/status")
        async def get_status() -> JSONResponse:
            botsignal = self._orchestrator._botsignal
            platforms = list(botsignal._senders.keys())
            return JSONResponse({"active_platforms": platforms, "status": "ok"})

        @app.get("/sessions")
        async def list_sessions() -> JSONResponse:
            try:
                from app.core.memory import get_memory_store

                store = get_memory_store()
                sessions = (
                    await store.list_sessions()
                    if hasattr(store, "list_sessions")
                    else []
                )
            except Exception as exc:
                logger.debug("Could not list sessions: %s", exc)
                sessions = []
            return JSONResponse({"sessions": sessions})

        @app.get("/sessions/{user_id}")
        async def get_session(user_id: str) -> JSONResponse:
            try:
                from app.core.memory import get_memory_store

                store = get_memory_store()
                history = (
                    await store.get_history(user_id)
                    if hasattr(store, "get_history")
                    else []
                )
            except Exception as exc:
                logger.debug("Could not get session for %s: %s", user_id, exc)
                history = []
            return JSONResponse({"user_id": user_id, "history": history})

        @app.post("/internal/camera-alert")
        async def camera_alert(request_obj: dict) -> JSONResponse:
            from app.sensors.camera_bridge import handle_camera_alert

            asyncio.create_task(handle_camera_alert(request_obj))
            return JSONResponse({"status": "queued"})

        @app.websocket("/chat/{user_id}")
        async def websocket_chat(ws: WebSocket, user_id: str) -> None:
            await ws.accept()
            _WS_CONNECTIONS[user_id] = ws
            logger.info("Web WS connected: user_id=%s", user_id)
            try:
                while True:
                    data = await ws.receive_json()
                    text = data.get("text", "").strip()
                    if not text:
                        continue

                    await ws.send_json({"type": "thinking"})

                    reply_target = ReplyTarget(platform="web", chat_id=user_id)
                    incoming = IncomingRequest(
                        platform="web",
                        user_id=user_id,
                        text=text,
                        reply_target=reply_target,
                        conversation_id=user_id,
                    )
                    # handle() will call send_to_target which pushes back to this ws
                    asyncio.create_task(
                        self._orchestrator.handle(incoming),
                        name=f"web-ws-{user_id}",
                    )
            except WebSocketDisconnect:
                logger.info("Web WS disconnected: user_id=%s", user_id)
            except Exception as exc:
                logger.warning("Web WS error for %s: %s", user_id, exc)
                try:
                    await ws.send_json({"type": "error", "message": str(exc)})
                except Exception:
                    pass
            finally:
                _WS_CONNECTIONS.pop(user_id, None)

        return app

    # ─── Server lifecycle ───────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Run the web dashboard server until cancelled."""
        config = uvicorn.Config(self._app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
