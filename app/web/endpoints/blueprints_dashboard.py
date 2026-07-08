"""Blueprints dashboard API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from app.core.blueprint_manager import BlueprintManager
from app.core.blueprint_runner import BlueprintRunner

logger = logging.getLogger(__name__)


def _get_manager() -> BlueprintManager:
    return BlueprintManager()


def list_blueprints(params: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = params
    manager = _get_manager()
    bps = manager.list_blueprints()
    return {
        "ok": True,
        "count": len(bps),
        "blueprints": [
            {
                "name": b.name,
                "version": b.version,
                "description": b.description,
                "author": b.author,
                "enabled": b.enabled,
                "run_count": b.run_count,
                "last_status": b.last_status,
                "last_run_at": b.last_run_at,
            }
            for b in bps
        ],
    }


def install_blueprint(params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = params or {}
    name = (p.get("name") or "").strip()
    content = (p.get("content") or "").strip()
    if not name or not content:
        return {"ok": False, "error": "name and content are required"}
    try:
        import yaml
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid YAML"}
        manager = _get_manager()
        bp_name = manager.install(data)
        return {"ok": True, "blueprint_id": bp_name}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_blueprint(params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = params or {}
    bp_id = (p.get("blueprint_id") or "").strip()
    if not bp_id:
        return {"ok": False, "error": "blueprint_id is required"}
    try:
        manager = _get_manager()
        bp = manager.get_blueprint(bp_id)
        if bp is None:
            return {"ok": False, "error": f"Blueprint {bp_id} not found"}
        runner = BlueprintRunner(manager=manager)
        result = runner.run(bp_id)
        return {
            "ok": True,
            "success": result.get("status") == "success",
            "steps_completed": sum(1 for s in result.get("steps_results", []) if s.get("status") == "success"),
            "steps_total": len(bp.steps),
            "duration_ms": int(result.get("duration", 0) * 1000),
            "error": result.get("error"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def enable_blueprint(params: dict[str, Any] | None = None) -> dict[str, Any]:
    bp_id = ((params or {}).get("blueprint_id") or "").strip()
    if not bp_id:
        return {"ok": False, "error": "blueprint_id is required"}
    manager = _get_manager()
    ok = manager.enable(bp_id)
    return {"ok": ok}


def disable_blueprint(params: dict[str, Any] | None = None) -> dict[str, Any]:
    bp_id = ((params or {}).get("blueprint_id") or "").strip()
    if not bp_id:
        return {"ok": False, "error": "blueprint_id is required"}
    manager = _get_manager()
    ok = manager.disable(bp_id)
    return {"ok": ok}


_ROUTES: dict[str, Any] = {
    "GET /api/blueprints/list": list_blueprints,
    "POST /api/blueprints/install": install_blueprint,
    "POST /api/blueprints/run": run_blueprint,
    "POST /api/blueprints/enable": enable_blueprint,
    "POST /api/blueprints/disable": disable_blueprint,
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
        logger.exception("Blueprints route %s failed: %s", route, exc)
        return {"ok": False, "error": str(exc)}
