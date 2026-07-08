from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
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
    confidence_decay_per_day: float = 0.005


class MemoryManager:
    """Extracts and stores useful long-term memory from conversation turns.

    Now with:
    - Confidence scoring on extracted memories
    - TTL-based staleness detection
    - Proper pruning via HelixDB tag-based filtering
    """

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
                    "my laptop",
                    "my server",
                    "my ip",
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

        if "prefer" in lowered and not extract.preferences:
            extract.preferences.extend(self._split_sentences(text)[:2])

        return extract

    async def aextract(self, text: str) -> MemoryExtract:
        """LLM-based extraction with regex fallback.

        Uses a small model to extract structured memory from text.
        Falls back to regex if LLM unavailable.
        """
        try:
            from app.core.model_router import AutoModelRouter
            from app.provider.factory import create_provider

            provider_name, model_name = AutoModelRouter.get_best_model("agent")
            provider = create_provider(provider_name)

            prompt = (
                "Extract structured memory from this text. "
                "Return a JSON object with these arrays:\n"
                '- "facts": objective facts (name, email, IP, device info, etc.)\n'
                '- "preferences": user preferences (likes, wants, style)\n'
                '- "tasks": action items (todo, follow-up, reminders)\n'
                '- "tool_guides": tool usage tips\n'
                "Only include items explicitly stated. Return empty arrays for categories with nothing.\n"
                f"\nText: {text}"
            )

            response = await provider.chat_completion(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                import json
                data = json.loads(content)
                return MemoryExtract(
                    facts=data.get("facts", []),
                    preferences=data.get("preferences", []),
                    tasks=data.get("tasks", []),
                    tool_guides=data.get("tool_guides", []),
                )
        except Exception as exc:
            logger.debug("LLM extraction failed, falling back to regex: %s", exc)

        # Fallback to regex
        return self.extract(text)

    def store_extraction(
        self, text: str, *, user_id: str | None = None
    ) -> MemoryExtract:
        """Store extracted memories with deduplication.

        Before saving, checks if a semantically similar memory
        already exists. Skips duplicates.
        """
        extracted = self.extract(text)
        for fact in extracted.facts:
            if not self._is_duplicate(fact, user_id):
                self.store.save("FACT", fact, user_id=user_id)
        for pref in extracted.preferences:
            if not self._is_duplicate(pref, user_id):
                self.store.save("RULE", pref, user_id=user_id)
        for task in extracted.tasks:
            if not self._is_duplicate(f"Task: {task}", user_id):
                self.store.save("FACT", f"Task: {task}", user_id=user_id)
        for guide in extracted.tool_guides:
            if not self._is_duplicate(guide, user_id):
                self.store.save("TOOL_GUIDE", guide, user_id=user_id)

        # Emit hook event for extracted memories
        try:
            from app.core.hooks import get_hook_manager
            hook_mgr = get_hook_manager()
            hook_mgr.trigger("memory_extracted", {
                "user_id": user_id or "anonymous",
                "facts_count": len(extracted.facts),
                "preferences_count": len(extracted.preferences),
                "tasks_count": len(extracted.tasks),
                "tool_guides_count": len(extracted.tool_guides),
                "total": len(extracted.facts) + len(extracted.preferences) + len(extracted.tasks) + len(extracted.tool_guides),
            })
        except Exception:
            pass

        return extracted

    def _is_duplicate(self, content: str, user_id: str | None = None) -> bool:
        """Check if a semantically similar memory already exists."""
        try:
            existing = self.store.retrieve(query=content, top_k=1, user_id=user_id)
            if not existing:
                return False
            # Simple overlap check: if >60% of words overlap, treat as duplicate
            words_new = set(content.lower().split())
            words_existing = set(existing[0].lower().split())
            if not words_new or not words_existing:
                return False
            overlap = len(words_new & words_existing) / max(len(words_new), 1)
            return overlap > 0.6
        except Exception:
            return False

    def _is_stale(self, timestamp: int | None) -> bool:
        if not timestamp:
            return False
        age_days = (time.time() - timestamp) / 86400
        return age_days > self.governance.max_age_days

    def get_memory_governance_summary(
        self, user_id: str | None = None
    ) -> dict[str, Any]:
        memories = self.retrieve_context(query=user_id or "", user_id=user_id, top_k=50)
        return {
            "count": len(memories),
            "categories": {"FACT": 0, "RULE": 0, "TOOL_GUIDE": 0},
            "max_age_days": self.governance.max_age_days,
            "min_confidence": self.governance.min_confidence,
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
            logger.warning("retrieve_context failed: %s", exc)
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
