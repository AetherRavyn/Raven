import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class MemoryTool(BaseTool):
    """
    Metacognitive memory tool. Allows agents to write permanent facts,
    learned rules, or topology data into the workspace memory files.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def get_name(self) -> str:
        return "save_memory"

    def get_description(self) -> str:
        return (
            "Saves important facts, learned rules, or network topology to permanent memory. "
            "Use this when you learn something new that you should remember for future sessions "
            "(e.g., 'User's laptop IP is 192.168.1.5', 'API requires batching of 40')."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="category",
                    type="string",
                    description="Category of memory: 'FACT' (personal data/topology), 'RULE' (learned behavior), 'TOOL_GUIDE' (how to use a tool better).",
                    required=True,
                    enum=["FACT", "RULE", "TOOL_GUIDE"],
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="The exact text to save permanently.",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        category = kwargs.get("category")
        content = kwargs.get("content")
        request = kwargs.get("_request")  # IncomingRequest injected by AgentRuntime
        user_id = request.user_id if request else None

        if not category or not content:
            return {"success": False, "error": "category and content are required"}

        file_map = {"FACT": "AGENTS.md", "RULE": "AGENTS.md", "TOOL_GUIDE": "TOOLS.md"}
        filename = file_map.get(category, "AGENTS.md")
        filepath = self.workspace_dir / filename

        try:
            # Write to ChromaDB vector store
            from app.core.memory import get_memory_store

            store = get_memory_store()
            store.save(category, content, user_id=user_id)

            # Also keep flat-file append as human-readable audit log
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n- [{category}] {content}\n")

            return {
                "success": True,
                "message": f"Successfully saved {category} to memory.",
            }
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return {"success": False, "error": str(e)}
