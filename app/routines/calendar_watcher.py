# app/routines/calendar_watcher.py
"""Proactive calendar watcher — alerts user before upcoming meetings.

Checks Google Calendar every 5 minutes and sends alerts:
  - 15 minutes before: "Meeting with X in 15 minutes"
  - 2 minutes past start: "Your meeting started 2 minutes ago"
  - Daily summary at first check of the day

Day 22: Adds a :func:`generate_signals` method that produces
:class:`~app.core.scheduling.Signal` objects (one per alert)
so the v2 scheduler can publish them through the
:class:`SignalRouter`.  The legacy string-returning
:func:`check_upcoming_events` is kept for the v1
APScheduler path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Track already-notified events to avoid duplicate alerts
_notified_events: set[str] = set()
_daily_summary_date: str = ""


class CalendarWatcher:
    """Watches Google Calendar and sends proactive notifications."""

    def __init__(self) -> None:
        self._calendar_tool = None

    def _get_calendar_tool(self):
        """Lazy-load the calendar tool."""
        if self._calendar_tool is None:
            try:
                from app.tools.toolkit.google.googlecalender import GoogleCalendarTool

                self._calendar_tool = GoogleCalendarTool()
            except Exception as exc:
                logger.warning("CalendarWatcher: GoogleCalendarTool unavailable — %s", exc)
        return self._calendar_tool

    async def check_upcoming_events(self, user_id: str, platform: str, chat_id: str) -> list[str]:
        """Check for upcoming events and return alert messages.

        v1 API: returns a list of formatted markdown strings.
        Kept for the legacy ``APScheduler`` registration path.
        v2 code should use :meth:`generate_signals` instead.
        """
        signals = await self.generate_signals(
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
        )
        return [s.body or s.title for s in signals]

    async def generate_signals(
        self,
        *,
        user_id: str,
        platform: str,
        chat_id: str,
        dedupe_cache: Any | None = None,
    ) -> list:
        """Check for upcoming events and return :class:`Signal` objects.

        Emits one signal per interesting event (15-minute
        warning, "just started" alert, or first-check daily
        summary).  When ``dedupe_cache`` is provided, the
        watcher's own state is consulted first to suppress
        duplicates; the caller can then keep emitting the
        resulting ``Signal`` objects through the
        :class:`SignalRouter` for delivery.
        """
        from app.core.scheduling import Signal, SignalKind, SignalSeverity

        global _notified_events, _daily_summary_date

        tool = self._get_calendar_tool()
        if not tool:
            return []

        now = datetime.now(timezone.utc)
        out: list[Signal] = []
        cache = dedupe_cache

        try:
            time_min = now.isoformat()
            time_max = (now + timedelta(minutes=30)).isoformat()

            result = await tool.execute(
                operation="list_events",
                time_min=time_min,
                time_max=time_max,
                max_results=10,
            )

            if not result.get("success"):
                logger.debug("CalendarWatcher: failed to fetch events — %s", result.get("error"))
                return []

            events = result.get("events", [])

            for event in events:
                event_id = event.get("id", "")
                summary = event.get("summary", "Untitled Event")
                start = event.get("start", {})

                start_str = start.get("dateTime") or start.get("date")
                if not start_str:
                    continue

                try:
                    if "T" in start_str:
                        if start_str.endswith("Z"):
                            event_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        elif "+" in start_str or start_str.count("-") > 2:
                            event_start = datetime.fromisoformat(start_str)
                        else:
                            event_start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
                    else:
                        # All-day event — skip time-based alerts
                        continue
                except Exception:
                    continue

                minutes_until = (event_start - now).total_seconds() / 60.0

                # 15-minute warning
                alert_key_15 = f"{event_id}:15min"
                if 10 <= minutes_until <= 16:
                    if alert_key_15 in _notified_events:
                        continue
                    if cache is not None and cache.check_and_record(
                        user_id, SignalKind.CALENDAR, alert_key_15
                    ):
                        continue
                    _notified_events.add(alert_key_15)
                    location = event.get("location", "")
                    attendees = event.get("attendees", [])
                    attendee_str = ""
                    if attendees:
                        names = [a.get("displayName") or a.get("email", "?") for a in attendees[:3]]
                        attendee_str = f" with {', '.join(names)}"
                    loc_str = f" at {location}" if location else ""
                    body = (
                        f"📅 **Meeting in {int(minutes_until)} minutes**: "
                        f"{summary}{attendee_str}{loc_str}"
                    )
                    out.append(
                        Signal.make(
                            kind=SignalKind.CALENDAR,
                            source="calendar_watcher",
                            user_id=user_id,
                            title=f"Meeting in {int(minutes_until)} minutes",
                            severity=SignalSeverity.NOTICE,
                            body=body,
                            payload={
                                "event_id": event_id,
                                "summary": summary,
                                "starts_at": event_start.isoformat(),
                                "minutes_until": int(minutes_until),
                                "kind": "upcoming_15min",
                                "platform": platform,
                                "chat_id": chat_id,
                            },
                            dedupe_key=alert_key_15,
                        )
                    )

                # Already started (0 to -5 minutes)
                alert_key_start = f"{event_id}:started"
                elif_ref = -5 <= minutes_until < 0
                if elif_ref:
                    if alert_key_start in _notified_events:
                        continue
                    if cache is not None and cache.check_and_record(
                        user_id, SignalKind.CALENDAR, alert_key_start
                    ):
                        continue
                    _notified_events.add(alert_key_start)
                    mins_late = abs(int(minutes_until))
                    body = f"⏰ **Your meeting started {mins_late} minute(s) ago**: {summary}"
                    out.append(
                        Signal.make(
                            kind=SignalKind.CALENDAR,
                            source="calendar_watcher",
                            user_id=user_id,
                            title=f"Meeting started {mins_late} min ago",
                            severity=SignalSeverity.WARNING,
                            body=body,
                            payload={
                                "event_id": event_id,
                                "summary": summary,
                                "minutes_late": mins_late,
                                "kind": "started",
                                "platform": platform,
                                "chat_id": chat_id,
                            },
                            dedupe_key=alert_key_start,
                        )
                    )

            # Daily summary — first check of each day
            today = now.strftime("%Y-%m-%d")
            if today != _daily_summary_date:
                _daily_summary_date = today
                summary_text = await self._generate_daily_summary(tool, now)
                if summary_text:
                    out.insert(
                        0,
                        Signal.make(
                            kind=SignalKind.CALENDAR,
                            source="calendar_watcher",
                            user_id=user_id,
                            title="Today's calendar",
                            severity=SignalSeverity.INFO,
                            body=summary_text,
                            payload={
                                "kind": "daily_summary",
                                "platform": platform,
                                "chat_id": chat_id,
                            },
                            dedupe_key=f"daily:{today}",
                        ),
                    )

                # Clean up old notified events (keep only today's)
                _notified_events = {
                    k for k in _notified_events
                    if not k.startswith("daily:")
                }

        except Exception as exc:
            logger.error("CalendarWatcher: error during check — %s", exc)

        return out

    async def _generate_daily_summary(self, tool, now: datetime) -> str | None:
        """Generate a morning summary of today's events."""
        try:
            time_min = now.replace(hour=0, minute=0, second=0).isoformat()
            time_max = now.replace(hour=23, minute=59, second=59).isoformat()

            result = await tool.execute(
                operation="list_events",
                time_min=time_min,
                time_max=time_max,
                max_results=20,
            )

            if not result.get("success"):
                return None

            events = result.get("events", [])
            if not events:
                return "📅 **Today's Calendar**: No events scheduled."

            lines = [f"📅 **Today's Calendar** ({len(events)} events):"]
            for ev in events:
                summary = ev.get("summary", "Untitled")
                start = ev.get("start", {})
                start_str = start.get("dateTime", start.get("date", ""))
                if "T" in start_str:
                    try:
                        t = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        time_fmt = t.strftime("%I:%M %p")
                    except Exception:
                        time_fmt = start_str
                else:
                    time_fmt = "All Day"
                lines.append(f"  • **{time_fmt}** — {summary}")

            return "\n".join(lines)

        except Exception as exc:
            logger.debug("CalendarWatcher: daily summary failed — %s", exc)
            return None


def register_calendar_watcher(
    scheduler, user_id: str, platform: str, chat_id: str, interval_minutes: int = 5
) -> str | None:
    """Register the calendar watcher as a scheduled routine.

    Returns the schedule id when registered on a v2
    :class:`~app.core.scheduling.Scheduler`, or ``None`` when
    the legacy APScheduler path is used.
    """
    from app.core.scheduling import Scheduler

    if isinstance(scheduler, Scheduler):
        return register_calendar_watcher_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            interval_minutes=interval_minutes,
        )

    watcher = CalendarWatcher()

    async def _check_and_notify() -> None:
        try:
            alerts = await watcher.check_upcoming_events(user_id, platform, chat_id)
            if alerts and scheduler._botsignal:
                from app.core.models import ReplyTarget, SignalPayload

                target = ReplyTarget(platform=platform, chat_id=chat_id)
                for alert in alerts:
                    payload = SignalPayload(text=alert, source_kind="calendar_alert")
                    await scheduler._botsignal.send(target, payload)
        except Exception as exc:
            logger.error("CalendarWatcher routine error: %s", exc)

    job_id = f"calendar_watcher_{user_id}"
    scheduler._scheduler.add_job(
        _check_and_notify,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "CalendarWatcher registered for user %s every %d minutes",
        user_id,
        interval_minutes,
    )
    return None


def register_calendar_watcher_v2(
    scheduler,
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    interval_minutes: int = 5,
    signal_router: Any = None,
    dedupe_cache: Any = None,
    schedule_id: str | None = None,
) -> str:
    """Register the calendar watcher on a v2 :class:`Scheduler`.

    Uses :class:`IntervalTrigger` and returns ``list[Signal]``
    from each fire so the scheduler can publish them through
    the :class:`SignalRouter` (or a custom router injected
    via ``signal_router=``).  Returns the schedule id.
    """
    from app.core.scheduling import (
        DedupeCache,
        IntervalTrigger,
        Scheduler,
        get_default_signal_router,
    )

    if not isinstance(scheduler, Scheduler):
        raise TypeError(
            "register_calendar_watcher_v2 requires a v2 Scheduler; "
            f"got {type(scheduler).__name__}"
        )

    routine_id = f"calendar_watcher::{user_id}"
    watcher = CalendarWatcher()
    router = signal_router or getattr(scheduler, "signal_router", None) or get_default_signal_router()
    cache = dedupe_cache or getattr(scheduler, "dedupe_cache", None) or DedupeCache()

    async def _fire(uid: str, *args: Any, triggered_at: datetime | None = None, **kwargs: Any) -> list:
        signals = await watcher.generate_signals(
            user_id=uid,
            platform=platform,
            chat_id=chat_id,
            dedupe_cache=cache,
        )
        if not signals:
            return []
        for sig in signals:
            await router.publish(sig)
        return signals

    if scheduler.routine_registry.get(routine_id) is None:
        scheduler.routine_registry.register_fn(
            routine_id,
            _fire,
            name="calendar_watcher",
            kind="watcher",
            metadata={
                "user_id": user_id,
                "platform": platform,
                "chat_id": chat_id,
                "interval_minutes": interval_minutes,
            },
        )

    sid = schedule_id or f"calendar_watcher_{user_id}"
    scheduler.add(
        routine_id=routine_id,
        trigger=IntervalTrigger(every=timedelta(minutes=interval_minutes)),
        user_id=user_id,
        schedule_id=sid,
    )
    logger.info(
        "CalendarWatcher v2 registered for user %s every %d minutes (schedule=%s)",
        user_id,
        interval_minutes,
        sid,
    )
    return sid
