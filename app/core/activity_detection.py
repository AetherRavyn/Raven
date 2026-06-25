"""Activity Detection — Raven understands what the user is currently doing.

Uses context clues to infer the user's current activity:
- Time of day patterns (morning = waking up, night = sleeping)
- Recent conversation topics (coding = working, gaming = leisure)
- Device usage (mobile = on-the-go, desktop = at desk)
- Calendar events (meeting = in meeting)
- Sensor data (camera, presence)

No GPS required — works from behavioral patterns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Activity:
    """User's current activity."""
    activity: str  # working, sleeping, commuting, exercising, relaxing, meeting, cooking, etc.
    confidence: float = 0.5  # 0.0 = uncertain, 1.0 = very confident
    source: str = "inferred"  # inferred, explicit, sensor
    details: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Activity patterns based on time of day
_TIME_ACTIVITIES: list[tuple[int, int, str, float]] = [
    (6, 8, "waking_up", 0.7),
    (8, 9, "morning_routine", 0.6),
    (9, 12, "working", 0.8),
    (12, 13, "lunch_break", 0.7),
    (13, 17, "working", 0.8),
    (17, 18, "commuting", 0.5),
    (18, 20, "evening_routine", 0.6),
    (20, 22, "relaxing", 0.6),
    (22, 24, "sleeping", 0.7),
    (0, 6, "sleeping", 0.8),
]

# Activity keywords
_ACTIVITY_KEYWORDS: dict[str, list[str]] = {
    "working": ["code", "implement", "debug", "deploy", "review", "pr", "commit", "refactor", "bug", "fix"],
    "gaming": ["game", "play", "match", "score", "win", "lose", "level"],
    "exercising": ["run", "gym", "workout", "exercise", "bike", "walk", "yoga"],
    "cooking": ["recipe", "cook", "bake", "ingredient", "meal", "dinner", "lunch"],
    "commuting": ["commute", "drive", "train", "bus", "traffic", "route"],
    "meeting": ["meeting", "call", "zoom", "standup", "sync", "presentation"],
    "reading": ["read", "book", "article", "paper", "study", "research"],
    "shopping": ["buy", "shop", "order", "price", "discount", "sale"],
    "relaxing": ["movie", "music", "show", "podcast", "youtube", "netflix"],
    "sleeping": ["sleep", "tired", "nap", "bedtime", "goodnight"],
}


class ActivityDetector:
    """Detects user activity from context clues."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "activity"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "activity.json"

    def detect_from_time(self) -> Activity:
        """Detect activity based on time of day."""
        now = datetime.now(timezone.utc)
        hour = now.hour

        for start, end, activity, confidence in _TIME_ACTIVITIES:
            if start <= hour < end:
                return Activity(
                    activity=activity,
                    confidence=confidence,
                    source="inferred",
                    details=f"Time-based: {hour}:00 UTC",
                )

        return Activity(activity="unknown", confidence=0.1, source="inferred")

    def detect_from_message(self, message: str) -> Activity | None:
        """Detect activity from conversation content."""
        lower = message.lower()
        words = set(lower.split())

        best_activity = None
        best_score = 0

        for activity, keywords in _ACTIVITY_KEYWORDS.items():
            matches = len(words & set(keywords))
            if matches > best_score:
                best_score = matches
                best_activity = activity

        if best_activity and best_score >= 2:
            return Activity(
                activity=best_activity,
                confidence=min(0.3 + best_score * 0.15, 0.9),
                source="explicit",
                details=f"Keyword match: {best_score} keywords",
            )

        return None

    def detect_from_calendar(self, calendar_events: list[dict[str, Any]]) -> Activity | None:
        """Detect activity from calendar events."""
        now = datetime.now(timezone.utc)
        for event in calendar_events:
            start = event.get("start", "")
            end = event.get("end", "")
            title = event.get("title", "")
            if start and end:
                try:
                    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    if start_dt <= now <= end_dt:
                        return Activity(
                            activity="meeting" if "meeting" in title.lower() else "busy",
                            confidence=0.9,
                            source="calendar",
                            details=title,
                        )
                except Exception:
                    continue
        return None

    def get_current_activity(self, user_id: str = "default") -> Activity:
        """Get the best-guess current activity from all sources."""
        # Check stored activity
        stored = self._load()
        if stored and stored.source == "explicit":
            return stored  # Explicit overrides everything

        # Try time-based
        time_activity = self.detect_from_time()

        # Try stored context
        if stored and stored.confidence > time_activity.confidence:
            return stored

        return time_activity

    def update_activity(self, activity: Activity) -> None:
        """Store an activity update."""
        self._save(activity)

    def _load(self) -> Activity | None:
        if not self._file.exists():
            return None
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return Activity(**data)
        except Exception:
            return None

    def _save(self, activity: Activity) -> None:
        from dataclasses import asdict
        self._file.write_text(
            json.dumps(asdict(activity), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_activity_context(self) -> str:
        """Build activity context string for prompts."""
        activity = self.get_current_activity()
        if not activity or activity.activity == "unknown":
            return ""
        return f"User activity: {activity.activity} (confidence: {activity.confidence:.0%})"
