from __future__ import annotations

"""Schedule Learner — Learns the user's daily schedule from conversation.

Observes:
- What time the user wakes/sleeps
- Work hours
- Meeting times
- Common routines

Predicts:
- Next day schedule
- Busy times
- Free times
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SchedulePattern:
    """A learned schedule pattern."""
    pattern_type: str  # wake, sleep, work, meeting, routine
    value: str
    confidence: float = 0.5
    last_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    occurrences: int = 1


class ScheduleLearner:
    """Learns the user's daily schedule from conversation patterns."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir or Config.MEMORY_ROOT)
        self.patterns_file = self.workspace_dir / "life_context" / "schedule_patterns.json"
        self.patterns_dir = self.workspace_dir / "life_context"
        self.patterns_dir.mkdir(parents=True, exist_ok=True)
        self._patterns: list[SchedulePattern] = self._load_patterns()

    def learn_from_conversation(self, text: str) -> list[SchedulePattern]:
        """Extract schedule patterns from conversation text."""
        new_patterns: list[SchedulePattern] = []
        low = text.lower()

        # Wake time patterns
        for pat in [
            r"i wake.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"wake up.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"my morning.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                new_patterns.append(SchedulePattern(
                    pattern_type="wake", value=m.group(1), confidence=0.6
                ))
                break

        # Sleep time patterns
        for pat in [
            r"i sleep.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"go to bed.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"bedtime.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                new_patterns.append(SchedulePattern(
                    pattern_type="sleep", value=m.group(1), confidence=0.6
                ))
                break

        # Work hour patterns
        for pat in [
            r"work.*?(?:from|starts?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm)).*?(?:to|until|ends?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"office.*?(?:from|opens?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm)).*?(?:to|until|closes?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                new_patterns.append(SchedulePattern(
                    pattern_type="work_start", value=m.group(1), confidence=0.6
                ))
                new_patterns.append(SchedulePattern(
                    pattern_type="work_end", value=m.group(2), confidence=0.6
                ))
                break

        # Meeting patterns
        for pat in [
            r"meeting.*?(?:at|on).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"call.*?(?:at|on).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                new_patterns.append(SchedulePattern(
                    pattern_type="meeting", value=m.group(1), confidence=0.5
                ))
                break

        # Routine patterns
        for pat in [
            r"i (?:usually|always|typically)\s+(.+?)(?:\.|$)",
            r"every\s+(?:day|morning|evening)\s+(?:i|we)\s+(.+?)(?:\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                new_patterns.append(SchedulePattern(
                    pattern_type="routine", value=m.group(1).strip(),
                    confidence=0.5
                ))
                break

        # Add to patterns
        for p in new_patterns:
            self._patterns.append(p)

        if new_patterns:
            self._save_patterns()
            logger.info("ScheduleLearner: learned %d patterns from conversation", len(new_patterns))

        return new_patterns

    def get_schedule(self) -> dict[str, str]:
        """Get the best-guess schedule based on learned patterns."""
        result: dict[str, str] = {}
        for p in self._patterns:
            if p.pattern_type not in result:
                result[p.pattern_type] = p.value
        return result

    def get_learning_summary(self) -> str:
        """Get a summary of learned schedule patterns."""
        if not self._patterns:
            return "No schedule patterns learned yet."

        lines = ["=== Learned Schedule Patterns ===", ""]
        by_type: dict[str, list[SchedulePattern]] = {}
        for p in self._patterns:
            by_type.setdefault(p.pattern_type, []).append(p)

        for ptype, patterns in by_type.items():
            lines.append(f"{ptype}:")
            for p in patterns:
                lines.append(f"  - {p.value} (confidence: {p.confidence:.0%})")
            lines.append("")

        return "\n".join(lines)

    # ── Persistence ─────────────────────────────────────────────

    def _load_patterns(self) -> list[SchedulePattern]:
        if not self.patterns_file.exists():
            return []
        try:
            data = json.loads(self.patterns_file.read_text(encoding="utf-8"))
            return [
                SchedulePattern(
                    pattern_type=p.get("pattern_type", ""),
                    value=p.get("value", ""),
                    confidence=p.get("confidence", 0.5),
                    last_seen=p.get("last_seen", ""),
                    occurrences=p.get("occurrences", 1),
                )
                for p in data
            ]
        except Exception:
            return []

    def _save_patterns(self) -> None:
        try:
            data = [
                {
                    "pattern_type": p.pattern_type,
                    "value": p.value,
                    "confidence": p.confidence,
                    "last_seen": p.last_seen,
                    "occurrences": p.occurrences,
                }
                for p in self._patterns
            ]
            self.patterns_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Failed to save patterns: %s", exc)


# ── Singleton ───────────────────────────────────────────────────
_learner: ScheduleLearner | None = None


def get_schedule_learner(workspace_dir: str | None = None) -> ScheduleLearner:
    global _learner
    if _learner is None:
        _learner = ScheduleLearner(workspace_dir)
    return _learner
