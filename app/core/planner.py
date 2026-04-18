from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    """Lightweight planner for decomposing a user goal into concrete steps."""

    def plan(self, goal: str) -> TaskPlan:
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
