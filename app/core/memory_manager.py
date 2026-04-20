from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.memory import get_memory_store

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryExtract:
    facts: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    tool_guides: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MemoryGovernanceRule:
    max_age_days: int = 180
    min_confidence: float = 0.3
    prefer_pinned: bool = True


class MemoryManager:
    """Extracts and stores useful long-term memory from conversation turns."""

    def __init__(self) -> None:
        self.store = get_memory_store()
        self.governance = MemoryGovernanceRule()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p.strip() for p in parts if p.strip()]

    def extract(self, text: str) -> MemoryExtract:
        lowered = text.lower()
        extract = MemoryExtract()

        for sentence in self._split_sentences(text):
            s_lower = sentence.lower()
            if any(
                phrase in s_lower
                for phrase in (
                    "i prefer",
                    "my preference",
                    "i like",
                    "i want",
                    "please use",
                )
            ):
                extract.preferences.append(sentence)
            if any(
                phrase in s_lower
                for phrase in (
                    "remember that",
                    "note that",
                    "i live",
                    "my name is",
                    "my email is",
                    "my phone is",
                )
            ):
                extract.facts.append(sentence)
            if any(
                phrase in s_lower
                for phrase in ("todo", "task", "follow up", "remind me", "please do")
            ):
                extract.tasks.append(sentence)
            if any(
                phrase in s_lower
                for phrase in ("use the", "tool", "command", "workflow")
            ):
                extract.tool_guides.append(sentence)

        # Lightweight heuristic for structured answers containing explicit preferences.
        if "prefer" in lowered and not extract.preferences:
            extract.preferences.extend(self._split_sentences(text)[:2])

        return extract

    def store_extraction(
        self, text: str, *, user_id: str | None = None
    ) -> MemoryExtract:
        extracted = self.extract(text)
        for fact in extracted.facts:
            self.store.save("FACT", fact, user_id=user_id)
        for pref in extracted.preferences:
            self.store.save("RULE", pref, user_id=user_id)
        for task in extracted.tasks:
            self.store.save("FACT", f"Task: {task}", user_id=user_id)
        for guide in extracted.tool_guides:
            self.store.save("TOOL_GUIDE", guide, user_id=user_id)
        return extracted

    def _is_stale(self, created_at: str | None) -> bool:
        if not created_at:
            return False
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            return age_days > self.governance.max_age_days
        except Exception:
            return False

    def prune_memory(self, user_id: str | None = None) -> int:
        """Best-effort memory pruning. Returns approximate removed count."""
        try:
            memory_files = getattr(self.store, "memory_files", None)
            if not memory_files:
                return 0
            removed = 0
            for item in list(memory_files):
                meta = getattr(item, "metadata", {}) or {}
                if user_id and meta.get("user_id") not in (None, user_id):
                    continue
                if self._is_stale(meta.get("created_at")):
                    try:
                        memory_files.remove(item)
                        removed += 1
                    except Exception:
                        continue
            return removed
        except Exception as exc:
            logger.debug("prune_memory failed: %s", exc)
            return 0

    def get_memory_governance_summary(
        self, user_id: str | None = None
    ) -> dict[str, Any]:
        memories = self.retrieve_context(query=user_id or "", user_id=user_id, top_k=20)
        return {
            "count": len(memories),
            "stale_prunable": sum(1 for m in memories if self._is_stale(None)),
            "min_confidence": self.governance.min_confidence,
            "prefer_pinned": self.governance.prefer_pinned,
        }

    def merge_conflicting_memory(
        self,
        user_id: str,
        old_value: str,
        new_value: str,
        category: str = "preferences",
    ) -> dict[str, Any]:
        from app.core.user_profile import UserProfileStore

        store = UserProfileStore()
        store.resolve_conflict(user_id, category, old_value, new_value, prefer_new=True)
        return {
            "user_id": user_id,
            "category": category,
            "old_value": old_value,
            "new_value": new_value,
            "merged": True,
        }

    def retrieve_context(
        self, query: str, *, user_id: str | None = None, top_k: int = 5
    ) -> list[str]:
        try:
            return self.store.retrieve(query=query, top_k=top_k, user_id=user_id)
        except Exception as exc:
            logger.debug("retrieve_context failed: %s", exc)
            return []

    def build_profile_summary(self, user_id: str) -> dict[str, Any]:
        profile_memories = self.retrieve_context(
            query=f"{user_id} preferences facts tasks",
            user_id=user_id,
            top_k=8,
        )
        preferences = [
            item
            for item in profile_memories
            if any(
                word in item.lower()
                for word in ("prefer", "like", "want", "use", "timezone", "language")
            )
        ]
        facts = [item for item in profile_memories if item not in preferences]
        return {
            "user_id": user_id,
            "preferences": preferences[:5],
            "facts": facts[:5],
            "raw": profile_memories[:8],
        }
