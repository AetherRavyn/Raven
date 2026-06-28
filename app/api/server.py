from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict
import logging
import asyncio
from datetime import datetime, timezone
import os

# Import RAVEN Core
from app.core.orchestrator import MessageOrchestrator
from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload
from app.dashboard.utils import get_daily_brief, get_system_mode
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.api.edge import router as edge_router
from app.api.ui import router as ui_router

logger = logging.getLogger(__name__)

# ── Dashboard event broadcast ───────────────────────────────────────
_WS_CONNECTIONS: dict[str, WebSocket] = {}
_EVENT_SUBSCRIBERS: set[WebSocket] = set()


async def broadcast_event(event: dict) -> None:
    """Push a system event to all /ws/events subscribers."""
    dead: list[WebSocket] = []
    for ws in _EVENT_SUBSCRIBERS:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _EVENT_SUBSCRIBERS.discard(ws)


app = FastAPI(
    title="RAVEN Intelligence OS API",
    description="Decoupled backend API for RAVEN (Phase 3). Connects to iOS, Next.js, and Tauri frontends.",
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
                    except Exception:
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
                await manager.send_message(user_id, {"type": "error", "content": str(e)})
                await manager.send_message(
                    user_id, {"type": "status", "state": "Error", "icon": "🔴"}
                )

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        logger.info(f"WebSocket disconnected for {user_id}")


# --- OpenAI-Compatible API Routes ---
try:
    from app.web.openai_api import create_openai_api_routes

    create_openai_api_routes(app)
    logger.info("OpenAI-compatible API routes registered at /v1/...")
except Exception as exc:
    logger.warning("OpenAI API routes not registered: %s", exc)


# --- ACP (Agent Communication Protocol) Routes ---
try:
    from app.core.acp import get_acp_handler
    from fastapi import Request

    @app.post("/acp")
    async def acp_endpoint(request: Request):
        """ACP endpoint for IDE/tool integration."""
        try:
            body = await request.json()
        except Exception:
            return {"success": False, "error": "Invalid JSON body"}
        handler = get_acp_handler()
        return await handler.handle_request(body)

    @app.get("/acp/health")
    async def acp_health():
        return {"status": "ok", "protocol": "acp/1.0"}

    logger.info("ACP routes registered at /acp")
except Exception as exc:
    logger.warning("ACP routes not registered: %s", exc)


# --- Hermes Dashboard Routes (Jinja2 pages + APIs) ---
# Unified dashboard: all Hermes page routes served on the same app
# so `raven run` gives you everything on one port.
try:
    _HERMES_STATIC = os.path.join(os.path.dirname(__file__), "..", "web", "static")
    if os.path.exists(_HERMES_STATIC):
        app.mount(
            "/static",
            StaticFiles(directory=_HERMES_STATIC),
            name="hermes_static",
        )

    from app.web.render import render_page
    from app.web.sidebar_nav import nav_entries, find_entry

    def _page_context(slug: str) -> dict:
        entry = find_entry(slug)
        label = entry.label if entry else slug.upper()
        return {
            "page": slug,
            "page_label": label,
            "nav_entries": nav_entries,
        }

    # --- Config Editor API (used by models.html and config_editor.js) ---
    try:
        from app.web.endpoints.config_editor import get_config_editor_router

        _config_router = get_config_editor_router()

        @app.get("/api/config/show")
        async def config_show():
            return _config_router.dispatch("GET /config/show")

        @app.post("/api/config/update")
        async def config_update(request: Request):
            form = await request.form()
            kwargs = {k: v for k, v in form.items()}
            return _config_router.dispatch("POST /config/update", **kwargs)

        @app.post("/api/config/reset")
        async def config_reset():
            return _config_router.dispatch("POST /config/reset")

        logger.info("Config editor routes registered at /api/config/*")
    except Exception as exc:
        logger.warning("Config editor routes not registered: %s", exc)

    # Direct slug routes — /providers -> /page/providers
    _DIRECT_SLUGS = [
        "chat",
        "sessions",
        "cowork",
        "knowledge-graph",
        "memory",
        "models",
        "providers",
        "provider-manage",
        "learned-skills",
        "learning",
        "personality",
        "logs",
        "cron",
        "skills",
        "plugins",
        "modules",
        "mcp",
        "channels",
        "webhooks",
        "pairing",
        "profiles",
    ]

    def _make_redirect(slug: str):
        @app.get(f"/{slug}", response_class=RedirectResponse)
        async def _redirect(request: Request) -> RedirectResponse:
            return RedirectResponse(url=f"/page/{slug}")

        return _redirect

    for _slug in _DIRECT_SLUGS:
        _make_redirect(_slug)

    @app.get("/", response_class=HTMLResponse)
    async def page_home(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/home.html",
            {**_page_context("home")},
        )

    @app.get("/page/home", response_class=HTMLResponse)
    async def page_home_full(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/home.html",
            {**_page_context("home")},
        )

    @app.get("/page/chat", response_class=HTMLResponse)
    async def page_chat(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/chat.html",
            {**_page_context("chat"), "messages": []},
        )

    @app.get("/page/sessions", response_class=HTMLResponse)
    async def page_sessions(request: Request) -> HTMLResponse:
        sessions: list[dict] = []
        try:
            from app.core.memory import get_memory_store

            store = get_memory_store()
            listed = await store.list_sessions() if hasattr(store, "list_sessions") else []
            for s in (listed or [])[:50]:
                if isinstance(s, dict):
                    sessions.append(s)
                else:
                    sessions.append({"user_id": str(s)})
        except Exception:
            pass
        return render_page(
            request,
            "pages/sessions.html",
            {**_page_context("sessions"), "sessions": sessions},
        )

    @app.get("/page/models", response_class=HTMLResponse)
    async def page_models(request: Request) -> HTMLResponse:
        from app.settings.config import Config

        return render_page(
            request,
            "pages/models.html",
            {
                **_page_context("models"),
                "llm_provider": Config.LLM_PROVIDER,
                "llm_model": Config.LLM_MODEL,
                "local_light_model": Config.LOCAL_LIGHT_MODEL,
                "cloud_heavy_model": Config.CLOUD_HEAVY_MODEL,
            },
        )

    @app.get("/page/providers", response_class=HTMLResponse)
    async def page_providers(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/providers.html",
            {**_page_context("providers")},
        )

    @app.get("/page/provider-manage", response_class=HTMLResponse)
    async def page_provider_manage(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/provider-manage.html",
            {**_page_context("provider-manage")},
        )

    @app.get("/page/cowork", response_class=HTMLResponse)
    async def page_cowork(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/cowork.html",
            {**_page_context("cowork")},
        )

    @app.get("/page/knowledge-graph", response_class=HTMLResponse)
    async def page_knowledge_graph(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/knowledge-graph.html",
            {**_page_context("knowledge-graph")},
        )

    @app.get("/page/memory", response_class=HTMLResponse)
    async def page_memory(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/memory.html",
            {**_page_context("memory")},
        )

    @app.get("/page/logs", response_class=HTMLResponse)
    async def page_logs(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/logs.html",
            {**_page_context("logs")},
        )

    @app.get("/page/cron", response_class=HTMLResponse)
    async def page_cron(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/cron.html",
            {**_page_context("cron")},
        )

    @app.get("/page/skills", response_class=HTMLResponse)
    async def page_skills(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/skills.html",
            {**_page_context("skills")},
        )

    @app.get("/page/plugins", response_class=HTMLResponse)
    async def page_plugins(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/plugins.html",
            {**_page_context("plugins")},
        )

    @app.get("/page/mcp", response_class=HTMLResponse)
    async def page_mcp(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/mcp.html",
            {**_page_context("mcp")},
        )

    @app.get("/page/channels", response_class=HTMLResponse)
    async def page_channels(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/channels.html",
            {**_page_context("channels")},
        )

    @app.get("/page/webhooks", response_class=HTMLResponse)
    async def page_webhooks(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/webhooks.html",
            {**_page_context("webhooks")},
        )

    @app.get("/page/pairing", response_class=HTMLResponse)
    async def page_pairing(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/pairing.html",
            {**_page_context("pairing")},
        )

    @app.get("/page/profiles", response_class=HTMLResponse)
    async def page_profiles(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/profiles.html",
            {**_page_context("profiles")},
        )

    # ── Learning Dashboard API ────────────────────────────────────────
    @app.get("/api/learning/stats")
    async def learning_stats():
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            return {"stats": store.get_stats()}
        except Exception as e:
            return {"stats": {"total": 0, "by_type": {}, "avg_confidence": 0.0}, "error": str(e)}

    @app.get("/api/learning/recent")
    async def learning_recent(type: str = "", limit: int = 20):
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            items = store.get_recent(type_=type or None, limit=limit)
            return {"items": items}
        except Exception as e:
            return {"items": [], "error": str(e)}

    @app.get("/api/learning/skills")
    async def learning_skills():
        try:
            from app.core.skill_crystallizer import SkillCrystallizer

            crystal = SkillCrystallizer()
            skills = crystal.get_crystallized_skills()
            return {"skills": skills}
        except Exception as e:
            return {"skills": [], "error": str(e)}

    @app.get("/api/learning/contradictions")
    async def learning_contradictions():
        try:
            from app.core.consolidation import ConsolidationEngine

            engine = ConsolidationEngine()
            contradictions = engine.get_contradictions_report()
            return {"contradictions": contradictions}
        except Exception as e:
            return {"contradictions": [], "error": str(e)}

    @app.get("/api/learning/search")
    async def learning_search(q: str = "", limit: int = 10):
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            results = store.search(q, limit=limit) if q else []
            return {"results": results, "query": q}
        except Exception as e:
            return {"results": [], "query": q, "error": str(e)}

    @app.get("/api/learning/health")
    async def learning_health():
        try:
            from app.core.learning_health import get_health_monitor

            monitor = get_health_monitor()
            snapshot = monitor.snapshot()
            return {"health": snapshot}
        except Exception as e:
            return {"health": {}, "error": str(e)}

    @app.get("/api/learning/events")
    async def learning_events(kind: str = "", limit: int = 20):
        try:
            from app.core.learning_events import get_events

            events = get_events(limit=limit, kind=kind or None)
            return {"events": events}
        except Exception as e:
            return {"events": [], "error": str(e)}

    @app.get("/api/learning/most-used")
    async def learning_most_used(limit: int = 10):
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            items = store.most_used(limit=limit)
            return {"items": items}
        except Exception as e:
            return {"items": [], "error": str(e)}

    @app.get("/api/learning/verification")
    async def learning_verification():
        try:
            from app.core.self_improvement import get_self_improvement_loop

            stats = get_self_improvement_loop().get_stats()
            return {"verification": stats}
        except Exception as e:
            return {"verification": {}, "error": str(e)}

    @app.get("/api/learning/topic-trends")
    async def learning_topic_trends(limit: int = 20):
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            topics = store.topic_trends(limit=limit)
            return {"topics": topics}
        except Exception as e:
            return {"topics": [], "error": str(e)}

    @app.get("/page/learning", response_class=HTMLResponse)
    async def page_learning(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/learning.html",
            {**_page_context("learning")},
        )

    @app.get("/page/learned-skills", response_class=HTMLResponse)
    async def page_learned_skills(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/learned-skills.html",
            {**_page_context("learned-skills")},
        )

    @app.get("/page/personality", response_class=HTMLResponse)
    async def page_personality(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/personality.html",
            {**_page_context("personality")},
        )

    @app.get("/page/modules", response_class=HTMLResponse)
    async def page_modules(request: Request) -> HTMLResponse:
        return render_page(
            request,
            "pages/modules.html",
            {**_page_context("modules")},
        )

    logger.info("Hermes dashboard routes registered (%d pages)", 22)
except Exception as exc:
    logger.warning("Hermes dashboard routes not registered: %s", exc)

# --- Static Frontend Serving (Command Center SPA at /app) ---
if os.path.exists("web"):
    try:
        app.mount("/app", StaticFiles(directory="web", html=True), name="web")
    except Exception:
        pass  # already mounted or invalid path
