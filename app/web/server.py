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

  Phase 4 additions:
  GET  /api/system/status      — full system health (CPU, mem, agents, tools)
  GET  /api/goals              — autonomy engine goals
  POST /api/goals              — create a new goal
  GET  /api/memory/search      — semantic memory search
  GET  /api/sessions/list      — list all session files
  GET  /api/agents             — list registered agents
  GET  /api/sentinel/events    — recent sentinel events
  WebSocket /ws/events         — real-time system event stream

  Phase 3 — life dashboard (finance / health / habits):
  GET  /life/finance/summary              — current-month spend + cap
  POST /life/finance/expense              — record a new expense
  POST /life/finance/budget               — set the active budget
  GET  /life/health/{metric}              — rolling average + today total
  POST /life/health/{metric}              — record a daily reading
  GET  /life/habits                       — list known habits + streaks
  POST /life/habits/{habit}/done          — mark habit done today
  POST /life/habits/{habit}/skipped       — mark habit explicitly skipped
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Set

import uvicorn
from fastapi import (
    FastAPI,
    File,
    Form,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    Query,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload

if TYPE_CHECKING:
    from app.core.orchestrator import MessageOrchestrator

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


# ──────────────────────────────────────────────────────────────────────
# Pydantic body models for the life dashboard routes
#
# Defined at module scope so FastAPI can resolve the type
# annotations (when ``from __future__ import annotations`` is in
# effect, locally-scoped class definitions appear as ForwardRefs
# and cannot be resolved into a Body type).
# ──────────────────────────────────────────────────────────────────────


class FinanceExpenseBody(BaseModel):
    amount: float
    category: str
    currency: str = "USD"
    note: str = ""


class FinanceBudgetBody(BaseModel):
    monthly_cap: float
    currency: str = "USD"
    category_caps: Dict[str, float] | None = None


class HealthReadingBody(BaseModel):
    value: float
    date: str | None = None


# ──────────────────────────────────────────────
# Connection registries
# ──────────────────────────────────────────────
_WS_CONNECTIONS: dict[str, WebSocket] = {}
_EVENT_SUBSCRIBERS: Set[WebSocket] = set()


# ──────────────────────────────────────────────
# Event broadcast helper
# ──────────────────────────────────────────────
async def broadcast_event(event: Dict[str, Any]) -> None:
    """Push a system event to all /ws/events subscribers."""
    dead: list[WebSocket] = []
    for ws in _EVENT_SUBSCRIBERS:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _EVENT_SUBSCRIBERS.discard(ws)


class WebDashboard:
    """FastAPI-based web dashboard that acts as a RAVEN platform connector."""

    def __init__(self, orchestrator: "MessageOrchestrator") -> None:
        self._orchestrator = orchestrator
        self._app = self._build_app()
        self._start_time = time.time()
        # Wire the orchestrator into the provider manager so model
        # selection in the dashboard also updates the running runtime.
        try:
            from app.web.endpoints.provider_manager import get_provider_manager_dashboard

            pm = get_provider_manager_dashboard()
            pm.bind_orchestrator(orchestrator)
        except Exception as exc:
            logger.debug("Provider manager binding skipped: %s", exc)

    # ─── BotSignal sender ───────────────────────────────────────────────────

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Push a reply back to the WebSocket connection for that user."""
        ws = _WS_CONNECTIONS.get(target.chat_id)
        if ws is None:
            logger.debug("Web: no active WS for chat_id=%s, dropping reply", target.chat_id)
            return
        text = payload.text or payload.caption or ""
        try:
            await ws.send_json({"type": "chunk", "text": text})
            await ws.send_json({"type": "done"})
        except Exception as exc:
            logger.warning("Web WS send error for %s: %s", target.chat_id, exc)

        # Also broadcast to event subscribers
        await broadcast_event(
            {
                "event": "message",
                "platform": "web",
                "user_id": target.chat_id,
                "text": text[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def register_output_sender(self, botsignal: BotSignal) -> None:
        botsignal.register_sender("web", self.send_to_target)

    # ─── App factory ────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="RAVEN Intelligence OS")

        # Mount Prometheus /metrics if available
        try:
            from prometheus_client import make_asgi_app as _make_asgi_app

            app.mount("/metrics", _make_asgi_app())
        except ImportError:
            pass

        # Mount static files directory
        if _STATIC_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        # ── Life dashboard routes ────────────────────────────────────────────
        # Phase 3 — expose finance / health / habit trackers over
        # the same FastAPI app.  The router is framework-agnostic
        # (returns plain dicts); the handlers below are thin
        # adapters that translate the FastAPI request into a
        # ``router.dispatch(route, **kwargs)`` call.  Any router
        # exception surfaces as a 500 with the error message;
        # an unknown route surfaces as a 404.

        from app.web.life_dashboard import (  # noqa: PLC0415 - lazy import
            LifeDashboardRouter,
        )

        life_router = LifeDashboardRouter()

        def _http_status(result: Dict[str, Any]) -> int:
            """Translate a router result dict into an HTTP status code."""
            if result.get("ok"):
                return 200
            err = result.get("error", "")
            if err == "unknown_route":
                return 404
            if err == "amount_must_be_positive":
                return 400
            return 500

        @app.get("/life/finance/summary")
        async def get_finance_summary(
            month: str | None = Query(default=None),
        ) -> JSONResponse:
            result = life_router.dispatch(
                "GET /life/finance/summary",
                month=month,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.post("/life/finance/expense")
        async def post_finance_expense(
            payload: FinanceExpenseBody,
        ) -> JSONResponse:
            result = life_router.dispatch(
                "POST /life/finance/expense",
                amount=payload.amount,
                category=payload.category,
                currency=payload.currency,
                note=payload.note,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.post("/life/finance/budget")
        async def post_finance_budget(
            payload: FinanceBudgetBody,
        ) -> JSONResponse:
            result = life_router.dispatch(
                "POST /life/finance/budget",
                monthly_cap=payload.monthly_cap,
                currency=payload.currency,
                category_caps=payload.category_caps,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.get("/life/health/{metric}")
        async def get_health_metric(
            metric: str,
            window_days: int = Query(default=7),
            ending: str | None = Query(default=None),
        ) -> JSONResponse:
            result = life_router.dispatch(
                "GET /life/health/metric",
                metric=metric,
                window_days=window_days,
                ending=ending,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.post("/life/health/{metric}")
        async def post_health_metric(
            metric: str,
            payload: HealthReadingBody,
        ) -> JSONResponse:
            result = life_router.dispatch(
                "POST /life/health/metric",
                metric=metric,
                value=payload.value,
                date=payload.date,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.get("/life/habits")
        async def get_habits() -> JSONResponse:
            result = life_router.dispatch("GET /life/habits")
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.post("/life/habits/{habit}/done")
        async def post_habit_done(
            habit: str,
            date: str | None = Query(default=None),
        ) -> JSONResponse:
            result = life_router.dispatch(
                "POST /life/habits/done",
                habit=habit,
                date=date,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        @app.post("/life/habits/{habit}/skipped")
        async def post_habit_skipped(
            habit: str,
            date: str | None = Query(default=None),
        ) -> JSONResponse:
            result = life_router.dispatch(
                "POST /life/habits/skipped",
                habit=habit,
                date=date,
            )
            return JSONResponse(
                content=result,
                status_code=_http_status(result),
            )

        # ── Existing routes ──────────────────────────────────────────────────

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
                if original_sender is not None:
                    self._orchestrator._botsignal.register_sender("web", original_sender)
                else:
                    self._orchestrator._botsignal.register_sender("web", self.send_to_target)
                process_task.cancel()

            return JSONResponse({"reply": reply_text})

        @app.post("/api/chat/send")
        async def api_chat_send(text: str = Form(...)) -> JSONResponse:
            """Send a chat message and return the response (JSON, used by the Alpine chat UI)."""
            import time

            start = time.time()
            reply_holder: list[str] = []
            reply_event = asyncio.Event()
            user_id = "default"

            reply_target = ReplyTarget(platform="web", chat_id=user_id)
            original_sender = self._orchestrator._botsignal._senders.get("web")

            async def _capture(target: ReplyTarget, payload: SignalPayload) -> None:
                reply_holder.append(payload.text or payload.caption or "")
                reply_event.set()

            self._orchestrator._botsignal.register_sender("web", _capture)

            incoming = IncomingRequest(
                platform="web",
                user_id=user_id,
                text=text,
                reply_target=reply_target,
                conversation_id=user_id,
            )

            process_task = asyncio.create_task(
                self._orchestrator.handle(incoming), name="web-chat-send"
            )
            try:
                await asyncio.wait_for(reply_event.wait(), timeout=30.0)
                reply_text = reply_holder[0] if reply_holder else ""
            except asyncio.TimeoutError:
                reply_text = "Request timed out."
            finally:
                if original_sender is not None:
                    self._orchestrator._botsignal.register_sender("web", original_sender)
                else:
                    self._orchestrator._botsignal.register_sender("web", self.send_to_target)
                process_task.cancel()

            elapsed_ms = int((time.time() - start) * 1000)
            return JSONResponse(
                {
                    "ok": True,
                    "response": reply_text,
                    "latency_ms": elapsed_ms,
                    "interaction_id": f"chat_{int(start)}",
                    "session_id": user_id,
                }
            )

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
                sessions = await store.list_sessions() if hasattr(store, "list_sessions") else []
            except Exception as exc:
                logger.debug("Could not list sessions: %s", exc)
                sessions = []
            return JSONResponse({"sessions": sessions})

        @app.get("/sessions/{user_id}")
        async def get_session(user_id: str) -> JSONResponse:
            try:
                from app.core.memory import get_memory_store

                store = get_memory_store()
                history = await store.get_history(user_id) if hasattr(store, "get_history") else []
            except Exception as exc:
                logger.debug("Could not get session for %s: %s", user_id, exc)
                history = []
            return JSONResponse({"user_id": user_id, "history": history})

        @app.post("/internal/camera-alert")
        async def camera_alert(request_obj: dict) -> JSONResponse:
            from app.sensors.camera_bridge import handle_camera_alert

            asyncio.create_task(handle_camera_alert(request_obj))
            return JSONResponse({"status": "queued"})

        # ── Phase 4: New API Endpoints ────────────────────────────────────────

        @app.get("/api/system/status")
        async def system_status() -> JSONResponse:
            """Full system health: CPU, memory, disk, uptime, agents, tools."""
            import shutil

            # System metrics
            try:
                import psutil

                cpu_percent = psutil.cpu_percent(interval=0.1)
                mem = psutil.virtual_memory()
                mem_used_gb = mem.used / (1024**3)
                mem_total_gb = mem.total / (1024**3)
                mem_percent = mem.percent
            except ImportError:
                cpu_percent = -1
                mem_used_gb = -1
                mem_total_gb = -1
                mem_percent = -1

            disk = shutil.disk_usage("/")
            uptime = time.time() - self._start_time

            # Agent/tool counts
            tools = (
                list(self._orchestrator._agent_runtime.tools.keys())
                if hasattr(self._orchestrator, "_agent_runtime")
                else []
            )
            agents = []
            if hasattr(self._orchestrator, "_swarm_manager"):
                agents = (
                    [a.name for a in self._orchestrator._swarm_manager._agents.values()]
                    if hasattr(self._orchestrator._swarm_manager, "_agents")
                    else []
                )

            # Active platforms
            platforms = list(self._orchestrator._botsignal._senders.keys())

            return JSONResponse(
                {
                    "status": "online",
                    "uptime_seconds": int(uptime),
                    "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
                    "system": {
                        "os": platform.system(),
                        "python": platform.python_version(),
                        "hostname": platform.node(),
                        "cpu_percent": cpu_percent,
                        "memory": {
                            "used_gb": round(mem_used_gb, 1),
                            "total_gb": round(mem_total_gb, 1),
                            "percent": mem_percent,
                        },
                        "disk": {
                            "used_gb": round(disk.used / (1024**3), 1),
                            "total_gb": round(disk.total / (1024**3), 1),
                            "free_gb": round(disk.free / (1024**3), 1),
                        },
                    },
                    "tools": {"count": len(tools), "names": tools[:20]},
                    "agents": {"count": len(agents), "names": agents},
                    "platforms": platforms,
                    "websocket_connections": len(_WS_CONNECTIONS),
                    "event_subscribers": len(_EVENT_SUBSCRIBERS),
                }
            )

        @app.get("/api/health")
        async def health_check() -> JSONResponse:
            """Check health of all external dependencies."""
            try:
                from app.core.health import get_health_monitor

                monitor = get_health_monitor()
                await monitor.check_all()
                return JSONResponse(
                    {
                        "summary": monitor.get_summary(),
                        "services": monitor.get_all_statuses(),
                    }
                )
            except Exception as exc:
                return JSONResponse({"error": str(exc), "services": []})

        @app.get("/api/goals")
        async def list_goals() -> JSONResponse:
            """List all autonomy engine goals."""
            try:
                from app.settings.config import Config

                goals_file = Path(Config.MEMORY_ROOT) / "goals.jsonl"
                goals = []
                if goals_file.exists():
                    with open(goals_file, "r") as f:
                        for line in f:
                            if line.strip():
                                try:
                                    goals.append(json.loads(line.strip()))
                                except Exception:
                                    pass
                return JSONResponse({"goals": goals, "count": len(goals)})
            except Exception as exc:
                return JSONResponse({"goals": [], "error": str(exc)})

        class GoalRequest(BaseModel):
            title: str
            description: str = ""
            priority: str = "normal"

        @app.post("/api/goals")
        async def create_goal(req: GoalRequest) -> JSONResponse:
            """Create a new autonomy engine goal."""
            try:
                from app.settings.config import Config

                goals_file = Path(Config.MEMORY_ROOT) / "goals.jsonl"
                goals_file.parent.mkdir(parents=True, exist_ok=True)

                goal = {
                    "title": req.title,
                    "description": req.description,
                    "priority": req.priority,
                    "status": "Active",
                    "blockers": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                with open(goals_file, "a") as f:
                    f.write(json.dumps(goal) + "\n")

                await broadcast_event(
                    {
                        "event": "goal_created",
                        "title": req.title,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

                return JSONResponse({"success": True, "goal": goal})
            except Exception as exc:
                return JSONResponse({"success": False, "error": str(exc)})

        @app.get("/api/memory/search")
        async def search_memory(q: str = Query(..., min_length=1)) -> JSONResponse:
            """Semantic search across memory store."""
            try:
                from app.core.memory import get_memory_store

                store = get_memory_store()
                results = store.retrieve(query=q, top_k=10)
                return JSONResponse({"query": q, "results": results, "count": len(results)})
            except Exception as exc:
                return JSONResponse({"query": q, "results": [], "error": str(exc)})

        @app.get("/api/sessions/list")
        async def list_session_files() -> JSONResponse:
            """List all session JSONL files."""
            try:
                from app.settings.config import Config

                sessions_dir = Path(Config.MEMORY_ROOT) / "sessions"
                sessions = []
                if sessions_dir.exists():
                    for f in sorted(
                        sessions_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True
                    )[:50]:
                        stat = f.stat()
                        sessions.append(
                            {
                                "session_id": f.stem,
                                "size_bytes": stat.st_size,
                                "modified_at": datetime.fromtimestamp(
                                    stat.st_mtime, tz=timezone.utc
                                ).isoformat(),
                            }
                        )
                return JSONResponse({"sessions": sessions, "count": len(sessions)})
            except Exception as exc:
                return JSONResponse({"sessions": [], "error": str(exc)})

        @app.get("/api/agents")
        async def list_agents() -> JSONResponse:
            """List registered agents with their roles."""
            try:
                agents = []
                if hasattr(self._orchestrator, "_swarm_manager") and hasattr(
                    self._orchestrator._swarm_manager, "_agents"
                ):
                    for name, agent in self._orchestrator._swarm_manager._agents.items():
                        agents.append(
                            {
                                "name": agent.name,
                                "soul": agent.soul[:100] if agent.soul else "",
                                "tools_count": len(agent.tools),
                                "perfectness": agent.perfectness,
                                "heartbeat_interval": agent.heartbeat_interval,
                            }
                        )
                return JSONResponse({"agents": agents, "count": len(agents)})
            except Exception as exc:
                return JSONResponse({"agents": [], "error": str(exc)})

        @app.get("/api/sentinel/events")
        async def sentinel_events(limit: int = Query(50, le=200)) -> JSONResponse:
            """Recent sentinel events from the event log."""
            try:
                from app.settings.config import Config

                log_path = Path(Config.MEMORY_ROOT) / "sentinel_events.jsonl"
                events = []
                if log_path.exists():
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                    # Take last N lines (most recent)
                    for line in lines[-limit:]:
                        if line.strip():
                            try:
                                events.append(json.loads(line.strip()))
                            except Exception:
                                pass
                    events.reverse()  # Newest first
                return JSONResponse({"events": events, "count": len(events)})
            except Exception as exc:
                return JSONResponse({"events": [], "error": str(exc)})

        # ── Phase 4: WebSocket Event Stream ──────────────────────────────────

        @app.websocket("/ws/events")
        async def websocket_events(ws: WebSocket) -> None:
            """Real-time system event stream for the dashboard."""
            await ws.accept()
            _EVENT_SUBSCRIBERS.add(ws)
            logger.info("Event WS subscriber connected")
            try:
                # Keep alive — just wait for disconnect
                while True:
                    # Send heartbeat every 30s
                    await asyncio.sleep(30)
                    await ws.send_json(
                        {
                            "event": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "connections": len(_WS_CONNECTIONS),
                        }
                    )
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                _EVENT_SUBSCRIBERS.discard(ws)
                logger.info("Event WS subscriber disconnected")

        # ── Existing WebSocket Chat ──────────────────────────────────────────

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

        # ── v33: browser-voice WebSocket ───────────────────────────────────
        # Streams TTS audio to the dashboard browser so the
        # chat page can play replies out of the user's speakers
        # without routing through the on-device sound card.
        # Binary frame format: 4-byte LE uint32 sample rate + raw
        # WAV bytes — the browser's ``voice.js`` decodes the
        # prefix and constructs the right ``AudioContext`` rate.
        from app.voice.sink_registry import get_sink_registry
        from app.voice.sinks import WebSocketVoiceSink
        from app.voice.tts import get_active_voice_metadata

        @app.websocket("/voice/{user_id}")
        async def websocket_voice(ws: WebSocket, user_id: str) -> None:
            """Register a WebSocketVoiceSink for *user_id* so all
            TTS replies are forwarded to this browser tab.

            Connection is bidirectional — the browser can send
            ``{"type": "stop"}`` to stop a play mid-stream, or
            ``{"type": "ping"}`` for keepalive.  The server
            only sends binary audio frames in response to TTS
            dispatch (no out-of-band audio generation)."""
            await ws.accept()
            conn_id = f"ws-{id(ws)}"
            sink = WebSocketVoiceSink(user_id, ws, conn_id)
            registry = get_sink_registry()
            registry.register(user_id, sink)
            logger.info(
                "Voice WS connected: user=%s cid=%s (sinks=%d)",
                user_id,
                conn_id,
                len(registry.sinks_for(user_id)),
            )
            try:
                # Send the active voice metadata as the first
                # JSON frame so the client can render "Voice:
                # autherRaven" without an extra REST fetch.
                await ws.send_json({"type": "voice_info", **get_active_voice_metadata()})
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("type") == "websocket.receive":
                        # Browsers send text control messages
                        # as JSON; ignore unknowns.
                        text = msg.get("text")
                        if not text:
                            continue
                        try:
                            import json as _json

                            data = _json.loads(text)
                        except (ValueError, TypeError):
                            continue
                        kind = data.get("type")
                        if kind == "stop":
                            sink._closed = True
                            await ws.send_json({"type": "stop_ack"})
                        elif kind == "ping":
                            await ws.send_json({"type": "pong"})
            except WebSocketDisconnect:
                logger.info("Voice WS disconnected: user=%s cid=%s", user_id, conn_id)
            except Exception as exc:
                logger.warning("Voice WS error user=%s: %s", user_id, exc)
            finally:
                registry.unregister(user_id, sink)
                logger.info(
                    "Voice WS cleanup: user=%s (sinks now=%d)",
                    user_id,
                    len(registry.sinks_for(user_id)),
                )

        @app.get("/api/voice/config")
        async def voice_config() -> dict:
            """Return the active TTS voice metadata for the dashboard.

            Powers the "Voice: autherRaven" header in the chat
            page and the 🎙 button label.  Pure read-only."""
            return get_active_voice_metadata()

        @app.post("/api/voice/transcribe")
        async def voice_transcribe(
            user_id: str = Query(...),
            audio: UploadFile = File(...),
        ) -> dict:
            """Accept a recorded browser utterance (webm/opus),
            transcribe it via the whisper.cpp engine, then
            dispatch the text to the orchestrator as a normal
            chat turn.

            Returns ``{"text": "..."}`` for the browser to put
            into the chat input and submit.  The orchestrator
            reply is delivered through the existing /chat WS
            channel — the voice WS only carries TTS audio."""
            import tempfile
            from pathlib import Path
            from app.voice.transcribe import transcribe_audio

            # Persist the upload to a temp file the whisper.cpp
            # loader can read.
            with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as tmp:
                content = await audio.read()
                tmp.write(content)
                tmp_path = tmp.name
            try:
                text = await transcribe_audio(tmp_path)
            finally:
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
            return {"text": text or ""}

        # ── WebSocket /ws/video — real-time camera feed ──────────────

        @app.websocket("/ws/video/{camera_id}")
        async def websocket_video(ws: WebSocket, camera_id: str) -> None:
            """Stream camera frames via WebSocket."""
            from raven_iot.core.video_stream import VideoStreamManager

            await ws.accept()
            manager = VideoStreamManager()

            try:
                while True:
                    frame = manager.get_latest_frame_base64(camera_id)
                    if frame:
                        await ws.send_json({"type": "frame", "data": frame})
                    await asyncio.sleep(0.2)  # 5 FPS
            except Exception:
                pass
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass

        # ── Webhook Receiver — incoming events from external services ──


        @app.post("/api/webhooks/{service}")
        async def receive_webhook(service: str, request: Request) -> JSONResponse:
            """Receive incoming webhook from external services.

            Supported: github, stripe, slack, custom.
            Events are stored in workspace/webhooks/ and trigger proactive responses.
            """
            from pathlib import Path as _Path

            webhook_dir = _Path("workspace/webhooks")
            webhook_dir.mkdir(parents=True, exist_ok=True)

            try:
                body = await request.body()
                headers = dict(request.headers)
                payload = {
                    "service": service,
                    "timestamp": time.time(),
                    "headers": {k: v for k, v in headers.items() if k.lower().startswith("x-")},
                    "body": body.decode("utf-8", errors="replace")[:10000],
                }

                # Parse JSON if possible
                try:
                    payload["data"] = json.loads(body)
                except Exception:
                    payload["data"] = None

                # Determine event type per service
                if service == "github":
                    payload["event_type"] = headers.get("x-github-event", "unknown")
                    payload["delivery_id"] = headers.get("x-github-delivery", "")
                elif service == "stripe":
                    payload["event_type"] = payload.get("data", {}).get("type", "unknown")
                elif service == "slack":
                    payload["event_type"] = payload.get("data", {}).get("type", "unknown")

                # Save event
                import time as _time
                event_file = webhook_dir / f"{service}_{int(_time.time())}.json"
                event_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

                # Keep only last 100 events per service
                events = sorted(webhook_dir.glob(f"{service}_*.json"))
                for old in events[:-100]:
                    old.unlink(missing_ok=True)

                logger.info("Webhook received: %s (%s)", service, payload.get("event_type", "unknown"))

                return JSONResponse({
                    "received": True,
                    "service": service,
                    "event_type": payload.get("event_type", "unknown"),
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/webhooks")
        async def list_webhooks() -> JSONResponse:
            """List recent webhook events across all services."""
            from pathlib import Path as _Path
            webhook_dir = _Path("workspace/webhooks")
            if not webhook_dir.exists():
                return JSONResponse({"events": []})
            events = []
            for f in sorted(webhook_dir.glob("*.json"))[-20:]:
                try:
                    events.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
            return JSONResponse({"events": events})

        # ── FRIDAY intelligence API endpoints ──────────────────────────

        @app.get("/api/world-model")
        async def api_world_model() -> JSONResponse:
            try:
                from app.core.world_model import WorldModel
                wm = WorldModel()
                people = [e.__dict__ for e in wm.find_entities("person")[:20]]
                projects = [e.__dict__ for e in wm.find_entities("project")[:20]]
                events = [e.__dict__ for e in wm.get_recent_events(20)]
                return JSONResponse({
                    "people": people, "projects": projects, "recent_events": events,
                    "habits": wm._load_habits(),
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/attention")
        async def api_attention() -> JSONResponse:
            try:
                from app.core.attention import WorkingMemory
                wm = WorkingMemory()
                return JSONResponse(wm.get_status())
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/analogy")
        async def api_analogy() -> JSONResponse:
            try:
                from app.core.analogy import AnalogyEngine
                ae = AnalogyEngine()
                cases = ae.list_cases() if hasattr(ae, "list_cases") else []
                return JSONResponse({"case_count": len(cases)})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/companion")
        async def api_companion() -> JSONResponse:
            try:
                from app.core.companion_ai import get_companion_manager
                mgr = get_companion_manager()
                return JSONResponse(mgr.get_collaboration_summary())
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/nudge")
        async def api_nudge() -> JSONResponse:
            try:
                from app.core.nudge_engine import get_nudge_engine
                engine = get_nudge_engine()
                nudges = engine.generate_nudges()
                return JSONResponse({
                    "nudges": [
                        {"type": n.nudge_type, "message": n.message, "priority": n.priority}
                        for n in nudges
                    ]
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/user-model/{user_id}")
        async def api_user_model(user_id: str) -> JSONResponse:
            try:
                from app.core.user_model import get_user_model
                um = get_user_model()
                profile = um.get_profile(user_id)
                return JSONResponse({
                    "trust": profile.trust_level,
                    "formality": profile.formality_level,
                    "topics": profile.topic_interests,
                    "personality_prompt": um.get_personality_prompt(user_id),
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/goals")
        async def api_goals() -> JSONResponse:
            try:
                from app.core.goal_manager import get_goal_manager
                gm = get_goal_manager()
                goals = gm.list_goals() if hasattr(gm, "list_goals") else []
                return JSONResponse({"goals": [str(g) for g in goals[:20]]})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/resilience")
        async def api_resilience() -> JSONResponse:
            try:
                from app.core.resilient_recovery import get_resilience_manager
                get_resilience_manager()
                return JSONResponse({"status": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/finance")
        async def api_finance() -> JSONResponse:
            try:
                from app.core.finance_tracker import get_finance_tracker
                ft = get_finance_tracker()
                summary = ft.get_monthly_summary() if hasattr(ft, "get_monthly_summary") else {}
                return JSONResponse({"summary": summary})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/habits")
        async def api_habits() -> JSONResponse:
            try:
                from app.core.habit_tracker import get_habit_tracker
                ht = get_habit_tracker()
                habits = ht.get_habits() if hasattr(ht, "get_habits") else []
                return JSONResponse({"habits": [str(h) for h in habits[:20]]})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/delegation")
        async def api_delegation() -> JSONResponse:
            try:
                from app.core.delegation_manager import get_delegation_manager
                get_delegation_manager()
                return JSONResponse({"status": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/ab-testing")
        async def api_ab_testing() -> JSONResponse:
            try:
                return JSONResponse({"status": "available"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/autonomous")
        async def api_autonomous() -> JSONResponse:
            try:
                return JSONResponse({"planner": "active", "engine": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/cache")
        async def api_cache() -> JSONResponse:
            try:
                from app.core.cache import get_response_cache
                cache = get_response_cache()
                stats = cache.stats() if hasattr(cache, "stats") else {}
                return JSONResponse({"stats": stats})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/degradation")
        async def api_degradation() -> JSONResponse:
            try:
                from app.core.degraded_mode import DegradationDetector
                DegradationDetector()
                return JSONResponse({"status": "monitoring"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/event-digest")
        async def api_event_digest() -> JSONResponse:
            try:
                return JSONResponse({"status": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/kernel")
        async def api_kernel() -> JSONResponse:
            try:
                from app.core.kernel import get_kernel
                k = get_kernel()
                modules = k.list_modules() if hasattr(k, "list_modules") else []
                return JSONResponse({"modules": [str(m) for m in modules[:20]]})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/multimodal")
        async def api_multimodal() -> JSONResponse:
            try:
                return JSONResponse({"retriever": "active", "processor": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/output-router")
        async def api_output_router() -> JSONResponse:
            try:
                from app.core.output_router import get_output_router
                _or = get_output_router()
                return JSONResponse({"status": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/sandbox")
        async def api_sandbox() -> JSONResponse:
            try:
                from app.core.sandbox_manager import get_sandbox_manager
                sm = get_sandbox_manager()
                status = sm.status() if hasattr(sm, "status") else {}
                return JSONResponse({"status": status})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/sensors")
        async def api_sensors() -> JSONResponse:
            try:
                from app.core.environmental_sensors import EnvironmentalSensor
                es = EnvironmentalSensor()
                readings = es.get_readings() if hasattr(es, "get_readings") else []
                return JSONResponse({"readings": readings})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/video-fusion")
        async def api_video_fusion() -> JSONResponse:
            try:
                return JSONResponse({"status": "active"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── Hermes-class dashboard pages (v31, 2026-06-21) ───────────────
        # Server-rendered Jinja2 + HTMX.  Each page is a real GET
        # (no SPA) so the back/forward buttons and curl work.
        # The 4 routes registered here are the v1 read-only skeleton;
        # CRUD on 6 sections + audit mount land in v32.

        from app.web.render import render_page
        from app.web.sidebar_nav import nav_entries, find_entry

        def _page_context(slug: str) -> dict:
            """Shared context for every dashboard page render."""
            entry = find_entry(slug)
            label = entry.label if entry else slug.upper()
            return {
                "page": slug,
                "page_label": label,
                "nav_entries": nav_entries,
            }

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
            # Read-only v31: best-effort pull from the memory store
            # (the same source as GET /api/sessions/list).
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
            except Exception as exc:  # never break the page render
                logger.debug("page_sessions: %s", exc)
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

        # ── v34 (2026-06-22): Providers dashboard ───────────────────
        # Lets the operator paste API keys for every LLM / voice /
        # search provider RAVEN can route through.  Keys land in
        # ``Config`` + ``os.environ`` immediately, so the agent
        # swarm's :func:`AutoModelRouter.get_best_model` re-picks
        # on the next dispatch — the swarm stops using the local
        # CLI fallback chain.  See :mod:`app.web.endpoints.providers`.

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

        # ── v36 (2026-06-23): Cowork (Kimi/Claude-style) ───────────
        # Pick a folder, propose a plan, approve steps, watch the
        # worker run them with diff preview.  See :mod:`app.cowork`.

        @app.get("/page/cowork", response_class=HTMLResponse)
        async def page_cowork(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/cowork.html",
                {**_page_context("cowork")},
            )

        @app.get("/api/cowork/workspaces")
        async def get_cowork_workspaces() -> JSONResponse:
            from app.cowork import get_cowork_manager

            return JSONResponse(
                {"ok": True, "workspaces": get_cowork_manager().list_workspaces()},
            )

        @app.post("/api/cowork/workspaces")
        async def post_cowork_workspaces(
            name: str = Form(...),
            path: str = Form(...),
            access: str = Form("rw"),
        ) -> JSONResponse:
            from app.cowork import get_cowork_manager

            try:
                ws = get_cowork_manager().add_workspace(
                    name=name, path=path, access=access,
                )
                return JSONResponse({"ok": True, "workspace": ws})
            except (ValueError, OSError) as exc:
                return JSONResponse(
                    {"ok": False, "error": str(exc)}, status_code=400,
                )

        @app.delete("/api/cowork/workspaces")
        async def delete_cowork_workspaces(workspace_id: str = Query(...)) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().remove_workspace(workspace_id)
            return JSONResponse({"ok": ok, "workspace_id": workspace_id})

        @app.get("/api/cowork/sessions")
        async def get_cowork_sessions() -> JSONResponse:
            from app.cowork import get_cowork_manager

            mgr = get_cowork_manager()
            return JSONResponse(
                {
                    "ok": True,
                    "sessions": mgr.list_sessions(),
                    "active": mgr.get_active_session(),
                },
            )

        @app.post("/api/cowork/sessions")
        async def post_cowork_sessions(
            workspace_id: str = Form(...),
            goal: str = Form(...),
            auto_approve: str = Form("false"),
            strategy: str = Form("default"),
        ) -> JSONResponse:
            from app.cowork import get_cowork_manager

            try:
                sess = await get_cowork_manager().start_session(
                    workspace_id=workspace_id,
                    goal=goal,
                    auto_approve_low_risk=auto_approve.lower() in {"1", "true", "yes"},
                    strategy=strategy.strip().lower() or "default",
                )
                return JSONResponse({"ok": True, "session": sess})
            except (ValueError, OSError) as exc:
                return JSONResponse(
                    {"ok": False, "error": str(exc)}, status_code=400,
                )

        @app.get("/api/cowork/sessions/current")
        async def get_cowork_session_current() -> JSONResponse:
            from app.cowork import get_cowork_manager

            return JSONResponse(
                {"ok": True, "session": get_cowork_manager().get_active_session()},
            )

        @app.post("/api/cowork/sessions/{session_id}/pause")
        async def post_cowork_session_pause(session_id: str) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().pause_session(session_id)
            return JSONResponse({"ok": ok, "session_id": session_id})

        @app.post("/api/cowork/sessions/{session_id}/resume")
        async def post_cowork_session_resume(session_id: str) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().resume_session(session_id)
            return JSONResponse({"ok": ok, "session_id": session_id})

        @app.post("/api/cowork/sessions/{session_id}/stop")
        async def post_cowork_session_stop(session_id: str) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().stop_session(session_id)
            return JSONResponse({"ok": ok, "session_id": session_id})

        @app.post("/api/cowork/sessions/{session_id}/approve-all")
        async def post_cowork_session_approve_all(session_id: str) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().approve_all(session_id)
            return JSONResponse({"ok": ok, "session_id": session_id})

        @app.post("/api/cowork/sessions/{session_id}/steps/{step_id}/approve")
        async def post_cowork_step_approve(
            session_id: str, step_id: str,
        ) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().approve_step(session_id, step_id)
            return JSONResponse(
                {"ok": ok, "session_id": session_id, "step_id": step_id},
            )

        @app.post("/api/cowork/sessions/{session_id}/steps/{step_id}/reject")
        async def post_cowork_step_reject(
            session_id: str, step_id: str,
            reason: str = Form(""),
        ) -> JSONResponse:
            from app.cowork import get_cowork_manager

            ok = get_cowork_manager().reject_step(session_id, step_id, reason)
            return JSONResponse(
                {"ok": ok, "session_id": session_id, "step_id": step_id},
            )

        @app.get("/api/cowork/sessions/{session_id}/events")
        async def get_cowork_session_events(
            session_id: str, limit: int = Query(200),
        ) -> JSONResponse:
            from app.cowork import get_cowork_manager

            return JSONResponse(
                {
                    "ok": True,
                    "events": get_cowork_manager().read_events(session_id, limit=limit),
                },
            )

        @app.get("/api/cowork/stream")
        async def get_cowork_stream(request: Request) -> StreamingResponse:
            """Server-Sent Events stream of live cowork events.

            Subscribes to :data:`COWORK_TOPIC` on the InProcBus and
            pushes each event to the browser.  Tauri shell uses
            the same endpoint for the desktop notification feed.
            """
            import asyncio
            import json
            from app.core.inproc_bus import get_inproc_bus
            from app.cowork import COWORK_TOPIC

            async def gen():
                bus = get_inproc_bus()
                queue: asyncio.Queue = asyncio.Queue()

                async def put(payload):
                    await queue.put(payload)

                bus.subscribe(COWORK_TOPIC, put)
                try:
                    while True:
                        try:
                            payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                            yield f"data: {json.dumps(payload, default=str)}\n\n"
                        except asyncio.TimeoutError:
                            yield ": keepalive\n\n"
                finally:
                    bus.unsubscribe(COWORK_TOPIC, put)

            return StreamingResponse(
                gen(), media_type="text/event-stream",
            )

        @app.get("/api/providers/list")
        async def get_providers_list() -> JSONResponse:
            res = get_providers_router().dispatch("GET /providers/list")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/keys")
        async def post_providers_keys(request: Request) -> JSONResponse:
            form = await request.form()
            res = get_providers_router().dispatch(
                "POST /providers/keys",
                **dict(form),
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/clear")
        async def post_providers_clear(request: Request) -> JSONResponse:
            form = await request.form()
            res = get_providers_router().dispatch(
                "POST /providers/clear",
                **dict(form),
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── v34 (2026-06-22): Provider manager (model selection) ─────
        # Lets the operator choose which provider/model to use, enable/
        # disable providers, and set ranking order.  See
        # :mod:`app.web.endpoints.provider_manager`.

        @app.get("/api/providers/status")
        async def get_providers_status() -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch("GET /providers/status")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.get("/api/models")
        async def get_models() -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch("GET /models")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.get("/api/models/current")
        async def get_current_model() -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch("GET /models/current")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/enable")
        async def post_providers_enable(
            provider_id: str = Query(...),
            enabled: str = Query("true"),
        ) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /providers/enable",
                provider_id=provider_id,
                enabled=enabled,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/rank")
        async def post_providers_rank(ranking: str = Query(...)) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /providers/rank",
                ranking=ranking,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/models/select")
        async def post_models_select(
            provider_id: str = Query(...),
            model_id: str = Query(...),
        ) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /models/select",
                provider_id=provider_id,
                model_id=model_id,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── v35 (2026-06-23): Combos + health + stats ────────────────
        # 9router-style named fallback chains + live health probing.

        @app.get("/api/combos")
        async def get_combos() -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch("GET /combos")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/combos")
        async def post_combos(
            name: str = Form(...),
            providers: str = Form(...),
        ) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /combos",
                name=name,
                providers=providers,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.put("/api/combos")
        async def put_combos(
            name: str = Form(...),
            providers: str = Form(...),
        ) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "PUT /combos",
                name=name,
                providers=providers,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.delete("/api/combos")
        async def delete_combos(name: str = Query(...)) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "DELETE /combos",
                name=name,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/combos/activate")
        async def post_combos_activate(name: str = Query("")) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /combos/activate",
                name=name,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.get("/api/providers/health/all")
        async def get_providers_health_all() -> JSONResponse:
            dashboard = get_provider_manager_dashboard()
            res = dashboard.dispatch("GET /providers/health/all")
            if asyncio.iscoroutine(res):
                res = await res
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/health/check")
        async def post_providers_health_check(
            provider_id: str = Query(...),
        ) -> JSONResponse:
            dashboard = get_provider_manager_dashboard()
            res = dashboard.dispatch(
                "POST /providers/health/check",
                provider_id=provider_id,
            )
            if asyncio.iscoroutine(res):
                res = await res
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.get("/api/providers/stats")
        async def get_providers_stats() -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch("GET /providers/stats")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/providers/select-with-fallback")
        async def post_select_with_fallback(
            task_type: str = Query("general"),
        ) -> JSONResponse:
            res = get_provider_manager_dashboard().dispatch(
                "POST /providers/select-with-fallback",
                task_type=task_type,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── v34 (2026-06-21): dashboard env editor ───────────────────
        # The operator can set LLM, voice, memory, and dashboard
        # env vars from the /page/models form.  The overlay is
        # process-local: see app/web/endpoints/config_editor.py.

        @app.get("/api/config/show")
        async def get_config_show() -> JSONResponse:
            res = get_config_editor_router().dispatch("GET /config/show")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/config/update")
        async def post_config_update(request: Request) -> JSONResponse:
            form = await request.form()
            res = get_config_editor_router().dispatch(
                "POST /config/update",
                **dict(form),
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/config/reset")
        async def post_config_reset() -> JSONResponse:
            res = get_config_editor_router().dispatch("POST /config/reset")
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.get("/page/logs", response_class=HTMLResponse)
        async def page_logs(request: Request) -> HTMLResponse:
            from app.settings.config import Config

            # Read-only v31: pull the last 50 sentinel events off
            # MEMORY_ROOT/sentinel_events.jsonl (the same source the
            # JSON endpoint at /api/sentinel/events uses).
            events: list[dict] = []
            try:
                log_path = Path(Config.MEMORY_ROOT) / "sentinel_events.jsonl"
                if log_path.exists():
                    lines = log_path.read_text().splitlines()[-50:]
                    for line in lines:
                        if line.strip():
                            try:
                                events.append(json.loads(line))
                            except Exception:
                                pass
                    events.reverse()
            except Exception as exc:  # never break the page render
                logger.debug("page_logs: %s", exc)
            return render_page(
                request,
                "pages/logs.html",
                {**_page_context("logs"), "events": events},
            )

        # ── Hermes-class dashboard v32 (2026-06-21) ────────────────────
        # CRUD-capable pages on 6 sections + pairing + webhooks stub
        # + audit-router mount.  Each page has 1–3 JSON action
        # endpoints; the page templates wire the buttons via
        # hx-post="…" hx-target="#main" hx-swap="outerHTML" so the
        # refresh returns a fresh <main> fragment.

        from app.web.endpoints.audit_bridge import mount_audit
        from app.web.endpoints.channels import get_channels_dashboard_router
        from app.web.endpoints.cron import get_cron_dashboard_router
        from app.web.endpoints.mcp import get_mcp_dashboard_router
        from app.web.endpoints.pairing import get_pairing_dashboard_router
        from app.web.endpoints.plugins import get_plugins_dashboard_router
        from app.web.endpoints.profiles import get_profiles_dashboard_router
        from app.web.endpoints.providers import get_providers_router
        from app.web.endpoints.provider_manager import get_provider_manager_dashboard
        from app.web.endpoints.skills import get_skills_dashboard_router
        from app.web.endpoints.config_editor import get_config_editor_router

        def _http_status_v32(result: Dict[str, Any]) -> int:
            # The router round-trip succeeded — the operation may
            # have completed with ok=False (e.g. pairing code not
            # found, cron toggle on a missing job).  Return 200
            # so the dashboard receives a JSON body it can render;
            # a real 5xx is reserved for raised exceptions.
            #
            # NOTE: deliberately a *separate* function from the
            # life-dashboard ``_http_status`` (line ~182) so its
            # stricter semantics (amount_must_be_positive → 400)
            # are not accidentally shadowed for the /life/* routes.
            if result.get("ok"):
                return 200
            err = result.get("error", "")
            if err == "unknown_route":
                return 404
            if err in {
                "not_implemented",
                "job_id required",
                "code required",
                "user_id required",
                "user_id and platform required",
                "name required",
            }:
                return 400
            return 200

        # ── CRON page + actions ──────────────────────────────────────

        @app.get("/page/cron", response_class=HTMLResponse)
        async def page_cron(request: Request) -> HTMLResponse:
            jobs: list[dict] = []
            try:
                res = get_cron_dashboard_router().dispatch("GET /cron/list")
                if res.get("ok"):
                    jobs = res.get("jobs", [])
            except Exception as exc:  # never break the page render
                logger.debug("page_cron: %s", exc)
            return render_page(
                request,
                "pages/cron.html",
                {**_page_context("cron"), "jobs": jobs},
            )

        @app.post("/api/cron/toggle")
        async def post_cron_toggle(job_id: str = Query(...)) -> JSONResponse:
            res = get_cron_dashboard_router().dispatch(
                "POST /cron/toggle",
                job_id=job_id,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/cron/add")
        async def post_cron_add(
            job_id: str = Query(...),
            name: str = Query(...),
            description: str = Query(""),
            schedule_type: str = Query(...),
            action_description: str = Query(""),
            time_str: str | None = Query(default=None),
            interval: int | None = Query(default=None),
        ) -> JSONResponse:
            res = get_cron_dashboard_router().dispatch(
                "POST /cron/add",
                job_id=job_id,
                name=name,
                description=description,
                schedule_type=schedule_type,
                action_description=action_description,
                time_str=time_str,
                interval=interval,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/cron/remove")
        async def post_cron_remove(job_id: str = Query(...)) -> JSONResponse:
            res = get_cron_dashboard_router().dispatch(
                "POST /cron/remove",
                job_id=job_id,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── SKILLS page ──────────────────────────────────────────────

        @app.get("/page/skills", response_class=HTMLResponse)
        async def page_skills(request: Request) -> HTMLResponse:
            skills_list: list[dict] = []
            summary: dict = {}
            try:
                lst = get_skills_dashboard_router().dispatch("GET /skills/list")
                if lst.get("ok"):
                    skills_list = lst.get("skills", [])
                summ = get_skills_dashboard_router().dispatch("GET /skills/summary")
                if summ.get("ok"):
                    summary = summ.get("summary", {})
            except Exception as exc:
                logger.debug("page_skills: %s", exc)
            return render_page(
                request,
                "pages/skills.html",
                {**_page_context("skills"), "skills": skills_list, "summary": summary},
            )

        # ── PLUGINS page ─────────────────────────────────────────────

        @app.get("/page/plugins", response_class=HTMLResponse)
        async def page_plugins(request: Request) -> HTMLResponse:
            plugins_list: list[dict] = []
            summary: dict = {}
            try:
                res = get_plugins_dashboard_router().dispatch("GET /plugins/list")
                if res.get("ok"):
                    plugins_list = res.get("plugins", [])
                summ = get_plugins_dashboard_router().dispatch("GET /plugins/summary")
                if summ.get("ok"):
                    summary = summ.get("summary", {})
            except Exception as exc:
                logger.debug("page_plugins: %s", exc)
            return render_page(
                request,
                "pages/plugins.html",
                {**_page_context("plugins"), "plugins": plugins_list, "summary": summary},
            )

        # ── MCP page ─────────────────────────────────────────────────

        @app.get("/page/mcp", response_class=HTMLResponse)
        async def page_mcp(request: Request) -> HTMLResponse:
            servers: list[str] = []
            tool_names: list[str] = []
            connected = False
            tool_count = 0
            try:
                res = get_mcp_dashboard_router().dispatch("GET /mcp/status")
                if res.get("ok"):
                    servers = res.get("servers", [])
                    tool_names = res.get("tool_names", [])
                    connected = bool(res.get("connected"))
                    tool_count = res.get("tool_count", 0)
            except Exception as exc:
                logger.debug("page_mcp: %s", exc)
            return render_page(
                request,
                "pages/mcp.html",
                {
                    **_page_context("mcp"),
                    "servers": servers,
                    "tool_names": tool_names,
                    "connected": connected,
                    "tool_count": tool_count,
                },
            )

        @app.post("/api/mcp/connect")
        async def post_mcp_connect() -> JSONResponse:
            res = get_mcp_dashboard_router().dispatch("POST /mcp/connect")
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── CHANNELS page + actions ──────────────────────────────────

        @app.get("/page/channels", response_class=HTMLResponse)
        async def page_channels(request: Request) -> HTMLResponse:
            channels: list[dict] = []
            active_count = 0
            pid = None
            try:
                res = get_channels_dashboard_router().dispatch("GET /channels/status")
                if res.get("ok"):
                    gateway = res.get("gateway", {})
                    channels = list(gateway.get("channels", {}).values())
                    active_count = gateway.get("active_count", 0)
                    pid = gateway.get("pid")
            except Exception as exc:
                logger.debug("page_channels: %s", exc)
            return render_page(
                request,
                "pages/channels.html",
                {
                    **_page_context("channels"),
                    "channels": channels,
                    "active_count": active_count,
                    "pid": pid,
                },
            )

        @app.post("/api/channels/start")
        async def post_channels_start(name: str = Query(...)) -> JSONResponse:
            res = get_channels_dashboard_router().dispatch(
                "POST /channels/start",
                name=name,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/channels/stop")
        async def post_channels_stop(name: str = Query(...)) -> JSONResponse:
            res = get_channels_dashboard_router().dispatch(
                "POST /channels/stop",
                name=name,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/channels/restart")
        async def post_channels_restart(name: str = Query(...)) -> JSONResponse:
            res = get_channels_dashboard_router().dispatch(
                "POST /channels/restart",
                name=name,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── CALL MANAGEMENT API ─────────────────────────────────────

        @app.get("/api/calls/status")
        async def get_calls_status() -> JSONResponse:
            from app.web.endpoints.channels import get_channels_dashboard_router
            res = get_channels_dashboard_router().dispatch("GET /calls/status")
            return JSONResponse(res)

        @app.post("/api/calls/make")
        async def post_calls_make(target: str = Query(...), platform: str = Query("")) -> JSONResponse:
            from app.web.endpoints.channels import get_channels_dashboard_router
            res = get_channels_dashboard_router().dispatch(
                "POST /calls/make",
                target=target,
                platform=platform,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/calls/hangup")
        async def post_calls_hangup(call_id: str = Query(...)) -> JSONResponse:
            from app.web.endpoints.channels import get_channels_dashboard_router
            res = get_channels_dashboard_router().dispatch(
                "POST /calls/hangup",
                call_id=call_id,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/calls/answer")
        async def post_calls_answer(call_id: str = Query(...)) -> JSONResponse:
            from app.web.endpoints.channels import get_channels_dashboard_router
            res = get_channels_dashboard_router().dispatch(
                "POST /calls/answer",
                call_id=call_id,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── PROFILES page ────────────────────────────────────────────

        @app.get("/page/profiles", response_class=HTMLResponse)
        async def page_profiles(request: Request) -> HTMLResponse:
            user_ids: list[str] = []
            try:
                res = get_profiles_dashboard_router().dispatch("GET /profiles/list")
                if res.get("ok"):
                    user_ids = res.get("user_ids", [])
            except Exception as exc:
                logger.debug("page_profiles: %s", exc)
            return render_page(
                request,
                "pages/profiles.html",
                {**_page_context("profiles"), "user_ids": user_ids, "selected": None},
            )

        # ── PAIRING page + actions ───────────────────────────────────

        @app.get("/page/pairing", response_class=HTMLResponse)
        async def page_pairing(request: Request) -> HTMLResponse:
            pending: list[dict] = []
            paired: list[dict] = []
            pending_count = 0
            paired_count = 0
            try:
                res = get_pairing_dashboard_router().dispatch("GET /pairing/list")
                if res.get("ok"):
                    pending = res.get("pending", [])
                    paired = res.get("paired", [])
                    pending_count = res.get("pending_count", 0)
                    paired_count = res.get("paired_count", 0)
            except Exception as exc:
                logger.debug("page_pairing: %s", exc)
            return render_page(
                request,
                "pages/pairing.html",
                {
                    **_page_context("pairing"),
                    "pending": pending,
                    "paired": paired,
                    "pending_count": pending_count,
                    "paired_count": paired_count,
                },
            )

        @app.post("/api/pairing/approve")
        async def post_pairing_approve(
            code: str = Query(...),
            approved_by: str = Query(default="admin"),
        ) -> JSONResponse:
            res = get_pairing_dashboard_router().dispatch(
                "POST /pairing/approve",
                code=code,
                approved_by=approved_by,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        @app.post("/api/pairing/revoke")
        async def post_pairing_revoke(
            user_id: str = Query(...),
            platform: str = Query(...),
        ) -> JSONResponse:
            res = get_pairing_dashboard_router().dispatch(
                "POST /pairing/revoke",
                user_id=user_id,
                platform=platform,
            )
            return JSONResponse(res, status_code=_http_status_v32(res))

        # ── WEBHOOKS page (stub) ─────────────────────────────────────

        @app.get("/page/webhooks", response_class=HTMLResponse)
        async def page_webhooks(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/webhooks.html",
                {**_page_context("webhooks"), "webhooks": []},
            )

        # ── LEARNED SKILLS page (RL + auto-skills) ───────────────────

        @app.get("/page/learned-skills", response_class=HTMLResponse)
        async def page_learned_skills(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/learned-skills.html",
                {**_page_context("learned-skills")},
            )

        @app.get("/api/learned-skills")
        async def api_learned_skills() -> JSONResponse:
            try:
                skills_list: list[dict] = []
                from pathlib import Path

                learned_dir = Path(__file__).resolve().parents[2] / "skills" / "learned"
                if learned_dir.exists():
                    for slug_dir in sorted(learned_dir.iterdir()):
                        if slug_dir.is_dir():
                            mod_file = slug_dir / "module.yaml"
                            if mod_file.exists():
                                import yaml

                                data = yaml.safe_load(mod_file.read_text()) or {}
                                skills_list.append(
                                    {
                                        "slug": slug_dir.name,
                                        "display_name": data.get("display_name", slug_dir.name),
                                        "description": data.get("description", ""),
                                        "tags": data.get("tags", []),
                                        "triggers": data.get("triggers", []),
                                        "origin": data.get("origin", "learned"),
                                        "invocation_count": data.get("invocation_count", 0),
                                        "success_rate": data.get("success_rate", 0.0),
                                        "learned_from": data.get("learned_from", ""),
                                        "created_at": data.get("created_at", ""),
                                    }
                                )
                from app.core.skill_learner import SkillLearner

                try:
                    learner = SkillLearner()
                    trace_count = len(getattr(learner, "_recent_traces", []))
                except Exception:
                    trace_count = 0
                return JSONResponse({"ok": True, "skills": skills_list, "trace_count": trace_count})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/learned-skills/{slug}/promote")
        async def api_promote_skill(slug: str) -> JSONResponse:
            try:
                from app.core.skill_curator import SkillCurator

                curator = SkillCurator()
                promoted = curator.promote() if hasattr(curator, "promote") else []
                return JSONResponse({"ok": True, "promoted": promoted})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/learned-skills/{slug}/archive")
        async def api_archive_skill(slug: str) -> JSONResponse:
            try:
                from app.core.skill_curator import SkillCurator

                curator = SkillCurator()
                archived = curator.prune() if hasattr(curator, "prune") else []
                return JSONResponse({"ok": True, "archived": archived})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.get("/api/reinforcement-learning")
        async def api_reinforcement_learning() -> JSONResponse:
            try:
                from app.core.reinforcement_learning import get_reinforcement_learner

                rl = get_reinforcement_learner()
                return JSONResponse(rl.summary())
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        # ── PERSONALITY page ─────────────────────────────────────────

        @app.get("/page/personality", response_class=HTMLResponse)
        async def page_personality(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/personality.html",
                {**_page_context("personality")},
            )

        @app.get("/api/personality")
        async def api_personality(user_id: str = Query(default="default")) -> JSONResponse:
            try:
                from app.core.persona import get_persona_engine

                engine = get_persona_engine()
                return JSONResponse(engine.dashboard_data(user_id))
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/feedback")
        async def api_feedback(
            user_id: str = Query(default="default"),
            item_type: str = Query(default="response"),
            item_id: str = Query(default=""),
            reward: float = Query(default=0.0),
            reason: str = Query(default=""),
        ) -> JSONResponse:
            try:
                from app.core.feedback import FeedbackStore

                store = FeedbackStore()
                event = store.add_feedback(
                    user_id=user_id,
                    item_type=item_type,
                    item_id=item_id,
                    reward=reward,
                    reason=reason,
                )
                # Also feed into RL engine
                from app.core.reinforcement_learning import get_reinforcement_learner
                from app.core.persona import get_persona_engine

                rl = get_reinforcement_learner()
                rl.record_outcome(
                    task_category=item_type, action=item_id, success=reward > 0, user_rating=reward
                )
                # Record correction as learned value
                if reward < 0 and reason:
                    persona = get_persona_engine()
                    persona.record_user_correction(user_id, reason, reason)
                return JSONResponse(
                    {
                        "ok": True,
                        "event": {
                            "user_id": event.user_id,
                            "item_type": event.item_type,
                            "item_id": event.item_id,
                            "reward": event.reward,
                        },
                    }
                )
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        # ── KNOWLEDGE GRAPH page + API ──────────────────────────────

        @app.get("/page/knowledge-graph", response_class=HTMLResponse)
        async def page_knowledge_graph(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/knowledge-graph.html",
                {**_page_context("knowledge-graph")},
            )

        @app.get("/api/kg/stats")
        async def api_kg_stats() -> JSONResponse:
            try:
                from app.tools.kgtool import KnowledgeGraphTool

                tool = KnowledgeGraphTool()
                stats = await tool.get_stats()
                return JSONResponse(stats)
            except Exception as e:
                return JSONResponse(
                    {
                        "entity_count": 0,
                        "relationship_count": 0,
                        "backend": "error",
                        "healthy": False,
                        "error": str(e),
                    }
                )

        @app.get("/api/kg/entities")
        async def api_kg_entities() -> JSONResponse:
            try:
                from app.tools.kgtool import KnowledgeGraphTool

                tool = KnowledgeGraphTool()
                entities = await tool.list_entities()
                return JSONResponse({"entities": entities})
            except Exception as e:
                return JSONResponse({"ok": False, "entities": [], "error": str(e)})

        @app.get("/api/kg/search")
        async def api_kg_search(q: str = Query(default="")) -> JSONResponse:
            try:
                from app.tools.kgtool import KnowledgeGraphTool

                tool = KnowledgeGraphTool()
                results = await tool.search_entities(q)
                return JSONResponse({"entities": results})
            except Exception as e:
                return JSONResponse({"ok": False, "entities": [], "error": str(e)})

        @app.post("/api/kg/add")
        async def api_kg_add(
            name: str = Query(...),
            kind: str = Query(default="entity"),
            properties: str = Query(default="{}"),
        ) -> JSONResponse:
            try:
                from app.tools.kgtool import KnowledgeGraphTool
                import json

                tool = KnowledgeGraphTool()
                props = json.loads(properties)
                if hasattr(tool, "add_entity"):
                    tool.add_entity(name, kind, props)
                elif hasattr(tool, "add_relationship"):
                    tool.add_relationship(name, None, props)
                return JSONResponse({"ok": True})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        # ── Root-level page routes (no /page/ prefix) ───────────────
        # Serve dashboard pages at /{slug} directly, not just /page/{slug}.
        _ROOT_PAGES = [
            "chat",
            "models",
            "providers",
            "provider-manage",
            "logs",
            "cron",
            "skills",
            "plugins",
            "mcp",
            "channels",
            "pairing",
            "profiles",
            "webhooks",
            "learned-skills",
            "personality",
            "knowledge-graph",
            "cowork",
        ]
        for _slug in _ROOT_PAGES:

            @app.get(f"/{_slug}", response_class=HTMLResponse)
            async def _root_page(request: Request, _s: str = _slug) -> HTMLResponse:
                return render_page(
                    request,
                    f"pages/{_s}.html",
                    {**_page_context(_s)},
                )

        # ── MEMORY page ───────────────────────────────────────────────

        @app.get("/page/memory", response_class=HTMLResponse)
        async def page_memory(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/memory.html",
                {**_page_context("memory")},
            )

        @app.get("/api/memory/search")
        async def api_memory_search(q: str = "") -> JSONResponse:
            try:
                from app.core.memory_facade import get_memory_facade
                facade = get_memory_facade()
                results = facade.recall(q, top_k=10)
                return JSONResponse({
                    "results": [{"content": r.content, "source": r.source} for r in results],
                    "total": len(results),
                })
            except Exception as e:
                return JSONResponse({"results": [], "total": 0, "error": str(e)})

        @app.post("/api/memory/store")
        async def api_memory_store(request: Request) -> JSONResponse:
            try:
                body = await request.json()
                from app.core.memory_facade import get_memory_facade
                facade = get_memory_facade()
                mem_id = facade.remember(
                    body.get("content", ""),
                    category=body.get("category", "FACT"),
                )
                return JSONResponse({"success": True, "memory_id": mem_id})
            except Exception as e:
                return JSONResponse({"success": False, "error": str(e)})

        # ── A2A MODULES page ────────────────────────────────────────

        @app.get("/page/modules", response_class=HTMLResponse)
        async def page_modules(request: Request) -> HTMLResponse:
            return render_page(
                request,
                "pages/modules.html",
                {**_page_context("modules")},
            )

        @app.get("/modules")
        async def list_a2a_modules() -> JSONResponse:
            try:
                from raven_protocol import get_registry
                registry = get_registry()
                return JSONResponse(registry.get_registry_summary())
            except Exception as e:
                return JSONResponse({"total_modules": 0, "modules": [], "error": str(e)})

        @app.post("/module/{module_name}/{method_name}")
        async def call_a2a_module(module_name: str, method_name: str, request: Request) -> JSONResponse:
            try:
                body = await request.json()
                from raven_protocol import Message, get_registry
                registry = get_registry()
                full_method = f"{module_name}.{method_name}"
                message = Message.request(method=full_method, params=body, target=module_name)
                response = await registry.route_message(message)
                return JSONResponse(response.to_dict())
            except Exception as e:
                return JSONResponse({"type": "error", "error": str(e)})

        # ── Audit router mount (v32 wires the 9 audit endpoints) ────

        try:
            mount_audit(app)
        except Exception as exc:  # never block the dashboard on audit
            logger.debug("audit router mount failed: %s", exc)

        return app

    # ─── Server lifecycle ───────────────────────────────────────────────────

    async def start(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Run the web dashboard server until cancelled."""
        config = uvicorn.Config(self._app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        try:
            await server.serve()
        except asyncio.CancelledError:
            server.should_exit = True
            try:
                await server.shutdown()
            except Exception:
                pass
            logger.info("Web dashboard server cancelled during shutdown")
