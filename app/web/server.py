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
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Set

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
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
    """FastAPI-based web dashboard that acts as a SARAS platform connector."""

    def __init__(self, orchestrator: "MessageOrchestrator") -> None:
        self._orchestrator = orchestrator
        self._app = self._build_app()
        self._start_time = time.time()

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

        # Also broadcast to event subscribers
        await broadcast_event({
            "event": "message",
            "platform": "web",
            "user_id": target.chat_id,
            "text": text[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def register_output_sender(self, botsignal: BotSignal) -> None:
        botsignal.register_sender("web", self.send_to_target)

    # ─── App factory ────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="SARAS Intelligence OS")

        # Mount Prometheus /metrics if available
        try:
            from prometheus_client import make_asgi_app as _make_asgi_app

            app.mount("/metrics", _make_asgi_app())
        except ImportError:
            pass

        # Mount static files directory
        if _STATIC_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        # ── Serve the main dashboard ─────────────────────────────────────────

        @app.get("/")
        async def serve_index() -> FileResponse:
            # Prefer web/index.html (project root) over static/index.html
            root_index = Path("web/index.html")
            static_index = _STATIC_DIR / "index.html"
            if root_index.exists():
                return FileResponse(str(root_index))
            if static_index.exists():
                return FileResponse(str(static_index))
            raise HTTPException(status_code=404, detail="index.html not found")

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
                mem_used_gb = mem.used / (1024 ** 3)
                mem_total_gb = mem.total / (1024 ** 3)
                mem_percent = mem.percent
            except ImportError:
                cpu_percent = -1
                mem_used_gb = -1
                mem_total_gb = -1
                mem_percent = -1

            disk = shutil.disk_usage("/")
            uptime = time.time() - self._start_time

            # Agent/tool counts
            tools = list(self._orchestrator._agent_runtime.tools.keys()) if hasattr(self._orchestrator, '_agent_runtime') else []
            agents = []
            if hasattr(self._orchestrator, '_swarm_manager'):
                agents = [a.name for a in self._orchestrator._swarm_manager._agents.values()] if hasattr(self._orchestrator._swarm_manager, '_agents') else []

            # Active platforms
            platforms = list(self._orchestrator._botsignal._senders.keys())

            return JSONResponse({
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
                        "used_gb": round(disk.used / (1024 ** 3), 1),
                        "total_gb": round(disk.total / (1024 ** 3), 1),
                        "free_gb": round(disk.free / (1024 ** 3), 1),
                    },
                },
                "tools": {"count": len(tools), "names": tools[:20]},
                "agents": {"count": len(agents), "names": agents},
                "platforms": platforms,
                "websocket_connections": len(_WS_CONNECTIONS),
                "event_subscribers": len(_EVENT_SUBSCRIBERS),
            })

        @app.get("/api/health")
        async def health_check() -> JSONResponse:
            """Check health of all external dependencies."""
            try:
                from app.core.health import get_health_monitor
                monitor = get_health_monitor()
                await monitor.check_all()
                return JSONResponse({
                    "summary": monitor.get_summary(),
                    "services": monitor.get_all_statuses(),
                })
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

                await broadcast_event({
                    "event": "goal_created",
                    "title": req.title,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

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
                    for f in sorted(sessions_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
                        stat = f.stat()
                        sessions.append({
                            "session_id": f.stem,
                            "size_bytes": stat.st_size,
                            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        })
                return JSONResponse({"sessions": sessions, "count": len(sessions)})
            except Exception as exc:
                return JSONResponse({"sessions": [], "error": str(exc)})

        @app.get("/api/agents")
        async def list_agents() -> JSONResponse:
            """List registered agents with their roles."""
            try:
                agents = []
                if hasattr(self._orchestrator, '_swarm_manager') and hasattr(self._orchestrator._swarm_manager, '_agents'):
                    for name, agent in self._orchestrator._swarm_manager._agents.items():
                        agents.append({
                            "name": agent.name,
                            "soul": agent.soul[:100] if agent.soul else "",
                            "tools_count": len(agent.tools),
                            "perfectness": agent.perfectness,
                            "heartbeat_interval": agent.heartbeat_interval,
                        })
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
                    await ws.send_json({
                        "event": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "connections": len(_WS_CONNECTIONS),
                    })
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

        return app

    # ─── Server lifecycle ───────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
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
