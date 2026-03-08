from __future__ import annotations

import datetime
import os
import uuid
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class GoogleCalendarTool(BaseTool):
    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ):
        self.credentials_file = (
            credentials_file or Config.GOOGLE_CALENDAR_CREDENTIALS_PATH
        )
        self.token_file = token_file or Config.GOOGLE_CALENDAR_TOKEN_PATH
        self._service = None

    # ------------------------------------------------------------------ #
    #  Auth / service                                                       #
    # ------------------------------------------------------------------ #

    def _get_service(self):
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
        return build("calendar", "v3", credentials=creds)

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                        #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "google_calendar"

    def get_description(self) -> str:
        return (
            "Google Calendar management tool. Supports: listing/searching/getting/"
            "creating/updating/deleting events, all-day events, recurring events, "
            "listing calendars, checking free/busy availability, quick-add from "
            "natural language, moving events between calendars, and managing reminders, "
            "location, color, visibility, conference links, and attendee responses."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                # ── Core ──────────────────────────────────────────────── #
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Calendar operation to perform.",
                    required=True,
                    enum=[
                        "list_calendars",
                        "list_events",
                        "get_event",
                        "search_events",
                        "create_event",
                        "update_event",
                        "delete_event",
                        "delete_events_bulk",
                        "move_event",
                        "quick_add",
                        "free_busy",
                        "get_recurring_instances",
                    ],
                ),
                ToolParameter(
                    name="calendar_id",
                    type="string",
                    description="Calendar ID (defaults to 'primary').",
                    required=False,
                ),
                ToolParameter(
                    name="destination_calendar_id",
                    type="string",
                    description="Destination calendar ID for move_event.",
                    required=False,
                ),
                ToolParameter(
                    name="event_id",
                    type="string",
                    description="Google Calendar event ID.",
                    required=False,
                ),
                ToolParameter(
                    name="event_ids",
                    type="array",
                    description="List of event IDs for bulk delete.",
                    required=False,
                ),
                # ── Event fields ───────────────────────────────────────── #
                ToolParameter(
                    name="summary",
                    type="string",
                    description="Event title.",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Detailed description of the event.",
                    required=False,
                ),
                ToolParameter(
                    name="location",
                    type="string",
                    description="Geographic location or address of the event.",
                    required=False,
                ),
                ToolParameter(
                    name="start_time",
                    type="string",
                    description=(
                        "Start time in ISO 8601 format for timed events "
                        "(e.g. '2026-03-01T10:00:00') or date-only for all-day events "
                        "(e.g. '2026-03-01')."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="end_time",
                    type="string",
                    description="End time in ISO 8601 format. For all-day events use date-only.",
                    required=False,
                ),
                ToolParameter(
                    name="timezone",
                    type="string",
                    description=(
                        "IANA timezone name for the event (e.g. 'America/New_York'). "
                        "Defaults to 'UTC'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="all_day",
                    type="boolean",
                    description="Set to true to create an all-day event.",
                    required=False,
                ),
                # ── Attendees ──────────────────────────────────────────── #
                ToolParameter(
                    name="attendees",
                    type="array",
                    description="List of attendee email addresses to invite.",
                    required=False,
                ),
                ToolParameter(
                    name="send_notifications",
                    type="boolean",
                    description="Send email notifications to attendees (default: false).",
                    required=False,
                ),
                # ── Recurrence ─────────────────────────────────────────── #
                ToolParameter(
                    name="recurrence",
                    type="array",
                    description=(
                        "RFC 5545 RRULE strings for recurring events. "
                        "E.g. ['RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10']."
                    ),
                    required=False,
                ),
                # ── Reminders ──────────────────────────────────────────── #
                ToolParameter(
                    name="reminders",
                    type="array",
                    description=(
                        "List of reminder dicts: [{'method': 'email'|'popup', 'minutes': 30}]. "
                        "Pass an empty list to clear all reminders."
                    ),
                    required=False,
                ),
                # ── Appearance & metadata ──────────────────────────────── #
                ToolParameter(
                    name="color_id",
                    type="string",
                    description=(
                        "Event color (1-11). "
                        "1=Tomato, 2=Flamingo, 3=Tangerine, 4=Banana, 5=Sage, "
                        "6=Basil, 7=Peacock, 8=Blueberry, 9=Lavender, 10=Grape, 11=Graphite."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="visibility",
                    type="string",
                    description="Event visibility: 'default', 'public', 'private', or 'confidential'.",
                    required=False,
                    enum=["default", "public", "private", "confidential"],
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    description="Event status: 'confirmed', 'tentative', or 'cancelled'.",
                    required=False,
                    enum=["confirmed", "tentative", "cancelled"],
                ),
                ToolParameter(
                    name="add_conference",
                    type="boolean",
                    description="Automatically add a Google Meet conference link to the event.",
                    required=False,
                ),
                # ── Search / filter ────────────────────────────────────── #
                ToolParameter(
                    name="query",
                    type="string",
                    description="Text query for searching events or natural-language text for quick_add.",
                    required=False,
                ),
                ToolParameter(
                    name="time_min",
                    type="string",
                    description="Lower bound (ISO 8601) for event listing. Defaults to now.",
                    required=False,
                ),
                ToolParameter(
                    name="time_max",
                    type="string",
                    description="Upper bound (ISO 8601) for event listing.",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of events to return (default: 10).",
                    required=False,
                ),
                # ── Free/busy ──────────────────────────────────────────── #
                ToolParameter(
                    name="calendar_ids",
                    type="array",
                    description=(
                        "List of calendar IDs to check for free_busy. "
                        "Defaults to ['primary']."
                    ),
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  Entry point                                                          #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        operation: str,
        calendar_id: str = "primary",
        destination_calendar_id: Optional[str] = None,
        event_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        timezone: str = "UTC",
        all_day: bool = False,
        attendees: Optional[List[str]] = None,
        send_notifications: bool = False,
        recurrence: Optional[List[str]] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
        color_id: Optional[str] = None,
        visibility: Optional[str] = None,
        status: Optional[str] = None,
        add_conference: bool = False,
        query: Optional[str] = None,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 10,
        calendar_ids: Optional[List[str]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            service = self._get_service()

            # ── list_calendars ───────────────────────────────────────── #
            if operation == "list_calendars":
                return self._list_calendars(service)

            # ── list_events ──────────────────────────────────────────── #
            elif operation == "list_events":
                events = self._list_events(
                    service,
                    calendar_id,
                    max_results,
                    time_min=time_min,
                    time_max=time_max,
                )
                return {
                    "success": True,
                    "operation": operation,
                    "events": events,
                    "count": len(events),
                }

            # ── search_events ────────────────────────────────────────── #
            elif operation == "search_events":
                if not query:
                    return {
                        "success": False,
                        "error": "'query' is required for search_events.",
                    }
                events = self._list_events(
                    service,
                    calendar_id,
                    max_results,
                    query=query,
                    time_min=time_min,
                    time_max=time_max,
                )
                return {
                    "success": True,
                    "operation": operation,
                    "query": query,
                    "events": events,
                    "count": len(events),
                }

            # ── get_event ────────────────────────────────────────────── #
            elif operation == "get_event":
                if not event_id:
                    return {"success": False, "error": "'event_id' is required."}
                event = self._get_event(service, calendar_id, event_id)
                return {"success": True, "operation": operation, "event": event}

            # ── create_event ─────────────────────────────────────────── #
            elif operation == "create_event":
                if not summary or not start_time or not end_time:
                    return {
                        "success": False,
                        "error": "'summary', 'start_time', and 'end_time' are required.",
                    }
                event = self._create_event(
                    service,
                    calendar_id,
                    summary,
                    description,
                    location,
                    start_time,
                    end_time,
                    timezone,
                    all_day,
                    attendees,
                    send_notifications,
                    recurrence,
                    reminders,
                    color_id,
                    visibility,
                    status,
                    add_conference,
                )
                return {"success": True, "operation": operation, "event": event}

            # ── update_event ─────────────────────────────────────────── #
            elif operation == "update_event":
                if not event_id:
                    return {"success": False, "error": "'event_id' is required."}
                event = self._update_event(
                    service,
                    calendar_id,
                    event_id,
                    summary,
                    description,
                    location,
                    start_time,
                    end_time,
                    timezone,
                    all_day,
                    attendees,
                    send_notifications,
                    recurrence,
                    reminders,
                    color_id,
                    visibility,
                    status,
                    add_conference,
                )
                return {"success": True, "operation": operation, "event": event}

            # ── delete_event ─────────────────────────────────────────── #
            elif operation == "delete_event":
                if not event_id:
                    return {"success": False, "error": "'event_id' is required."}
                self._delete_event(service, calendar_id, event_id, send_notifications)
                return {
                    "success": True,
                    "operation": operation,
                    "event_id": event_id,
                    "deleted": True,
                }

            # ── delete_events_bulk ───────────────────────────────────── #
            elif operation == "delete_events_bulk":
                if not event_ids:
                    return {
                        "success": False,
                        "error": "'event_ids' is required for bulk delete.",
                    }
                results = self._delete_events_bulk(
                    service, calendar_id, event_ids, send_notifications
                )
                return {"success": True, "operation": operation, "results": results}

            # ── move_event ───────────────────────────────────────────── #
            elif operation == "move_event":
                if not event_id or not destination_calendar_id:
                    return {
                        "success": False,
                        "error": "'event_id' and 'destination_calendar_id' are required.",
                    }
                event = self._move_event(
                    service,
                    calendar_id,
                    event_id,
                    destination_calendar_id,
                    send_notifications,
                )
                return {"success": True, "operation": operation, "event": event}

            # ── quick_add ────────────────────────────────────────────── #
            elif operation == "quick_add":
                if not query:
                    return {
                        "success": False,
                        "error": "'query' (natural-language text) is required for quick_add.",
                    }
                event = (
                    service.events()
                    .quickAdd(calendarId=calendar_id, text=query)
                    .execute()
                )
                return {"success": True, "operation": operation, "event": event}

            # ── free_busy ────────────────────────────────────────────── #
            elif operation == "free_busy":
                if not start_time or not end_time:
                    return {
                        "success": False,
                        "error": "'start_time' and 'end_time' are required for free_busy.",
                    }
                result = self._free_busy(
                    service,
                    calendar_ids or [calendar_id],
                    start_time,
                    end_time,
                    timezone,
                )
                return {"success": True, "operation": operation, "free_busy": result}

            # ── get_recurring_instances ──────────────────────────────── #
            elif operation == "get_recurring_instances":
                if not event_id:
                    return {"success": False, "error": "'event_id' is required."}
                instances = self._get_recurring_instances(
                    service, calendar_id, event_id, max_results, time_min, time_max
                )
                return {
                    "success": True,
                    "operation": operation,
                    "instances": instances,
                    "count": len(instances),
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as e:
            return {"success": False, "error": f"Calendar tool error: {str(e)}"}

    # ------------------------------------------------------------------ #
    #  Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _list_calendars(self, service) -> Dict[str, Any]:
        """Return all calendars accessible by the authenticated user."""
        calendars = []
        page_token = None
        while True:
            response = service.calendarList().list(pageToken=page_token).execute()
            calendars.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return {
            "success": True,
            "operation": "list_calendars",
            "calendars": calendars,
            "count": len(calendars),
        }

    def _list_events(
        self,
        service,
        calendar_id: str,
        max_results: int,
        query: Optional[str] = None,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
    ) -> List[Dict]:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        kwargs: Dict[str, Any] = dict(
            calendarId=calendar_id,
            timeMin=time_min or now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        if query:
            kwargs["q"] = query
        if time_max:
            kwargs["timeMax"] = time_max
        return service.events().list(**kwargs).execute().get("items", [])

    def _get_event(self, service, calendar_id: str, event_id: str) -> Dict:
        return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    def _build_time_field(
        self, dt_str: str, timezone: str, all_day: bool
    ) -> Dict[str, str]:
        """Return a Calendar API start/end dict for either a date or dateTime."""
        if all_day or len(dt_str) == 10:  # date-only string
            return {"date": dt_str[:10]}
        return {"dateTime": dt_str, "timeZone": timezone}

    def _build_event_body(
        self,
        summary: Optional[str],
        description: Optional[str],
        location: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        timezone: str,
        all_day: bool,
        attendees: Optional[List[str]],
        recurrence: Optional[List[str]],
        reminders: Optional[List[Dict[str, Any]]],
        color_id: Optional[str],
        visibility: Optional[str],
        status: Optional[str],
        add_conference: bool,
        existing_body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = existing_body or {}

        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if start_time is not None:
            body["start"] = self._build_time_field(start_time, timezone, all_day)
        if end_time is not None:
            body["end"] = self._build_time_field(end_time, timezone, all_day)
        if recurrence is not None:
            body["recurrence"] = recurrence
        if attendees is not None:
            body["attendees"] = [{"email": e} for e in attendees]
        if color_id is not None:
            body["colorId"] = color_id
        if visibility is not None:
            body["visibility"] = visibility
        if status is not None:
            body["status"] = status

        # Reminders
        if reminders is not None:
            if reminders:
                body["reminders"] = {"useDefault": False, "overrides": reminders}
            else:
                body["reminders"] = {"useDefault": False, "overrides": []}

        # Google Meet
        if add_conference:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        return body

    def _create_event(
        self,
        service,
        calendar_id: str,
        summary: str,
        description: Optional[str],
        location: Optional[str],
        start_time: str,
        end_time: str,
        timezone: str,
        all_day: bool,
        attendees: Optional[List[str]],
        send_notifications: bool,
        recurrence: Optional[List[str]],
        reminders: Optional[List[Dict[str, Any]]],
        color_id: Optional[str],
        visibility: Optional[str],
        status: Optional[str],
        add_conference: bool,
    ) -> Dict:
        body = self._build_event_body(
            summary,
            description,
            location,
            start_time,
            end_time,
            timezone,
            all_day,
            attendees,
            recurrence,
            reminders,
            color_id,
            visibility,
            status,
            add_conference,
        )
        kwargs: Dict[str, Any] = dict(calendarId=calendar_id, body=body)
        if add_conference:
            kwargs["conferenceDataVersion"] = 1
        if send_notifications:
            kwargs["sendNotifications"] = True
        return service.events().insert(**kwargs).execute()

    def _update_event(
        self,
        service,
        calendar_id: str,
        event_id: str,
        summary: Optional[str],
        description: Optional[str],
        location: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        timezone: str,
        all_day: bool,
        attendees: Optional[List[str]],
        send_notifications: bool,
        recurrence: Optional[List[str]],
        reminders: Optional[List[Dict[str, Any]]],
        color_id: Optional[str],
        visibility: Optional[str],
        status: Optional[str],
        add_conference: bool,
    ) -> Dict:
        existing = self._get_event(service, calendar_id, event_id)
        body = self._build_event_body(
            summary,
            description,
            location,
            start_time,
            end_time,
            timezone,
            all_day,
            attendees,
            recurrence,
            reminders,
            color_id,
            visibility,
            status,
            add_conference,
            existing_body=existing,
        )
        kwargs: Dict[str, Any] = dict(
            calendarId=calendar_id, eventId=event_id, body=body
        )
        if add_conference:
            kwargs["conferenceDataVersion"] = 1
        if send_notifications:
            kwargs["sendNotifications"] = True
        return service.events().update(**kwargs).execute()

    def _delete_event(
        self, service, calendar_id: str, event_id: str, send_notifications: bool = False
    ):
        kwargs: Dict[str, Any] = dict(calendarId=calendar_id, eventId=event_id)
        if send_notifications:
            kwargs["sendNotifications"] = True
        service.events().delete(**kwargs).execute()

    def _delete_events_bulk(
        self, service, calendar_id: str, event_ids: List[str], send_notifications: bool
    ) -> List[Dict[str, Any]]:
        results = []
        for eid in event_ids:
            try:
                self._delete_event(service, calendar_id, eid, send_notifications)
                results.append({"event_id": eid, "deleted": True})
            except Exception as e:
                results.append({"event_id": eid, "deleted": False, "error": str(e)})
        return results

    def _move_event(
        self,
        service,
        calendar_id: str,
        event_id: str,
        destination_calendar_id: str,
        send_notifications: bool,
    ) -> Dict:
        kwargs: Dict[str, Any] = dict(
            calendarId=calendar_id,
            eventId=event_id,
            destination=destination_calendar_id,
        )
        if send_notifications:
            kwargs["sendNotifications"] = True
        return service.events().move(**kwargs).execute()

    def _free_busy(
        self,
        service,
        calendar_ids: List[str],
        time_min: str,
        time_max: str,
        timezone: str,
    ) -> Dict:
        body = {
            "timeMin": time_min if time_min.endswith("Z") else time_min + "Z",
            "timeMax": time_max if time_max.endswith("Z") else time_max + "Z",
            "timeZone": timezone,
            "items": [{"id": cid} for cid in calendar_ids],
        }
        response = service.freebusy().query(body=body).execute()
        # Enrich with human-readable busy slots
        enriched: Dict[str, Any] = {}
        for cid, data in response.get("calendars", {}).items():
            busy_slots = data.get("busy", [])
            enriched[cid] = {
                "busy": busy_slots,
                "busy_count": len(busy_slots),
                "is_free": len(busy_slots) == 0,
                "errors": data.get("errors", []),
            }
        return enriched

    def _get_recurring_instances(
        self,
        service,
        calendar_id: str,
        event_id: str,
        max_results: int,
        time_min: Optional[str],
        time_max: Optional[str],
    ) -> List[Dict]:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        kwargs: Dict[str, Any] = dict(
            calendarId=calendar_id,
            eventId=event_id,
            maxResults=max_results,
            timeMin=time_min or now,
        )
        if time_max:
            kwargs["timeMax"] = time_max
        return service.events().instances(**kwargs).execute().get("items", [])
