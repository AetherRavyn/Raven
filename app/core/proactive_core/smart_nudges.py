"""Smart nudges — high-value signal generators for common events.

Each helper is a pure function: it takes typed inputs and returns
a :class:`ProactiveSignal` (or ``None`` if no nudge is warranted).
No I/O, no state — easy to test, easy to call from any routine.

The four built-in generators cover the most common "the user
should know about this now" cases from PLAN_v3.md:

* **calendar prep** — "your meeting starts in 5 min, here's the
  context you need"
* **weather** — "leave 10 min early, rain in 30"
* **task priority** — "you have 5 open tasks, this one's overdue"
* **email urgency** — "important email arrived, X waiting"

The helpers are intentionally conservative: a high confidence
threshold means we only fire when we're sure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.proactive_core import ProactiveSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CalendarEvent:
    """Minimal calendar event the prep helper needs."""

    id: str
    title: str
    starts_at: datetime
    location: str | None = None
    attendees: list[str] | None = None
    agenda: str | None = None


@dataclass(slots=True)
class WeatherForecast:
    """Snapshot used by the weather nudge."""

    summary: str  # "Heavy rain"
    temperature_c: float
    precipitation_chance: float  # 0.0-1.0
    # Optional commute-time impact in minutes (positive = slower).
    commute_impact_min: int = 0


@dataclass(slots=True)
class TaskSummary:
    """Open task surfaced for priority review."""

    id: str
    title: str
    due_at: datetime | None
    priority: str  # "low" | "normal" | "high" | "urgent"
    is_overdue: bool = False
    age_days: float = 0.0


@dataclass(slots=True)
class EmailSummary:
    """Email flagged as worth a nudge."""

    id: str
    subject: str
    sender: str
    is_important: bool = False
    age_hours: float = 0.0


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def calendar_prep_signal(
    user_id: str,
    event: CalendarEvent,
    *,
    now: datetime | None = None,
    lead_time_min: int = 5,
) -> "ProactiveSignal | None":
    """Signal the user before ``event`` by ``lead_time_min`` minutes.

    Returns None if the event is too far away (we don't want
    to spam the user about meetings that are 4 hours out).
    """
    from app.core.proactive_core import ProactiveSignal, SignalKind, Urgency

    moment = now or datetime.now(timezone.utc)
    delta_s = (event.starts_at - moment).total_seconds()
    lead_s = lead_time_min * 60
    if delta_s <= 0 or delta_s > 30 * 60 or delta_s > lead_s:
        return None

    body_lines = [f"Starts in {int(delta_s / 60)} min: {event.title}"]
    if event.location:
        body_lines.append(f"Location: {event.location}")
    if event.attendees:
        body_lines.append(f"Attendees: {', '.join(event.attendees)}")
    if event.agenda:
        body_lines.append(f"Agenda: {event.agenda[:300]}")

    return ProactiveSignal(
        id=f"calendar-prep:{event.id}",
        user_id=user_id,
        kind=SignalKind.CALENDAR_PREP,
        title=f"Upcoming: {event.title}",
        body="\n".join(body_lines),
        urgency=Urgency.NORMAL,
        value=0.85,
        confidence=0.95,
        source="calendar_prep",
        metadata={
            "target_id": event.id,
            "starts_at": event.starts_at.isoformat(),
            "location": event.location,
        },
    )


def weather_signal(
    user_id: str,
    forecast: WeatherForecast,
    *,
    commute_min: int = 30,
) -> "ProactiveSignal | None":
    """Nudge the user to leave early if the weather warrants it."""
    from app.core.proactive_core import ProactiveSignal, SignalKind, Urgency

    extra = forecast.commute_impact_min
    precipitates = forecast.precipitation_chance >= 0.5
    cold = forecast.temperature_c <= 0
    hot = forecast.temperature_c >= 35
    if not (precipitates or extra >= 15 or cold or hot):
        return None

    parts: list[str] = []
    if precipitates:
        parts.append(f"{forecast.precipitation_chance * 100:.0f}% chance of rain")
    if extra > 0:
        parts.append(f"commute ~{extra} min slower")
    if cold:
        parts.append(f"it's {forecast.temperature_c:.0f}°C — bundle up")
    if hot:
        parts.append(f"it's {forecast.temperature_c:.0f}°C — stay hydrated")
    body = f"Leave ~{max(extra, 10)} min early: " + ", ".join(parts) + "."

    return ProactiveSignal(
        id=f"weather:{forecast.summary}:{commute_min}",
        user_id=user_id,
        kind=SignalKind.ROUTINE,
        title="Weather nudge",
        body=body,
        urgency=Urgency.LOW,
        value=0.6,
        confidence=0.8,
        source="weather_nudge",
        metadata={
            "target_id": f"weather:{forecast.summary}",
            "commute_min": commute_min,
            "extra_min": extra,
            "precip_chance": forecast.precipitation_chance,
        },
    )


def task_priority_signal(
    user_id: str,
    task: TaskSummary,
    *,
    open_count: int = 1,
) -> "ProactiveSignal | None":
    """Nudge when a single task deserves attention."""
    from app.core.proactive_core import ProactiveSignal, SignalKind, Urgency

    is_hot = task.priority in {"high", "urgent"} or task.is_overdue
    is_old = task.age_days >= 7
    if not (is_hot or is_old):
        return None

    if task.is_overdue:
        body = f"Overdue: {task.title}"
        urgency = Urgency.HIGH
    elif task.priority == "urgent":
        body = f"Urgent: {task.title}"
        urgency = Urgency.HIGH
    elif task.priority == "high":
        body = f"High priority: {task.title}"
        urgency = Urgency.NORMAL
    else:
        body = f"Stale ({task.age_days:.0f}d): {task.title}"
        urgency = Urgency.LOW

    return ProactiveSignal(
        id=f"task:{task.id}",
        user_id=user_id,
        kind=SignalKind.REMINDER,
        title="Task priority",
        body=body,
        urgency=urgency,
        value=0.7 if is_hot else 0.5,
        confidence=0.9,
        source="task_priority",
        metadata={
            "target_id": task.id,
            "priority": task.priority,
            "open_count": open_count,
            "age_days": task.age_days,
        },
    )


def email_urgent_signal(
    user_id: str,
    email: EmailSummary,
) -> "ProactiveSignal | None":
    """Nudge when an important email is fresh and unanswered."""
    from app.core.proactive_core import ProactiveSignal, SignalKind, Urgency

    if not email.is_important or email.age_hours > 24:
        return None
    urgency = Urgency.NORMAL if email.age_hours > 4 else Urgency.HIGH
    return ProactiveSignal(
        id=f"email:{email.id}",
        user_id=user_id,
        kind=SignalKind.REMINDER,
        title="Important email",
        body=f"From {email.sender}: {email.subject}",
        urgency=urgency,
        value=0.75,
        confidence=0.85,
        source="email_urgent",
        metadata={
            "target_id": email.id,
            "sender": email.sender,
            "age_hours": email.age_hours,
        },
    )
