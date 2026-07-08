"""Codex App-Server Runtime — isolated process lifecycle manager."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppInstance:
    id: str
    name: str
    status: str = "stopped"
    port: int = 0
    pid: int | None = None
    created_at: str = ""
    started_at: str | None = None
    last_health_at: str | None = None
    restart_count: int = 0
    health_status: str = "unknown"
    code: str = ""
    requirements: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    network_access: bool = False
    auto_restart: bool = True


@dataclass(slots=True)
class AppSpec:
    name: str
    code: str
    requirements: list[str] = field(default_factory=list)
    port_request: int | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    network_access: bool = False
    auto_restart: bool = True


@dataclass(slots=True)
class AppLog:
    line: str
    timestamp: str
    stream: str


_PORT_MIN = 9000
_PORT_MAX = 9999
_MAX_RESTART_ATTEMPTS = 3
_HEALTH_CHECK_INTERVAL = 30
_RING_BUFFER_SIZE = 1000
_SHUTDOWN_GRACE_SECONDS = 5


class PortPoolExhausted(Exception):
    """Raised when all ports in the range 9000-9999 are in use."""


class AppServerManager:
    """Manages the lifecycle of isolated code execution apps."""

    def __init__(
        self,
        workspace_dir: str = "workspace/apps",
        db_path: str | None = None,
    ) -> None:
        self._workspace = Path(workspace_dir).resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)
        if db_path is None:
            db_path = "workspace/memory/app_server.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._apps: dict[str, AppInstance] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._ring_buffers: dict[str, deque[AppLog]] = {}
        self._used_ports: set[int] = set()
        self._health_tasks: dict[str, asyncio.Task[Any]] = {}
        self._watch_tasks: dict[str, asyncio.Task[Any]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

        self._init_db()
        self._load_apps()

    # ── SQLite Persistence ─────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS apps (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'created',
                    port INTEGER,
                    pid INTEGER,
                    code TEXT NOT NULL,
                    requirements TEXT NOT NULL DEFAULT '[]',
                    env_vars TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    last_health_at TEXT,
                    restart_count INTEGER NOT NULL DEFAULT 0,
                    network_access INTEGER NOT NULL DEFAULT 0,
                    auto_restart INTEGER NOT NULL DEFAULT 1
                );
            """)

    def _persist_app(self, app: AppInstance) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO apps
                    (id, name, status, port, pid, code, requirements, env_vars,
                     created_at, started_at, last_health_at, restart_count,
                     network_access, auto_restart)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app.id,
                    app.name,
                    app.status,
                    app.port,
                    app.pid,
                    app.code,
                    json.dumps(app.requirements),
                    json.dumps(app.env_vars),
                    app.created_at,
                    app.started_at,
                    app.last_health_at,
                    app.restart_count,
                    int(app.network_access),
                    int(app.auto_restart),
                ),
            )

    def _remove_app_from_db(self, app_id: str) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))

    def _load_apps(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM apps").fetchall()
        for row in rows:
            app = AppInstance(
                id=row["id"],
                name=row["name"],
                status="stopped",
                port=row["port"] or 0,
                pid=None,
                code=row["code"],
                requirements=json.loads(row["requirements"]),
                env_vars=json.loads(row["env_vars"]),
                created_at=row["created_at"],
                started_at=None,
                last_health_at=row["last_health_at"],
                restart_count=row["restart_count"],
                network_access=bool(row["network_access"]),
                auto_restart=bool(row["auto_restart"]),
            )
            self._apps[app.id] = app
            self._ring_buffers[app.id] = deque(maxlen=_RING_BUFFER_SIZE)
            if app.port:
                self._used_ports.add(app.port)

    # ── Port Allocation ───────────────────────────────────────────────────

    def _allocate_port(self, requested: int | None = None) -> int:
        if requested is not None:
            if requested < _PORT_MIN or requested > _PORT_MAX:
                raise ValueError(
                    f"Requested port {requested} is out of range [{_PORT_MIN}-{_PORT_MAX}]"
                )
            if requested not in self._used_ports:
                self._used_ports.add(requested)
                return requested
            raise ValueError(f"Requested port {requested} is already in use")

        for port in range(_PORT_MIN, _PORT_MAX + 1):
            if port not in self._used_ports:
                self._used_ports.add(port)
                return port

        raise PortPoolExhausted(f"No available ports in range [{_PORT_MIN}-{_PORT_MAX}]")

    def _release_port(self, port: int) -> None:
        self._used_ports.discard(port)

    # ── App CRUD ──────────────────────────────────────────────────────────

    async def create_app(self, spec: AppSpec) -> AppInstance:
        async with self._lock:
            app_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            port = self._allocate_port(spec.port_request)

            app = AppInstance(
                id=app_id,
                name=spec.name,
                status="starting",
                port=port,
                created_at=now,
                code=spec.code,
                requirements=spec.requirements.copy(),
                env_vars=spec.env_vars.copy(),
                network_access=spec.network_access,
                auto_restart=spec.auto_restart,
            )

            app_dir = self._workspace / spec.name
            app_dir.mkdir(parents=True, exist_ok=True)

            (app_dir / "main.py").write_text(spec.code)

            if spec.requirements:
                (app_dir / "requirements.txt").write_text("\n".join(spec.requirements) + "\n")

            if spec.env_vars:
                (app_dir / ".env").write_text(
                    "\n".join(f"{k}={v}" for k, v in spec.env_vars.items()) + "\n"
                )

            if spec.requirements:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    "requirements.txt",
                    cwd=str(app_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.warning(
                        "pip install failed for %s: %s",
                        spec.name,
                        stderr.decode(errors="replace")[:500],
                    )

            self._apps[app_id] = app
            self._ring_buffers[app_id] = deque(maxlen=_RING_BUFFER_SIZE)
            self._persist_app(app)

            await self._start_process(app)

            return app

    async def start_app(self, app_id: str) -> bool:
        async with self._lock:
            app = self._apps.get(app_id)
            if app is None:
                return False
            if app.status in ("running", "starting"):
                return True
            app.restart_count = 0
            await self._start_process(app)
            return True

    async def stop_app(self, app_id: str) -> bool:
        async with self._lock:
            app = self._apps.get(app_id)
            if app is None:
                return False
            await self._stop_process(app_id)
            return True

    async def restart_app(self, app_id: str) -> bool:
        async with self._lock:
            app = self._apps.get(app_id)
            if app is None:
                return False
            app.restart_count = 0
            await self._stop_process(app_id)
            await self._start_process(app)
            return True

    async def delete_app(self, app_id: str) -> bool:
        async with self._lock:
            app = self._apps.get(app_id)
            if app is None:
                return False

            await self._stop_process(app_id)
            self._ring_buffers.pop(app_id, None)

            if app.port:
                self._release_port(app.port)

            self._remove_app_from_db(app_id)
            del self._apps[app_id]

            return True

    # ── Query ─────────────────────────────────────────────────────────────

    def get_app(self, app_id: str) -> AppInstance | None:
        return self._apps.get(app_id)

    def list_apps(self, status: str | None = None) -> list[AppInstance]:
        if status is None:
            return list(self._apps.values())
        return [a for a in self._apps.values() if a.status == status]

    def get_logs(self, app_id: str, tail: int = 100) -> list[AppLog]:
        buffer = self._ring_buffers.get(app_id)
        if not buffer:
            return []
        logs = list(buffer)
        return logs[-tail:]

    # ── Health Check ──────────────────────────────────────────────────────

    async def health_check(self, app_id: str) -> bool:
        app = self._apps.get(app_id)
        if app is None or app.status != "running":
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://localhost:{app.port}/health")
                healthy = resp.status_code == 200
                app.health_status = "healthy" if healthy else "unhealthy"
                app.last_health_at = datetime.now(timezone.utc).isoformat()
                self._persist_app(app)
                return healthy
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
            app.health_status = "unhealthy"
            app.last_health_at = datetime.now(timezone.utc).isoformat()
            self._persist_app(app)
            return False

    # ── Process Lifecycle ─────────────────────────────────────────────────

    async def _start_process(self, app: AppInstance) -> None:
        current = asyncio.current_task()

        old_watcher = self._watch_tasks.pop(app.id, None)
        if old_watcher is not None and old_watcher is not current and not old_watcher.done():
            old_watcher.cancel()

        old_health = self._health_tasks.pop(app.id, None)
        if old_health is not None and not old_health.done():
            old_health.cancel()

        self._stop_events.pop(app.id, None)

        app_dir = self._workspace / app.name
        env = os.environ.copy()
        env["PORT"] = str(app.port)
        env["PYTHONUNBUFFERED"] = "1"
        for k, v in app.env_vars.items():
            env[k] = v

        if not app.network_access:
            env["NO_NETWORK"] = "1"

        app.pid = None
        app.status = "starting"
        app.started_at = datetime.now(timezone.utc).isoformat()
        self._persist_app(app)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "main.py",
            cwd=str(app_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        app.pid = proc.pid
        app.status = "running"
        self._processes[app.id] = proc
        self._persist_app(app)

        asyncio.create_task(self._pipe_reader(app.id, proc.stdout, "stdout"))
        asyncio.create_task(self._pipe_reader(app.id, proc.stderr, "stderr"))

        stop_event = asyncio.Event()
        self._stop_events[app.id] = stop_event
        self._health_tasks[app.id] = asyncio.create_task(
            self._health_loop(app.id, stop_event),
        )

        self._watch_tasks[app.id] = asyncio.create_task(
            self._process_watcher(app),
        )

    async def _pipe_reader(
        self,
        app_id: str,
        stream: asyncio.StreamReader | None,
        stream_name: str,
    ) -> None:
        if stream is None:
            return
        buffer = self._ring_buffers.setdefault(app_id, deque(maxlen=_RING_BUFFER_SIZE))
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                log = AppLog(
                    line=line.decode(errors="replace").rstrip("\n\r"),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    stream=stream_name,
                )
                buffer.append(log)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("pipe reader error for %s (%s)", app_id, stream_name)

    async def _process_watcher(self, app: AppInstance) -> None:
        proc = self._processes.get(app.id)
        if proc is None:
            return
        try:
            await proc.wait()
        except asyncio.CancelledError:
            return

        stop_event = self._stop_events.get(app.id)
        if stop_event is not None:
            stop_event.set()

        old_health = self._health_tasks.pop(app.id, None)
        if old_health is not None and not old_health.done():
            old_health.cancel()

        self._processes.pop(app.id, None)
        app.pid = None

        if app.auto_restart and app.restart_count < _MAX_RESTART_ATTEMPTS:
            app.restart_count += 1
            app.status = "restarting"
            self._persist_app(app)
            backoff = 2**app.restart_count
            logger.info(
                "App %s crashed (attempt %d/%d), restarting in %ds",
                app.name,
                app.restart_count,
                _MAX_RESTART_ATTEMPTS,
                backoff,
            )
            await asyncio.sleep(backoff)
            async with self._lock:
                if app.id in self._apps:
                    await self._start_process(app)
        else:
            app.status = "crashed"
            if app.restart_count >= _MAX_RESTART_ATTEMPTS:
                logger.warning(
                    "App %s exceeded max restart attempts (%d)",
                    app.name,
                    _MAX_RESTART_ATTEMPTS,
                )
            self._persist_app(app)

    async def _stop_process(self, app_id: str) -> None:
        proc = self._processes.pop(app_id, None)
        app = self._apps.get(app_id)
        if app is not None:
            app.status = "stopped"
            app.pid = None
            self._persist_app(app)

        old_health = self._health_tasks.pop(app_id, None)
        if old_health is not None and not old_health.done():
            old_health.cancel()

        old_watcher = self._watch_tasks.pop(app_id, None)
        if old_watcher is not None and not old_watcher.done():
            old_watcher.cancel()

        stop_event = self._stop_events.pop(app_id, None)
        if stop_event is not None:
            stop_event.set()

        if proc is None:
            return

        try:
            if sys.platform != "win32":
                send_signal = getattr(proc, "send_signal", None)
                if callable(send_signal):
                    send_signal(signal.SIGTERM)
                else:
                    proc.terminate()
            else:
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
            except asyncio.TimeoutError:
                kill = getattr(proc, "kill", None)
                if callable(kill):
                    kill()
                await proc.wait()
        except ProcessLookupError:
            pass

    async def _health_loop(self, app_id: str, stop_event: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
                if stop_event.is_set():
                    break
                if app_id not in self._apps:
                    break
                await self.health_check(app_id)
        except asyncio.CancelledError:
            pass
