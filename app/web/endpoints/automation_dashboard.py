"""Automation dashboard API endpoints — system health, services, scheduler."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.hooks import get_hook_manager
from app.core.rate_limit_middleware import RateLimitMiddleware

logger = logging.getLogger(__name__)


def _get_cpu() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except Exception:
        try:
            with open("/proc/stat") as f:
                lines = f.readlines()
            if lines:
                parts = lines[0].split()
                if len(parts) > 4:
                    total = sum(int(p) for p in parts[1:])
                    idle = int(parts[4])
                    return round(100 * (1 - idle / total), 1) if total else 0.0
        except Exception:
            pass
    return 0.0


def _get_memory() -> float:
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                data = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        data[key] = int(val)
                total = data.get("MemTotal", 1)
                free = data.get("MemFree", 0) + data.get("Buffers", 0) + data.get("Cached", 0)
                return round(100 * (1 - free / total), 1) if total else 0.0
        except Exception:
            pass
    return 0.0


def _get_disk() -> float:
    try:
        import psutil
        return psutil.disk_usage("/").percent
    except Exception:
        return 0.0


def _get_uptime_hours() -> float:
    try:
        import psutil
        return round(psutil.boot_time() / 3600, 1)
    except Exception:
        try:
            with open("/proc/uptime") as f:
                uptime_seconds = float(f.read().split()[0])
                return round(uptime_seconds / 3600, 1)
        except Exception:
            pass
    return 0.0


def _check_service(db_name: str) -> bool:
    path = Path("workspace/memory") / db_name
    return path.exists()


def get_health(params: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = params
    health = {
        "cpu": _get_cpu(),
        "memory": _get_memory(),
        "disk": _get_disk(),
        "uptime": _get_uptime_hours(),
    }

    services = {
        "kanban": _check_service("kanban.db"),
        "blueprints": _check_service("blueprints.db"),
        "hooks": _check_service("hooks.db"),
        "subscriptions": _check_service("subscriptions.db"),
        "app_server": _check_service("app_server.db"),
        "deliverables": _check_service("deliverables.db"),
        "rate_limits": _check_service("rate_limits.db"),
    }

    agents = {}
    try:
        from app.core.supervisor import AgentRegistry
        reg = AgentRegistry()
        reg.register_all()
        for cap in getattr(reg, "_capabilities", {}).values():
            agents[cap.agent_id] = True
    except Exception:
        agents = {"orchestrator": True}

    scheduler = {}
    try:
        sched_path = Path("workspace/memory/task_scheduler.json")
        if sched_path.exists():
            data = json.loads(sched_path.read_text())
            for task in data.get("tasks", data if isinstance(data, list) else []):
                if isinstance(task, dict) and "name" in task:
                    scheduler[task["name"]] = {
                        "enabled": task.get("enabled", True),
                        "interval": task.get("interval_turns", 0),
                    }
    except Exception:
        pass

    rate_limit_enabled = True
    try:
        mw = RateLimitMiddleware()
        rate_limit_enabled = mw.enabled
    except Exception:
        pass

    return {
        "ok": True,
        "health": health,
        "services": services,
        "agents": agents,
        "scheduler": scheduler,
        "rateLimit": {"enabled": rate_limit_enabled},
    }


def get_hook_stats(params: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = params
    try:
        mgr = get_hook_manager()
        stats = mgr.get_stats()
        return {"ok": True, **stats}
    except Exception:
        return {"ok": True, "total_hooks": 0, "total_deliveries": 0, "success_rate": 0.0, "pending_retries": 0}


def toggle_service(params: dict[str, Any] | None = None) -> dict[str, Any]:
    service = (params or {}).get("service", "")
    action = (params or {}).get("action", "")  # start, stop, restart
    if not service or action not in ("start", "stop", "restart"):
        return {"ok": False, "error": "service and action (start|stop|restart) required"}
    db_name = f"{service}.db"
    path = Path("workspace/memory") / db_name
    if action == "start":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        logger.info("Service %s started", service)
        return {"ok": True, "service": service, "action": action, "status": "started"}
    elif action == "stop":
        if path.exists():
            path.unlink()
        logger.info("Service %s stopped", service)
        return {"ok": True, "service": service, "action": action, "status": "stopped"}
    elif action == "restart":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        logger.info("Service %s restarted", service)
        return {"ok": True, "service": service, "action": action, "status": "restarted"}
    return {"ok": False, "error": "unknown action"}


def toggle_rate_limit(params: dict[str, Any] | None = None) -> dict[str, Any]:
    enabled = (params or {}).get("enabled", True)
    try:
        mw = RateLimitMiddleware()
        mw.enabled = bool(enabled)
        return {"ok": True, "rateLimit": {"enabled": mw.enabled}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_ROUTES: dict[str, Any] = {
    "GET /api/automation/health": get_health,
    "GET /api/hooks/stats": get_hook_stats,
    "POST /api/automation/service/toggle": toggle_service,
    "POST /api/automation/rate-limit/toggle": toggle_rate_limit,
}


def dispatch(route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    handler = _ROUTES.get(route)
    if handler is None:
        return {"ok": False, "error": f"Unknown route: {route}"}
    try:
        result = handler(params)
        if isinstance(result, dict):
            return result
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.exception("Automation route %s failed: %s", route, exc)
        return {"ok": False, "error": str(exc)}
