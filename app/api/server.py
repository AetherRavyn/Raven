from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import logging
import asyncio
from datetime import datetime, timezone
import os

# Import SARAS Core
from app.core.orchestrator import MessageOrchestrator
from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload
from app.dashboard.utils import get_daily_brief, get_system_mode
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.api.edge import router as edge_router
from app.api.ui import router as ui_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SARAS Intelligence OS API",
    description="Decoupled backend API for SARAS (Phase 3). Connects to iOS, Next.js, and Tauri frontends.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow any frontend in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(edge_router)
app.include_router(ui_router)

# --- Global Orchestrator Instance ---
_orchestrator = None

_sync_chat_queues: Dict[str, asyncio.Queue] = {}


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_message(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)


manager = ConnectionManager()


async def api_sender(target: ReplyTarget, payload: SignalPayload) -> None:
    if target.platform == "websocket":
        user_id = target.chat_id
        if payload.text:
            msg = {
                "type": "message",
                "role": "assistant",
                "content": payload.text,
                "source_kind": payload.source_kind,
                "tool_traces": [
                    {
                        "tool": t.tool_name,
                        "action": t.action,
                        "success": t.success,
                        "detail": t.detail,
                    }
                    for t in (payload.tool_traces or [])
                ],
            }
            await manager.send_message(user_id, msg)
    elif target.platform == "web":
        q = _sync_chat_queues.get(target.chat_id)
        if q:
            await q.put(payload.text)


def get_orchestrator() -> MessageOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        signal = BotSignal()
        signal.register_sender("websocket", api_sender)
        signal.register_sender("web", api_sender)
        _orchestrator = MessageOrchestrator(signal, output_directory="workspace")
    return _orchestrator


# --- REST Endpoints (Stateless Data) ---


class ChatRequest(BaseModel):
    user_id: str
    message: str
    platform: str = "web"
    chat_id: str = "default_chat"


class ChatResponse(BaseModel):
    success: bool
    reply: str
    state: str
    timestamp: str


@app.get("/health")
async def health_check():
    mode = get_system_mode()
    return {
        "status": "ok",
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/inbox/{user_id}")
async def get_inbox(user_id: str):
    store = TaskInboxStore("workspace")
    return {"summary": store.get_summary(user_id), "items": store.list_items(user_id)}


@app.get("/api/v1/brief/{user_id}")
async def get_brief(user_id: str):
    return get_daily_brief(user_id)


@app.get("/api/v1/goals/{user_id}")
async def get_goals(user_id: str):
    goals_file = os.path.join("workspace", "goals.jsonl")
    goals = []
    if os.path.exists(goals_file):
        import json

        with open(goals_file, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        goals.append(json.loads(line))
                    except:
                        pass
    return {"goals": goals}


@app.get("/api/v1/ledger/{user_id}")
async def get_ledger(user_id: str):
    ledger = TaskLedger("workspace")
    tasks = ledger.list_tasks()
    return {"tasks": tasks}


@app.post("/api/v1/chat")
async def sync_chat(req: ChatRequest):
    """Fallback synchronous chat endpoint (not recommended for UX, use WebSockets instead)."""
    orch = get_orchestrator()
    q = asyncio.Queue()
    _sync_chat_queues[req.chat_id] = q
    try:
        request = IncomingRequest(
            platform=req.platform,
            user_id=req.user_id,
            text=req.message,
            reply_target=ReplyTarget(platform=req.platform, chat_id=req.chat_id),
        )
        await orch.handle(request)

        # Wait up to 30 seconds for a reply
        try:
            reply = await asyncio.wait_for(q.get(), timeout=30.0)
        except asyncio.TimeoutError:
            reply = "Timeout waiting for response."

        return ChatResponse(
            success=True,
            reply=reply,
            state="Completed",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return ChatResponse(
            success=False,
            reply=f"System Error: {str(e)}",
            state="Failed",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        _sync_chat_queues.pop(req.chat_id, None)


# --- WebSocket Streaming (Live UX) ---


@app.websocket("/ws/v1/chat/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: str):
    """
    Real-time, bidirectional streaming endpoint.
    Provides live thinking states, tool call notifications, and streaming text.
    """
    await manager.connect(user_id, websocket)
    orch = get_orchestrator()

    try:
        while True:
            data = await websocket.receive_text()

            # 1. State Change: Thinking
            await manager.send_message(
                user_id, {"type": "status", "state": "Thinking", "icon": "🧠"}
            )

            try:
                req = IncomingRequest(
                    platform="websocket",
                    user_id=user_id,
                    text=data,
                    reply_target=ReplyTarget(platform="websocket", chat_id=user_id),
                )
                await orch.handle(req)

                # 3. State Change: Idle
                await manager.send_message(
                    user_id, {"type": "status", "state": "Idle", "icon": "💤"}
                )

            except Exception as e:
                await manager.send_message(
                    user_id, {"type": "error", "content": str(e)}
                )
                await manager.send_message(
                    user_id, {"type": "status", "state": "Error", "icon": "🔴"}
                )

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        logger.info(f"WebSocket disconnected for {user_id}")


# --- Static Frontend Serving ---
if os.path.exists("web"):
    app.mount("/app", StaticFiles(directory="web", html=True), name="web")

    @app.get("/")
    async def redirect_to_app():
        return RedirectResponse(url="/app/index.html")
