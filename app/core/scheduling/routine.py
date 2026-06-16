"""Routine registry (Day 21).

A :class:`Routine` is an async callable that the scheduler
fires when a :class:`Schedule` triggers.  The
:class:`RoutineRegistry` maps ``routine_id`` → :class:`Routine`
and is injected into the :class:`Scheduler` at construction
time.  Schedules can be migrated off the legacy
``scheduler._scheduler`` (APScheduler) by registering the
routine here and adding a schedule.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# A routine is an async callable that takes
# (user_id, *args, triggered_at, **kwargs) and returns None.
RoutineFn = Callable[..., Awaitable[None]]


@dataclass(slots=True)
class Routine:
    """A registered async routine the scheduler can fire.

    Attributes
    ----------
    id:
        Unique key — matches ``Schedule.routine_id``.
    name:
        Human-readable name for logs.
    fn:
        The async callable.  Receives
        ``(user_id, *args, triggered_at, **kwargs)``.
    kind:
        Free-form category (e.g. ``"morning_briefing"``,
        ``"evening_review"``).  Used for audit / metrics.
    """

    id: str
    name: str
    fn: RoutineFn
    kind: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


class RoutineRegistry:
    """Thread-safe registry of :class:`Routine` objects."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Routine] = {}

    def register(self, routine: Routine) -> None:
        with self._lock:
            if routine.id in self._by_id:
                raise ValueError(f"routine id already exists: {routine.id!r}")
            self._by_id[routine.id] = routine
            logger.debug("routine registered: id=%s name=%s kind=%s", routine.id, routine.name, routine.kind)

    def register_fn(
        self,
        id: str,
        fn: RoutineFn,
        *,
        name: str | None = None,
        kind: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> Routine:
        """Convenience: register a callable directly."""
        routine = Routine(
            id=id,
            name=name or id,
            fn=fn,
            kind=kind,
            metadata=metadata or {},
        )
        self.register(routine)
        return routine

    def unregister(self, id: str) -> bool:
        with self._lock:
            return self._by_id.pop(id, None) is not None

    def get(self, id: str) -> Routine | None:
        with self._lock:
            return self._by_id.get(id)

    def all(self) -> list[Routine]:
        with self._lock:
            return list(self._by_id.values())

    def count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()


__all__ = ["Routine", "RoutineRegistry", "RoutineFn"]
