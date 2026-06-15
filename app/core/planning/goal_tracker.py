"""Long-horizon goal tracking.

A ``Goal`` is a high-level outcome the user wants to achieve, with an
optional deadline.  The tracker decomposes a goal into daily/weekly
sub-plans and tracks progress across sessions.

The tracker is intentionally simple: it stores goals in HelixDB
(via :class:`PlanStore`) and surfaces a daily digest to the
ambient loop.  Auto-decomposition is rule-based; an LLM can be
plugged in via :class:`GoalTracker.decomposer`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.core.planning.types import PlanStatus, TaskPlan

logger = logging.getLogger(__name__)


class GoalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"

    @property
    def is_terminal(self) -> bool:
        return self in {GoalStatus.COMPLETED, GoalStatus.ABANDONED}


Decomposer = Callable[["Goal"], Awaitable[list[TaskPlan]]]


@dataclass(slots=True)
class Goal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    user_id: str | None = None
    status: GoalStatus = GoalStatus.PENDING
    deadline: datetime | None = None
    sub_plans: list[str] = field(default_factory=list)  # plan ids
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    progress: float = 0.0  # 0..1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "user_id": self.user_id,
            "status": self.status.value,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "sub_plans": list(self.sub_plans),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "progress": self.progress,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Goal":
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            user_id=data.get("user_id"),
            status=GoalStatus(data.get("status", "pending")),
            deadline=datetime.fromisoformat(data["deadline"])
            if data.get("deadline")
            else None,
            sub_plans=list(data.get("sub_plans") or []),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(timezone.utc),
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            progress=float(data.get("progress", 0.0)),
            metadata=data.get("metadata") or {},
        )


@dataclass(slots=True)
class GoalTracker:
    """Manages long-horizon goals and their sub-plans."""

    store: Any = None  # PlanStore
    decomposer: Optional[Decomposer] = None  # LLM-backed decomposition
    # rule-based default: split goal into N sub-plans by deadline
    default_subplan_count: int = 3

    async def create(
        self,
        title: str,
        *,
        description: str = "",
        user_id: str | None = None,
        deadline: datetime | None = None,
    ) -> Goal:
        goal = Goal(
            title=title, description=description, user_id=user_id, deadline=deadline
        )
        if self.decomposer is not None:
            try:
                sub_plans = await self.decomposer(goal)
                for p in sub_plans:
                    p.metadata["goal_id"] = goal.id
                    if self.store is not None:
                        await self.store.save(p)
                    goal.sub_plans.append(p.id)
                    if goal.status == GoalStatus.PENDING:
                        goal.status = GoalStatus.ACTIVE
            except Exception as e:  # noqa: BLE001
                logger.warning("decomposer failed (%s); using rule-based", e)
                self._rule_decompose(goal)
        else:
            self._rule_decompose(goal)

        if goal.status == GoalStatus.PENDING and goal.sub_plans:
            goal.status = GoalStatus.ACTIVE

        if self.store is not None:
            await self.store.save_goal(goal)
        return goal

    def _rule_decompose(self, goal: Goal) -> None:
        """Default decomposition: N sub-plans spaced between now and deadline."""
        n = max(1, self.default_subplan_count)
        if goal.deadline is None:
            # No deadline → 1 sub-plan
            n = 1
        now = datetime.now(timezone.utc)
        deadline = goal.deadline
        # Be liberal in what we accept: normalize naive datetimes to UTC.
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        span = (deadline - now) if deadline else timedelta(days=1)
        for i in range(n):
            scheduled = now + span * (i / max(1, n))
            plan = TaskPlan(
                goal=f"{goal.title} (step {i + 1}/{n})",
                user_id=goal.user_id,
                metadata={
                    "goal_id": goal.id,
                    "step_index": i,
                    "scheduled_for": scheduled.isoformat(),
                },
            )
            goal.sub_plans.append(plan.id)
            # Save synchronously via the store's underlying cache.
            # (create() will also call store.save_goal, but we need the
            # sub-plans visible to progress tracking immediately.)
            if self.store is not None:
                self.store._cache[plan.id] = {  # type: ignore[attr-defined]
                    "id": plan.id,
                    "user_id": plan.user_id or "",
                    "status": plan.status.value,
                    "payload": __import__("json").dumps(plan.to_dict()),
                }

    async def update_progress(self, goal: Goal) -> None:
        """Recompute progress from sub-plans in the store."""
        if not goal.sub_plans or self.store is None:
            return
        completed = 0
        for plan_id in goal.sub_plans:
            plan = await self.store.load(plan_id)
            if plan is None:
                continue
            if plan.status == PlanStatus.COMPLETED:
                completed += 1
        goal.progress = completed / len(goal.sub_plans)
        goal.updated_at = datetime.now(timezone.utc)
        if goal.progress >= 1.0:
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = datetime.now(timezone.utc)
        await self.store.save_goal(goal)

    async def active_goals(self, user_id: str | None = None) -> list[Goal]:
        if self.store is None:
            return []
        return await self.store.list_goals(user_id=user_id, status=GoalStatus.ACTIVE)


__all__ = ["Goal", "GoalStatus", "GoalTracker"]
