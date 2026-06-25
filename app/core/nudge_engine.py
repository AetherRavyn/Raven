"""Nudge System — proactive reminders and knowledge persistence prompts.

FRIDAY-style: periodically reminds the user to:
- Save important information
- Review pending tasks
- Update their profile
- Check on goals
- Follow up on habits
- Review world model entities

Nudges are sent via BotSignal when the user is available.
They're context-aware (don't nudge during quiet hours).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Nudge:
    """A proactive nudge to the user."""
    nudge_type: str  # save_memory, review_task, update_profile, check_goal, habit_reminder, world_model
    message: str
    priority: str = "low"  # low, medium, high
    cooldown_hours: float = 24.0
    last_sent: float = 0.0


class NudgeEngine:
    """FRIDAY-style proactive nudge system."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "nudges"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._nudges_file = self._dir / "nudge_state.json"
        self._nudges = self._load_nudges()

    def _load_nudges(self) -> dict[str, float]:
        if not self._nudges_file.exists():
            return {}
        try:
            return json.loads(self._nudges_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_nudges(self) -> None:
        self._nudges_file.write_text(json.dumps(self._nudges, indent=2), encoding="utf-8")

    def generate_nudges(self, context: dict[str, Any] | None = None) -> list[Nudge]:
        """Generate context-aware nudges from world model, tasks, habits."""
        nudges: list[Nudge] = []
        now = time.time()
        ctx = context or {}

        # ── Task-based nudges ────────────────────────────────────
        if self._should_nudge("save_memory", now, 6 * 3600):
            pending = ctx.get("pending_tasks", [])
            if pending:
                nudges.append(Nudge(nudge_type="save_memory",
                    message=f"You have {len(pending)} pending tasks. Save a progress update?",
                    priority="low", cooldown_hours=6))

        if self._should_nudge("review_tasks", now, 12 * 3600):
            overdue = ctx.get("overdue_tasks", [])
            if overdue:
                nudges.append(Nudge(nudge_type="review_task",
                    message=f"{len(overdue)} overdue task(s). Help prioritize?",
                    priority="medium", cooldown_hours=12))

        if self._should_nudge("check_goal", now, 24 * 3600):
            nudges.append(Nudge(nudge_type="check_goal",
                message="Review your goals and progress?",
                priority="low", cooldown_hours=24))

        # ── World model nudges ──────────────────────────────────
        if self._should_nudge("world_model", now, 48 * 3600):
            try:
                from app.core.world_model import WorldModel
                wm = WorldModel()
                people = wm.find_entities(entity_type="person")
                stale = [p for p in people if not p.last_seen or (now - _parse_iso(p.last_seen)) > 30 * 86400]
                if stale:
                    names = ", ".join(p.name for p in stale[:3])
                    nudges.append(Nudge(nudge_type="world_model",
                        message=f"Haven't mentioned {names} in a while. Want to update their info?",
                        priority="low", cooldown_hours=48))
            except Exception:
                pass

        # ── Habit nudges ────────────────────────────────────────
        if self._should_nudge("habit_reminder", now, 24 * 3600):
            try:
                from app.core.world_model import WorldModel
                wm = WorldModel()
                habits = wm._load_habits()
                for habit_name, timestamps in habits.items():
                    if timestamps:
                        last = _parse_iso(timestamps[-1])
                        days_since = (now - last) / 86400
                        freq = len(timestamps) / max(30, 1)
                        if freq > 0.3 and days_since > 2:
                            nudges.append(Nudge(nudge_type="habit_reminder",
                                message=f"It's been {int(days_since)} days since you last did '{habit_name}'. Want to get back on track?",
                                priority="low", cooldown_hours=24))
                            break  # Max one habit nudge per cycle
            except Exception:
                pass

        # ── Personality nudge ───────────────────────────────────
        if self._should_nudge("personality_review", now, 168 * 3600):
            try:
                from app.core.adaptive_personality import AdaptivePersonality
                ap = AdaptivePersonality()
                profile = ap.get_profile()
                trending = [name for name, trait in profile.traits.items() if trait.trend != "stable"]
                if trending:
                    nudges.append(Nudge(nudge_type="personality_review",
                        message=f"My communication style is evolving ({', '.join(trending)}). Check it out?",
                        priority="low", cooldown_hours=168))
            except Exception:
                pass

        return nudges

    def _should_nudge(self, nudge_type: str, now: float, cooldown: float) -> bool:
        last_sent = self._nudges.get(nudge_type, 0.0)
        return (now - last_sent) >= cooldown

    def mark_sent(self, nudge_type: str) -> None:
        self._nudges[nudge_type] = time.time()
        self._save_nudges()


def _parse_iso(ts: str | float) -> float:
    """Parse an ISO timestamp or float to Unix time."""
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


_nudge_engine: NudgeEngine | None = None

def get_nudge_engine() -> NudgeEngine:
    global _nudge_engine
    if _nudge_engine is None:
        _nudge_engine = NudgeEngine()
    return _nudge_engine
