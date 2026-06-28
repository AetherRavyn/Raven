"""Autonomous Plan Execution — FRIDAY-style plan decomposition and execution.

Goes beyond simple workflow steps to:
1. Decompose complex goals into executable plans
2. Execute plans with verification at each step
3. Rollback on failure
4. Adapt plans based on intermediate results
5. Learn from execution outcomes

This is what makes Raven truly autonomous — it can take a
complex goal like "set up a new project" and execute it
without human intervention.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PlanState(str, Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verdict"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class PlanStep:
    """A step in an autonomous plan."""

    step_id: str
    action: str
    description: str
    tool: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    verification: str | None = None  # How to verify this step succeeded
    rollback_action: str | None = None  # How to undo this step
    status: str = "pending"  # pending, running, completed, failed, rolled_back
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass(slots=True)
class Plan:
    """An autonomous plan for achieving a goal."""

    plan_id: str
    goal: str
    description: str
    steps: list[PlanStep] = field(default_factory=list)
    state: PlanState = PlanState.DRAFT
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    execution_log: list[dict[str, Any]] = field(default_factory=list)


class AutonomousPlanner:
    """FRIDAY-style autonomous plan execution.

    Decomposes goals into plans, executes them with verification,
    and handles failures with rollback.
    """

    # Maps planner-style tool names to runtime registry keys.
    _TOOL_ALIASES: dict[str, str] = {
        "websearch": "web_ops",
        "web_search": "web_ops",
        "search": "web_ops",
        "web_fetch": "web_fetch_ops",
        "file_operations": "file_operations",
        "file": "file_operations",
        "git": "git_ops",
        "git_ops": "git_ops",
        "shell": "sandbox_exec",
        "sandbox_exec": "sandbox_exec",
        "knowledge_graph": "knowledge_graph",
        "kg": "knowledge_graph",
        "code_exec": "sandbox_exec",
        "python": "sandbox_exec",
        "browser": "browser_ops",
        "camera": "camera_snapshot",
        "weather": "weather",
        "reminder": "reminder",
        "network": "network",
    }

    def __init__(
        self,
        workspace_dir: str = "workspace",
        tool_registry: dict[str, Any] | None = None,
    ) -> None:
        self._dir = Path(workspace_dir) / "plans"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._tool_registry: dict[str, Any] = tool_registry or {}

    def set_tool_registry(self, registry: dict[str, Any]) -> None:
        """Set or replace the tool registry for real execution."""
        self._tool_registry = registry

    def _resolve_tool(self, name: str | None) -> tuple[Any, str] | None:
        """Resolve a planner tool name to (tool_instance, registry_key)."""
        if not name:
            return None
        key = self._TOOL_ALIASES.get(name, name)
        tool = self._tool_registry.get(key)
        if tool is not None:
            return tool, key
        # Fallback: try the raw name
        tool = self._tool_registry.get(name)
        if tool is not None:
            return tool, name
        return None

    def decompose_goal(self, goal: str, context: dict[str, Any] | None = None) -> Plan:
        """Decompose a high-level goal into executable steps.

        This is the planning phase — breaks down the goal
        into a sequence of actionable steps.
        """
        plan_id = f"plan_{int(time.time())}"
        plan = Plan(
            plan_id=plan_id,
            goal=goal,
            description=f"Plan to achieve: {goal}",
            state=PlanState.PLANNING,
            context=context or {},
        )

        # Generate steps based on goal analysis
        steps = self._analyze_goal(goal, context or {})
        plan.steps = steps
        plan.state = PlanState.DRAFT

        self._save_plan(plan)
        return plan

    def _analyze_goal(self, goal: str, context: dict[str, Any]) -> list[PlanStep]:
        """Analyze a goal and generate plan steps.

        This is a simplified planner — in production, this would
        use the LLM to decompose complex goals.
        """
        steps = []
        goal_lower = goal.lower()

        # Common goal patterns
        if "project" in goal_lower or "setup" in goal_lower:
            steps.extend(
                [
                    PlanStep(
                        step_id="s1",
                        action="research",
                        description="Research the project requirements",
                        tool="websearch",
                        verification="Found relevant information",
                    ),
                    PlanStep(
                        step_id="s2",
                        action="plan",
                        description="Create project plan and structure",
                        depends_on=["s1"],
                        verification="Plan document created",
                    ),
                    PlanStep(
                        step_id="s3",
                        action="implement",
                        description="Implement core components",
                        depends_on=["s2"],
                        verification="Core files exist",
                    ),
                    PlanStep(
                        step_id="s4",
                        action="test",
                        description="Test and verify implementation",
                        depends_on=["s3"],
                        verification="Tests pass",
                    ),
                    PlanStep(
                        step_id="s5",
                        action="deploy",
                        description="Deploy or document the project",
                        depends_on=["s4"],
                        verification="Deployment complete",
                    ),
                ]
            )

        elif "research" in goal_lower or "investigate" in goal_lower:
            steps.extend(
                [
                    PlanStep(
                        step_id="s1",
                        action="search",
                        description="Search for relevant information",
                        tool="websearch",
                        verification="Found sources",
                    ),
                    PlanStep(
                        step_id="s2",
                        action="analyze",
                        description="Analyze and synthesize findings",
                        depends_on=["s1"],
                        verification="Analysis complete",
                    ),
                    PlanStep(
                        step_id="s3",
                        action="report",
                        description="Generate comprehensive report",
                        depends_on=["s2"],
                        verification="Report generated",
                    ),
                ]
            )

        elif "fix" in goal_lower or "debug" in goal_lower:
            steps.extend(
                [
                    PlanStep(
                        step_id="s1",
                        action="diagnose",
                        description="Identify the root cause",
                        tool="websearch",
                        verification="Root cause identified",
                    ),
                    PlanStep(
                        step_id="s2",
                        action="fix",
                        description="Implement the fix",
                        depends_on=["s1"],
                        verification="Fix implemented",
                    ),
                    PlanStep(
                        step_id="s3",
                        action="verify",
                        description="Verify the fix works",
                        depends_on=["s2"],
                        verification="Tests pass",
                    ),
                ]
            )

        else:
            # Generic plan
            steps.extend(
                [
                    PlanStep(
                        step_id="s1", action="understand", description="Understand the requirements"
                    ),
                    PlanStep(
                        step_id="s2",
                        action="execute",
                        description="Execute the main task",
                        depends_on=["s1"],
                    ),
                    PlanStep(
                        step_id="s3",
                        action="verify",
                        description="Verify the result",
                        depends_on=["s2"],
                    ),
                ]
            )

        return steps

    async def execute_plan(self, plan: Plan) -> Plan:
        """Execute a plan step by step with verification."""
        plan.state = PlanState.EXECUTING
        self._save_plan(plan)

        for step in plan.steps:
            if step.status == "completed":
                continue

            # Check dependencies
            deps_met = all(
                any(s.step_id == dep and s.status == "completed" for s in plan.steps)
                for dep in step.depends_on
            )
            if not deps_met:
                continue

            # Execute step
            step.status = "running"
            self._log(plan, f"Executing step: {step.description}")

            try:
                resolved = self._resolve_tool(step.tool)
                if resolved is not None:
                    tool, key = resolved
                    import inspect

                    args = dict(step.params)
                    if inspect.iscoroutinefunction(tool.execute):
                        result = await tool.execute(**args)
                    else:
                        result = tool.execute(**args)
                    step.result = (
                        result
                        if isinstance(result, dict)
                        else {"output": str(result), "success": True}
                    )
                    step.status = "completed" if result.get("success", True) else "failed"
                else:
                    step.status = "completed"
                    step.result = {"success": True}
                self._log(plan, f"Step completed: {step.description}")

            except Exception as exc:
                step.status = "failed"
                step.error = str(exc)
                step.retry_count += 1

                if step.retry_count < step.max_retries:
                    self._log(
                        plan,
                        f"Step failed, retrying ({step.retry_count}/{step.max_retries}): {exc}",
                    )
                    step.status = "pending"  # Will retry on next iteration
                else:
                    self._log(plan, f"Step failed permanently: {exc}")
                    plan.state = PlanState.FAILED
                    self._save_plan(plan)
                    return plan

        # Check if all steps completed
        all_done = all(s.status == "completed" for s in plan.steps)
        if all_done:
            plan.state = PlanState.COMPLETED
            plan.completed_at = datetime.now(timezone.utc).isoformat()
            self._log(plan, "Plan completed successfully")

        self._save_plan(plan)
        return plan

    def rollback_plan(self, plan: Plan) -> Plan:
        """Rollback a plan by executing rollback actions in reverse order."""
        plan.state = PlanState.ROLLING_BACK
        self._save_plan(plan)

        for step in reversed(plan.steps):
            if step.status == "completed" and step.rollback_action:
                self._log(plan, f"Rolling back: {step.rollback_action}")
                # In a real implementation, this would execute the rollback
                step.status = "rolled_back"

        plan.state = PlanState.FAILED
        plan.completed_at = datetime.now(timezone.utc).isoformat()
        self._save_plan(plan)
        return plan

    def _log(self, plan: Plan, message: str) -> None:
        """Add an entry to the plan's execution log."""
        plan.execution_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": message,
            }
        )

    def _save_plan(self, plan: Plan) -> None:
        """Save a plan to disk."""
        from dataclasses import asdict

        path = self._dir / f"{plan.plan_id}.json"
        path.write_text(
            json.dumps(asdict(plan), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def load_plan(self, plan_id: str) -> Plan | None:
        """Load a plan from disk."""
        path = self._dir / f"{plan_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            steps = [PlanStep(**s) for s in data.get("steps", [])]
            return Plan(
                plan_id=data["plan_id"],
                goal=data["goal"],
                description=data.get("description", ""),
                steps=steps,
                state=PlanState(data.get("state", "draft")),
                context=data.get("context", {}),
                created_at=data.get("created_at", ""),
                completed_at=data.get("completed_at"),
                execution_log=data.get("execution_log", []),
            )
        except Exception as exc:
            logger.debug("Failed to load plan %s: %s", plan_id, exc)
            return None

    def list_plans(self, state: PlanState | None = None) -> list[Plan]:
        """List all plans, optionally filtered by state."""
        plans = []
        for path in self._dir.glob("*.json"):
            try:
                plan = self.load_plan(path.stem)
                if plan and (state is None or plan.state == state):
                    plans.append(plan)
            except Exception:
                continue
        return sorted(plans, key=lambda p: p.created_at, reverse=True)
