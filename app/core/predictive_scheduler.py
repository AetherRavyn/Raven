"""Predictive Scheduling — FRIDAY-style auto-scheduling.

Learns from user behavior to predict and auto-schedule:
- Best time for deep work (based on coding patterns)
- Best time for meetings (based on calendar history)
- Best time for exercise (based on activity patterns)
- Break reminders (based on work duration)
- Follow-up scheduling (based on commitment tracking)

Uses the pattern learner to extract temporal patterns
and the cron engine to create schedules.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScheduleSuggestion:
    """A suggested schedule based on learned patterns."""
    title: str
    description: str
    suggested_time: str  # "HH:MM" or "cron expression"
    schedule_type: str  # "daily_at", "interval_minutes", "cron"
    confidence: float
    reason: str
    source_pattern: str = ""


class PredictiveScheduler:
    """Learns from user behavior and suggests schedules.

    FRIDAY-style: notices patterns like "user codes best at 9am"
    and suggests "Start deep work block at 9:00 AM daily".
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "predictive_schedules"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._suggestions_file = self._dir / "suggestions.jsonl"

    def analyze_patterns(self, patterns: list[dict[str, Any]]) -> list[ScheduleSuggestion]:
        """Analyze learned patterns and generate schedule suggestions."""
        suggestions = []

        # Time-preference patterns
        for pattern in patterns:
            if pattern.get("pattern_type") == "time_preference":
                hour = pattern.get("metadata", {}).get("hour")
                topic = pattern.get("metadata", {}).get("topic", "")
                confidence = pattern.get("confidence", 0.3)

                if hour and topic and confidence > 0.4:
                    suggestions.append(ScheduleSuggestion(
                        title=f"Optimal {topic} time",
                        description=f"You tend to {topic} around {hour}:00. Schedule focused blocks then.",
                        suggested_time=f"{hour:02d}:00",
                        schedule_type="daily_at",
                        confidence=confidence,
                        reason=f"Pattern: {topic} at hour {hour} (confidence: {confidence:.0%})",
                        source_pattern=pattern.get("description", ""),
                    ))

        # Topic-interest patterns → suggest regular research
        topic_counts: dict[str, int] = {}
        for pattern in patterns:
            if pattern.get("pattern_type") == "topic_interest":
                topic = pattern.get("metadata", {}).get("topic", "")
                if topic:
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1

        for topic, count in topic_counts.items():
            if count >= 3:
                suggestions.append(ScheduleSuggestion(
                    title=f"{topic.title()} research reminder",
                    description=f"You've discussed {topic} {count} times. Consider a weekly review.",
                    suggested_time="0 10 * * 1",  # Monday at 10am
                    schedule_type="cron",
                    confidence=min(0.3 + count * 0.1, 0.8),
                    reason=f"Topic frequency: {count} mentions",
                    source_pattern=f"topic_interest:{topic}",
                ))

        # Work duration patterns → suggest breaks
        work_hours = [p.get("metadata", {}).get("hour", 0) for p in patterns
                     if p.get("pattern_type") == "time_preference"
                     and p.get("metadata", {}).get("topic") == "coding"]

        if len(work_hours) >= 5:
            avg_hour = sum(work_hours) / len(work_hours)
            suggestions.append(ScheduleSuggestion(
                title="Deep work block",
                description=f"Schedule 2-hour focused coding blocks starting at {int(avg_hour):02d}:00",
                suggested_time=f"{int(avg_hour):02d}:00",
                schedule_type="daily_at",
                confidence=0.6,
                reason=f"Based on {len(work_hours)} coding sessions",
                source_pattern="work_duration",
            ))

            # Suggest breaks every 2 hours
            suggestions.append(ScheduleSuggestion(
                title="Break reminder",
                description="Take a 10-minute break every 2 hours during deep work",
                suggested_time="0 */2 * * *",
                schedule_type="cron",
                confidence=0.5,
                reason="Standard Pomodoro-adjacent rhythm",
                source_pattern="break_reminder",
            ))

        # Sort by confidence
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:10]  # Top 10 suggestions

    def save_suggestions(self, suggestions: list[ScheduleSuggestion]) -> None:
        """Save suggestions to disk."""
        from dataclasses import asdict
        with open(self._suggestions_file, "a", encoding="utf-8") as f:
            for s in suggestions:
                f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")

    def get_suggestions(self, limit: int = 10) -> list[ScheduleSuggestion]:
        """Get recent suggestions."""
        if not self._suggestions_file.exists():
            return []
        suggestions = []
        for line in self._suggestions_file.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                suggestions.append(ScheduleSuggestion(**data))
            except Exception:
                continue
        return suggestions[:limit]

    def auto_schedule(self, suggestion: ScheduleSuggestion) -> dict[str, Any]:
        """Automatically create a cron job from a suggestion."""
        from app.core.cron_engine import CronEngine
        engine = CronEngine()

        job_id = f"predictive_{suggestion.title.lower().replace(' ', '_')}"

        return engine.add_job(
            job_id=job_id,
            name=suggestion.title,
            description=suggestion.description,
            schedule_type=suggestion.schedule_type,
            action_description=suggestion.description,
            time_str=suggestion.suggested_time if suggestion.schedule_type == "daily_at" else None,
            cron_expr=suggestion.suggested_time if suggestion.schedule_type == "cron" else None,
        )
