import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class MemoryTool(BaseTool):
    """
    Metacognitive memory tool with approval-gated persistence.

    Supports two modes:
    - ``mode=save`` — immediately persists (backward compatible, default)
    - ``mode=pend`` — queues for review; must be approved before persisting

    Use ``list_pending``, ``approve``, and ``reject`` actions to manage
    the pending queue after the fact.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._pending_file = self.workspace_dir / "pending_memory.jsonl"

    def get_name(self) -> str:
        return "save_memory"

    def get_description(self) -> str:
        return (
            "Saves important facts, learned rules, or network topology to permanent memory. "
            "Use this when you learn something new that you should remember for future sessions "
            "(e.g., 'User's laptop IP is 192.168.1.5', 'API requires batching of 40'). "
            "Set mode='pend' to queue for approval (requires later approve action). "
            "Use action='list_pending' to see queued entries, action='approve' or 'reject' "
            "with pending_id to resolve them."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="category",
                    type="string",
                    description="Category of memory: 'FACT', 'RULE', 'TOOL_GUIDE'.",
                    required=False,
                    enum=["FACT", "RULE", "TOOL_GUIDE"],
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="The exact text to save permanently.",
                    required=False,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'save' (direct write, default), 'pend' (queue for approval). "
                    "Mutually exclusive with action.",
                    required=False,
                    enum=["save", "pend"],
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description="'list_pending', 'approve', or 'reject'. "
                    "Mutually exclusive with mode.",
                    required=False,
                    enum=["list_pending", "approve", "reject"],
                ),
                ToolParameter(
                    name="pending_id",
                    type="string",
                    description="Required for approve/reject actions.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        action = kwargs.get("action")
        mode = kwargs.get("mode", "save")
        category = kwargs.get("category")
        content = kwargs.get("content")
        pending_id = kwargs.get("pending_id")
        request = kwargs.get("_request")
        user_id = request.user_id if request else None

        # ── Approval management actions ─────────────────────────────
        if action == "list_pending":
            return self._list_pending()
        if action == "approve":
            return self._approve_pending(pending_id)
        if action == "reject":
            return self._reject_pending(pending_id)

        # ── Write mode: pend or save ────────────────────────────────
        if not category or not content:
            return {"success": False, "error": "category and content are required for save/pend mode"}

        if mode == "pend":
            return self._pend_memory(category, content, user_id)

        # Default: direct write (backward compatible)
        return self._save_direct(category, content, user_id)

    # ── Direct save (backward compatible path) ──────────────────────

    def _save_direct(self, category: str, content: str, user_id: str | None) -> Dict[str, Any]:
        file_map = {"FACT": "AGENTS.md", "RULE": "AGENTS.md", "TOOL_GUIDE": "TOOLS.md"}
        filename = file_map.get(category, "AGENTS.md")
        filepath = self.workspace_dir / filename

        try:
            from app.core.memory import get_memory_store
            store = get_memory_store()
            store.save(category, content, user_id=user_id)

            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n- [{category}] {content}\n")

            return {"success": True, "message": f"Successfully saved {category} to memory."}
        except Exception as e:
            logger.error("Failed to save memory: %s", e)
            return {"success": False, "error": str(e)}

    # ── Pending write queue (approval gate) ─────────────────────────

    def _pend_memory(self, category: str, content: str, user_id: str | None) -> Dict[str, Any]:
        import uuid
        entry = {
            "pending_id": uuid.uuid4().hex[:12],
            "category": category,
            "content": content,
            "user_id": user_id or "unknown",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._pending_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True) + "\n")
            return {
                "success": True,
                "message": f"Memory queued for approval (pending_id={entry['pending_id']}). "
                "Use save_memory action='list_pending' to review, "
                "action='approve' or 'reject' to resolve.",
                "pending_id": entry["pending_id"],
            }
        except Exception as e:
            logger.error("Failed to pend memory: %s", e)
            return {"success": False, "error": str(e)}

    def _list_pending(self) -> Dict[str, Any]:
        entries = self._load_pending()
        pending = [e for e in entries if e.get("status") == "pending"]
        return {
            "success": True,
            "pending_count": len(pending),
            "pending_entries": [
                {
                    "pending_id": e["pending_id"],
                    "category": e.get("category"),
                    "content": (e.get("content") or "")[:200],
                    "created_at": e.get("created_at"),
                }
                for e in pending
            ],
        }

    def _approve_pending(self, pending_id: str | None) -> Dict[str, Any]:
        if not pending_id:
            return {"success": False, "error": "pending_id is required"}
        entries = self._load_pending()
        for entry in entries:
            if entry.get("pending_id") == pending_id and entry.get("status") == "pending":
                entry["status"] = "approved"
                entry["approved_at"] = datetime.now(timezone.utc).isoformat()
                self._flush_pending(entries)
                # Commit to permanent storage
                result = self._save_direct(
                    entry.get("category", "FACT"),
                    entry.get("content", ""),
                    entry.get("user_id"),
                )
                if result["success"]:
                    return {"success": True, "message": f"Memory {pending_id} approved and saved."}
                return {"success": False, "error": f"Memory approved but save failed: {result.get('error')}"}
        return {"success": False, "error": f"Pending memory {pending_id} not found or already resolved"}

    def _reject_pending(self, pending_id: str | None) -> Dict[str, Any]:
        if not pending_id:
            return {"success": False, "error": "pending_id is required"}
        entries = self._load_pending()
        for entry in entries:
            if entry.get("pending_id") == pending_id and entry.get("status") == "pending":
                entry["status"] = "rejected"
                entry["rejected_at"] = datetime.now(timezone.utc).isoformat()
                self._flush_pending(entries)
                return {"success": True, "message": f"Memory {pending_id} rejected and discarded."}
        return {"success": False, "error": f"Pending memory {pending_id} not found or already resolved"}

    def _load_pending(self) -> list[Dict[str, Any]]:
        if not self._pending_file.exists():
            return []
        entries: list[Dict[str, Any]] = []
        try:
            for line in self._pending_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        except Exception as e:
            logger.error("Failed to load pending memories: %s", e)
        return entries

    def _flush_pending(self, entries: list[Dict[str, Any]]) -> None:
        try:
            self._pending_file.write_text(
                "\n".join(json.dumps(e, ensure_ascii=True) for e in entries) + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to flush pending memories: %s", e)
