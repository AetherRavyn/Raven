"""Goal Manager — Autonomous multi-day goal pursuit with task decomposition.

Enables AetherRavyn to autonomously pursue complex, multi-step goals over
days or weeks. Goals are decomposed into subtasks, tracked, and advanced
during ambient loop cycles.

Usage:
    manager = GoalManager()
    goal = await manager.create_goal("Deploy v2.0", "Ship the new release")
    report = await manager.advance_goals()
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class SubTask:
    """A single step toward completing a goal."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    status: str = SubTaskStatus.PENDING.value
    result: str = ""
    depends_on: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    attempts: int = 0
    max_attempts: int = 3


@dataclass
class Goal:
    """A high-level objective with decomposed subtasks."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    priority: int = 3  # 1 (highest) to 5
    status: str = GoalStatus.ACTIVE.value
    subtasks: list[SubTask] = field(default_factory=list)
    progress: float = 0.0
    deadline: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = ""
    completed_at: str = ""
    journal: list[str] = field(default_factory=list)

    def update_progress(self) -> float:
        """Recalculate progress from subtask completion."""
        if not self.subtasks:
            self.progress = 0.0
            return 0.0
        done = sum(1 for s in self.subtasks if s.status == SubTaskStatus.COMPLETED.value)
        self.progress = done / len(self.subtasks)
        return self.progress

    def get_next_subtask(self) -> SubTask | None:
        """Find the next actionable subtask (pending, not blocked)."""
        for sub in self.subtasks:
            if sub.status != SubTaskStatus.PENDING.value:
                continue
            if sub.attempts >= sub.max_attempts:
                sub.status = SubTaskStatus.FAILED.value
                continue
            # Check dependencies
            if sub.depends_on:
                dep_met = all(
                    any(
                        s.id == dep_id and s.status == SubTaskStatus.COMPLETED.value
                        for s in self.subtasks
                    )
                    for dep_id in sub.depends_on
                )
                if not dep_met:
                    continue
            return sub
        return None

    def is_complete(self) -> bool:
        return all(
            s.status in (SubTaskStatus.COMPLETED.value, SubTaskStatus.FAILED.value)
            for s in self.subtasks
        )

    def add_journal_entry(self, entry: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        self.journal.append(f"[{ts}] {entry}")


class GoalManager:
    """Manages autonomous goal pursuit with persistence."""

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            from app.settings.config import Config
            store_dir = Path(Config.MEMORY_ROOT) / "goals"
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._goals: dict[str, Goal] = {}
        self._load()

    # ── Goal CRUD ───────────────────────────────────────────────────

    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: int = 3,
        subtasks: list[dict[str, str]] | None = None,
        tags: list[str] | None = None,
        deadline: str = "",
    ) -> Goal:
        """Create a new goal with optional subtasks."""
        goal = Goal(
            title=title,
            description=description,
            priority=max(1, min(5, priority)),
            deadline=deadline,
            tags=tags or [],
        )

        if subtasks:
            for st_data in subtasks:
                goal.subtasks.append(SubTask(
                    title=st_data.get("title", ""),
                    description=st_data.get("description", ""),
                    depends_on=st_data.get("depends_on", []),
                ))

        goal.add_journal_entry(f"Created: {title}")
        self._goals[goal.id] = goal
        self._save()
        logger.info("Created goal: %s (%s)", goal.title, goal.id)
        return goal

    def get_goal(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    def list_goals(
        self, status: str | None = None, tag: str | None = None
    ) -> list[Goal]:
        """List goals, optionally filtered by status or tag."""
        goals = list(self._goals.values())
        if status:
            goals = [g for g in goals if g.status == status]
        if tag:
            goals = [g for g in goals if tag in g.tags]
        return sorted(goals, key=lambda g: g.priority)

    def get_active_goals(self) -> list[Goal]:
        return self.list_goals(status=GoalStatus.ACTIVE.value)

    # ── Subtask Management ──────────────────────────────────────────

    def add_subtask(
        self, goal_id: str, title: str, description: str = "",
        depends_on: list[str] | None = None,
    ) -> SubTask | None:
        goal = self._goals.get(goal_id)
        if not goal:
            return None
        sub = SubTask(
            title=title,
            description=description,
            depends_on=depends_on or [],
        )
        goal.subtasks.append(sub)
        goal.add_journal_entry(f"Added subtask: {title}")
        self._save()
        return sub

    def complete_subtask(
        self, goal_id: str, subtask_id: str, result: str = ""
    ) -> bool:
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        for sub in goal.subtasks:
            if sub.id == subtask_id:
                sub.status = SubTaskStatus.COMPLETED.value
                sub.result = result
                sub.completed_at = datetime.now(timezone.utc).isoformat()
                goal.update_progress()
                goal.add_journal_entry(
                    f"Completed subtask: {sub.title} ({goal.progress:.0%})"
                )
                # Auto-complete goal if all subtasks done
                if goal.is_complete():
                    goal.status = GoalStatus.COMPLETED.value
                    goal.completed_at = datetime.now(timezone.utc).isoformat()
                    goal.add_journal_entry("Goal completed!")
                self._save()
                return True
        return False

    def fail_subtask(
        self, goal_id: str, subtask_id: str, reason: str = ""
    ) -> bool:
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        for sub in goal.subtasks:
            if sub.id == subtask_id:
                sub.status = SubTaskStatus.FAILED.value
                sub.result = reason
                goal.add_journal_entry(f"Failed subtask: {sub.title} — {reason}")
                self._save()
                return True
        return False

    # ── Goal Lifecycle ──────────────────────────────────────────────

    def pause_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal and goal.status == GoalStatus.ACTIVE.value:
            goal.status = GoalStatus.PAUSED.value
            goal.add_journal_entry("Paused")
            self._save()
            return True
        return False

    def resume_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal and goal.status == GoalStatus.PAUSED.value:
            goal.status = GoalStatus.ACTIVE.value
            goal.add_journal_entry("Resumed")
            self._save()
            return True
        return False

    def cancel_goal(self, goal_id: str, reason: str = "") -> bool:
        goal = self._goals.get(goal_id)
        if goal and goal.status in (GoalStatus.ACTIVE.value, GoalStatus.PAUSED.value):
            goal.status = GoalStatus.CANCELLED.value
            goal.add_journal_entry(f"Cancelled: {reason or 'No reason given'}")
            self._save()
            return True
        return False

    # ── Advancement (called by ambient loop) ────────────────────────

    def advance(self) -> tuple[Goal, SubTask] | None:
        """Find the next goal+subtask to work on.

        Returns (goal, subtask) or None if nothing to do.
        Called periodically by the ambient loop.
        """
        active = self.get_active_goals()
        for goal in active:
            subtask = goal.get_next_subtask()
            if subtask:
                subtask.status = SubTaskStatus.IN_PROGRESS.value
                subtask.attempts += 1
                goal.add_journal_entry(
                    f"Starting subtask: {subtask.title} (attempt {subtask.attempts})"
                )
                self._save()
                return goal, subtask
        return None

    def report_progress(self) -> str:
        """Generate a progress report for all active goals."""
        active = self.get_active_goals()
        if not active:
            return "No active goals."

        lines: list[str] = [f"📋 **Active Goals ({len(active)})**\n"]
        for goal in active:
            goal.update_progress()
            bar = self._progress_bar(goal.progress)
            lines.append(f"### {goal.title} (P{goal.priority})")
            lines.append(f"  {bar} {goal.progress:.0%}")
            for sub in goal.subtasks:
                icon = {"completed": "✅", "in_progress": "🔄", "failed": "❌",
                        "blocked": "🚫"}.get(sub.status, "⬜")
                lines.append(f"  {icon} {sub.title}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _progress_bar(progress: float, width: int = 20) -> str:
        filled = int(progress * width)
        return f"[{'█' * filled}{'░' * (width - filled)}]"

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = {gid: asdict(g) for gid, g in self._goals.items()}
            path = self._store_dir / "goals.json"
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("Failed to save goals: %s", exc)

    def _load(self) -> None:
        path = self._store_dir / "goals.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for gid, gdata in data.items():
                subtasks_raw = gdata.pop("subtasks", [])
                goal = Goal(**gdata)
                goal.subtasks = [SubTask(**s) for s in subtasks_raw]
                self._goals[gid] = goal
        except Exception as exc:
            logger.warning("Failed to load goals: %s", exc)


_GLOBAL_GOAL_MANAGER: GoalManager | None = None


def get_goal_manager() -> GoalManager:
    global _GLOBAL_GOAL_MANAGER
    if _GLOBAL_GOAL_MANAGER is None:
        _GLOBAL_GOAL_MANAGER = GoalManager()
    return _GLOBAL_GOAL_MANAGER
