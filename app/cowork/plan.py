"""Cowork plan + plan-step dataclasses.

A plan is generated from a goal by the worker (or by a planner
LLM call).  Each step has:

- a human-readable title + description
- an action (e.g. ``"read_file"``, ``"write_file"``, ``"apply_patch"``,
  ``"run_shell"``, ``"search"``)
- the target paths / commands the step intends to touch
- a ``status`` that drives the UI (pending / awaiting_approval /
  running / done / failed / skipped)
- an optional ``risk`` field that the UI uses to colour the row

The user can approve / reject steps individually, or ``approve_all``
the entire plan at once.  The worker checks approval before
executing any step.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class StepStatus(str, Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


@dataclass(slots=True)
class PlanStep:
    id: str
    title: str
    description: str
    action: str  # read_file | write_file | apply_patch | run_shell | search
    # Free-form per-action arguments.  Examples:
    #   {"path": "README.md"}                                  (read_file)
    #   {"path": "src/foo.py", "content": "..."}              (write_file)
    #   {"path": "src/foo.py", "patch": "..."}                (apply_patch)
    #   {"command": "pytest -q", "timeout_s": 60}             (run_shell)
    #   {"query": "TODO", "glob": "**/*.py"}                  (search)
    args: dict[str, Any] = field(default_factory=dict)
    # Files this step will touch (for diff preview + per-step audit).
    target_paths: list[str] = field(default_factory=list)
    # Risk classification: low (read-only) | medium (single-file edit) |
    # high (multi-file, deletes, or runs shell).  Drives the UI badge.
    risk: str = "low"
    # Depends-on step ids — the worker runs in topo order.
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    # Outputs produced by execution (diffs, command results, etc.).
    result: Optional[dict[str, Any]] = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:10]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PlanStep":
        raw = dict(raw)
        raw["status"] = StepStatus(raw.get("status", "pending"))
        return cls(**raw)


@dataclass(slots=True)
class Plan:
    id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    # Short human-readable title (e.g. "Refactor auth module").
    # Set by LLM planners; left empty by the rule planner.
    title: str = ""
    # Plan-level approval flag — when set, the worker doesn't ask
    # per-step (still asks for high-risk steps by default).
    approved_all: bool = False
    # Free-form notes from the planner.
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]

    def step(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def awaiting_steps(self) -> list[PlanStep]:
        return [
            s
            for s in self.steps
            if s.status in {StepStatus.AWAITING_APPROVAL, StepStatus.APPROVED}
        ]

    def progress(self) -> tuple[int, int]:
        """Return ``(done, total)`` for the progress bar."""
        done = sum(
            1
            for s in self.steps
            if s.status in {StepStatus.DONE, StepStatus.SKIPPED, StepStatus.REJECTED}
        )
        return done, len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "created_at": self.created_at,
            "approved_all": self.approved_all,
            "notes": self.notes,
            "steps": [s.to_dict() for s in self.steps],
            "progress": list(self.progress()),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Plan":
        steps_raw = raw.get("steps", [])
        return cls(
            id=raw["id"],
            goal=raw["goal"],
            steps=[PlanStep.from_dict(s) for s in steps_raw],
            created_at=raw.get("created_at", time.time()),
            approved_all=raw.get("approved_all", False),
            notes=raw.get("notes", ""),
        )
