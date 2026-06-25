"""Compat shim — delegates to the new :mod:`app.core.planning` module.

The original 132-line planner lives here for backwards compatibility. New
code should import from :mod:`app.core.planning` directly. This shim
keeps the old ``TaskPlanner`` / ``ResultVerifier`` interface intact so
the existing runtime doesn't break.

The new planner is selected when the env var ``RAVEN_PLANNER_V2=true`` is
set; otherwise we use the legacy rule-based path so nothing regresses
during the migration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# Re-export everything from the new module so downstream callers can
# `from app.core.planner import Planner` and get the new one.
from app.core.planning import (  # noqa: F401
    CostEstimate,
    CostEstimator,
    PlanExecutor,
    Planner,
    PlanStatus,
    PlanStep as _NewPlanStep,
    PlanStore,
    Replanner,
    StepStatus,
    TaskPlan as _NewTaskPlan,
)


# ---------------------------------------------------------------------------
# Legacy shapes (kept verbatim for runtime callers)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PlanStep:
    step: int
    action: str
    description: str
    success_criteria: str = ""
    depends_on: list[int] = field(default_factory=list)


@dataclass(slots=True)
class TaskPlan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskPlanner:
    """Rule-based planner with optional LLM-augmented v2 path.

    When ``RAVEN_PLANNER_V2=true``, this delegates to the new async
    :class:`app.core.planning.Planner`. If an ``llm_planner`` callable
    is provided, complex / low-confidence goals will consult the LLM
    for richer task decomposition.
    """

    def __init__(self, llm_planner=None):
        self._llm_planner = llm_planner

    def plan(self, goal: str) -> TaskPlan:
        return _legacy_plan(goal)

    async def plan_async(self, goal: str) -> TaskPlan:
        if os.environ.get("RAVEN_PLANNER_V2", "").lower() in {"1", "true", "yes"}:
            return await _plan_via_new_planner(goal, self._llm_planner)
        return _legacy_plan(goal)


def _legacy_plan(goal: str) -> TaskPlan:
    text = goal.strip()
    lower = text.lower()
    steps: list[PlanStep] = []

    if any(word in lower for word in ("fix", "bug", "error", "fail", "broken")):
        steps = [
            PlanStep(
                1,
                "inspect",
                "Inspect the failing area and reproduce the issue.",
                "Failure cause identified.",
            ),
            PlanStep(
                2,
                "patch",
                "Apply the smallest safe fix.",
                "Patch aligns with existing patterns.",
                [1],
            ),
            PlanStep(
                3,
                "verify",
                "Run targeted tests and confirm the fix.",
                "Relevant tests pass.",
                [2],
            ),
        ]
    elif any(word in lower for word in ("implement", "build", "add", "create")):
        steps = [
            PlanStep(
                1,
                "design",
                "Map the request to the smallest viable change.",
                "Implementation scope is clear.",
            ),
            PlanStep(
                2,
                "implement",
                "Make the change in the minimal number of files.",
                "Feature behavior is present.",
                [1],
            ),
            PlanStep(
                3,
                "verify",
                "Run focused tests or a targeted smoke check.",
                "Core flow works end to end.",
                [2],
            ),
        ]
    else:
        steps = [
            PlanStep(
                1,
                "understand",
                "Restate the request and identify the core objective.",
                "Objective is explicit.",
            ),
            PlanStep(
                2,
                "act",
                "Perform the main work or gather the answer.",
                "Requested outcome is produced.",
                [1],
            ),
            PlanStep(
                3,
                "verify",
                "Check the output for obvious issues.",
                "Output is internally consistent.",
                [2],
            ),
        ]

    return TaskPlan(
        goal=text,
        steps=steps,
        verification=[s.success_criteria for s in steps if s.success_criteria],
    )


async def _plan_via_new_planner(goal: str, llm_planner=None) -> TaskPlan:
    """Build a plan using the v2 Planner, optionally LLM-augmented."""
    new_plan = await Planner(llm_planner=llm_planner).plan(goal)
    return _adapt_to_legacy(new_plan)


def _adapt_to_legacy(new_plan: _NewTaskPlan) -> TaskPlan:
    """Translate the new ``TaskPlan`` into the legacy shape used by runtime."""
    legacy_steps: list[PlanStep] = []
    step_index_by_id: dict[str, int] = {}
    for i, s in enumerate(new_plan.steps, start=1):
        step_index_by_id[s.id] = i
    for i, s in enumerate(new_plan.steps, start=1):
        legacy_steps.append(
            PlanStep(
                step=i,
                action=_action_to_legacy(s),
                description=s.description,
                success_criteria=s.success_criteria or "",
                depends_on=[step_index_by_id[d] for d in s.deps if d in step_index_by_id],
            )
        )
    return TaskPlan(
        goal=new_plan.goal,
        steps=legacy_steps,
        verification=[s.success_criteria for s in new_plan.steps if s.success_criteria],
        metadata=new_plan.metadata,
    )


def _action_to_legacy(step: _NewPlanStep) -> str:
    """Map a new step to the legacy action vocabulary."""
    if step.action == "tool" and step.tool_name:
        return step.tool_name
    if step.action == "llm":
        return "think"
    if step.action == "ask_user":
        return "confirm"
    if step.action == "wait":
        return "wait"
    if step.action == "subplan":
        return "subplan"
    return step.action or "act"


# ---------------------------------------------------------------------------
# Legacy verifier (unchanged)
# ---------------------------------------------------------------------------


class ResultVerifier:
    """Simple post-action verifier for tool outputs and plan completion."""

    def verify(self, plan: TaskPlan, result: Any) -> dict[str, Any]:
        text = result if isinstance(result, str) else str(result)
        findings: list[str] = []
        passed = True

        if not text.strip():
            passed = False
            findings.append("empty result")

        for criterion in plan.verification:
            if criterion and criterion.lower() not in text.lower():
                findings.append(f"missing criterion: {criterion}")

        if findings:
            passed = False

        return {
            "success": passed,
            "findings": findings,
            "checked_against": plan.verification,
        }


__all__ = [
    "PlanStep",
    "TaskPlan",
    "TaskPlanner",
    "ResultVerifier",
    # Re-exports from the new module
    "CostEstimate",
    "CostEstimator",
    "PlanExecutor",
    "Planner",
    "PlanStatus",
    "PlanStore",
    "Replanner",
    "StepStatus",
]
