"""Persistence for plans, steps, and goals.

The store wraps a :class:`HelixClient` and a simple in-process dict cache.
If Helix is not reachable, the store falls back to the in-memory cache
(plan survives until the process restarts).  The cache is the source of
truth during tests; the HelixDB layer is for production durability.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.planning.goal_tracker import Goal, GoalStatus
from app.core.planning.types import PlanStatus, TaskPlan

logger = logging.getLogger(__name__)


def _plan_to_node_props(plan: TaskPlan) -> dict[str, Any]:
    """Convert a TaskPlan into a flat dict for KV storage."""
    return {
        "id": plan.id,
        "goal": plan.goal,
        "user_id": plan.user_id or "",
        "status": plan.status.value,
        "cost_total": json.dumps(plan.cost_total),
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else "",
        "replan_count": plan.replan_count,
        "metadata": json.dumps(plan.metadata),
        "payload": json.dumps(plan.to_dict()),
    }


def _goal_to_node_props(goal: Goal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "user_id": goal.user_id or "",
        "status": goal.status.value,
        "deadline": goal.deadline.isoformat() if goal.deadline else "",
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
        "completed_at": goal.completed_at.isoformat() if goal.completed_at else "",
        "progress": goal.progress,
        "metadata": json.dumps(goal.metadata),
        "payload": json.dumps(goal.to_dict()),
    }


class PlanStore:
    """Persist plans and goals.  HelixDB primary, in-memory fallback."""

    def __init__(self, helix: Any = None) -> None:
        self._helix = helix  # may be None
        self._cache: dict[str, dict[str, Any]] = {}
        self._goals: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    async def save(self, plan: TaskPlan) -> None:
        props = _plan_to_node_props(plan)
        self._cache[plan.id] = props
        if self._helix is not None:
            try:
                # KV-style write — the Helix schema defines a Plan node + KV index.
                await self._helix.kv_set(f"plan:{plan.id}", props)
            except Exception as e:  # noqa: BLE001
                logger.warning("helix plan save failed: %s", e)

    async def load(self, plan_id: str) -> Optional[TaskPlan]:
        # Try cache first
        cached = self._cache.get(plan_id)
        if cached is None and self._helix is not None:
            try:
                cached = await self._helix.kv_get(f"plan:{plan_id}")
                if cached is not None:
                    self._cache[plan_id] = cached
            except Exception as e:  # noqa: BLE001
                logger.warning("helix plan load failed: %s", e)
        if cached is None:
            return None
        payload = cached.get("payload")
        if not payload:
            return None
        try:
            return TaskPlan.from_dict(json.loads(payload))
        except Exception as e:  # noqa: BLE001
            logger.warning("plan parse failed for %s: %s", plan_id, e)
            return None

    async def list_plans(
        self,
        user_id: str | None = None,
        status: PlanStatus | None = None,
        limit: int = 50,
    ) -> list[TaskPlan]:
        out: list[TaskPlan] = []
        for cached in list(self._cache.values()):
            if user_id and cached.get("user_id") != user_id:
                continue
            if status and cached.get("status") != status.value:
                continue
            try:
                out.append(TaskPlan.from_dict(json.loads(cached["payload"])))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda p: p.updated_at, reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    async def save_goal(self, goal: Goal) -> None:
        props = _goal_to_node_props(goal)
        self._goals[goal.id] = props
        if self._helix is not None:
            try:
                await self._helix.kv_set(f"goal:{goal.id}", props)
            except Exception as e:  # noqa: BLE001
                logger.warning("helix goal save failed: %s", e)

    async def load_goal(self, goal_id: str) -> Optional[Goal]:
        cached = self._goals.get(goal_id)
        if cached is None and self._helix is not None:
            try:
                cached = await self._helix.kv_get(f"goal:{goal_id}")
                if cached is not None:
                    self._goals[goal_id] = cached
            except Exception as e:  # noqa: BLE001
                logger.warning("helix goal load failed: %s", e)
        if cached is None:
            return None
        try:
            return Goal.from_dict(json.loads(cached["payload"]))
        except Exception:  # noqa: BLE001
            return None

    async def list_goals(
        self,
        user_id: str | None = None,
        status: GoalStatus | None = None,
        limit: int = 50,
    ) -> list[Goal]:
        out: list[Goal] = []
        for cached in list(self._goals.values()):
            if user_id and cached.get("user_id") != user_id:
                continue
            if status and cached.get("status") != status.value:
                continue
            try:
                out.append(Goal.from_dict(json.loads(cached["payload"])))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda g: g.updated_at, reverse=True)
        return out[:limit]


__all__ = ["PlanStore"]
