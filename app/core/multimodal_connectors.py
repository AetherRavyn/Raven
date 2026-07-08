"""Multimodal Data Connectors — Integrates external data sources into unified context."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    """Calendar event from any provider."""
    event_id: str
    title: str
    start: str  # ISO format
    end: str | None = None
    location: str = ""
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    source: str = "google"  # google, outlook, caldav
    calendar_id: str = ""


@dataclass
class EmailMessage:
    """Email message from any provider."""
    message_id: str
    subject: str
    from_addr: str
    to_addrs: list[str]
    body: str
    snippet: str = ""
    received_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    labels: list[str] = field(default_factory=list)
    source: str = "gmail"  # gmail, outlook, imap
    has_attachments: bool = False


@dataclass
class FileContent:
    """File content summary."""
    file_id: str
    name: str
    path: str
    mime_type: str
    size: int
    summary: str = ""
    content_preview: str = ""
    modified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "local"  # local, google_drive, onedrive, dropbox


class CalendarConnector:
    """Unified calendar interface."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "connectors" / "calendar"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._dir / "events_cache.json"
        self._events: list[CalendarEvent] = []
        self._load_cache()
    
    def _load_cache(self) -> None:
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._events = [CalendarEvent(**e) for e in data]
        except Exception as e:
            logger.warning("Failed to load calendar cache: %s", e)
    
    def _save_cache(self) -> None:
        try:
            self._cache_file.write_text(
                json.dumps([e.__dict__ for e in self._events], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save calendar cache: %s", e)
    
    def add_event(self, event: CalendarEvent) -> None:
        self._events.append(event)
        self._save_cache()
    
    def get_upcoming_events(self, days: int = 7, max_events: int = 10) -> list[dict[str, Any]]:
        """Get upcoming events within N days."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        
        upcoming = []
        for event in self._events:
            try:
                start = datetime.fromisoformat(event.start.replace('Z', '+00:00'))
                if now <= start <= end:
                    upcoming.append({
                        "event_id": event.event_id,
                        "title": event.title,
                        "start": event.start,
                        "end": event.end,
                        "location": event.location,
                        "description": event.description,
                        "attendees": event.attendees,
                        "source": event.source
                    })
            except Exception:
                continue
        
        upcoming.sort(key=lambda e: e["start"])
        return upcoming[:max_events]
    
    def get_events_for_context(self, max_events: int = 5) -> list[dict[str, Any]]:
        """Get events formatted for context injection."""
        events = self.get_upcoming_events(days=3, max_events=max_events)
        return events


class EmailConnector:
    """Unified email interface."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "connectors" / "email"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._dir / "messages_cache.json"
        self._messages: list[EmailMessage] = []
        self._load_cache()
    
    def _load_cache(self) -> None:
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._messages = [EmailMessage(**m) for m in data]
        except Exception as e:
            logger.warning("Failed to load email cache: %s", e)
    
    def _save_cache(self) -> None:
        try:
            self._cache_file.write_text(
                json.dumps([m.__dict__ for m in self._messages], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save email cache: %s", e)
    
    def add_message(self, message: EmailMessage) -> None:
        self._messages.append(message)
        self._save_cache()
    
    def get_recent_messages(self, hours: int = 24, max_messages: int = 10) -> list[dict[str, Any]]:
        """Get recent messages within N hours."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        
        recent = []
        for msg in self._messages:
            try:
                received = datetime.fromisoformat(msg.received_at.replace('Z', '+00:00'))
                if received >= cutoff:
                    recent.append({
                        "message_id": msg.message_id,
                        "subject": msg.subject,
                        "from": msg.from_addr,
                        "to": msg.to_addrs,
                        "snippet": msg.snippet or msg.body[:200],
                        "received_at": msg.received_at,
                        "labels": msg.labels,
                        "source": msg.source,
                        "has_attachments": msg.has_attachments
                    })
            except Exception:
                continue
        
        recent.sort(key=lambda m: m["received_at"], reverse=True)
        return recent[:max_messages]
    
    def get_messages_for_context(self, max_messages: int = 3) -> list[dict[str, Any]]:
        """Get messages formatted for context injection."""
        return self.get_recent_messages(hours=48, max_messages=max_messages)


class FileConnector:
    """Unified file interface."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "connectors" / "files"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._dir / "files_cache.json"
        self._files: list[FileContent] = []
        self._load_cache()
    
    def _load_cache(self) -> None:
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._files = [FileContent(**f) for f in data]
        except Exception as e:
            logger.warning("Failed to load file cache: %s", e)
    
    def _save_cache(self) -> None:
        try:
            self._cache_file.write_text(
                json.dumps([f.__dict__ for f in self._files], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save file cache: %s", e)
    
    def add_file(self, file: FileContent) -> None:
        self._files.append(file)
        self._save_cache()
    
    def get_recent_files(self, hours: int = 168, max_files: int = 10) -> list[dict[str, Any]]:
        """Get recently modified files within N hours (default 1 week)."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        
        recent = []
        for file in self._files:
            try:
                modified = datetime.fromisoformat(file.modified_at.replace('Z', '+00:00'))
                if modified >= cutoff:
                    recent.append({
                        "file_id": file.file_id,
                        "name": file.name,
                        "path": file.path,
                        "mime_type": file.mime_type,
                        "size": file.size,
                        "summary": file.summary,
                        "content_preview": file.content_preview[:500] if file.content_preview else "",
                        "modified_at": file.modified_at,
                        "source": file.source
                    })
            except Exception:
                continue
        
        recent.sort(key=lambda f: f["modified_at"], reverse=True)
        return recent[:max_files]
    
    def get_files_for_context(self, max_files: int = 3) -> list[dict[str, Any]]:
        """Get files formatted for context injection."""
        return self.get_recent_files(hours=168, max_files=max_files)


class SensorConnector:
    """Unified sensor/IoT interface."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "connectors" / "sensors"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._dir / "sensor_state.json"
        self._state: dict[str, Any] = {}
        self._history_file = self._dir / "sensor_history.jsonl"
        self._load_state()
    
    def _load_state(self) -> None:
        try:
            if self._state_file.exists():
                self._state = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load sensor state: %s", e)
    
    def _save_state(self) -> None:
        try:
            self._state_file.write_text(
                json.dumps(self._state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save sensor state: %s", e)
    
    def update_sensor(self, topic: str, payload: dict[str, Any]) -> None:
        """Update sensor reading."""
        self._state[topic] = {
            "value": payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "topic": topic
        }
        
        # Append to history
        try:
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "topic": datetime.now(timezone.utc).isoformat(),
                    "topic": topic,
                    "payload": payload
                }) + "\n")
        except Exception:
            pass
        
        self._save_state()
    
    def get_state(self) -> dict[str, Any]:
        """Get current sensor state."""
        return self._state
    
    def get_state_for_context(self) -> dict[str, Any]:
        """Get sensor state formatted for context."""
        return self._state


class MultimodalConnectorHub:
    """Central hub for all multimodal data connectors."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.workspace_dir = workspace_dir
        self.calendar = CalendarConnector(workspace_dir)
        self.email = EmailConnector(workspace_dir)
        self.files = FileConnector(workspace_dir)
        self.sensors = SensorConnector(workspace_dir)
    
    def get_all_context_data(self) -> dict[str, Any]:
        """Get all context data from all connectors."""
        return {
            "calendar_events": self.calendar.get_events_for_context(),
            "emails": self.email.get_messages_for_context(),
            "files": self.files.get_files_for_context(),
            "sensor_state": self.sensors.get_state_for_context()
        }
    
    def inject_into_builder(self, builder: "UnifiedMultimodalContextBuilder") -> None:
        """Inject all connector data into the unified context builder."""
        data = self.get_all_context_data()
        builder.update_sensor_state(data["sensor_state"])
        # Calendar, email, files are passed directly to build()
    
    def sync_from_google_calendar(self, credentials: dict[str, Any]) -> int:
        """Sync events from Google Calendar (placeholder)."""
        # Would use google_calendar tool
        return 0
    
    def sync_from_outlook(self, credentials: dict[str, Any]) -> int:
        """Sync events from Outlook/CalDAV (placeholder)."""
        # Would use outlook_calendar tool
        return 0
    
    def sync_from_gmail(self, credentials: dict[str, Any]) -> int:
        """Sync messages from Gmail (placeholder)."""
        # Would use gmail tool
        return 0
    
    def sync_from_google_drive(self, credentials: dict[str, Any]) -> int:
        """Sync files from Google Drive (placeholder)."""
        # Would use google_drive tool
        return 0


# Global instance
_connector_hub: MultimodalConnectorHub | None = None


def get_connector_hub() -> MultimodalConnectorHub:
    """Get global connector hub instance."""
    global _connector_hub
    if _connector_hub is None:
        _connector_hub = MultimodalConnectorHub()
    return _connector_hub