from __future__ import annotations

"""Task Decomposer — Breaks goals into executable tasks using user context.

Takes a high-level goal and produces:
- Individual tasks with deadlines
- Task dependencies
- Priority assignments
- Time estimates

Uses LifeContext to:
- Schedule tasks around existing work
- Respect user's work hours
- Account for current projects
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DecomposedTask:
    """A single task produced by the decomposer."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    priority: int = 3  # 1=highest, 5=lowest
    estimated_minutes: int = 30
    deadline: str | None = None
    dependencies: list[str] = field(default_factory=list)
    project: str | None = None
    status: str = "pending"  # pending, in_progress, completed, cancelled
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TaskDecomposer:
    """Breaks goals into executable tasks using user context."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir or Config.MEMORY_ROOT)
        self.tasks_file = self.workspace_dir / "life_context" / "decomposed_tasks.json"
        self.tasks_dir = self.workspace_dir / "life_context"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: list[DecomposedTask] = self._load_tasks()

    def decompose_goal(
        self,
        goal: str,
        user_context: Any = None,
    ) -> list[DecomposedTask]:
        """Break a goal into executable tasks.

        Uses heuristic decomposition based on goal keywords.
        Can be enhanced with LLM for smarter decomposition.
        """
        new_tasks: list[DecomposedTask] = []
        goal_lower = goal.lower()

        # Project-based decomposition
        project_name = self._extract_project(goal_lower)

        # Common goal patterns
        if any(kw in goal_lower for kw in ["deploy", "ship", "release", "launch"]):
            new_tasks.extend(self._decompose_deploy_goal(goal, project_name))
        elif any(kw in goal_lower for kw in ["learn", "study", "understand", "read"]):
            new_tasks.extend(self._decompose_learning_goal(goal, project_name))
        elif any(kw in goal_lower for kw in ["build", "create", "implement", "develop"]):
            new_tasks.extend(self._decompose_build_goal(goal, project_name))
        elif any(kw in goal_lower for kw in ["fix", "repair", "debug", "resolve"]):
            new_tasks.extend(self._decompose_fix_goal(goal, project_name))
        elif any(kw in goal_lower for kw in ["plan", "organize", "prepare", "set up"]):
            new_tasks.extend(self._decompose_planning_goal(goal, project_name))
        else:
            new_tasks.extend(self._decompose_generic_goal(goal, project_name))

        # Apply context-based scheduling
        if user_context:
            self._apply_schedule_context(new_tasks, user_context)

        # Save tasks
        for t in new_tasks:
            self._tasks.append(t)
        self._save_tasks()

        logger.info("TaskDecomposer: decomposed '%s' into %d tasks", goal, len(new_tasks))
        return new_tasks

    def get_pending_tasks(self, project: str | None = None) -> list[DecomposedTask]:
        """Get all pending tasks, optionally filtered by project."""
        tasks = [t for t in self._tasks if t.status == "pending"]
        if project:
            tasks = [t for t in tasks if t.project == project]
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed."""
        for t in self._tasks:
            if t.id == task_id:
                t.status = "completed"
                self._save_tasks()
                return True
        return False

    def get_task_summary(self) -> str:
        """Get a summary of all tasks."""
        pending = [t for t in self._tasks if t.status == "pending"]
        completed = [t for t in self._tasks if t.status == "completed"]
        in_progress = [t for t in self._tasks if t.status == "in_progress"]

        lines = ["=== Task Summary ===", ""]
        if pending:
            lines.append(f"Pending: {len(pending)}")
            for t in pending[:10]:
                lines.append(f"  [{t.priority}] {t.title}")
        if in_progress:
            lines.append(f"\nIn Progress: {len(in_progress)}")
            for t in in_progress:
                lines.append(f"  [{t.priority}] {t.title}")
        if completed:
            lines.append(f"\nCompleted: {len(completed)}")

        return "\n".join(lines)

    def clear_completed(self) -> int:
        """Remove completed tasks. Returns count removed."""
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.status != "completed"]
        removed = before - len(self._tasks)
        if removed:
            self._save_tasks()
        return removed

    # ── Goal Decomposition Patterns ─────────────────────────────

    def _decompose_deploy_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Review code changes for: {goal}", priority=2, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Run tests before deployment", priority=1, project=project, estimated_minutes=20),
            DecomposedTask(title=f"Update version and changelog", priority=3, project=project, estimated_minutes=15),
            DecomposedTask(title=f"Deploy to production", priority=1, project=project, estimated_minutes=10),
            DecomposedTask(title=f"Verify deployment is working", priority=1, project=project, estimated_minutes=15),
        ]

    def _decompose_learning_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Research: {goal}", priority=3, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Create learning plan for: {goal}", priority=3, project=project, estimated_minutes=15),
            DecomposedTask(title=f"Study and take notes: {goal}", priority=3, project=project, estimated_minutes=60),
            DecomposedTask(title=f"Practice and apply: {goal}", priority=3, project=project, estimated_minutes=45),
        ]

    def _decompose_build_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Define requirements for: {goal}", priority=2, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Design architecture for: {goal}", priority=2, project=project, estimated_minutes=45),
            DecomposedTask(title=f"Implement core components: {goal}", priority=1, project=project, estimated_minutes=120),
            DecomposedTask(title=f"Test and iterate: {goal}", priority=2, project=project, estimated_minutes=60),
            DecomposedTask(title=f"Document and finalize: {goal}", priority=3, project=project, estimated_minutes=30),
        ]

    def _decompose_fix_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Reproduce the issue: {goal}", priority=1, project=project, estimated_minutes=20),
            DecomposedTask(title=f"Identify root cause: {goal}", priority=1, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Implement fix: {goal}", priority=1, project=project, estimated_minutes=45),
            DecomposedTask(title=f"Test fix and verify: {goal}", priority=1, project=project, estimated_minutes=20),
        ]

    def _decompose_planning_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Gather requirements: {goal}", priority=2, project=project, estimated_minutes=20),
            DecomposedTask(title=f"Create plan: {goal}", priority=2, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Review plan: {goal}", priority=3, project=project, estimated_minutes=15),
            DecomposedTask(title=f"Execute plan: {goal}", priority=2, project=project, estimated_minutes=60),
        ]

    def _decompose_generic_goal(self, goal: str, project: str | None) -> list[DecomposedTask]:
        return [
            DecomposedTask(title=f"Research: {goal}", priority=3, project=project, estimated_minutes=30),
            DecomposedTask(title=f"Plan: {goal}", priority=3, project=project, estimated_minutes=20),
            DecomposedTask(title=f"Execute: {goal}", priority=2, project=project, estimated_minutes=60),
            DecomposedTask(title=f"Review: {goal}", priority=3, project=project, estimated_minutes=15),
        ]

    def _extract_project(self, goal_lower: str) -> str | None:
        """Try to extract a project name from the goal."""
        for kw in ["project", "app", "website", "api", "bot", "tool"]:
            if kw in goal_lower:
                words = goal_lower.split()
                idx = words.index(kw)
                if idx > 0:
                    return " ".join(words[max(0, idx - 2):idx + 1]).title()
        return None

    def _apply_schedule_context(
        self, tasks: list[DecomposedTask], ctx: Any
    ) -> None:
        """Adjust task deadlines based on user's schedule."""
        if not hasattr(ctx, 'work_start') or not ctx.work_start:
            return
        # Just mark tasks with estimated time
        for t in tasks:
            if t.estimated_minutes > 60:
                t.priority = min(t.priority, 2)  # Big tasks get higher priority

    # ── Persistence ─────────────────────────────────────────────

    def _load_tasks(self) -> list[DecomposedTask]:
        if not self.tasks_file.exists():
            return []
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
            return [
                DecomposedTask(
                    id=t.get("id", ""), title=t.get("title", ""),
                    description=t.get("description", ""), priority=t.get("priority", 3),
                    estimated_minutes=t.get("estimated_minutes", 30),
                    deadline=t.get("deadline"), dependencies=t.get("dependencies", []),
                    project=t.get("project"), status=t.get("status", "pending"),
                    created_at=t.get("created_at", ""),
                )
                for t in data
            ]
        except Exception:
            return []

    def _save_tasks(self) -> None:
        try:
            data = [
                {
                    "id": t.id, "title": t.title, "description": t.description,
                    "priority": t.priority, "estimated_minutes": t.estimated_minutes,
                    "deadline": t.deadline, "dependencies": t.dependencies,
                    "project": t.project, "status": t.status,
                    "created_at": t.created_at,
                }
                for t in self._tasks
            ]
            self.tasks_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Failed to save tasks: %s", exc)


# ── Singleton ───────────────────────────────────────────────────
_decomposer: TaskDecomposer | None = None


def get_task_decomposer(workspace_dir: str | None = None) -> TaskDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer(workspace_dir)
    return _decomposer
