"""Working Memory — Human-like 7±2 item attention buffer.

Provides a bounded working memory that holds the most relevant items
for the current task. Implements relevance decay and priority-based
eviction, mimicking human cognitive attention constraints.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CAPACITY = 7  # Miller's Law: 7±2


@dataclass
class MemoryItem:
    """A single item in working memory."""

    id: str
    content: str
    category: str = "general"
    relevance: float = 1.0       # 0.0 to 1.0
    importance: float = 0.5      # 0.0 to 1.0 (higher = harder to evict)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_score(self) -> float:
        """Combined score for eviction decisions."""
        recency = max(0.0, 1.0 - (time.time() - self.last_accessed) / 3600)
        return (self.relevance * 0.4) + (self.importance * 0.3) + (recency * 0.3)


class WorkingMemory:
    """Bounded attention buffer with 7±2 items.

    Mimics human working memory constraints:
    - Fixed capacity (default 7)
    - Relevance decay over time
    - Priority-based eviction when full
    - Items can be explicitly focused or dismissed

    Usage:
        wm = WorkingMemory()
        wm.focus(MemoryItem(id="task", content="Deploy v2.0"))
        context = wm.get_context()
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._items: list[MemoryItem] = []
        self._capacity = max(3, min(12, capacity))  # Clamp 3-12
        self._evicted_count = 0

    # ── Core Operations ─────────────────────────────────────────────

    def focus(self, item: MemoryItem) -> MemoryItem | None:
        """Add an item to working memory. Returns evicted item if any.

        If the item already exists (by id), it's refreshed.
        If memory is full, the least relevant item is evicted.
        """
        # Check for existing item — refresh it
        for existing in self._items:
            if existing.id == item.id:
                existing.content = item.content
                existing.relevance = max(existing.relevance, item.relevance)
                existing.last_accessed = time.time()
                existing.access_count += 1
                return None

        evicted: MemoryItem | None = None

        # Evict if at capacity
        if len(self._items) >= self._capacity:
            evicted = self._evict_least_relevant()

        self._items.append(item)
        logger.debug(
            "Focused on '%s' (capacity: %d/%d)",
            item.id, len(self._items), self._capacity,
        )
        return evicted

    def dismiss(self, item_id: str) -> bool:
        """Explicitly remove an item from working memory."""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                self._items.pop(i)
                return True
        return False

    def get(self, item_id: str) -> MemoryItem | None:
        """Retrieve an item by id (also refreshes its access time)."""
        for item in self._items:
            if item.id == item_id:
                item.last_accessed = time.time()
                item.access_count += 1
                return item
        return None

    def contains(self, item_id: str) -> bool:
        return any(item.id == item_id for item in self._items)

    # ── Context Generation ──────────────────────────────────────────

    def get_context(self) -> list[MemoryItem]:
        """Return all items sorted by relevance (highest first)."""
        return sorted(self._items, key=lambda x: -x.effective_score)

    def get_context_text(self) -> str:
        """Return working memory as a text block for prompt injection."""
        items = self.get_context()
        if not items:
            return ""

        lines = ["## Working Memory\n"]
        for item in items:
            relevance_bar = "●" * int(item.relevance * 5) + "○" * (5 - int(item.relevance * 5))
            lines.append(f"- [{item.category}] {item.content} ({relevance_bar})")
        return "\n".join(lines)

    # ── Decay & Maintenance ─────────────────────────────────────────

    def apply_decay(self, decay_rate: float = 0.05) -> int:
        """Reduce relevance scores over time. Returns items removed."""
        removed = 0
        surviving: list[MemoryItem] = []

        for item in self._items:
            item.relevance = max(0.0, item.relevance - decay_rate)
            # Items with very low relevance and importance are dropped
            if item.relevance <= 0.05 and item.importance < 0.3:
                removed += 1
                self._evicted_count += 1
            else:
                surviving.append(item)

        self._items = surviving
        if removed:
            logger.debug("Decay removed %d items from working memory", removed)
        return removed

    def boost(self, item_id: str, amount: float = 0.2) -> bool:
        """Boost an item's relevance (e.g., when referenced again)."""
        for item in self._items:
            if item.id == item_id:
                item.relevance = min(1.0, item.relevance + amount)
                item.last_accessed = time.time()
                item.access_count += 1
                return True
        return False

    # ── Eviction ────────────────────────────────────────────────────

    def _evict_least_relevant(self) -> MemoryItem | None:
        if not self._items:
            return None
        # Find item with lowest effective score
        worst_idx = min(range(len(self._items)), key=lambda i: self._items[i].effective_score)
        evicted = self._items.pop(worst_idx)
        self._evicted_count += 1
        logger.debug("Evicted '%s' from working memory (score: %.2f)", evicted.id, evicted.effective_score)
        return evicted

    # ── Properties ──────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def is_full(self) -> bool:
        return len(self._items) >= self._capacity

    @property
    def evicted_count(self) -> int:
        return self._evicted_count

    def clear(self) -> None:
        """Clear all items from working memory."""
        self._items.clear()

    def get_status(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "capacity": self._capacity,
            "is_full": self.is_full,
            "evicted_total": self._evicted_count,
            "items": [
                {"id": i.id, "category": i.category, "relevance": round(i.relevance, 2)}
                for i in self.get_context()
            ],
        }
