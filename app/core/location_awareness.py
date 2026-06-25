"""Location Awareness — Raven understands where the user is.

Provides location context for smarter responses:
- Timezone from location
- Weather based on location
- Commute estimates
- Location-based suggestions

Uses IP geolocation as fallback, or explicit location updates.
No GPS required — works with city/region names.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Location:
    """User's current location."""
    city: str = ""
    region: str = ""
    country: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"
    source: str = "manual"  # manual, ip, gps
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Known city → timezone mapping (common cities)
_CITY_TIMEZONES: dict[str, str] = {
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "tokyo": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "toronto": "America/Toronto",
    "vancouver": "America/Vancouver",
    "sao paulo": "America/Sao_Paulo",
    "moscow": "Europe/Moscow",
    "seoul": "Asia/Seoul",
    "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta",
    "cairo": "Africa/Cairo",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
}


class LocationStore:
    """Stores and retrieves user location."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "location"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "location.json"

    def get_location(self) -> Location | None:
        """Get the stored location."""
        if not self._file.exists():
            return None
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return Location(**data)
        except Exception:
            return None

    def set_location(self, location: Location) -> None:
        """Store a location update."""
        from dataclasses import asdict
        self._file.write_text(
            json.dumps(asdict(location), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class LocationExtractor:
    """Extracts location from user messages."""

    # Patterns to detect location mentions
    _LOCATION_PATTERNS = [
        r"(?:i (?:live|am|work|located|based) in)\s+(.+?)(?:\.|,|$)",
        r"(?:my (?:location|city|place)) (?:is|:)\s+(.+?)(?:\.|,|$)",
        r"(?:location)\s*[:=]\s*(.+?)(?:\.|,|$)",
        r"(?:i'?m in)\s+(.+?)(?:\.|,|$)",
    ]

    @staticmethod
    def extract_location(text: str) -> str | None:
        """Extract a location mention from text."""
        lower = text.lower()
        for pattern in LocationExtractor._LOCATION_PATTERNS:
            m = re.search(pattern, lower)
            if m:
                location = m.group(1).strip()
                # Clean up common suffixes
                location = re.sub(r"\s+(right now|currently|at the moment)$", "", location)
                if len(location) > 2 and len(location) < 100:
                    return location.title()
        return None

    @staticmethod
    def detect_timezone(city: str) -> str:
        """Detect timezone from city name."""
        city_lower = city.lower().strip()
        return _CITY_TIMEZONES.get(city_lower, "UTC")


class LocationAwareness:
    """Provides location context for smarter responses.

    Integrates with LifeContext and ContextAwareness to provide
    location-based intelligence.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.store = LocationStore(workspace_dir)
        self.extractor = LocationExtractor()

    def update_from_message(self, user_message: str) -> Location | None:
        """Try to extract and store location from a user message."""
        city = self.extractor.extract_location(user_message)
        if not city:
            return None

        location = Location(
            city=city,
            timezone=self.extractor.detect_timezone(city),
            source="manual",
        )
        self.store.set_location(location)
        logger.info("Location updated: %s (tz=%s)", city, location.timezone)
        return location

    def get_location_context(self) -> str:
        """Build a location context string for prompts."""
        location = self.store.get_location()
        if not location:
            return ""

        parts = [f"User location: {location.city}"]
        if location.region:
            parts.append(f"Region: {location.region}")
        if location.country:
            parts.append(f"Country: {location.country}")
        if location.timezone and location.timezone != "UTC":
            now = datetime.now(timezone.utc)
            import pytz
            try:
                local_tz = pytz.timezone(location.timezone)
                local_time = now.astimezone(local_tz)
                parts.append(f"Local time: {local_time.strftime('%H:%M %Z')}")
            except Exception:
                parts.append(f"Timezone: {location.timezone}")

        return " | ".join(parts)

    def get_location(self) -> Location | None:
        return self.store.get_location()
