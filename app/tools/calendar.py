"""Calendar integration — Google Calendar and Outlook/CalDAV.

Provides read/write/query capabilities for both providers with a unified
interface. Falls back gracefully when provider credentials are missing.

Architecture:
    CalendarEvent  — data class for event representation
    GoogleCalendar — Google Calendar API via google-auth + google-api-python-client
    OutlookCalendar— Outlook/CalDAV via caldav library
    CalendarTool   — unified entry point used by orchestrator
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    location: str = ""
    id: str = ""
    provider: str = ""  # "google" or "outlook"


class GoogleCalendar:
    """Google Calendar integration via the REST API.

    Requires:
        - google-api-python-client
        - google-auth-httplib2
        - google-auth-oauthlib
        - GOOGLE_CREDENTIALS_FILE env var or token pickled in workspace
    """

    def __init__(self) -> None:
        self._service = None

    async def _ensure_authenticated(self) -> Any:
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            logger.warning("google-api-python-client not installed")
            return None

        SCOPES = ["https://www.googleapis.com/auth/calendar"]

        creds = None
        token_path = "workspace/memory/google_token.json"

        if os.path.exists(token_path):
            import json

            with open(token_path) as f:
                creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds_path = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
                if not os.path.exists(creds_path):
                    logger.warning("Google credentials file not found at %s", creds_path)
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            import json

            with open(token_path, "w") as f:
                f.write(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    async def list_events(
        self,
        max_results: int = 10,
        days_ahead: int = 7,
    ) -> list[CalendarEvent]:
        service = await self._ensure_authenticated()
        if service is None:
            return []

        now = datetime.now(timezone.utc)
        later = now + timedelta(days=days_ahead)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=later.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        result: list[CalendarEvent] = []
        for event in events_result.get("items", []):
            start_str = event["start"].get("dateTime", event["start"].get("date"))
            end_str = event["end"].get("dateTime", event["end"].get("date"))
            result.append(
                CalendarEvent(
                    summary=event.get("summary", ""),
                    start=datetime.fromisoformat(start_str),
                    end=datetime.fromisoformat(end_str),
                    description=event.get("description", ""),
                    location=event.get("location", ""),
                    id=event.get("id", ""),
                    provider="google",
                )
            )
        return result

    async def create_event(self, event: CalendarEvent) -> str | None:
        service = await self._ensure_authenticated()
        if service is None:
            return None

        body = {
            "summary": event.summary,
            "description": event.description,
            "location": event.location,
            "start": {
                "dateTime": event.start.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": event.end.isoformat(),
                "timeZone": "UTC",
            },
        }
        created = service.events().insert(calendarId="primary", body=body).execute()
        return created.get("id")

    async def delete_event(self, event_id: str) -> bool:
        service = await self._ensure_authenticated()
        if service is None:
            return False
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return True
        except Exception as e:
            logger.error("Failed to delete event %s: %s", event_id, e)
            return False


class OutlookCalendar:
    """Outlook/CalDAV calendar integration.

    Requires:
        - caldav library
        - CALDAV_URL, CALDAV_USERNAME, CALDAV_PASSWORD env vars
    """

    def __init__(self) -> None:
        self._client = None

    async def _ensure_authenticated(self) -> Any:
        if self._client is not None:
            return self._client

        url = os.environ.get("CALDAV_URL")
        username = os.environ.get("CALDAV_USERNAME")
        password = os.environ.get("CALDAV_PASSWORD")

        if not url or not username:
            logger.warning("CALDAV_URL or CALDAV_USERNAME not set")
            return None

        try:
            import caldav

            self._client = caldav.DAVClient(url=url, username=username, password=password)
            return self._client
        except ImportError:
            logger.warning("caldav library not installed")
            return None

    async def list_events(
        self,
        max_results: int = 10,
        days_ahead: int = 7,
    ) -> list[CalendarEvent]:
        client = await self._ensure_authenticated()
        if client is None:
            return []

        try:
            principal = client.principal()
            calendars = principal.calendars()
            if not calendars:
                return []

            cal = calendars[0]
            now = datetime.now(timezone.utc)
            later = now + timedelta(days=days_ahead)

            events = cal.date_search(now, later, expand=True)
            result: list[CalendarEvent] = []
            import uuid

            for ev in events:
                data = ev.data
                result.append(
                    CalendarEvent(
                        summary=data.get("summary", ""),
                        start=data.get("dtstart", now),
                        end=data.get("dtend", now + timedelta(hours=1)),
                        description=data.get("description", ""),
                        id=str(uuid.uuid4()),
                        provider="outlook",
                    )
                )
                if len(result) >= max_results:
                    break
            return result
        except Exception as e:
            logger.error("Outlook calendar error: %s", e)
            return []

    async def create_event(self, event: CalendarEvent) -> str | None:
        client = await self._ensure_authenticated()
        if client is None:
            return None
        try:
            from icalendar import Calendar, Event as IEvent

            cal = Calendar()
            cal.add("prodid", "-//Raven Calendar//EN")
            cal.add("version", "2.0")

            ievent = IEvent()
            ievent.add("summary", event.summary)
            ievent.add("dtstart", event.start)
            ievent.add("dtend", event.end)
            if event.description:
                ievent.add("description", event.description)
            ievent.add("dtstamp", datetime.now(timezone.utc))
            ievent.add("uid", event.id or str(hash(event.summary + str(event.start))))
            cal.add_component(ievent)

            principal = client.principal()
            calendars = principal.calendars()
            if not calendars:
                return None

            cal_obj = calendars[0]
            cal_obj.save_event(cal.to_ical())
            return event.id or "saved"
        except Exception as e:
            logger.error("Outlook create event error: %s", e)
            return None


class CalendarTool:
    """Unified calendar tool — tries Google first, falls back to Outlook."""

    def __init__(self) -> None:
        self._google = GoogleCalendar()
        self._outlook = OutlookCalendar()

    async def list_upcoming(
        self,
        max_results: int = 10,
        days_ahead: int = 7,
    ) -> list[CalendarEvent]:
        events = await self._google.list_events(max_results, days_ahead)
        if events:
            return events
        return await self._outlook.list_events(max_results, days_ahead)

    async def add_event(self, event: CalendarEvent) -> str | None:
        event_id = await self._google.create_event(event)
        if event_id:
            return event_id
        return await self._outlook.create_event(event)

    async def remove_event(self, event_id: str) -> bool:
        return await self._google.delete_event(event_id)

    async def handle_calendar_intent(self, text: str) -> str:
        """Parse a natural language calendar request and execute it.

        Supported patterns:
            "what's on my calendar" → list upcoming
            "add event <summary> on <date>" → create event
            "delete event <id>" → delete event
        """
        text_lower = text.lower()

        if any(
            p in text_lower for p in ["what", "upcoming", "next", "list", "show", "my schedule"]
        ):
            events = await self.list_upcoming()
            if not events:
                return "No upcoming events found."
            lines = [
                f"- {e.summary} ({e.start.strftime('%a %b %d %H:%M')} — {e.end.strftime('%H:%M')})"
                for e in events
            ]
            return "## Upcoming Events\n" + "\n".join(lines)

        if any(p in text_lower for p in ["add", "create", "schedule", "new event"]):
            # Very basic parsing — extract summary (first meaningful text)
            # and default to tomorrow at 10am for 1 hour
            tokens = text_lower.split()
            summary_words = []
            for i, t in enumerate(tokens):
                if t in ("add", "create", "schedule", "event", "a", "new"):
                    continue
                summary_words.append(tokens[i])
            summary = " ".join(summary_words[:6]) if summary_words else "New Event"
            tomorrow = datetime.now(timezone.utc).replace(
                hour=10,
                minute=0,
                second=0,
                microsecond=0,
            ) + timedelta(days=1)
            event = CalendarEvent(
                summary=summary[:100],
                start=tomorrow,
                end=tomorrow + timedelta(hours=1),
            )
            event_id = await self.add_event(event)
            if event_id:
                return f"✅ Event '{event.summary}' created on {tomorrow.strftime('%a %b %d')} at 10:00."
            return "❌ Could not create event (no calendar provider configured)."

        if any(p in text_lower for p in ["delete", "remove"]):
            # Try to extract an event ID from the text
            for token in text_lower.split():
                if len(token) > 20 and token.isalnum():
                    ok = await self.remove_event(token)
                    if ok:
                        return "✅ Event deleted."
            return "Could not find event ID in your request."

        return (
            'Try: "what\'s on my calendar", "add event meeting tomorrow", or "delete event <id>".'
        )


# Singleton
_calendar: CalendarTool | None = None


def get_calendar_tool() -> CalendarTool:
    global _calendar
    if _calendar is None:
        _calendar = CalendarTool()
    return _calendar
