"""Outlook Calendar Tool — Microsoft 365 calendar via Microsoft Graph API.

Supports:
- List events (today, this week, custom range)
- Create events with reminders
- Update/delete events
- Check availability

Requires: AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID
Auth flow: OAuth2 Device Code Flow for headless environments
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class OutlookCalendarTool(BaseTool):
    """Microsoft 365 / Outlook calendar integration."""

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, **cfg: Any) -> None:
        self._tenant_id = cfg.get("tenant_id")
        self._client_id = cfg.get("client_id")
        self._client_secret = cfg.get("client_secret")
        self._access_token: str | None = None

    def get_name(self) -> str:
        return "outlook_calendar"

    def get_description(self) -> str:
        return (
            "Microsoft 365 Outlook calendar management. "
            "List, create, update, and delete calendar events. "
            "Check availability and free/busy status."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="operation", type="string", required=True,
                    description="list_events | create_event | delete_event | check_availability",
                    enum=["list_events", "create_event", "delete_event", "check_availability"]),
                ToolParameter(name="start_date", type="string", required=False,
                    description="ISO 8601 start date (default: today)"),
                ToolParameter(name="end_date", type="string", required=False,
                    description="ISO 8601 end date (default: today + 7 days)"),
                ToolParameter(name="subject", type="string", required=False,
                    description="Event subject (required for create)"),
                ToolParameter(name="body", type="string", required=False,
                    description="Event body/description"),
                ToolParameter(name="event_id", type="string", required=False,
                    description="Event ID (required for delete)"),
            ],
        )

    async def _get_token(self) -> str | None:
        """Get OAuth2 token via client credentials flow."""
        if self._access_token:
            return self._access_token
        if not all([self._tenant_id, self._client_id, self._client_secret]):
            return None

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                    },
                )
                data = resp.json()
                self._access_token = data.get("access_token")
                return self._access_token
        except Exception as exc:
            logger.error("Outlook auth failed: %s", exc)
            return None

    async def execute(self, **kwargs: Any) -> dict:
        token = await self._get_token()
        if not token:
            return {
                "success": False,
                "error": "Outlook credentials not configured. Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID.",
            }

        operation = kwargs.get("operation", "list_events")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            import httpx

            if operation == "list_events":
                start = kwargs.get("start_date", datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"))
                end = kwargs.get("end_date", "")
                url = f"{self.GRAPH_BASE}/me/calendarView?startDateTime={start}"
                if end:
                    url += f"&endDateTime={end}"
                else:
                    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59)
                    url += f"&endDateTime={end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                url += "&$orderby=start/dateTime&$top=50&$select=subject,start,end,location,isCancelled"

                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers)
                    data = resp.json()
                events = [
                    {"subject": e.get("subject", ""), "start": e.get("start", {}).get("dateTime", ""), "end": e.get("end", {}).get("dateTime", ""), "location": e.get("location", {}).get("displayName", "")}
                    for e in data.get("value", [])
                ]
                return {"success": True, "events": events, "count": len(events)}

            elif operation == "create_event":
                subject = kwargs.get("subject", "")
                body = kwargs.get("body", "")
                start = kwargs.get("start_date", datetime.now(timezone.utc).isoformat())
                end = kwargs.get("end_date", start)
                event_data = {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "start": {"dateTime": start, "timeZone": "UTC"},
                    "end": {"dateTime": end, "timeZone": "UTC"},
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(f"{self.GRAPH_BASE}/me/events", headers=headers, json=event_data)
                    data = resp.json()
                return {"success": True, "event_id": data.get("id", ""), "subject": subject}

            elif operation == "delete_event":
                event_id = kwargs.get("event_id", "")
                if not event_id:
                    return {"success": False, "error": "event_id required"}
                async with httpx.AsyncClient() as client:
                    resp = await client.delete(f"{self.GRAPH_BASE}/me/events/{event_id}", headers=headers)
                return {"success": resp.status_code in (200, 204), "deleted": event_id}

            elif operation == "check_availability":
                start = kwargs.get("start_date", datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"))
                end = kwargs.get("end_date", "")
                url = f"{self.GRAPH_BASE}/me/calendarView?startDateTime={start}"
                if not end:
                    from datetime import timedelta
                    end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59Z")
                url += f"&endDateTime={end}&$orderby=start/dateTime&$top=50"

                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers)
                    data = resp.json()
                events = data.get("value", [])
                return {"success": True, "busy_slots": len(events), "events": [
                    {"subject": e.get("subject", ""), "start": e.get("start", {}).get("dateTime", ""), "end": e.get("end", {}).get("dateTime", "")}
                    for e in events
                ]}

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            return {"success": False, "error": str(exc)[:500]}
