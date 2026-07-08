from __future__ import annotations

import logging
from typing import Any

from app.core.kanban import KanbanBoard, TaskStatus
from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.tools.__init__ import tool_error, tool_success

logger = logging.getLogger(__name__)


class KanbanTool(BaseTool):
    def get_name(self) -> str:
        return "kanban"

    def get_description(self) -> str:
        return "Multi-agent Kanban board for task tracking and workflow management"

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform",
                    required=True,
                    enum=[
                        "add_card",
                        "move_card",
                        "list_cards",
                        "get_card",
                        "delete_card",
                        "agent_queue",
                        "summary",
                    ],
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="Card title (required for add_card)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Card description",
                    required=False,
                ),
                ToolParameter(
                    name="agent_id",
                    type="string",
                    description="Assigned agent ID",
                    required=False,
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    description="Target status for move_card",
                    required=False,
                    enum=["backlog", "ready", "in_progress", "review", "done", "blocked"],
                ),
                ToolParameter(
                    name="card_id",
                    type="integer",
                    description="Card ID (required for move_card, get_card, delete_card)",
                    required=False,
                ),
                ToolParameter(
                    name="priority",
                    type="integer",
                    description="Priority (0-5, default 0)",
                    required=False,
                ),
                ToolParameter(
                    name="tags",
                    type="string",
                    description="Comma-separated tags",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = str(kwargs.get("action", "")).strip()
        board = KanbanBoard()

        if action == "add_card":
            title = kwargs.get("title", "").strip()
            if not title:
                return tool_error("title is required for add_card", action=action)
            description = kwargs.get("description", "").strip()
            agent_id = kwargs.get("agent_id", "").strip()
            priority = int(kwargs.get("priority", 0))
            tags_str = kwargs.get("tags", "").strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
            card = board.create_card(
                title=title,
                description=description,
                agent_id=agent_id,
                priority=priority,
                tags=tags,
            )
            return tool_success(
                action=action,
                card_id=card.id,
                title=card.title,
                status=card.status.value,
            )

        if action == "move_card":
            card_id = kwargs.get("card_id")
            if card_id is None:
                return tool_error("card_id is required for move_card", action=action)
            status_str = kwargs.get("status", "").strip()
            if not status_str:
                return tool_error("status is required for move_card", action=action)
            try:
                new_status = TaskStatus(status_str.lower())
            except ValueError:
                valid = [s.value for s in TaskStatus]
                return tool_error(
                    f"Invalid status. Valid: {', '.join(valid)}", action=action
                )
            moved = board.move_card(int(card_id), new_status)
            if not moved:
                return tool_error(f"Card {card_id} not found", action=action)
            card = board.get_card(int(card_id))
            if card is None:
                return tool_error(f"Card {card_id} not found after move", action=action)
            return tool_success(
                action=action,
                card_id=card.id,
                title=card.title,
                status=card.status.value,
            )

        if action == "list_cards":
            status_filter = None
            status_str = kwargs.get("status")
            if status_str:
                try:
                    status_filter = TaskStatus(status_str.strip().lower())
                except ValueError:
                    valid = [s.value for s in TaskStatus]
                    return tool_error(
                        f"Invalid status filter. Valid: {', '.join(valid)}",
                        action=action,
                    )
            agent_filter = kwargs.get("agent_id", "").strip() or None
            cards = board.list_cards(status=status_filter, agent_id=agent_filter)
            return tool_success(
                action=action,
                count=len(cards),
                cards=[
                    {
                        "id": c.id,
                        "title": c.title,
                        "status": c.status.value,
                        "agent_id": c.agent_id,
                        "priority": c.priority,
                    }
                    for c in cards
                ],
            )

        if action == "get_card":
            card_id = kwargs.get("card_id")
            if card_id is None:
                return tool_error("card_id is required for get_card", action=action)
            card = board.get_card(int(card_id))
            if card is None:
                return tool_error(f"Card {card_id} not found", action=action)
            return tool_success(
                action=action,
                id=card.id,
                title=card.title,
                description=card.description,
                status=card.status.value,
                agent_id=card.agent_id,
                priority=card.priority,
                tags=card.tags,
                blocked_reason=card.blocked_reason,
                created_at=card.created_at,
                updated_at=card.updated_at,
            )

        if action == "delete_card":
            card_id = kwargs.get("card_id")
            if card_id is None:
                return tool_error("card_id is required for delete_card", action=action)
            result = board.delete_card(int(card_id))
            if not result:
                return tool_error(f"Card {card_id} not found", action=action)
            return tool_success(action=action, deleted=True, card_id=int(card_id))

        if action == "agent_queue":
            agent_id = kwargs.get("agent_id", "").strip()
            if not agent_id:
                return tool_error("agent_id is required for agent_queue", action=action)
            cards = board.get_agent_queue(agent_id)
            return tool_success(
                action=action,
                agent_id=agent_id,
                count=len(cards),
                cards=[
                    {
                        "id": c.id,
                        "title": c.title,
                        "status": c.status.value,
                        "priority": c.priority,
                    }
                    for c in cards
                ],
            )

        if action == "summary":
            stats = board.get_board_summary()
            return tool_success(action=action, stats=stats)

        return tool_error(f"Unknown action: {action}", action=action)
