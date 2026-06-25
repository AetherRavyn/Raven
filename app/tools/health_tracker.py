"""Health Tracker — sleep, exercise, nutrition logging with trends.

FRIDAY-style: Raven tracks the user's health data locally,
identifies trends, and can nudge about patterns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HealthEntry:
    entry_type: str  # sleep, exercise, nutrition, mood, weight
    value: float
    unit: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthTrackerTool(BaseTool):
    """Track sleep, exercise, nutrition, and health metrics."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "health"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entries_file = self._dir / "entries.jsonl"

    def get_name(self) -> str:
        return "health_tracker"

    def get_description(self) -> str:
        return (
            "Track health metrics: sleep (hours/quality), exercise (type/duration/calories), "
            "nutrition (calories/meals), mood, weight. Log entries, view trends, get summaries."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["log", "today", "week", "stats", "trends"],
                    "description": "Operation to perform",
                },
                "entry_type": {
                    "type": "string",
                    "enum": ["sleep", "exercise", "nutrition", "mood", "weight"],
                    "description": "Type of health entry",
                },
                "value": {"type": "number", "description": "Numeric value (hours, calories, kg, etc.)"},
                "unit": {"type": "string", "description": "Unit of measurement"},
                "metadata": {"type": "object", "description": "Additional details (exercise type, meal items, sleep quality)"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "today")

        if operation == "log":
            return self._log_entry(
                entry_type=kwargs.get("entry_type", ""),
                value=kwargs.get("value", 0),
                unit=kwargs.get("unit", ""),
                metadata=kwargs.get("metadata", {}),
            )
        elif operation == "today":
            return self._get_today()
        elif operation == "week":
            return self._get_week()
        elif operation == "stats":
            return self._get_stats()
        elif operation == "trends":
            return self._get_trends()
        return {"error": f"Unknown operation: {operation}"}

    def _load_entries(self) -> list[dict]:
        if not self._entries_file.exists():
            return []
        entries = []
        for line in self._entries_file.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return entries

    def _log_entry(self, entry_type: str, value: float, unit: str, metadata: dict) -> dict:
        if not entry_type:
            return {"error": "entry_type is required (sleep, exercise, nutrition, mood, weight)"}
        entry = HealthEntry(
            entry_type=entry_type, value=value, unit=unit, metadata=metadata,
        )
        from dataclasses import asdict
        with open(self._entries_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return {"logged": True, "type": entry_type, "value": value, "unit": unit}

    def _get_today(self) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        entries = [
            e for e in self._load_entries()
            if e.get("timestamp", "")[:10] == today
        ]
        by_type: dict[str, list] = {}
        for e in entries:
            by_type.setdefault(e.get("entry_type", ""), []).append(e)
        summary: dict[str, Any] = {}
        if "sleep" in by_type:
            summary["sleep_hours"] = sum(e["value"] for e in by_type["sleep"])
        if "exercise" in by_type:
            summary["exercise_count"] = len(by_type["exercise"])
            summary["exercise_calories"] = sum(
                e.get("metadata", {}).get("calories", 0) for e in by_type["exercise"]
            )
        if "nutrition" in by_type:
            summary["meals"] = len(by_type["nutrition"])
            summary["total_calories"] = sum(e["value"] for e in by_type["nutrition"])
        if "mood" in by_type:
            avg_mood = sum(e["value"] for e in by_type["mood"]) / len(by_type["mood"])
            summary["avg_mood"] = round(avg_mood, 1)
        summary["entries_today"] = len(entries)
        return summary

    def _get_week(self) -> dict:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        entries = [
            e for e in self._load_entries()
            if e.get("timestamp", "")[:10] >= week_ago
        ]
        by_type: dict[str, list] = {}
        for e in entries:
            by_type.setdefault(e.get("entry_type", ""), []).append(e)
        return {
            "total_entries": len(entries),
            "types": {t: len(v) for t, v in by_type.items()},
            "date_range": f"{week_ago} to {datetime.now(timezone.utc).date().isoformat()}",
        }

    def _get_stats(self) -> dict:
        entries = self._load_entries()
        if not entries:
            return {"total_entries": 0, "message": "No entries yet. Start logging!"}
        by_type: dict[str, list] = {}
        for e in entries:
            by_type.setdefault(e.get("entry_type", ""), []).append(e)
        stats: dict[str, Any] = {"total_entries": len(entries), "types": {}}
        for t, items in by_type.items():
            values = [i["value"] for i in items]
            stats["types"][t] = {
                "count": len(items),
                "avg": round(sum(values) / len(values), 2) if values else 0,
                "min": min(values) if values else 0,
                "max": max(values) if values else 0,
            }
        return stats

    def _get_trends(self) -> dict:
        entries = self._load_entries()
        if len(entries) < 7:
            return {"message": "Need at least 7 entries for trend analysis"}
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        two_weeks_ago = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        this_week = [e for e in entries if e.get("timestamp", "")[:10] >= week_ago]
        last_week = [
            e for e in entries
            if two_weeks_ago <= e.get("timestamp", "")[:10] < week_ago
        ]
        trends: dict[str, str] = {}
        for entry_type in set(e.get("entry_type") for e in entries):
            tw_vals = [e["value"] for e in this_week if e.get("entry_type") == entry_type]
            lw_vals = [e["value"] for e in last_week if e.get("entry_type") == entry_type]
            if tw_vals and lw_vals:
                tw_avg = sum(tw_vals) / len(tw_vals)
                lw_avg = sum(lw_vals) / len(lw_vals)
                if tw_avg > lw_avg * 1.1:
                    trends[entry_type] = "increasing"
                elif tw_avg < lw_avg * 0.9:
                    trends[entry_type] = "decreasing"
                else:
                    trends[entry_type] = "stable"
        return {"trends": trends, "this_week_entries": len(this_week), "last_week_entries": len(last_week)}
