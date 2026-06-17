"""Phase F1 — Trust & Explainability: Rollback.

Every mutating action the agent performs is registered with
a compensating function (an "undo").  The runtime can then
answer commands like:

  * "undo last action"
  * "undo all from the last hour"
  * "undo all from last turn"

Design
------

* A :class:`RollbackAction` is a record: who did what, when,
  with what arguments, and the function that undoes it.
* The :class:`RollbackRegistry` stores them in insertion order
  (newest first for O(1) "undo last").
* :class:`RollbackManager` is the public facade.  Tools call
  :meth:`record` after a successful mutation; the runtime
  calls :meth:`undo_last` / :meth:`undo_since` / :meth:`undo_all`.

The undo function is a plain :class:`Callable` that returns
anything (usually ``None``, sometimes the restored value).
Failures are captured per-action so one bad undo doesn't
block the rest.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class RollbackStatus(str, Enum):
    """Outcome of an :meth:`RollbackManager.undo_*` call."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class RollbackAction:
    """A registered undo-able action."""

    action_id: str
    tool_name: str
    args: dict[str, Any]
    user_id: str
    undo: Callable[[], Any]
    timestamp: datetime
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    undone: bool = False
    undone_at: datetime | None = None
    undo_result: Any = None
    undo_error: str | None = None
    status: RollbackStatus = RollbackStatus.SUCCESS

    def mark_undone(
        self,
        result: Any = None,
        *,
        error: str | None = None,
        status: RollbackStatus = RollbackStatus.SUCCESS,
    ) -> None:
        self.undone = True
        self.undone_at = datetime.now(timezone.utc)
        self.undo_result = result
        self.undo_error = error
        self.status = status


@dataclass(slots=True, frozen=True)
class RollbackResult:
    """The outcome of a single undo call."""

    action_id: str
    tool_name: str
    status: RollbackStatus
    result: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is RollbackStatus.SUCCESS


class RollbackRegistry:
    """In-memory store of :class:`RollbackAction` records.

    Newest-first ordering.  Bounded by ``maxlen`` to prevent
    unbounded growth in long-running processes.
    """

    def __init__(self, *, maxlen: int = 1000) -> None:
        self._lock = threading.RLock()
        self._maxlen = maxlen
        self._actions: list[RollbackAction] = []

    def add(self, action: RollbackAction) -> None:
        with self._lock:
            self._actions.insert(0, action)  # newest first
            if len(self._actions) > self._maxlen:
                # Drop the oldest entries.
                del self._actions[self._maxlen :]

    def list(
        self,
        *,
        user_id: str | None = None,
        tool_name: str | None = None,
        since: datetime | None = None,
        include_undone: bool = True,
    ) -> list[RollbackAction]:
        """Return actions matching the filters, newest first."""
        with self._lock:
            actions = list(self._actions)
        if user_id is not None:
            actions = [a for a in actions if a.user_id == user_id]
        if tool_name is not None:
            actions = [a for a in actions if a.tool_name == tool_name]
        if since is not None:
            actions = [a for a in actions if a.timestamp >= since]
        if not include_undone:
            actions = [a for a in actions if not a.undone]
        return actions

    def get(self, action_id: str) -> RollbackAction | None:
        with self._lock:
            for a in self._actions:
                if a.action_id == action_id:
                    return a
            return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._actions)

    def clear(self) -> None:
        with self._lock:
            self._actions.clear()


class RollbackManager:
    """Public facade for recording and undoing mutating actions.

    Typical wiring::

        rm = RollbackManager()

        # A tool does a mutation:
        rm.record(
            tool_name="calendar.delete_event",
            args={"event_id": "evt_42"},
            user_id="u1",
            undo=lambda: calendar.restore_event("evt_42"),
            description="Deleted calendar event 'lunch with Alex'",
        )

        # The user says "undo that":
        result = rm.undo_last(user_id="u1")
    """

    def __init__(self, *, registry: RollbackRegistry | None = None) -> None:
        self._lock = threading.RLock()
        self._registry = registry or RollbackRegistry()

    # -- recording -------------------------------------------------------

    def record(
        self,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        user_id: str,
        undo: Callable[[], Any],
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register an undo-able action.  Returns its ``action_id``."""
        action = RollbackAction(
            action_id=uuid.uuid4().hex,
            tool_name=tool_name,
            args=dict(args or {}),
            user_id=user_id,
            undo=undo,
            timestamp=datetime.now(timezone.utc),
            description=description,
            metadata=dict(metadata or {}),
        )
        self._registry.add(action)
        return action.action_id

    # -- undo ------------------------------------------------------------

    def undo_last(
        self,
        *,
        user_id: str | None = None,
        tool_name: str | None = None,
    ) -> RollbackResult | None:
        """Undo the most recent matching action.  Returns ``None`` if none."""
        actions = self._registry.list(
            user_id=user_id,
            tool_name=tool_name,
            include_undone=False,
        )
        if not actions:
            return None
        return self._undo(actions[0])

    def undo_since(
        self,
        since: datetime,
        *,
        user_id: str | None = None,
    ) -> list[RollbackResult]:
        """Undo every action at or after ``since``, newest first."""
        actions = self._registry.list(
            user_id=user_id,
            since=since,
            include_undone=False,
        )
        return [self._undo(a) for a in actions]

    def undo_last_hour(self, *, user_id: str | None = None) -> list[RollbackResult]:
        """Undo every action from the last hour."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        return self.undo_since(cutoff, user_id=user_id)

    def undo_all(self, *, user_id: str | None = None) -> list[RollbackResult]:
        """Undo every registered action, newest first."""
        actions = self._registry.list(user_id=user_id, include_undone=False)
        return [self._undo(a) for a in actions]

    def undo_by_id(self, action_id: str) -> RollbackResult | None:
        """Undo a specific action by id."""
        action = self._registry.get(action_id)
        if action is None or action.undone:
            return None
        return self._undo(action)

    def _undo(self, action: RollbackAction) -> RollbackResult:
        """Run an action's undo function, capturing the outcome."""
        with self._lock:
            try:
                result = action.undo()
            except Exception as exc:  # noqa: BLE001
                action.mark_undone(
                    error=str(exc), status=RollbackStatus.FAILED,
                )
                return RollbackResult(
                    action_id=action.action_id,
                    tool_name=action.tool_name,
                    status=RollbackStatus.FAILED,
                    error=str(exc),
                )
            action.mark_undone(result=result, status=RollbackStatus.SUCCESS)
            return RollbackResult(
                action_id=action.action_id,
                tool_name=action.tool_name,
                status=RollbackStatus.SUCCESS,
                result=result,
            )

    # -- introspection --------------------------------------------------

    def history(
        self,
        *,
        user_id: str | None = None,
        tool_name: str | None = None,
        since: datetime | None = None,
        include_undone: bool = True,
    ) -> list[RollbackAction]:
        """Return the full history (read-only)."""
        return self._registry.list(
            user_id=user_id,
            tool_name=tool_name,
            since=since,
            include_undone=include_undone,
        )

    def __len__(self) -> int:
        return len(self._registry)

    def reset(self) -> None:
        """Drop the registry.  Tests only."""
        self._registry.clear()


# -- module-level singleton helpers ------------------------------------------


_DEFAULT_MANAGER: RollbackManager | None = None
_LOCK = threading.RLock()


def get_default_rollback_manager() -> RollbackManager:
    """Return the process-singleton :class:`RollbackManager`."""
    global _DEFAULT_MANAGER
    with _LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = RollbackManager()
        return _DEFAULT_MANAGER


def set_default_rollback_manager(manager: RollbackManager | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = manager


def reset_default_rollback_manager() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = None


__all__ = [
    "RollbackAction",
    "RollbackManager",
    "RollbackRegistry",
    "RollbackResult",
    "RollbackStatus",
    "get_default_rollback_manager",
    "reset_default_rollback_manager",
    "set_default_rollback_manager",
]
