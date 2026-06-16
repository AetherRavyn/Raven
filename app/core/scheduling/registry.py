"""Schedule dataclass and registry (Day 21).

A :class:`Schedule` pairs a :class:`Trigger` with a
``routine_id`` (looked up in the :class:`RoutineRegistry`).
The :class:`ScheduleRegistry` is a thread-safe in-memory
store of schedules with a JSON-friendly dict format.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.scheduling.trigger import Trigger


@dataclass(slots=True)
class Schedule:
    """A registered (trigger, routine) pair.

    Attributes
    ----------
    id:
        Unique schedule id.  Auto-generated when not supplied.
    user_id:
        Optional scoping: when set, the schedule only fires
        for that user.  Empty string = global.
    routine_id:
        Key into the :class:`RoutineRegistry`.
    trigger:
        The trigger primitive that decides firing.
    args:
        Positional arguments to pass to the routine.
    kwargs:
        Keyword arguments to pass to the routine.
    enabled:
        When False, the schedule is skipped on every tick.
    last_fired_at:
        Updated by the scheduler after each fire.
    fire_count:
        Total number of times this schedule has fired.
    created_at:
        Auto-set at registration time.
    metadata:
        Free-form dict for tags / labels / debug info.
    """

    id: str
    user_id: str
    routine_id: str
    trigger: Trigger
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_fired_at: datetime | None = None
    fire_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches_user(self, user_id: str | None) -> bool:
        """A global schedule (``user_id == ""``) matches any user."""
        if not self.user_id:
            return True
        if user_id is None:
            return False
        return self.user_id == user_id

    def to_dict(self) -> dict[str, Any]:
        """Serialise for logging / persistence.

        Round-trips with :meth:`from_dict` (except the trigger,
        which serialises to a dict of primitives).
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "routine_id": self.routine_id,
            "trigger": self.trigger.to_dict(),
            "args": list(self.args),
            "kwargs": dict(self.kwargs),
            "enabled": self.enabled,
            "last_fired_at": (
                self.last_fired_at.isoformat() if self.last_fired_at else None
            ),
            "fire_count": self.fire_count,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


def make_schedule_id() -> str:
    return f"sched_{uuid.uuid4().hex[:12]}"


class ScheduleRegistry:
    """Thread-safe in-memory store of :class:`Schedule` objects.

    Schedules are keyed by id; the registry also tracks
    per-routine and per-user indexes for fast lookup.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Schedule] = {}
        self._by_routine: dict[str, set[str]] = {}
        self._by_user: dict[str, set[str]] = {}

    def add(self, schedule: Schedule) -> None:
        with self._lock:
            if schedule.id in self._by_id:
                raise ValueError(f"schedule id already exists: {schedule.id!r}")
            self._by_id[schedule.id] = schedule
            self._by_routine.setdefault(schedule.routine_id, set()).add(schedule.id)
            if schedule.user_id:
                self._by_user.setdefault(schedule.user_id, set()).add(schedule.id)
            else:
                # Global schedules (user_id="") match every
                # user.  Tag them on a sentinel key so
                # :meth:`for_user` can include them.
                self._by_user.setdefault("", set()).add(schedule.id)

    def remove(self, schedule_id: str) -> bool:
        with self._lock:
            sched = self._by_id.pop(schedule_id, None)
            if sched is None:
                return False
            self._by_routine.get(sched.routine_id, set()).discard(schedule_id)
            key = sched.user_id or ""
            self._by_user.get(key, set()).discard(schedule_id)
            return True

    def get(self, schedule_id: str) -> Schedule | None:
        with self._lock:
            return self._by_id.get(schedule_id)

    def all(self) -> list[Schedule]:
        with self._lock:
            return list(self._by_id.values())

    def for_routine(self, routine_id: str) -> list[Schedule]:
        with self._lock:
            ids = list(self._by_routine.get(routine_id, set()))
            return [self._by_id[i] for i in ids if i in self._by_id]

    def for_user(self, user_id: str) -> list[Schedule]:
        with self._lock:
            # Per-user schedules + global schedules (user_id="").
            ids = set(self._by_user.get(user_id, set()))
            ids.update(self._by_user.get("", set()))
            return [self._by_id[i] for i in ids if i in self._by_id]

    def enabled(self) -> list[Schedule]:
        with self._lock:
            return [s for s in self._by_id.values() if s.enabled]

    def set_enabled(self, schedule_id: str, enabled: bool) -> bool:
        with self._lock:
            s = self._by_id.get(schedule_id)
            if s is None:
                return False
            s.enabled = enabled
            return True

    def count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._by_routine.clear()
            self._by_user.clear()


__all__ = ["Schedule", "ScheduleRegistry", "make_schedule_id"]
