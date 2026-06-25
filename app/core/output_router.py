# app/core/output_router.py
"""Output Priority Router — smart routing of RAVEN responses.

Jarvis doesn't blast every alert through speakers. This module classifies
output by urgency and routes it to the appropriate channel:

  CRITICAL  → Voice announcement + all active platforms + push notification
  HIGH      → Primary platform + voice (if active)
  NORMAL    → Reply on originating platform only
  LOW       → Silent inbox (user checks when they want)
  DIGEST    → Batched and delivered at scheduled intervals

Classification is based on:
  - Content keywords (security, emergency, meeting, etc.)
  - Source system (sentinel = higher priority, forecast = lower)
  - User preferences (do-not-disturb hours, preferred channels)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    CRITICAL = 5
    HIGH = 4
    NORMAL = 3
    LOW = 2
    DIGEST = 1


@dataclass
class RoutedOutput:
    """A classified output with routing metadata."""
    text: str
    priority: Priority
    source: str                             # sentinel, calendar, forecast, user_reply, etc.
    target_platforms: List[str]             # which platforms to deliver to
    use_voice: bool = False                 # also speak through TTS?
    use_notification: bool = False          # push notification?
    silent: bool = False                    # don't notify, just log to inbox


# ── Classification Patterns ────────────────────────────────────────────

_CRITICAL_PATTERNS = re.compile(
    r"\b(intrusion|break.?in|fire|smoke|emergency|unauthorized|alarm|danger|breach)\b",
    re.IGNORECASE,
)

_HIGH_PATTERNS = re.compile(
    r"\b(meeting\s+in\s+\d+|late\s+for|deadline|urgent|critical\s+alert|security\s+alert|"
    r"error\s+rate|down|outage|failed)\b",
    re.IGNORECASE,
)

_LOW_PATTERNS = re.compile(
    r"\b(forecast|prediction|weekly\s+summary|digest|tip|suggestion|"
    r"might\s+want|consider|fyi|heads.?up)\b",
    re.IGNORECASE,
)

# Source-based default priorities
_SOURCE_PRIORITIES: Dict[str, Priority] = {
    "sentinel": Priority.HIGH,
    "sentinel_critical": Priority.CRITICAL,
    "calendar": Priority.HIGH,
    "calendar_summary": Priority.LOW,
    "forecast": Priority.LOW,
    "autonomy": Priority.NORMAL,
    "workflow": Priority.NORMAL,
    "user_reply": Priority.NORMAL,
    "morning_briefing": Priority.NORMAL,
    "self_improvement": Priority.DIGEST,
}


class OutputRouter:
    """Classifies and routes outputs based on priority."""

    def __init__(self) -> None:
        self._dnd_start: int = 23   # Do-Not-Disturb: 11 PM
        self._dnd_end: int = 7     # to 7 AM
        self._user_preferences: Dict[str, Dict[str, Any]] = {}

    # ── Priority Classification ────────────────────────────────────────

    def classify(
        self,
        text: str,
        source: str = "user_reply",
        explicit_priority: Priority | None = None,
    ) -> Priority:
        """Determine the priority of an output."""
        # Explicit override
        if explicit_priority is not None:
            return explicit_priority

        # Source-based default
        priority = _SOURCE_PRIORITIES.get(source, Priority.NORMAL)

        # Content-based escalation
        if _CRITICAL_PATTERNS.search(text):
            priority = max(priority, Priority.CRITICAL)
        elif _HIGH_PATTERNS.search(text):
            priority = max(priority, Priority.HIGH)
        elif _LOW_PATTERNS.search(text):
            priority = min(priority, Priority.LOW)

        return priority

    # ── Routing Decision ───────────────────────────────────────────────

    def route(
        self,
        text: str,
        source: str = "user_reply",
        originating_platform: str = "telegram",
        user_id: str = "",
        explicit_priority: Priority | None = None,
    ) -> RoutedOutput:
        """Classify and determine routing for an output."""
        priority = self.classify(text, source, explicit_priority)
        is_dnd = self._is_dnd_hours()

        target_platforms = [originating_platform]
        use_voice = False
        use_notification = False
        silent = False

        if priority == Priority.CRITICAL:
            # Blast everywhere, even during DND
            target_platforms = self._get_all_platforms(user_id)
            use_voice = True
            use_notification = True

        elif priority == Priority.HIGH:
            # Primary platform + voice if not DND
            use_voice = not is_dnd
            use_notification = True

        elif priority == Priority.NORMAL:
            # Reply on originating platform only
            pass

        elif priority == Priority.LOW:
            # Just originating platform, no voice
            if is_dnd:
                silent = True  # During DND, low priority goes silent

        elif priority == Priority.DIGEST:
            # Always silent — goes to inbox
            silent = True

        return RoutedOutput(
            text=text,
            priority=priority,
            source=source,
            target_platforms=target_platforms,
            use_voice=use_voice,
            use_notification=use_notification,
            silent=silent,
        )

    # ── Do-Not-Disturb ─────────────────────────────────────────────────

    def _is_dnd_hours(self) -> bool:
        """Check if current time is within Do-Not-Disturb window."""
        hour = datetime.now().hour
        if self._dnd_start > self._dnd_end:
            return hour >= self._dnd_start or hour < self._dnd_end
        return self._dnd_start <= hour < self._dnd_end

    def set_dnd(self, start_hour: int, end_hour: int) -> None:
        """Configure Do-Not-Disturb hours."""
        self._dnd_start = start_hour % 24
        self._dnd_end = end_hour % 24
        logger.info("DND set: %02d:00 — %02d:00", self._dnd_start, self._dnd_end)

    # ── Platform Discovery ─────────────────────────────────────────────

    def _get_all_platforms(self, user_id: str) -> List[str]:
        """Get all platforms the user is registered on."""
        try:
            from app.core.user_identity import get_identity_store
            store = get_identity_store()
            aliases = store.get_aliases(user_id)
            return list(set(a["platform"] for a in aliases)) or ["telegram"]
        except Exception:
            return ["telegram", "web"]

    # ── User Preferences ───────────────────────────────────────────────

    def set_user_preference(self, user_id: str, key: str, value: Any) -> None:
        """Store a user routing preference."""
        prefs = self._user_preferences.setdefault(user_id, {})
        prefs[key] = value

    def get_user_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        return self._user_preferences.get(user_id, {}).get(key, default)


# ── Module singleton ───────────────────────────────────────────────────

_ROUTER: OutputRouter | None = None


def get_output_router() -> OutputRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = OutputRouter()
    return _ROUTER
