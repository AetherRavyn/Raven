"""Core dataclasses for the hierarchical planner.

All planner sub-modules import from here. The shapes are stable; the
storage layer serializes these to HelixDB nodes/edges (see
``app.core.planning.store``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class PlanStatus(str, Enum):
    """Lifecycle of a ``TaskPlan`` as a whole."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"

    @property
    def is_terminal(self) -> bool:
        return self in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.ABANDONED}


class StepStatus(str, Enum):
    """Lifecycle of a single ``PlanStep``."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED}


# Discriminated union over what a step actually *does*.
StepAction = Literal["tool", "subplan", "llm", "ask_user", "wait"]


@dataclass(slots=True)
class PlanStep:
    """A single node in a plan graph.

    ``deps`` are the step IDs that must reach ``COMPLETED`` before this
    step may run. ``parallel_group`` lets the executor batch steps that
    have no inter-dependencies.
    """

    id: str
    description: str
    action: StepAction
    # tool call payload
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    # LLM call payload
    prompt: str | None = None
    # user-ask payload
    ask_question: str | None = None
    # wait payload (seconds, or ISO-8601 absolute)
    wait_seconds: float | None = None
    # graph
    deps: list[str] = field(default_factory=list)
    parallel_group: int = 0
    # estimation + verification
    cost_estimate: dict[str, Any] = field(default_factory=dict)
    success_criteria: str | None = None
    # runtime
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    attempts: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # replanning metadata
    replanned_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "action": self.action,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "prompt": self.prompt,
            "ask_question": self.ask_question,
            "wait_seconds": self.wait_seconds,
            "deps": list(self.deps),
            "parallel_group": self.parallel_group,
            "cost_estimate": dict(self.cost_estimate),
            "success_criteria": self.success_criteria,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "attempts": self.attempts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "replanned_from": self.replanned_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanStep":
        return cls(
            id=data["id"],
            description=data["description"],
            action=data["action"],
            tool_name=data.get("tool_name"),
            tool_args=data.get("tool_args") or {},
            prompt=data.get("prompt"),
            ask_question=data.get("ask_question"),
            wait_seconds=data.get("wait_seconds"),
            deps=list(data.get("deps") or []),
            parallel_group=int(data.get("parallel_group", 0)),
            cost_estimate=data.get("cost_estimate") or {},
            success_criteria=data.get("success_criteria"),
            status=StepStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            attempts=int(data.get("attempts", 0)),
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            replanned_from=data.get("replanned_from"),
        )


@dataclass(slots=True)
class TaskPlan:
    """A directed acyclic graph of ``PlanStep`` nodes.

    The plan carries its own bookkeeping so the executor can be stateless
    and the plan can be persisted + resumed across crashes.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    user_id: str | None = None
    status: PlanStatus = PlanStatus.PENDING
    steps: list[PlanStep] = field(default_factory=list)
    # aggregates
    cost_total: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    # replan log
    replan_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)
        self.updated_at = datetime.now(timezone.utc)

    def get_step(self, step_id: str) -> PlanStep:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(f"step not found: {step_id}")

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    def ready_steps(self) -> list[PlanStep]:
        """Steps whose deps are all completed."""
        done = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        return [
            s
            for s in self.steps
            if s.status == StepStatus.PENDING and all(d in done for d in s.deps)
        ]

    def parallel_groups(self) -> list[list[PlanStep]]:
        """Group ready steps by ``parallel_group`` for batch execution."""
        ready = self.ready_steps()
        groups: dict[int, list[PlanStep]] = {}
        for s in ready:
            groups.setdefault(s.parallel_group, []).append(s)
        return [g for _, g in sorted(groups.items())]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "user_id": self.user_id,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "cost_total": dict(self.cost_total),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "replan_count": self.replan_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        return cls(
            id=data["id"],
            goal=data.get("goal", ""),
            user_id=data.get("user_id"),
            status=PlanStatus(data.get("status", "pending")),
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            cost_total=data.get("cost_total") or {},
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(timezone.utc),
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            replan_count=int(data.get("replan_count", 0)),
            metadata=data.get("metadata") or {},
        )

    # ------------------------------------------------------------------
    # Invariants
    # ------------------------------------------------------------------

    def is_well_formed(self) -> bool:
        """DAG + no duplicate ids + every dep points to a real step."""
        ids = {s.id for s in self.steps}
        if len(ids) != len(self.steps):
            return False
        for s in self.steps:
            for d in s.deps:
                if d not in ids:
                    return False
        # cycle check via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {s.id: WHITE for s in self.steps}

        def visit(node: str) -> bool:
            color[node] = GRAY
            for d in self.get_step(node).deps:
                if color[d] == GRAY:
                    return False
                if color[d] == WHITE and not visit(d):
                    return False
            color[node] = BLACK
            return True

        return all(visit(s.id) for s in self.steps if color[s.id] == WHITE)
