"""Kanban dashboard API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from app.core.kanban import KanbanBoard, TaskStatus

logger = logging.getLogger(__name__)


def list_cards(params: dict[str, Any] | None = None) -> dict[str, Any]:
    board = KanbanBoard()
    status_str = (params or {}).get("status", "")
    agent_id = (params or {}).get("agent_id", "")
    status = None
    if status_str:
        try:
            status = TaskStatus(status_str)
        except ValueError:
            pass
    cards = board.list_cards(status=status, agent_id=agent_id or None)
    return {
        "ok": True,
        "count": len(cards),
        "cards": [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "status": c.status.value,
                "agent_id": c.agent_id,
                "priority": c.priority,
                "tags": c.tags,
                "blocked_reason": c.blocked_reason,
                "created_at": c.created_at,
            }
            for c in cards
        ],
    }


def get_summary(params: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = params
    board = KanbanBoard()
    stats = board.get_board_summary()
    return {"ok": True, **stats}  # type: ignore[arg-type]


def add_card(params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = params or {}
    title = (p.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title is required"}
    board = KanbanBoard()
    card = board.create_card(
        title=title,
        description=(p.get("description") or "").strip(),
        agent_id=(p.get("agent_id") or "").strip(),
        priority=int(p.get("priority", 0)),
    )
    return {
        "ok": True,
        "card": {
            "id": card.id,
            "title": card.title,
            "status": card.status.value,
        },
    }


def move_card(params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = params or {}
    card_id = p.get("card_id")
    new_status = (p.get("status") or "").strip()
    if card_id is None or not new_status:
        return {"ok": False, "error": "card_id and status are required"}
    try:
        status = TaskStatus(new_status)
    except ValueError:
        return {"ok": False, "error": f"Invalid status: {new_status}"}
    board = KanbanBoard()
    moved = board.move_card(int(card_id), status)
    if not moved:
        return {"ok": False, "error": f"Card {card_id} not found"}
    return {"ok": True}


_ROUTES: dict[str, Any] = {
    "GET /api/kanban/list": list_cards,
    "GET /api/kanban/summary": get_summary,
    "POST /api/kanban/add": add_card,
    "POST /api/kanban/move": move_card,
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
        logger.exception("Kanban route %s failed: %s", route, exc)
        return {"ok": False, "error": str(exc)}
