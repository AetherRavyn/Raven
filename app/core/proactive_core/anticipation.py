"""Anticipation engine — predict what the user needs next.

The engine is a thin layer over the per-user :class:`Habit`
records.  It supports three pattern types:

* **Time-of-day** — "user checks email at 9am" → fire a forecast
  signal 5 minutes before the historical mean.
* **Day-of-week** — "user does deep work on Saturdays" → fire a
  signal at the start of the window.
* **Sequence** — "user reads X then Y" → after detecting X, fire
  a signal hinting at Y.

Patterns are *learned* from :class:`Habit` records.  The simplest
way to populate them is the explicit :meth:`HabitTracker.record`
API; an LLM-powered extractor can fill the same store.

The engine exposes a single :func:`generate_signals` helper that
turns (commitments, anomalies, predictions) into
:class:`ProactiveSignal` objects ready to feed into the engine.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PatternKind(str, Enum):
    """What kind of pattern we detected."""

    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    SEQUENCE = "sequence"


@dataclass(slots=True)
class Habit:
    """A single learned (or seeded) user habit."""

    id: str
    user_id: str
    name: str  # "check email", "morning workout", "review PRs"
    kind: PatternKind
    # For TIME_OF_DAY: the historical mean trigger hour (0-23)
    # and minute (0-59).  For DAY_OF_WEEK: the dominant day
    # (0=Mon..6=Sun).  For SEQUENCE: the previous habit name.
    trigger_hour: int | None = None
    trigger_minute: int | None = None
    trigger_day: int | None = None
    sequence_after: str | None = None
    # Number of times we've seen this habit fire — supports
    # the PLAN_v3.md "min support: 3 occurrences" rule.
    occurrences: int = 0
    # Most recent fire time.
    last_seen: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def trigger_time(self) -> time | None:
        if self.trigger_hour is None or self.trigger_minute is None:
            return None
        return time(self.trigger_hour, self.trigger_minute)


class HabitStore(Protocol):
    def add(self, habit: Habit) -> None:  # pragma: no cover
        ...

    def list(
        self, user_id: str, kind: PatternKind | None = None
    ) -> list[Habit]:  # pragma: no cover
        ...

    def by_name(self, user_id: str, name: str) -> Habit | None:  # pragma: no cover
        ...


class InMemoryHabitStore:
    """Default :class:`HabitStore` for tests and single-process use."""

    def __init__(self) -> None:
        self._items: list[Habit] = []

    def add(self, habit: Habit) -> None:
        # De-dup by (user_id, name, kind).
        for i, existing in enumerate(self._items):
            if (
                existing.user_id == habit.user_id
                and existing.name == habit.name
                and existing.kind == habit.kind
            ):
                self._items[i] = habit
                return
        self._items.append(habit)

    def list(self, user_id: str, kind: PatternKind | None = None) -> list[Habit]:
        return [h for h in self._items if h.user_id == user_id and (kind is None or h.kind == kind)]

    def by_name(self, user_id: str, name: str) -> Habit | None:
        for h in self._items:
            if h.user_id == user_id and h.name == name:
                return h
        return None


@dataclass(slots=True)
class HabitTracker:
    """High-level API for recording habits.

    Callers (a scheduler, an LLM extractor, a UI button) call
    :meth:`record_fire` each time they see the user perform a
    habit; the tracker updates the rolling average trigger time
    and the occurrence count.
    """

    store: HabitStore = field(default_factory=InMemoryHabitStore)
    # A habit with fewer than this many observations is
    # considered noise and is not eligible for prediction.
    min_support: int = 3

    def record_fire(
        self,
        user_id: str,
        name: str,
        when: datetime | None = None,
        *,
        kind: PatternKind = PatternKind.TIME_OF_DAY,
        sequence_after: str | None = None,
    ) -> Habit:
        moment = when or datetime.now(timezone.utc)
        existing = self.store.by_name(user_id, name)
        if existing is None:
            existing = Habit(
                id=f"hab-{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                name=name,
                kind=kind,
                trigger_hour=moment.hour,
                trigger_minute=moment.minute,
                trigger_day=moment.weekday(),
                sequence_after=sequence_after,
                occurrences=0,
            )
        # Rolling average of trigger time.
        if existing.trigger_hour is not None and existing.trigger_minute is not None:
            n = existing.occurrences
            old_minutes = existing.trigger_hour * 60 + existing.trigger_minute
            new_minutes = moment.hour * 60 + moment.minute
            avg = (old_minutes * n + new_minutes) / (n + 1)
            existing.trigger_hour = int(avg) // 60
            existing.trigger_minute = int(avg) % 60
        existing.occurrences += 1
        existing.last_seen = moment
        if kind == PatternKind.DAY_OF_WEEK:
            existing.trigger_day = moment.weekday()
        if kind == PatternKind.SEQUENCE and sequence_after is not None:
            existing.sequence_after = sequence_after
        self.store.add(existing)
        return existing

    def eligible(self, user_id: str) -> list[Habit]:
        return [h for h in self.store.list(user_id) if h.occurrences >= self.min_support]


@dataclass(slots=True)
class Prediction:
    """A single predicted next action."""

    habit: Habit
    predicted_for: datetime
    confidence: float
    lead_time_s: float


class AnticipationEngine:
    """Compute predictions from a user's habits."""

    def __init__(
        self,
        tracker: HabitTracker | None = None,
        *,
        # How long before the predicted trigger to fire the
        # forecast signal.
        lead_time_s: float = 300.0,
    ) -> None:
        self._tracker = tracker or HabitTracker()
        self._lead_time_s = lead_time_s

    @property
    def tracker(self) -> HabitTracker:
        return self._tracker

    def predict_for_user(self, user_id: str, now: datetime | None = None) -> list[Prediction]:
        moment = now or datetime.now(timezone.utc)
        out: list[Prediction] = []
        for h in self._tracker.eligible(user_id):
            if (
                h.kind == PatternKind.TIME_OF_DAY
                and h.trigger_hour is not None
                and h.trigger_minute is not None
            ):
                predicted = moment.replace(
                    hour=h.trigger_hour,
                    minute=h.trigger_minute,
                    second=0,
                    microsecond=0,
                )
                if predicted <= moment:
                    predicted = predicted + timedelta(days=1)
                out.append(self._build_prediction(h, predicted, moment))
            elif h.kind == PatternKind.DAY_OF_WEEK and h.trigger_day is not None:
                days_ahead = (h.trigger_day - moment.weekday()) % 7
                predicted = (moment + timedelta(days=days_ahead)).replace(
                    hour=h.trigger_hour or 9,
                    minute=h.trigger_minute or 0,
                    second=0,
                    microsecond=0,
                )
                if predicted <= moment:
                    predicted = predicted + timedelta(days=7)
                out.append(self._build_prediction(h, predicted, moment))
        out.sort(key=lambda p: p.predicted_for)
        return out

    def _build_prediction(self, habit: Habit, predicted_for: datetime, now: datetime) -> Prediction:
        # Confidence grows with occurrences, asymptoting at 0.95.
        confidence = min(0.95, 0.5 + 0.1 * habit.occurrences)
        return Prediction(
            habit=habit,
            predicted_for=predicted_for,
            confidence=confidence,
            lead_time_s=self._lead_time_s,
        )


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


def habit_to_signal(habit: Habit, predicted_for: datetime) -> Any:
    """Convert a habit + predicted time into a :class:`ProactiveSignal`."""
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
    )

    minutes_until = int((predicted_for - datetime.now(timezone.utc)).total_seconds() / 60)
    return ProactiveSignal(
        id=f"habit:{habit.id}:{predicted_for.isoformat()}",
        user_id=habit.user_id,
        kind=SignalKind.FORECAST,
        title=f"Upcoming: {habit.name}",
        body=(
            f"Based on your pattern, {habit.name} is due in "
            f"~{max(0, minutes_until)} min. Pre-fetching context."
        ),
        urgency=Urgency.LOW,
        value=0.55,
        confidence=0.7,
        source="anticipation_engine",
        metadata={
            "target_id": f"{habit.id}:{predicted_for.isoformat()}",
            "habit_id": habit.id,
            "habit_name": habit.name,
        },
    )


def commitment_to_signal(c: Any) -> Any:
    """Convert a :class:`Commitment` into a :class:`ProactiveSignal`."""
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
    )
    from app.core.proactive_core.follow_up import (
        CommitmentKind,
        CommitmentStatus,
    )

    if c.status not in {
        CommitmentStatus.PENDING,
        CommitmentStatus.SNOOZED,
    }:
        return None
    overdue = c.is_overdue()
    urgency = (
        Urgency.HIGH
        if overdue
        else Urgency.NORMAL
        if c.due_at is not None and (c.due_at - datetime.now(timezone.utc)).total_seconds() < 3600
        else Urgency.LOW
    )
    title_map = {
        CommitmentKind.REMINDER: "Reminder",
        CommitmentKind.PROMISE: "Promise to self",
        CommitmentKind.DEADLINE: "Deadline",
        CommitmentKind.FOLLOW_UP: "Follow-up",
    }
    return ProactiveSignal(
        id=f"commitment:{c.id}",
        user_id=c.user_id,
        kind=SignalKind.FOLLOW_UP,
        title=title_map.get(c.kind, "Follow-up"),
        body=c.text,
        urgency=urgency,
        value=0.8 if overdue else 0.65,
        confidence=0.9,
        source="follow_up_tracker",
        metadata={
            "target_id": c.id,
            "kind": c.kind.value,
            "due_at": c.due_at.isoformat() if c.due_at else None,
        },
    )


def generate_signals(
    *,
    user_id: str,
    follow_up: Any,
    anomalies: Iterable[Any],
    anticipation: AnticipationEngine,
    now: datetime | None = None,
    # How far ahead to surface forecast / deadline signals.
    lead_time_s: float = 900.0,
) -> list[Any]:
    """Build a deduplicated list of proactive signals from all sources.

    The caller is expected to dispatch each signal through the
    proactive engine.  This function is a pure builder: no
    side effects, no I/O.
    """
    from app.core.proactive_core import ProactiveSignal

    moment = now or datetime.now(timezone.utc)
    signals: list[ProactiveSignal] = []

    # 1) Follow-ups
    due_soon = follow_up.list_due_soon(user_id, lead_time_s, moment)
    for c in due_soon:
        s = commitment_to_signal(c)
        if s is not None:
            signals.append(s)
    for c in follow_up.list_overdue(user_id, moment):
        s = commitment_to_signal(c)
        if s is not None:
            signals.append(s)

    # 2) Anomalies
    for a in anomalies:
        signals.append(_anomaly_to_signal(a))

    # 3) Predictions (only those within the lead time)
    for p in anticipation.predict_for_user(user_id, moment):
        if (p.predicted_for - moment).total_seconds() <= lead_time_s:
            signals.append(habit_to_signal(p.habit, p.predicted_for))

    # Dedupe by signal id; keep the first occurrence.
    seen: set[str] = set()
    unique: list[ProactiveSignal] = []
    for s in signals:
        if s.id in seen:
            continue
        seen.add(s.id)
        unique.append(s)
    return unique


def _anomaly_to_signal(anomaly: Any) -> Any:
    """Forward to the helper in :mod:`anomaly` to avoid a cycle."""
    from app.core.proactive_core.anomaly import anomaly_to_signal

    return anomaly_to_signal(anomaly)
