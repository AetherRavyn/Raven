"""Trigger primitives for the flexible scheduler (Day 21).

A :class:`Trigger` decides *when* a schedule should fire.
The scheduler evaluates all triggers on every tick, marks the
ones that fire, and the runtime calls the associated
routine.

Five trigger kinds are supported out of the box:

* :class:`TimeOfDayTrigger` — daily at HH:MM (optionally
  limited to specific weekdays).
* :class:`IntervalTrigger` — every N seconds/minutes/hours.
* :class:`CronTrigger` — full cron expression (minute, hour,
  day-of-month, month, day-of-week).
* :class:`EventTrigger` — fires when an explicit
  :meth:`Scheduler.fire_event` call arrives on the scheduler;
  an optional payload filter narrows the match.
* :class:`OneShotTrigger` — fires at a specific datetime,
  then auto-disables.

All triggers are:

* **Pure** — ``should_fire(now, last_fired_at)`` is a function
  of its arguments only.  No I/O, no side effects.
* **Deterministic** — given the same inputs, the same
  triggers fire.  This is what makes the scheduler
  testable with a fake clock.
* **Idempotent** — re-evaluating twice in a row with the same
  ``last_fired_at`` window returns ``False``.

Custom triggers subclass :class:`Trigger` and implement
:meth:`should_fire` and :meth:`next_fire_after`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class Trigger(ABC):
    """Base class for all schedule triggers."""

    kind: str = "abstract"

    @abstractmethod
    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        """Return True if this trigger wants to fire at ``now``."""

    @abstractmethod
    def next_fire_after(self, now: datetime) -> datetime | None:
        """Earliest future time this trigger *might* fire.

        Returns ``None`` when the trigger has no predictable
        next firing (event-driven, one-shot in the past).
        """

    def to_dict(self) -> dict[str, Any]:
        """Serialise for logging / persistence.

        Reads each dataclass field on the concrete subclass
        (the base :class:`Trigger` itself is not a dataclass,
        but every concrete trigger kind is).
        """
        from dataclasses import fields

        d: dict[str, Any] = {"kind": self.kind}
        # `type(self)` is `type[Trigger]`, but the concrete
        # subclass is always a dataclass.  Silence pyright's
        # "type[Self] is not dataclass" check.
        cls = type(self)
        for f in fields(cls):  # type: ignore[arg-type]
            v = getattr(self, f.name)
            if isinstance(v, timezone):
                d[f.name] = v.tzname(None) or str(v)
            else:
                d[f.name] = v
        return d

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.to_dict()})"


# ---------------------------------------------------------------------------
# Time-of-day: daily at HH:MM, optionally limited to weekdays
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TimeOfDayTrigger(Trigger):
    """Fire every day (or specific weekdays) at a fixed time."""

    kind: str = "time_of_day"
    hour: int = 0
    minute: int = 0
    # 0=Mon … 6=Sun, Python's ``weekday()`` convention.
    # Empty tuple → every day.
    weekdays: tuple[int, ...] = field(default_factory=tuple)
    # Optional timezone for evaluation.  None = use ``now`` as-is.
    tz: timezone | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.hour < 24):
            raise ValueError(f"hour must be 0..23, got {self.hour!r}")
        if not (0 <= self.minute < 60):
            raise ValueError(f"minute must be 0..59, got {self.minute!r}")
        for wd in self.weekdays:
            if not (0 <= wd <= 6):
                raise ValueError(f"weekday must be 0..6, got {wd!r}")

    def _local_now(self, now: datetime) -> datetime:
        if self.tz is None:
            return now
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        local = self._local_now(now)
        if local.hour != self.hour or local.minute != self.minute:
            return False
        if self.weekdays and local.weekday() not in self.weekdays:
            return False
        if last_fired_at is not None:
            last_local = self._local_now(last_fired_at)
            if (
                last_local.year == local.year
                and last_local.month == local.month
                and last_local.day == local.day
                and last_local.hour == local.hour
                and last_local.minute == local.minute
            ):
                return False
        return True

    def next_fire_after(self, now: datetime) -> datetime | None:
        local = self._local_now(now)
        candidate = local.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0
        )
        if candidate <= local:
            candidate = candidate + timedelta(days=1)
        if self.weekdays:
            while candidate.weekday() not in self.weekdays:
                candidate = candidate + timedelta(days=1)
        if self.tz is not None:
            return candidate.astimezone(timezone.utc)
        return candidate


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IntervalTrigger(Trigger):
    """Fire every ``every`` timedelta."""

    kind: str = "interval"
    every: timedelta = field(default_factory=lambda: timedelta(hours=1))
    # Anchor for the cadence — first fire is anchor + every
    # (anchor defaults to ``now`` at registration time).
    anchor: datetime | None = None
    # When True, fire on every tick where enough time has
    # passed since the last fire (catch up missed ticks).
    # When False, fire only at exact every-boundaries.
    catch_up: bool = True

    def __post_init__(self) -> None:
        if self.every.total_seconds() <= 0:
            raise ValueError(f"every must be positive, got {self.every!r}")

    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        if last_fired_at is None:
            # Wait for the first interval to elapse.
            if self.anchor is None:
                return False
            return now >= self.anchor + self.every
        return now - last_fired_at >= self.every

    def next_fire_after(self, now: datetime) -> datetime | None:
        anchor = self.anchor or now
        target = anchor
        while target <= now:
            target = target + self.every
        return target


# ---------------------------------------------------------------------------
# Cron (5-field: minute hour day-of-month month day-of-week)
# ---------------------------------------------------------------------------

_CRON_FIELDS = ("minute", "hour", "day", "month", "weekday")
_CRON_BOUNDS = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 6),
}

# Day-of-week names (3-letter, like cron; also accept full names).
_DOW_NAMES = {
    "sun": 6, "sunday": 6,
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
}


def _parse_cron_field(spec: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field into the set of allowed values."""
    allowed: set[int] = set()
    for piece in spec.split(","):
        step = 1
        if "/" in piece:
            base, step_s = piece.split("/", 1)
            step = int(step_s)
        else:
            base = piece
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            start_s, end_s = base.split("-", 1)
            start, end = _cron_value(start_s, lo, hi), _cron_value(end_s, lo, hi)
        else:
            start = end = _cron_value(base, lo, hi)
        for v in range(start, end + 1, step):
            if lo <= v <= hi:
                allowed.add(v)
    return allowed


def _cron_value(token: str, lo: int, hi: int) -> int:
    """Resolve a single cron token (number or DOW name) to int."""
    lower = token.strip().lower()
    if lower in _DOW_NAMES and hi <= 6:
        return _DOW_NAMES[lower]
    return int(lower)


def _parse_cron_expression(expr: str) -> list[set[int]]:
    """Parse a 5-field cron expression into per-field allowed sets."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {expr!r}")
    out: list[set[int]] = []
    for i, field_name in enumerate(_CRON_FIELDS):
        lo, hi = _CRON_BOUNDS[field_name]
        out.append(_parse_cron_field(parts[i], lo, hi))
    return out


@dataclass(slots=True)
class CronTrigger(Trigger):
    """Fire on a 5-field cron expression.

    Field order: ``minute hour day-of-month month day-of-week``.
    Each field accepts ``*``, exact values (``5``), ranges
    (``1-5``), steps (``*/15``), and lists (``1,3,5``).
    """

    kind: str = "cron"
    expression: str = "0 0 * * *"
    tz: timezone | None = None

    def __post_init__(self) -> None:
        self._allowed: list[set[int]] = _parse_cron_expression(self.expression)

    def _local_now(self, now: datetime) -> datetime:
        if self.tz is None:
            return now
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        local = self._local_now(now)
        if local.minute not in self._allowed[0]:
            return False
        if local.hour not in self._allowed[1]:
            return False
        if local.day not in self._allowed[2]:
            return False
        if local.month not in self._allowed[3]:
            return False
        if local.weekday() not in self._allowed[4]:
            return False
        if last_fired_at is not None:
            last_local = self._local_now(last_fired_at)
            if last_local == local:
                return False
        return True

    def next_fire_after(self, now: datetime) -> datetime | None:
        local = self._local_now(now)
        candidate = local.replace(second=0, microsecond=0)
        if candidate <= local:
            candidate = candidate + timedelta(minutes=1)
        for _ in range(60 * 24 * 8):
            if (
                candidate.minute in self._allowed[0]
                and candidate.hour in self._allowed[1]
                and candidate.day in self._allowed[2]
                and candidate.month in self._allowed[3]
                and candidate.weekday() in self._allowed[4]
            ):
                if self.tz is None:
                    return candidate
                return candidate.astimezone(timezone.utc)
            candidate = candidate + timedelta(minutes=1)
        return None


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EventTrigger(Trigger):
    """Fire when an event with a matching name is fired.

    Use :meth:`Scheduler.fire_event` to push events.  The
    scheduler consults ``pending_events`` directly on each
    tick — :meth:`should_fire` is unused for event triggers.
    """

    kind: str = "event"
    event_name: str = ""
    # Optional payload filter; only events whose payload dict
    # is a superset of this filter match.
    payload_filter: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_name:
            raise ValueError("event_name must be non-empty")

    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        # The scheduler drives event matching from its own
        # queue.  This method is intentionally a no-op so a
        # stray tick call doesn't accidentally fire an event.
        return False

    def matches(self, event_name: str, payload: Mapping[str, Any]) -> bool:
        if event_name != self.event_name:
            return False
        if not self.payload_filter:
            return True
        return all(payload.get(k) == v for k, v in self.payload_filter.items())

    def next_fire_after(self, now: datetime) -> datetime | None:
        return None


# ---------------------------------------------------------------------------
# One-shot
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OneShotTrigger(Trigger):
    """Fire once at a specific datetime, then auto-disable."""

    kind: str = "one_shot"
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.run_at.tzinfo is None:
            self.run_at = self.run_at.replace(tzinfo=timezone.utc)

    def should_fire(
        self,
        now: datetime,
        last_fired_at: datetime | None,
    ) -> bool:
        if last_fired_at is not None:
            return False  # already fired
        return now >= self.run_at

    def next_fire_after(self, now: datetime) -> datetime | None:
        if self.run_at > now:
            return self.run_at
        return None


__all__ = [
    "Trigger",
    "TimeOfDayTrigger",
    "IntervalTrigger",
    "CronTrigger",
    "EventTrigger",
    "OneShotTrigger",
]
