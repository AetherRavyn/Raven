"""Agent Communication Protocol (ACP) — Enable IDE/tool integration.

Provides a lightweight protocol for external tools (IDEs, editors,
CI/CD pipelines) to communicate with Raven. Supports task submission,
status polling, and tool execution via a simple JSON-based protocol.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AcpRequest:
    """An ACP request from an external tool."""

    id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass
class AcpResponse:
    """Response to an ACP request."""

    id: str
    success: bool
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0


class AcpHandler:
    """Handles ACP requests from external tools (IDEs, editors, CI)."""

    def __init__(self) -> None:
        self._pending: dict[str, AcpRequest] = {}
        self._completed: dict[str, AcpResponse] = {}

    async def handle_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming ACP request."""
        req_id = body.get("id", uuid.uuid4().hex[:12])
        action = body.get("action", "")
        params = body.get("params", {})

        start = time.time()
        request = AcpRequest(id=req_id, action=action, params=params, created_at=start)
        self._pending[req_id] = request

        try:
            result = await self._dispatch(action, params)
            elapsed = (time.time() - start) * 1000
            response = AcpResponse(id=req_id, success=True, result=result, duration_ms=elapsed)
            self._completed[req_id] = response
            return {
                "id": req_id,
                "success": True,
                "result": result,
                "duration_ms": round(elapsed, 1),
            }
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            response = AcpResponse(id=req_id, success=False, error=str(e), duration_ms=elapsed)
            self._completed[req_id] = response
            return {
                "id": req_id,
                "success": False,
                "error": str(e),
                "duration_ms": round(elapsed, 1),
            }
        finally:
            self._pending.pop(req_id, None)

    async def _dispatch(self, action: str, params: dict[str, Any]) -> Any:
        """Route an ACP action to the appropriate handler."""
        if action == "ping":
            return {"status": "ok", "version": "1.0"}
        elif action == "execute":
            return await self._execute(params)
        elif action == "list_tools":
            return await self._list_tools()
        elif action == "read_file":
            return self._read_file(params)
        elif action == "search":
            return await self._search(params)
        elif action == "status":
            return self._get_status()
        else:
            raise ValueError(f"Unknown ACP action: {action}")

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        cmd = params.get("command", "")
        if not cmd:
            raise ValueError("No command specified")
        import asyncio

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return {
                "stdout": stdout.decode("utf-8", errors="replace")[:5000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
                "return_code": proc.returncode,
            }
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError("Command timed out")

    async def _list_tools(self) -> list[dict[str, str]]:
        try:
            from app.core.orchestrator import get_orchestrator

            orch = get_orchestrator()
            runtime = getattr(orch, "_agent_runtime", None)
            if runtime and hasattr(runtime, "tools"):
                return [
                    {"name": name, "description": getattr(t, "get_description", lambda: "")()[:100]}
                    for name, t in runtime.tools.items()
                ]
        except Exception:
            pass
        return []

    def _read_file(self, params: dict[str, Any]) -> str:
        from pathlib import Path

        filepath = params.get("filepath", "")
        if not filepath:
            raise ValueError("No filepath specified")
        path = Path(filepath).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        if path.stat().st_size > 100_000:
            return path.read_text(encoding="utf-8", errors="replace")[:100_000]
        return path.read_text(encoding="utf-8", errors="replace")

    async def _search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        query = params.get("query", "")
        if not query:
            raise ValueError("No query specified")
        try:
            from app.core.session import SessionManager

            mgr = SessionManager()
            results = mgr.search_conversations(query)
            return [
                {
                    "session_id": r.get("session_id", ""),
                    "snippet": r.get("snippet", "")[:200],
                    "score": r.get("score", 0),
                }
                for r in (results or [])
            ][:10]
        except Exception:
            return []

    def _get_status(self) -> dict[str, Any]:
        import shutil

        mem = None
        try:
            import psutil

            mem = psutil.virtual_memory().percent
        except ImportError:
            pass

        return {
            "uptime": time.time(),
            "python_version": __import__("sys").version,
            "docker_available": shutil.which("docker") is not None,
            "memory_percent": mem,
        }


# Singleton
_handler: AcpHandler | None = None


def get_acp_handler() -> AcpHandler:
    global _handler
    if _handler is None:
        _handler = AcpHandler()
    return _handler
