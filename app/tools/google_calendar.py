"""Google Calendar Tool — full calendar management via Google Calendar API.

Supports:
- List events (today, this week, custom range)
- Create events with reminders
- Update/delete events
- Check availability
- List calendars

Requires: GOOGLE_CALENDAR_CREDENTIALS_PATH and GOOGLE_CALENDAR_TOKEN_PATH
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class GoogleCalendarTool(BaseTool):
    """Google Calendar integration for scheduling and event management."""

    def __init__(self, **cfg: Any) -> None:
        self._creds_path = cfg.get("credentials_path")
        self._token_path = cfg.get("token_path")

    def get_name(self) -> str:
        return "google_calendar"

    def get_description(self) -> str:
        return (
            "Manage Google Calendar: list/create/update/delete events, "
            "check availability, list calendars. Requires OAuth2 credentials."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="operation", type="string", required=True,
                             description="Operation: list_events, create_event, delete_event, list_calendars, check_availability",
                             enum=["list_events", "create_event", "delete_event", "list_calendars", "check_availability"]),
                ToolParameter(name="calendar_id", type="string", required=False,
                             description="Calendar ID (default: primary)"),
                ToolParameter(name="time_min", type="string", required=False,
                             description="Start of time range (ISO 8601)"),
                ToolParameter(name="time_max", type="string", required=False,
                             description="End of time range (ISO 8601)"),
                ToolParameter(name="summary", type="string", required=False,
                             description="Event title (for create_event)"),
                ToolParameter(name="description", type="string", required=False,
                             description="Event description"),
                ToolParameter(name="location", type="string", required=False,
                             description="Event location"),
                ToolParameter(name="event_id", type="string", required=False,
                             description="Event ID (for delete_event)"),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "")
        try:
            import google.oauth2.credentials
            from googleapiclient.discovery import build

            creds = self._load_credentials()
            if not creds:
                return {"success": False, "error": "Google Calendar credentials not configured. Set GOOGLE_CALENDAR_CREDENTIALS_PATH and GOOGLE_CALENDAR_TOKEN_PATH."}

            service = build("calendar", "v3", credentials=creds)
            calendar_id = kwargs.get("calendar_id", "primary")

            if operation == "list_events":
                time_min = kwargs.get("time_min", datetime.now(timezone.utc).isoformat())
                time_max = kwargs.get("time_max")
                events_result = service.events().list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=50,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                events = events_result.get("items", [])
                return {
                    "success": True,
                    "events": [
                        {
                            "id": e.get("id"),
                            "summary": e.get("summary", ""),
                            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                            "location": e.get("location", ""),
                            "description": e.get("description", "")[:200],
                        }
                        for e in events
                    ],
                    "count": len(events),
                }

            elif operation == "create_event":
                summary = kwargs.get("summary", "")
                if not summary:
                    return {"success": False, "error": "summary is required"}
                event = {
                    "summary": summary,
                    "description": kwargs.get("description", ""),
                    "location": kwargs.get("location", ""),
                    "start": {"dateTime": kwargs.get("time_min", datetime.now(timezone.utc).isoformat())},
                    "end": {"dateTime": kwargs.get("time_max", datetime.now(timezone.utc).isoformat())},
                }
                result = service.events().insert(calendarId=calendar_id, body=event).execute()
                return {"success": True, "event_id": result.get("id"), "summary": summary}

            elif operation == "delete_event":
                event_id = kwargs.get("event_id", "")
                if not event_id:
                    return {"success": False, "error": "event_id is required"}
                service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
                return {"success": True, "deleted": event_id}

            elif operation == "list_calendars":
                cal_list = service.calendarList().list().execute()
                calendars = [
                    {"id": c.get("id"), "summary": c.get("summary", ""), "primary": c.get("primary", False)}
                    for c in cal_list.get("items", [])
                ]
                return {"success": True, "calendars": calendars, "count": len(calendars)}

            elif operation == "check_availability":
                time_min = kwargs.get("time_min", datetime.now(timezone.utc).isoformat())
                time_max = kwargs.get("time_max")
                freebusy = service.freebusy().query(
                    body={"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]}
                ).execute()
                busy = freebusy.get("calendars", {}).get(calendar_id, {}).get("busy", [])
                return {"success": True, "busy": busy, "is_free": len(busy) == 0}

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except ImportError:
            return {"success": False, "error": "google-api-python-client not installed"}
        except Exception as e:
            logger.exception("GoogleCalendarTool error")
            return {"success": False, "error": str(e)}

    def _load_credentials(self):
        try:
            from app.settings.config import Config
            creds_path = self._creds_path or getattr(Config, "GOOGLE_CALENDAR_CREDENTIALS_PATH", "")
            token_path = self._token_path or getattr(Config, "GOOGLE_CALENDAR_TOKEN_PATH", "")
            if not creds_path or not Path(creds_path).exists():
                return None
            import google.oauth2.credentials
            if token_path and Path(token_path).exists():
                return google.oauth2.credentials.Credentials.from_authorized_user_file(token_path)
            return None
        except Exception:
            return None
