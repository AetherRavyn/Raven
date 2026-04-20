# app/routines/calendar_watcher.py
"""Proactive calendar watcher — alerts user before upcoming meetings.

Checks Google Calendar every 5 minutes and sends alerts:
  - 15 minutes before: "Meeting with X in 15 minutes"
  - 2 minutes past start: "Your meeting started 2 minutes ago"
  - Daily summary at first check of the day
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Set

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Track already-notified events to avoid duplicate alerts
_notified_events: Set[str] = set()
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

    async def check_upcoming_events(self, user_id: str, platform: str, chat_id: str) -> List[str]:
        """Check for upcoming events and return alert messages."""
        global _notified_events, _daily_summary_date

        tool = self._get_calendar_tool()
        if not tool:
            return []

        now = datetime.now(timezone.utc)
        alerts: List[str] = []

        try:
            # Look ahead 30 minutes
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

                # Parse start time
                start_str = start.get("dateTime") or start.get("date")
                if not start_str:
                    continue

                try:
                    if "T" in start_str:
                        # DateTime event
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

                # Generate alert key to prevent duplicates
                alert_key_15 = f"{event_id}:15min"
                alert_key_start = f"{event_id}:started"

                # 15-minute warning
                if 10 <= minutes_until <= 16 and alert_key_15 not in _notified_events:
                    _notified_events.add(alert_key_15)
                    location = event.get("location", "")
                    attendees = event.get("attendees", [])
                    attendee_str = ""
                    if attendees:
                        names = [a.get("displayName") or a.get("email", "?") for a in attendees[:3]]
                        attendee_str = f" with {', '.join(names)}"
                    loc_str = f" at {location}" if location else ""

                    alerts.append(
                        f"📅 **Meeting in {int(minutes_until)} minutes**: {summary}{attendee_str}{loc_str}"
                    )

                # Already started (0 to -5 minutes)
                elif -5 <= minutes_until < 0 and alert_key_start not in _notified_events:
                    _notified_events.add(alert_key_start)
                    mins_late = abs(int(minutes_until))
                    alerts.append(
                        f"⏰ **Your meeting started {mins_late} minute(s) ago**: {summary}"
                    )

            # Daily summary — first check of each day
            today = now.strftime("%Y-%m-%d")
            if today != _daily_summary_date:
                _daily_summary_date = today
                summary_text = await self._generate_daily_summary(tool, now)
                if summary_text:
                    alerts.insert(0, summary_text)

                # Clean up old notified events (keep only today's)
                _notified_events = {
                    k for k in _notified_events
                    if not k.startswith("daily:")
                }

        except Exception as exc:
            logger.error("CalendarWatcher: error during check — %s", exc)

        return alerts

    async def _generate_daily_summary(self, tool, now: datetime) -> str | None:
        """Generate a morning summary of today's events."""
        try:
            # Get all events for today
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
) -> None:
    """Register the calendar watcher as a scheduled routine."""

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
