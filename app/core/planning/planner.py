"""Rule-based + LLM-augmented planner.

The planner turns a user goal into a ``TaskPlan``.  It is intentionally
deterministic so the test suite is reproducible; an LLM is only consulted
when (a) a provider is configured and (b) the rule-based classifier is
unconfident.

Algorithm:

1. **Classify** the goal into a ``GoalKind`` (regex/keyword match).
2. **Template** — pick a plan template for that kind and instantiate it.
3. **Estimate** — attach a cost estimate to each step.
4. **Validate** — assert the resulting plan is a well-formed DAG.

For an LLM-augmented path, see :meth:`Planner.plan_with_llm`.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.core.planning.cost_estimator import CostEstimator
from app.core.planning.types import PlanStep, TaskPlan

logger = logging.getLogger(__name__)


class GoalKind(str, Enum):
    """Coarse taxonomy of user goals."""

    GREETING = "greeting"
    TIME_QUERY = "time_query"
    STATUS_QUERY = "status_query"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    CODE_TASK = "code_task"
    RESEARCH = "research"
    SHELL_TASK = "shell_task"
    REMINDER = "reminder"
    UNKNOWN = "unknown"


# A provider that can produce a plan when the rule-based path is uncertain.
LLMPlanner = Callable[[str, list[dict[str, Any]]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class Planner:
    """Builds ``TaskPlan`` objects from free-text goals."""

    cost_estimator: CostEstimator = field(default_factory=CostEstimator)
    llm_planner: Optional[LLMPlanner] = None
    # confidence threshold below which we ask the LLM
    llm_confidence_threshold: float = 0.4

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskPlan:
        """Produce a ``TaskPlan`` for ``goal``.

        Always returns a plan — at minimum a single ``ask_user`` step that
        asks for clarification, if nothing else fits.
        """
        ctx = context or {}
        kind, confidence = self.classify(goal)

        if kind is GoalKind.UNKNOWN or confidence < self.llm_confidence_threshold:
            if self.llm_planner is not None:
                try:
                    plan = await self._llm_plan(goal, ctx)
                    if plan.is_well_formed():
                        plan.user_id = user_id
                        plan.metadata.setdefault("source", "llm")
                        plan.metadata.setdefault("goal_kind", kind.value)
                        plan.metadata.setdefault("confidence", confidence)
                        return plan
                except Exception as e:  # noqa: BLE001
                    logger.warning("LLM planner failed (%s); falling back to rules", e)

        plan = self._template_plan(goal, kind, ctx)
        plan.user_id = user_id
        plan.metadata.setdefault("source", "rules")
        plan.metadata.setdefault("goal_kind", kind.value)
        plan.metadata.setdefault("confidence", confidence)
        self.cost_estimator.estimate_plan(plan)
        return plan

    async def plan_with_llm(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskPlan:
        """Force the LLM path.  Raises if no provider is configured."""
        if self.llm_planner is None:
            raise RuntimeError("no LLM planner configured")
        plan = await self._llm_plan(goal, context or {})
        plan.user_id = user_id
        plan.metadata.setdefault("source", "llm")
        self.cost_estimator.estimate_plan(plan)
        return plan

    # ------------------------------------------------------------------
    # Classifier
    # ------------------------------------------------------------------

    def classify(self, goal: str) -> tuple[GoalKind, float]:
        """Return (kind, confidence in 0..1)."""
        g = goal.lower().strip()

        # 1.0: greetings and meta
        if re.search(
            r"^\s*(hi|hello|hey|yo|hola|namaste|good (morning|afternoon|evening))\b", g
        ):
            return GoalKind.GREETING, 1.0
        if re.search(r"\b(what(?:'s| is) the )?time\b", g):
            return GoalKind.TIME_QUERY, 0.95
        if re.search(r"\b(status|health|how are you|are you (up|alive|there))\b", g):
            return GoalKind.STATUS_QUERY, 0.9

        # 0.85+: very specific patterns
        if re.search(r"\bread (the )?file\b", g):
            return GoalKind.FILE_READ, 0.85
        if re.search(r"\b(remind|reminder) me\b", g):
            return GoalKind.REMINDER, 0.85
        if re.search(r"\bresearch\b|\binvestigate\b|\bfind out\b", g):
            return GoalKind.RESEARCH, 0.8

        # 0.7: code task
        if re.search(
            r"\b(write|implement|fix|debug|review|refactor|add|create) (a |the |some )?(function|class|module|test|file|method|api|endpoint|bug|feature)\b",
            g,
        ):
            return GoalKind.CODE_TASK, 0.75
        if (
            re.search(r"\b(in )?python\b|\b(in )?rust\b|\b(in )?typescript\b", g)
            and len(g) < 200
        ):
            return GoalKind.CODE_TASK, 0.7

        # 0.65: shell task
        if re.search(r"\b(run|execute|shell|bash|command)\b", g):
            return GoalKind.SHELL_TASK, 0.65

        # 0.6: file write
        if re.search(
            r"\b(write|create|save|edit|update) (a |the |to )?(file|note|doc|readme|script)\b",
            g,
        ):
            return GoalKind.FILE_WRITE, 0.6

        return GoalKind.UNKNOWN, 0.2

    # ------------------------------------------------------------------
    # Plan templates
    # ------------------------------------------------------------------

    def _template_plan(
        self,
        goal: str,
        kind: GoalKind,
        context: dict[str, Any],
    ) -> TaskPlan:
        plan = TaskPlan(goal=goal)
        builder = _PlanBuilder(plan, self.cost_estimator)
        getattr(builder, f"build_{kind.value}", builder.build_unknown)(goal, context)
        return plan

    async def _llm_plan(self, goal: str, context: dict[str, Any]) -> TaskPlan:
        """Build a plan by asking the configured LLM provider.

        Expected response shape (JSON)::

            {
              "steps": [
                {"id": "research", "description": "...",
                 "action": "tool", "tool_name": "web_search",
                 "tool_args": {"query": "..."}, "deps": []}
              ]
            }
        """
        assert self.llm_planner is not None
        raw = await self.llm_planner(
            goal, [{"role": "system", "content": _LLM_SYSTEM_PROMPT}]
        )
        plan = TaskPlan(goal=goal)
        for i, step_data in enumerate(raw.get("steps", [])):
            step = PlanStep(
                id=step_data.get("id") or f"step_{i}_{uuid.uuid4().hex[:6]}",
                description=step_data.get("description", ""),
                action=step_data.get("action", "llm"),
                tool_name=step_data.get("tool_name"),
                tool_args=step_data.get("tool_args", {}),
                prompt=step_data.get("prompt"),
                ask_question=step_data.get("ask_question"),
                wait_seconds=step_data.get("wait_seconds"),
                deps=step_data.get("deps", []),
                parallel_group=step_data.get("parallel_group", 0),
                success_criteria=step_data.get("success_criteria"),
            )
            plan.add_step(step)
        if not plan.steps:
            # LLM returned nothing usable — fall back to a single llm step.
            plan.add_step(
                PlanStep(
                    id="llm_respond",
                    description="Use LLM to answer",
                    action="llm",
                    prompt=goal,
                )
            )
        return plan


class _PlanBuilder:
    """Appends steps to a plan.  Each ``build_*`` produces a complete plan."""

    def __init__(self, plan: TaskPlan, cost: CostEstimator) -> None:
        self.plan = plan
        self.cost = cost

    # ------------------------------------------------------------------
    # Concrete templates
    # ------------------------------------------------------------------

    def build_greeting(self, goal: str, ctx: dict[str, Any]) -> None:
        # No LLM needed; the response is templated.
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Reply with a tailored greeting",
                action="ask_user",
                ask_question=goal,
                success_criteria="user receives a friendly reply",
            )
        )

    def build_time_query(self, goal: str, ctx: dict[str, Any]) -> None:
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Return the current local time",
                action="ask_user",
                ask_question=goal,
                success_criteria="user sees the time",
            )
        )

    def build_status_query(self, goal: str, ctx: dict[str, Any]) -> None:
        self.plan.add_step(
            PlanStep(
                id="status_check",
                description="Collect system + agent status",
                action="tool",
                tool_name="system_stats",
                tool_args={},
            )
        )
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Format a status reply",
                action="llm",
                prompt="Format a concise status report based on the previous step's output.",
                deps=["status_check"],
            )
        )

    def build_file_read(self, goal: str, ctx: dict[str, Any]) -> None:
        path = self._extract_path(goal) or ctx.get("default_path", "")
        self.plan.add_step(
            PlanStep(
                id="read_file",
                description=f"Read file: {path}",
                action="tool",
                tool_name="file_read",
                tool_args={"path": path},
            )
        )
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Summarize the file contents",
                action="llm",
                prompt="Summarize the file contents from the previous step.",
                deps=["read_file"],
            )
        )

    def build_file_write(self, goal: str, ctx: dict[str, Any]) -> None:
        path = self._extract_path(goal) or ctx.get("default_path", "output.txt")
        self.plan.add_step(
            PlanStep(
                id="draft_content",
                description="Draft the file content",
                action="llm",
                prompt=f"Draft content for a file at {path} based on: {goal}",
            )
        )
        self.plan.add_step(
            PlanStep(
                id="write_file",
                description=f"Write to {path}",
                action="tool",
                tool_name="file_write",
                tool_args={"path": path},
                deps=["draft_content"],
            )
        )

    def build_code_task(self, goal: str, ctx: dict[str, Any]) -> None:
        self.plan.add_step(
            PlanStep(
                id="research",
                description="Find similar code or docs",
                action="tool",
                tool_name="web_search",
                tool_args={"query": goal},
            )
        )
        self.plan.add_step(
            PlanStep(
                id="design",
                description="Design the change",
                action="llm",
                prompt=f"Design a code change for: {goal}",
                deps=["research"],
            )
        )
        self.plan.add_step(
            PlanStep(
                id="implement",
                description="Implement the change",
                action="llm",
                prompt=f"Implement: {goal}. Use the design above.",
                deps=["design"],
            )
        )
        self.plan.add_step(
            PlanStep(
                id="verify",
                description="Run tests / lint",
                action="tool",
                tool_name="exec",
                tool_args={"command": "pytest -q || ruff check"},
                deps=["implement"],
            )
        )
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Report results",
                action="llm",
                prompt="Summarize the result of the implementation step for the user.",
                deps=["verify"],
            )
        )

    def build_research(self, goal: str, ctx: dict[str, Any]) -> None:
        self.plan.add_step(
            PlanStep(
                id="search",
                description="Search the web",
                action="tool",
                tool_name="web_search",
                tool_args={"query": goal, "k": 5},
            )
        )
        self.plan.add_step(
            PlanStep(
                id="fetch",
                description="Fetch top results",
                action="tool",
                tool_name="web_fetch",
                tool_args={"urls": "$$search.top_urls"},
                deps=["search"],
                parallel_group=1,
            )
        )
        self.plan.add_step(
            PlanStep(
                id="synthesize",
                description="Synthesize findings",
                action="llm",
                prompt="Synthesize the fetched content into a concise report.",
                deps=["fetch"],
            )
        )
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Reply to user",
                action="llm",
                prompt="Format the synthesis for the user.",
                deps=["synthesize"],
            )
        )

    def build_shell_task(self, goal: str, ctx: dict[str, Any]) -> None:
        # shell tasks require explicit approval — mark as ask_user first.
        self.plan.add_step(
            PlanStep(
                id="confirm",
                description="Confirm the shell command with the user",
                action="ask_user",
                ask_question=f"I will run: {goal}. Proceed?",
            )
        )
        self.plan.add_step(
            PlanStep(
                id="run",
                description="Execute the shell command",
                action="tool",
                tool_name="exec",
                tool_args={"command": goal},
                deps=["confirm"],
            )
        )
        self.plan.add_step(
            PlanStep(
                id="respond",
                description="Show output",
                action="llm",
                prompt="Show the output of the shell command to the user.",
                deps=["run"],
            )
        )

    def build_reminder(self, goal: str, ctx: dict[str, Any]) -> None:
        self.plan.add_step(
            PlanStep(
                id="set_reminder",
                description="Create a reminder",
                action="tool",
                tool_name="reminder",
                tool_args={"text": goal},
            )
        )

    def build_unknown(self, goal: str, ctx: dict[str, Any]) -> None:
        # Fall back to a single LLM step.
        self.plan.add_step(
            PlanStep(
                id="llm_respond",
                description="Use LLM to answer",
                action="llm",
                prompt=goal,
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_path(goal: str) -> str | None:
        m = re.search(r"([/~][\w./\-]+\.[a-zA-Z0-9]{1,8})", goal)
        return m.group(1) if m else None


# ---------------------------------------------------------------------------
# LLM integration helpers
# ---------------------------------------------------------------------------


_LLM_SYSTEM_PROMPT = """\
You are a planning module. Given a user goal, output a JSON object with a
"steps" array. Each step has:

- id: short string
- description: human-readable
- action: one of tool | subplan | llm | ask_user | wait
- tool_name / tool_args: when action=tool
- prompt: when action=llm
- ask_question: when action=ask_user
- wait_seconds: when action=wait
- deps: list of step ids that must finish first
- parallel_group: integer (steps with the same group run in parallel)
- success_criteria: how to verify the step

Constraints:
- 1-10 steps
- No cycles in deps
- Total cost (your estimate) should fit in $0.50
"""


__all__ = ["Planner", "GoalKind"]
