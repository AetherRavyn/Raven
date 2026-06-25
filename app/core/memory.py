# app/core/memory.py
"""Persistent semantic memory store — HelixDB + SQLite only.

Singleton — call get_memory_store() to get the single shared instance.

Usage:
    store = get_memory_store()
    store.save("FACT", "User's laptop IP is 192.168.1.5", user_id="123")
    snippets = store.retrieve("what is the user's laptop IP", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

MemoryCategory = Literal["FACT", "RULE", "TOOL_GUIDE"]

_HELIX_INSTANCE: Any = None


def get_memory_store() -> Any:
    """Return the HelixDB memory backend.

    MEMORY_BACKEND=helix → HelixDB HelixMemoryStore
    """
    global _HELIX_INSTANCE
    if _HELIX_INSTANCE is None:
        from app.db.memory_helix import HelixMemoryStore

        _HELIX_INSTANCE = HelixMemoryStore()
    return _HELIX_INSTANCE
