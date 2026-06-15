"""Failure recovery for the planner.

On step failure, the executor asks the :class:`Replanner` for an
alternate strategy.  The replanner produces a new plan that replaces
the failed step (or its descendants) and the executor resumes from the
last good step.

Two strategies are supported out of the box:

- ``Retry`` — re-attempt the same step up to N times (already handled
  by the executor; the replanner can bump N).
- ``SubstituteTool`` — swap the failing tool for a different one
  (e.g. ``web_fetch`` failing → ``web_search``).
- ``Skip`` — if the step is non-critical, mark it skipped and continue.
- ``Abort`` — give up and surface a clear failure to the user.

The default behavior is conservative: the replanner tries ``SubstituteTool``
then ``Skip`` before ``Abort``.  An LLM-augmented replanner can be
configured for richer strategies.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.core.planning.types import PlanStatus, PlanStep, StepStatus, TaskPlan

logger = logging.getLogger(__name__)


class ReplanStrategy(str, Enum):
    RETRY = "retry"
    SUBSTITUTE_TOOL = "substitute_tool"
    SKIP = "skip"
    ABORT = "abort"


ReplanAdvisor = Callable[[PlanStep, str], Awaitable[ReplanStrategy]]


@dataclass(slots=True)
class ReplanResult:
    strategy: ReplanStrategy
    new_step: PlanStep | None = None
    note: str = ""


@dataclass(slots=True)
class Replanner:
    """Decide what to do when a plan step fails."""

    max_replans: int = 3
    advisor: Optional[ReplanAdvisor] = None
    history: list[dict[str, Any]] = field(default_factory=list)

    async def on_failure(self, plan: TaskPlan, failed_step: PlanStep) -> ReplanResult:
        """Return a recovery strategy for the failed step."""
        if plan.replan_count >= self.max_replans:
            return self._apply(plan, failed_step, ReplanStrategy.ABORT)

        # Ask the advisor (LLM) for a strategy if configured
        if self.advisor is not None:
            try:
                strategy = await self.advisor(failed_step, failed_step.error or "")
                return self._apply(plan, failed_step, strategy)
            except Exception as e:  # noqa: BLE001
                logger.warning("replan advisor failed (%s); using default", e)

        # Default: try substitute, then skip
        candidate = self._suggest_substitute(failed_step)
        if candidate is not None:
            return self._apply(
                plan, failed_step, ReplanStrategy.SUBSTITUTE_TOOL, replacement=candidate
            )
        return self._apply(plan, failed_step, ReplanStrategy.SKIP)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _suggest_substitute(self, step: PlanStep) -> PlanStep | None:
        """Static substitute table — a richer advisor can do better."""
        subs: dict[str, tuple[str, str]] = {
            "web_search": ("web_fetch", "fetch the top URL inline"),
            "web_fetch": ("web_search", "search again with a refined query"),
            "file_read": ("exec", "cat the file via shell"),
            "file_write": ("exec", "echo/write via shell"),
            "exec": ("docker_exec", "run in a container instead"),
        }
        if not step.tool_name or step.tool_name not in subs:
            return None
        new_tool, _ = subs[step.tool_name]
        return PlanStep(
            id=f"{step.id}_retry_{uuid.uuid4().hex[:6]}",
            description=f"{step.description} (retry via {new_tool})",
            action=step.action,
            tool_name=new_tool,
            tool_args=dict(step.tool_args or {}),
            prompt=step.prompt,
            ask_question=step.ask_question,
            wait_seconds=step.wait_seconds,
            deps=list(step.deps),
            parallel_group=step.parallel_group,
            success_criteria=step.success_criteria,
            replanned_from=step.id,
        )

    def _apply(
        self,
        plan: TaskPlan,
        failed_step: PlanStep,
        strategy: ReplanStrategy,
        replacement: PlanStep | None = None,
    ) -> ReplanResult:
        if strategy is ReplanStrategy.SKIP:
            failed_step.status = StepStatus.SKIPPED
            failed_step.error = (failed_step.error or "") + " [skipped by replanner]"
            plan.replan_count += 1
            self.history.append(
                {"step": failed_step.id, "strategy": strategy.value, "plan_id": plan.id}
            )
            return ReplanResult(strategy=strategy, note="step skipped")

        if strategy is ReplanStrategy.ABORT:
            plan.status = PlanStatus.ABANDONED
            plan.metadata["failure_reason"] = failed_step.error
            return ReplanResult(strategy=strategy, note="plan abandoned")

        if (
            strategy in {ReplanStrategy.RETRY, ReplanStrategy.SUBSTITUTE_TOOL}
            and replacement is not None
        ):
            # Mark original as skipped, insert replacement
            failed_step.status = StepStatus.SKIPPED
            failed_step.error = (
                failed_step.error or ""
            ) + f" [replanned: {strategy.value}]"
            # Update deps: anything that pointed to failed_step now points to replacement
            for s in plan.steps:
                if failed_step.id in s.deps:
                    s.deps = [
                        d if d != failed_step.id else replacement.id for d in s.deps
                    ]
            plan.add_step(replacement)
            plan.replan_count += 1
            self.history.append(
                {
                    "step": failed_step.id,
                    "strategy": strategy.value,
                    "replacement": replacement.id,
                    "plan_id": plan.id,
                }
            )
            return ReplanResult(
                strategy=strategy, new_step=replacement, note="replanned"
            )

        return ReplanResult(strategy=ReplanStrategy.ABORT, note="no strategy applied")


__all__ = ["Replanner", "ReplanStrategy", "ReplanResult"]
