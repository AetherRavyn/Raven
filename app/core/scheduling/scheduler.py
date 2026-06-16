"""Scheduler facade (Day 21).

A :class:`Scheduler` ties everything together:

* :class:`ScheduleRegistry` — schedules (trigger + routine id)
* :class:`RoutineRegistry` — async callables to fire
* A pluggable **clock** for deterministic time
* A pluggable **fire callback** so the runtime can run
  routines in its own loop / thread

The two main entry points are:

* :meth:`tick` — evaluate every schedule and return what
  fired.  Pure: no async, no side effects, easy to test.
* :meth:`run_forever` — async loop that calls ``tick`` on a
  fixed interval and fires routines via the callback.

The scheduler also exposes :meth:`fire_event` for
event-driven schedules — push an event and any matching
``EventTrigger`` schedules will fire on the next tick.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.scheduling.registry import Schedule, ScheduleRegistry, make_schedule_id
from app.core.scheduling.routine import RoutineRegistry
from app.core.scheduling.trigger import (
    EventTrigger,
    OneShotTrigger,
    Trigger,
)

logger = logging.getLogger(__name__)

# Callback signatures.
FireCallback = Callable[[Schedule, datetime], Awaitable[None]]
ClockFn = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class FiredSchedule:
    """Record of one schedule firing on a tick."""

    schedule: Schedule
    triggered_at: datetime

    @property
    def routine_id(self) -> str:
        return self.schedule.routine_id

    @property
    def user_id(self) -> str:
        return self.schedule.user_id


@dataclass(slots=True)
class Scheduler:
    """In-process scheduler with pluggable clock + fire callback.

    Schedules are evaluated on every :meth:`tick`.  When a
    trigger fires, the scheduler:

    1. Records :attr:`Schedule.last_fired_at` and increments
       :attr:`Schedule.fire_count`.
    2. Auto-disables one-shot triggers.
    3. Returns a :class:`FiredSchedule` for the caller to act
       on (or, when running with a fire callback, awaits the
       callback inline).

    Thread-safe: every public method holds the registry lock.
    """

    schedule_registry: ScheduleRegistry = field(default_factory=ScheduleRegistry)
    routine_registry: RoutineRegistry = field(default_factory=RoutineRegistry)
    # Pluggable clock for tests.
    clock: ClockFn = field(default=_default_clock)
    # Pluggable fire callback.  When None, :meth:`tick` only
    # returns the fired list and the caller must act.
    fire_callback: FireCallback | None = None
    # Pending event-driven fires: (event_name, payload) tuples
    # that arrived via :meth:`fire_event` and haven't been
    # consumed by a tick yet.
    pending_events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Whether event triggers should fire at most once per event
    # arrival (True, default) or every tick that finds the
    # event in the queue (False).
    consume_event_on_fire: bool = True
    # Optional router that receives :class:`Signal` objects
    # produced by routines.  When a routine's fire callable
    # returns a ``list[Signal]`` and this is set, the default
    # :meth:`fire` publishes them through the router in
    # addition to the routine's side-effects.
    signal_router: Any = None
    # Optional per-user dedupe cache shared by watcher routines.
    dedupe_cache: Any = None

    # ---- public lifecycle ----

    def add(
        self,
        routine_id: str,
        trigger: Trigger,
        *,
        user_id: str = "",
        schedule_id: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> Schedule:
        """Register a new schedule."""
        sched = Schedule(
            id=schedule_id or make_schedule_id(),
            user_id=user_id,
            routine_id=routine_id,
            trigger=trigger,
            args=tuple(args),
            kwargs=dict(kwargs or {}),
            enabled=enabled,
            metadata=dict(metadata or {}),
        )
        self.schedule_registry.add(sched)
        logger.debug(
            "schedule added: id=%s routine=%s user=%s trigger=%s",
            sched.id,
            routine_id,
            user_id or "*",
            trigger.kind,
        )
        return sched

    def remove(self, schedule_id: str) -> bool:
        return self.schedule_registry.remove(schedule_id)

    def enable(self, schedule_id: str) -> bool:
        return self.schedule_registry.set_enabled(schedule_id, True)

    def disable(self, schedule_id: str) -> bool:
        return self.schedule_registry.set_enabled(schedule_id, False)

    # ---- event-driven ----

    def fire_event(self, event_name: str, payload: dict[str, Any] | None = None) -> int:
        """Push an event onto the pending queue.

        Returns the number of pending events (including the
        one just added).  The next :meth:`tick` will match
        against any :class:`EventTrigger` schedules.
        """
        self.pending_events.append((event_name, dict(payload or {})))
        return len(self.pending_events)

    def drain_events(self) -> list[tuple[str, dict[str, Any]]]:
        """Remove and return all pending events."""
        out = self.pending_events
        self.pending_events = []
        return out

    # ---- core: tick ----

    def tick(self, now: datetime | None = None) -> list[FiredSchedule]:
        """Evaluate every enabled schedule against ``now``.

        Pure: no async, no I/O.  Returns the list of
        :class:`FiredSchedule` that fired on this tick.
        """
        if now is None:
            now = self.clock()
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        fired: list[FiredSchedule] = []
        events_to_consume: set[int] = set()

        for sched in self.schedule_registry.enabled():
            try:
                if isinstance(sched.trigger, EventTrigger):
                    matched_idx: int | None = None
                    for idx, (name, payload) in enumerate(self.pending_events):
                        if sched.trigger.matches(name, payload):
                            matched_idx = idx
                            break
                    if matched_idx is None:
                        continue
                    if self.consume_event_on_fire:
                        events_to_consume.add(matched_idx)
                    fired.append(self._record_fire(sched, now))
                elif sched.trigger.should_fire(now, sched.last_fired_at):
                    fired.append(self._record_fire(sched, now))
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "scheduler tick: schedule %s raised %s", sched.id, e
                )

        # Consume events that were matched.
        if events_to_consume:
            new_pending: list[tuple[str, dict[str, Any]]] = []
            for idx, ev in enumerate(self.pending_events):
                if idx not in events_to_consume:
                    new_pending.append(ev)
            self.pending_events = new_pending

        return fired

    def _record_fire(self, sched: Schedule, now: datetime) -> FiredSchedule:
        sched.last_fired_at = now
        sched.fire_count += 1
        if isinstance(sched.trigger, OneShotTrigger):
            sched.enabled = False
        return FiredSchedule(schedule=sched, triggered_at=now)

    # ---- async loop ----

    async def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Run the scheduler loop until ``stop`` is set.

        On each iteration, calls :meth:`tick` and invokes the
        fire callback for every fired schedule.  Exceptions
        in the callback are logged but do not stop the loop.
        """
        while True:
            fired = self.tick()
            for fs in fired:
                if self.fire_callback is None:
                    logger.debug(
                        "schedule fired: id=%s routine=%s (no callback set)",
                        fs.schedule.id,
                        fs.routine_id,
                    )
                    continue
                try:
                    await self.fire_callback(fs.schedule, fs.triggered_at)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "fire callback failed for schedule %s: %s",
                        fs.schedule.id,
                        e,
                    )
            if stop is not None and stop.is_set():
                return
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                return

    async def fire(self, schedule: Schedule, triggered_at: datetime) -> None:
        """Default fire callback: look up the routine and call it.

        The runtime can either:
        * install a custom ``fire_callback`` on the scheduler, or
        * iterate over :meth:`tick` results and call :meth:`fire`
          itself.

        If the routine returns a ``list[Signal]`` and the
        scheduler was constructed with a :attr:`signal_router`,
        the signals are published through the router in
        addition to the routine's own side-effects.  This lets
        watcher-style routines (``calendar_watcher``,
        ``internet_watcher``, ``autonomy_worker``) emit typed
        events without knowing how they're delivered.
        """
        routine = self.routine_registry.get(schedule.routine_id)
        if routine is None:
            logger.debug(
                "fire: routine not found: %s (schedule %s)",
                schedule.routine_id,
                schedule.id,
            )
            return
        try:
            result = await routine.fn(
                schedule.user_id,
                *schedule.args,
                triggered_at=triggered_at,
                **schedule.kwargs,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "routine %s raised %s", schedule.routine_id, e
            )
            return

        if self.signal_router is not None and result:
            await self._publish_routine_signals(result)

    async def _publish_routine_signals(self, result: Any) -> None:
        """Best-effort publish of a routine's return value as Signals.

        Accepts:
        * ``list[Signal]`` — published as-is
        * a single :class:`Signal` — published alone
        * anything else — silently ignored

        Per-signal errors are caught and logged so a broken
        subscriber can't take down the routine's outcome.
        """
        from app.core.scheduling.signal import Signal

        if isinstance(result, Signal):
            signals: list[Signal] = [result]
        elif isinstance(result, list) and all(
            isinstance(x, Signal) for x in result
        ):
            signals = result
        else:
            return

        for sig in signals:
            try:
                await self.signal_router.publish(sig)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "signal_router.publish failed for %s: %s", sig.id, exc
                )

    # ---- diagnostics ----

    def explain(self) -> dict[str, Any]:
        """Return a snapshot for logs / dashboards."""
        schedules = [s.to_dict() for s in self.schedule_registry.all()]
        routines = [
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind,
            }
            for r in self.routine_registry.all()
        ]
        return {
            "schedules": schedules,
            "routines": routines,
            "pending_events": list(self.pending_events),
        }


__all__ = [
    "Scheduler",
    "FiredSchedule",
    "FireCallback",
    "ClockFn",
    "get_default_scheduler",
    "set_default_scheduler",
    "reset_default_scheduler",
]


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_DEFAULT: Scheduler | None = None


def get_default_scheduler() -> Scheduler:
    """Return the process-singleton :class:`Scheduler`.

    Built lazily on first call.  Tests should call
    :func:`reset_default_scheduler` between cases.
    """
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = Scheduler()
        return _DEFAULT


def set_default_scheduler(scheduler: Scheduler | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear it.

    The runtime / bootstrap wires this in.  Tests use it to
    inject a custom scheduler (e.g. with a fixed clock).
    """
    global _DEFAULT
    with _LOCK:
        _DEFAULT = scheduler


def reset_default_scheduler() -> None:
    """Drop the singleton.  Next :func:`get_default_scheduler`
    call will build a fresh one."""
    global _DEFAULT
    with _LOCK:
        _DEFAULT = None
