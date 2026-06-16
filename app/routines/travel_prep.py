"""Travel prep routine — fires ahead of a calendar event flagged as travel.

For any upcoming event in the next N hours that has a
``location`` different from the user's home city, the routine:

1. Composes a "leave by" digest
2. Surfaces the destination weather

The routine is *passive* — it takes the calendar event + the
weather forecast as inputs and produces a digest.  Callers
(a scheduler, a calendar watcher) feed it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.proactive_core import (
    ProactiveSignal,
    SignalKind,
    Urgency,
    get_context,
    weather_signal,
)
from app.core.proactive_core.smart_nudges import (
    CalendarEvent,
    WeatherForecast,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TravelPlan:
    """Inputs the routine consumes."""

    event: CalendarEvent
    home_location: str
    destination_location: str
    forecast: WeatherForecast
    # How long the trip is expected to take (minutes).
    trip_minutes: int = 0


async def compose_travel_prep(
    user_id: str,
    plan: TravelPlan,
    *,
    now: datetime | None = None,
) -> tuple[str, WeatherForecast | None]:
    """Build the digest text + the weather snapshot (if any).

    Returns ``(text, forecast_or_None)`` so callers can surface
    them separately or as one combined message.
    """
    moment = now or datetime.now(timezone.utc)
    starts_in_min = int((plan.event.starts_at - moment).total_seconds() / 60)

    lines: list[str] = [
        f"Travel: {plan.event.title}",
        f"  starts in {starts_in_min} min at {plan.destination_location}",
    ]

    if plan.trip_minutes > 0:
        leave_by = starts_in_min - plan.trip_minutes
        if leave_by < 0:
            lines.append(f"  ⚠ you'd need to leave {-leave_by} min ago — consider rescheduling")
        else:
            lines.append(f"  leave by: {leave_by} min from now")

    sig = weather_signal(user_id, plan.forecast)
    if sig is not None:
        lines.append(f"  weather: {sig.body}")
        return "\n".join(lines), plan.forecast

    lines.append(f"  weather: {plan.forecast.summary}")
    return "\n".join(lines), plan.forecast


async def send_travel_prep(user_id: str, plan: TravelPlan) -> bool:
    """Send the travel prep through the engine if a context is registered.

    Returns True on a successful engine send, False on
    legacy / no-op.  Callers should fall back to a direct
    channel send when this returns False.
    """
    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False

    text, _ = await compose_travel_prep(user_id, plan)

    sig = ProactiveSignal(
        id=f"travel_prep:{plan.event.id}",
        user_id=user_id,
        kind=SignalKind.CALENDAR_PREP,
        title=f"Travel: {plan.event.title}",
        body=text,
        urgency=Urgency.NORMAL,
        value=0.85,
        confidence=0.9,
        interruption_cost=0.2,
        source="travel_prep",
        metadata={
            "target_id": plan.event.id,
            "home": plan.home_location,
            "destination": plan.destination_location,
            "starts_at": plan.event.starts_at.isoformat(),
        },
    )
    decision = await ctx.adapter.dispatch(sig)
    logger.info(
        "travel_prep: user=%s event=%s verdict=%s stage=%s",
        user_id,
        plan.event.id,
        decision.verdict.value,
        decision.stage,
    )
    return True
