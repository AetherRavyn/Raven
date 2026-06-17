"""Phase F2 — Privacy: Inspector.

"What do you know about me?"  The :class:`Inspector` is a
queryable index over the user's stored data.  It groups
items by :class:`DataClass`, supports browsing, editing,
deleting, and pinning (marking an item as "keep forever").

The Inspector is intentionally data-source-agnostic.  Items
are registered via :meth:`Inspector.add` or by wiring a
:func:`DataSource` that yields :class:`DataItem` objects on
demand.  The runtime + memory store + knowledge graph are
expected to register their data on startup.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.privacy.consent import DataClass


# -- data model ---------------------------------------------------------------


@dataclass(slots=True)
class DataItem:
    """One piece of data the agent knows about the user."""

    id: str
    user_id: str
    data_class: DataClass | str
    content: str
    source: str = "memory"  # memory | file | web | tool | graph | user
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.data_class, str):
            self.data_class = DataClass(self.data_class)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "data_class": (
                self.data_class.value if isinstance(self.data_class, DataClass) else self.data_class
            ),
            "content": self.content,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "pinned": self.pinned,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class InspectorQuery:
    """Filter for :meth:`Inspector.query`."""

    user_id: str
    data_class: DataClass | str | None = None
    source: str | None = None
    contains: str | None = None
    pinned_only: bool | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = None

    def matches(self, item: DataItem) -> bool:
        if item.user_id != self.user_id:
            return False
        if self.data_class is not None and item.data_class != self.data_class:
            return False
        if self.source is not None and item.source != self.source:
            return False
        if self.contains is not None and self.contains not in item.content:
            return False
        if self.pinned_only is not None and item.pinned != self.pinned_only:
            return False
        if self.since is not None and item.timestamp < self.since:
            return False
        if self.until is not None and item.timestamp > self.until:
            return False
        return True


# -- data source protocol -----------------------------------------------------

DataSource = Callable[[str], Iterable[DataItem]]
"""A function that yields all items for a user from one backend.

Registered with :meth:`Inspector.add_source`.  The Inspector
deduplicates by :attr:`DataItem.id` across sources.
"""


# -- manager ------------------------------------------------------------------


class Inspector:
    """Browse / edit / delete / pin the user's data."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, DataItem] = {}
        self._sources: dict[str, DataSource] = {}

    # -- source registration --------------------------------------------

    def add_source(self, name: str, source: DataSource) -> None:
        """Register a data source.  Items are pulled lazily on :meth:`refresh`."""
        with self._lock:
            self._sources[name] = source

    def remove_source(self, name: str) -> None:
        with self._lock:
            self._sources.pop(name, None)

    def sources(self) -> list[str]:
        with self._lock:
            return list(self._sources)

    def refresh(self, user_id: str) -> int:
        """Pull fresh items from every source for ``user_id``.

        Returns the number of new items added.  Existing items
        are left alone unless the source no longer yields them
        — those are NOT auto-removed (call :meth:`prune` for that).
        """
        added = 0
        with self._lock:
            for name, source in self._sources.items():
                try:
                    items = list(source(user_id))
                except Exception:  # noqa: BLE001
                    continue
                for item in items:
                    if item.id not in self._items:
                        self._items[item.id] = item
                        added += 1
        return added

    def prune(self, user_id: str) -> int:
        """Remove items for ``user_id`` that no source still yields.

        Returns the number of items removed.
        """
        live: set[str] = set()
        with self._lock:
            for source in self._sources.values():
                try:
                    for item in source(user_id):
                        live.add(item.id)
                except Exception:  # noqa: BLE001
                    continue
            to_remove = [
                iid
                for iid, item in self._items.items()
                if item.user_id == user_id and iid not in live
            ]
            for iid in to_remove:
                self._items.pop(iid, None)
        return len(to_remove)

    # -- direct manipulation --------------------------------------------

    def add(
        self,
        *,
        user_id: str,
        data_class: DataClass | str,
        content: str,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
        pinned: bool = False,
        item_id: str | None = None,
        when: datetime | None = None,
    ) -> DataItem:
        """Register a single item directly (e.g. from a UI form)."""
        item = DataItem(
            id=item_id or uuid.uuid4().hex,
            user_id=user_id,
            data_class=data_class,
            content=content,
            source=source,
            pinned=pinned,
            timestamp=when or datetime.now(timezone.utc),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def get(self, item_id: str) -> DataItem | None:
        with self._lock:
            return self._items.get(item_id)

    def edit(
        self,
        item_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataItem | None:
        """Edit an item's content or metadata.  Returns the updated item."""
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            if content is not None:
                item.content = content
            if metadata is not None:
                item.metadata.update(metadata)
        return item

    def delete(self, item_id: str) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None

    def pin(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return False
            item.pinned = True
            return True

    def unpin(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return False
            item.pinned = False
            return True

    # -- queries ---------------------------------------------------------

    def query(self, q: InspectorQuery) -> list[DataItem]:
        with self._lock:
            items = [i for i in self._items.values() if q.matches(i)]
        items.sort(key=lambda i: i.timestamp, reverse=True)
        if q.limit is not None:
            items = items[: q.limit]
        return items

    def all_for_user(self, user_id: str) -> list[DataItem]:
        with self._lock:
            items = [i for i in self._items.values() if i.user_id == user_id]
        items.sort(key=lambda i: i.timestamp, reverse=True)
        return items

    def by_category(self, user_id: str) -> dict[str, list[DataItem]]:
        """Group a user's items by :class:`DataClass` value."""
        out: dict[str, list[DataItem]] = {}
        for item in self.all_for_user(user_id):
            key = (
                item.data_class.value
                if isinstance(item.data_class, DataClass)
                else str(item.data_class)
            )
            out.setdefault(key, []).append(item)
        return out

    def count(self, user_id: str) -> dict[str, int]:
        """Return per-category counts for ``user_id``."""
        out: dict[str, int] = {}
        for item in self.all_for_user(user_id):
            key = (
                item.data_class.value
                if isinstance(item.data_class, DataClass)
                else str(item.data_class)
            )
            out[key] = out.get(key, 0) + 1
        return out

    # -- lifecycle -------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._sources.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# -- module-level singleton helpers --------------------------------------------


_DEFAULT_INSPECTOR: Inspector | None = None
_LOCK = threading.RLock()


def get_default_inspector() -> Inspector:
    """Return the process-singleton :class:`Inspector`."""
    global _DEFAULT_INSPECTOR
    with _LOCK:
        if _DEFAULT_INSPECTOR is None:
            _DEFAULT_INSPECTOR = Inspector()
        return _DEFAULT_INSPECTOR


def set_default_inspector(inspector: Inspector | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_INSPECTOR
    with _LOCK:
        _DEFAULT_INSPECTOR = inspector


def reset_default_inspector() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_INSPECTOR
    with _LOCK:
        _DEFAULT_INSPECTOR = None


__all__ = [
    "DataItem",
    "DataSource",
    "Inspector",
    "InspectorQuery",
    "get_default_inspector",
    "reset_default_inspector",
    "set_default_inspector",
]
