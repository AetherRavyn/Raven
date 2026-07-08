"""Unified Memory Facade — single entry point for all memory operations.

Ties together the 6+ memory subsystems into one coherent API:

  MemoryFacade
  ├── semantic search  → HelixDB (memory_helix.py)
  ├── knowledge graph  → HelixDB (knowledge_graph_helix.py)
  ├── user profile     → JSON files (user_profile.py)
  ├── life context     → JSON files (life_context.py)
  ├── conversation     → in-memory (conversation/manager.py)
  └── continuity       → HelixDB + SQLite (continuity/)

Usage:
    from app.core.memory_facade import get_memory_facade
    facade = get_memory_facade()
    facade.remember("user prefers dark mode", user_id="swadhin")
    results = facade.recall("what does the user prefer?", user_id="swadhin")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryResult:
    """A single memory retrieval result with provenance."""
    content: str
    source: str  # "semantic", "kg", "profile", "life_context"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryFacade:
    """Unified API for all memory subsystems.

    Provides:
    - remember(content, user_id, category) — store a memory
    - recall(query, user_id, top_k) — retrieve relevant memories
    - build_context(user_id) — build full context for LLM prompt
    - profile(user_id) — get user profile summary
    - graph_query(entity) — query knowledge graph
    """

    def __init__(self) -> None:
        self._semantic_store = None
        self._kg_tool = None
        self._profile_store = None
        self._life_context = None
        self._memory_manager = None

    def _get_semantic(self):
        if self._semantic_store is None:
            from app.core.memory import get_memory_store
            self._semantic_store = get_memory_store()
        return self._semantic_store

    def _get_kg(self):
        if self._kg_tool is None:
            try:
                from app.tools.kgtool import KnowledgeGraphTool
                self._kg_tool = KnowledgeGraphTool()
            except Exception:
                return None
        return self._kg_tool

    def _get_profile(self):
        if self._profile_store is None:
            from app.core.user_profile import UserProfileStore
            self._profile_store = UserProfileStore()
        return self._profile_store

    def _get_life_context(self):
        if self._life_context is None:
            from app.core.life_context import get_life_context_engine
            self._life_context = get_life_context_engine()
        return self._life_context

    def _get_memory_manager(self):
        if self._memory_manager is None:
            from app.core.memory_manager import MemoryManager
            self._memory_manager = MemoryManager()
        return self._memory_manager

    # ── Write ────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        *,
        user_id: str | None = None,
        category: str = "FACT",
    ) -> str:
        """Store a memory in the semantic store.

        Categories: FACT, RULE, TOOL_GUIDE
        Returns the memory ID.
        """
        store = self._get_semantic()
        try:
            mem_id = store.save(category=category, content=content, user_id=user_id)
            # Emit hook event after successful memory storage
            if mem_id:
                try:
                    from app.core.hooks import get_hook_manager
                    hook_mgr = get_hook_manager()
                    hook_mgr.trigger("memory_extracted", {
                        "memory_id": mem_id,
                        "category": category,
                        "user_id": user_id or "anonymous",
                        "content_preview": content[:100],
                    })
                except Exception:
                    pass
            return mem_id
        except Exception as exc:
            logger.warning("remember failed: %s", exc)
            return ""

    def remember_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Store a knowledge graph triple."""
        kg = self._get_kg()
        if kg is None:
            return {"success": False, "error": "KG unavailable"}
        import asyncio
        coro = kg.add_relationship(subject, predicate.upper(), obj, user_id=user_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, coro).result(timeout=30)
            else:
                result = asyncio.run(coro)
            return result
        except Exception as exc:
            logger.warning("remember_triple failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def update_profile(self, user_id: str, **kwargs: Any) -> None:
        """Update user profile fields."""
        profile = self._get_profile().load(user_id)
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._get_profile().save(profile)

    # ── Read ─────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        *,
        user_id: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryResult]:
        """Retrieve relevant memories from the semantic store."""
        store = self._get_semantic()
        try:
            raw = store.retrieve(query=query, top_k=top_k, user_id=user_id)
            return [
                MemoryResult(content=r, source="semantic", confidence=1.0)
                for r in raw
            ]
        except Exception as exc:
            logger.warning("recall failed: %s", exc)
            return []

    def graph_query(self, entity: str) -> dict[str, Any]:
        """Query the knowledge graph for an entity."""
        kg = self._get_kg()
        if kg is None:
            return {"success": False, "error": "KG unavailable"}
        try:
            import asyncio
            # Determine the coroutine to run
            if hasattr(kg, 'execute'):
                coro = kg.execute(operation="query_entity", query=entity)
            elif hasattr(kg, 'query_entity'):
                coro = kg.query_entity(entity)
            else:
                return {"success": False, "error": "KG tool has no query method"}

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result(timeout=30)
            return asyncio.run(coro)
        except Exception as exc:
            logger.warning("graph_query failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def profile(self, user_id: str) -> dict[str, Any]:
        """Get user profile as dict."""
        p = self._get_profile().load(user_id)
        from dataclasses import asdict
        return asdict(p)

    def life_context(self, user_id: str = "default") -> dict[str, Any]:
        """Get life context as dict."""
        ctx = self._get_life_context().get_context(user_id)
        from dataclasses import asdict
        return asdict(ctx)

    # ── Context Builder ──────────────────────────────────────────────

    def build_context(
        self,
        user_id: str,
        *,
        current_topic: str = "",
        max_chars: int = 4000,
    ) -> str:
        """Build a rich context string for LLM prompt injection.

        Combines: semantic memories, user profile, life context.
        """
        parts: list[str] = []

        # 1. Semantic memories
        if current_topic:
            memories = self.recall(current_topic, user_id=user_id, top_k=5)
        else:
            memories = self.recall(
                f"{user_id} recent tasks and preferences",
                user_id=user_id,
                top_k=5,
            )
        if memories:
            mem_lines = [f"- {m.content}" for m in memories]
            parts.append("## Relevant Memories\n" + "\n".join(mem_lines))

        # 2. User profile
        try:
            p = self.profile(user_id)
            if p.get("preferences"):
                parts.append("## Preferences\n" + "\n".join(f"- {x}" for x in p["preferences"][:5]))
            if p.get("facts"):
                parts.append("## Known Facts\n" + "\n".join(f"- {x}" for x in p["facts"][:5]))
        except Exception:
            pass

        # 3. Life context
        try:
            ctx = self.life_context(user_id)
            if ctx.get("current_project"):
                parts.append(f"## Current Project\n{ctx['current_project']}")
            if ctx.get("active_goals"):
                parts.append("## Active Goals\n" + "\n".join(f"- {x}" for x in ctx["active_goals"][:3]))
        except Exception:
            pass

        result = "\n\n".join(parts)
        return result[:max_chars] if len(result) > max_chars else result


_facade: MemoryFacade | None = None


def get_memory_facade() -> MemoryFacade:
    """Return the singleton MemoryFacade."""
    global _facade
    if _facade is None:
        _facade = MemoryFacade()
    return _facade
