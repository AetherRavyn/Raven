"""Plan executor with retry, parallel groups, and checkpointing.

The executor is intentionally minimal at the I/O layer: it calls
``tool_dispatcher`` for ``action="tool"`` steps and ``llm_dispatcher``
for ``action="llm"`` steps. Higher-level code injects the actual
implementations so the executor is testable without the full runtime.

Checkpoints are persisted to the ``PlanStore`` (HelixDB + in-memory
fallback) after every step.  On crash + restart, ``resume()`` rebuilds
the plan from the last checkpoint.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.core.planning.types import (
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskPlan,
)

logger = logging.getLogger(__name__)


class _SubplanFailed(RuntimeError):
    """Sentinel raised by :meth:`PlanExecutor._dispatch_subplan`
    when the referenced sub-plan completed in a non-``COMPLETED``
    state (failed, abandoned).

    The parent step's :meth:`PlanExecutor._run_step` retry loop
    treats this as a **non-retryable** terminal failure: the
    sub-plan already exhausted its own retries, so re-running
    it from the parent side would just re-trigger the same
    failure.  The first attempt's error message is preserved
    rather than overwritten by the third retry.
    """


# Dispatcher signatures
ToolDispatcher = Callable[[str, dict[str, Any]], Awaitable[Any]]
LLMDispatcher = Callable[[str], Awaitable[str]]
AskUserDispatcher = Callable[[str], Awaitable[str]]
# Sub-plan resolver: given a subplan_id, return the TaskPlan
# to execute.  Returns ``None`` when the sub-plan is unknown.
# Injected so the executor does not need a reference to the
# PlanStore directly (avoids a circular import with
# ``app.core.planning.store``).
SubplanResolver = Callable[[str], Awaitable[TaskPlan | None] | TaskPlan | None]


@dataclass(slots=True)
class StepExecutionResult:
    step_id: str
    status: StepStatus
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class ExecutionResult:
    plan: TaskPlan
    step_results: list[StepExecutionResult] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.plan.status == PlanStatus.COMPLETED

    @property
    def is_failure(self) -> bool:
        return self.plan.status in {PlanStatus.FAILED, PlanStatus.ABANDONED}


@dataclass(slots=True)
class PlanExecutor:
    """Execute a ``TaskPlan`` step by step with retries + parallel batches."""

    tool_dispatcher: Optional[ToolDispatcher] = None
    llm_dispatcher: Optional[LLMDispatcher] = None
    ask_user_dispatcher: Optional[AskUserDispatcher] = None
    # Resolver for sub-plan steps.  Called with the
    # ``subplan_id`` from a step whose ``action == "subplan"``.
    # When the resolver returns ``None`` the step fails with
    # a "sub-plan not found" error; when the resolver itself
    # raises the failure is propagated.
    subplan_resolver: Optional[SubplanResolver] = None
    # Optional dedicated executor for sub-plans.  When set,
    # sub-plan dispatch recurses through this executor (so
    # sub-plans get the same retry/checkpoint behaviour as
    # top-level plans).  When ``None`` the executor recurses
    # into its own ``execute()`` method, which is what tests
    # and simple deployments want.
    subplan_executor: Optional["PlanExecutor"] = None
    max_retries: int = 3
    retry_backoff_s: float = 0.5
    step_timeout_s: float = 120.0
    # hook called after each step
    on_step_complete: Optional[
        Callable[[PlanStep, StepExecutionResult], Awaitable[None] | None]
    ] = None
    # the store is injected so checkpointing is observable / testable
    store: Any = None  # PlanStore (avoid import cycle)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, plan: TaskPlan) -> ExecutionResult:
        """Run ``plan`` to completion (or failure)."""
        if plan.status.is_terminal:
            return ExecutionResult(plan=plan, step_results=[])

        plan.status = PlanStatus.IN_PROGRESS
        await self._checkpoint(plan)

        result = ExecutionResult(plan=plan)
        max_steps = 1000  # safety net
        steps_run = 0

        while not self._is_done(plan) and steps_run < max_steps:
            groups = plan.parallel_groups()
            if not groups:
                # No ready steps but plan not done → something is wrong
                plan.status = PlanStatus.FAILED
                plan.metadata.setdefault(
                    "failure_reason", "no ready steps but plan not done"
                )
                break

            # Execute groups in order, but steps within a group in parallel
            for group in groups:
                group_results = await self._run_group(plan, group)
                result.step_results.extend(group_results)
                # If any step in the group failed terminally, abort
                if any(r.status == StepStatus.FAILED for r in group_results):
                    plan.status = PlanStatus.FAILED
                    break
            steps_run += 1

        if plan.status == PlanStatus.IN_PROGRESS:
            plan.status = PlanStatus.COMPLETED
        await self._checkpoint(plan)
        return result

    async def resume(self, plan: TaskPlan) -> ExecutionResult:
        """Resume a plan from its last checkpoint."""
        logger.info("resuming plan %s from step state", plan.id)
        return await self.execute(plan)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_done(self, plan: TaskPlan) -> bool:
        if plan.status.is_terminal:
            return True
        return all(s.status.is_terminal for s in plan.steps)

    async def _run_group(
        self, plan: TaskPlan, group: list[PlanStep]
    ) -> list[StepExecutionResult]:
        tasks = [self._run_step(plan, step) for step in group]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _run_step(self, plan: TaskPlan, step: PlanStep) -> StepExecutionResult:
        from datetime import datetime, timezone  # local import to keep types.py lean

        if step.status in {StepStatus.COMPLETED, StepStatus.SKIPPED}:
            return StepExecutionResult(step_id=step.id, status=step.status)

        step.status = StepStatus.IN_PROGRESS
        step.started_at = datetime.now(timezone.utc)
        step.attempts += 1
        last_error: str | None = None
        t0 = asyncio.get_event_loop().time()

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._dispatch_step(step),
                    timeout=self.step_timeout_s,
                )
                step.status = StepStatus.COMPLETED
                step.result = result
                step.completed_at = datetime.now(timezone.utc)
                sr = StepExecutionResult(
                    step_id=step.id,
                    status=StepStatus.COMPLETED,
                    result=result,
                    duration_ms=int((asyncio.get_event_loop().time() - t0) * 1000),
                )
                if self.on_step_complete is not None:
                    out = self.on_step_complete(step, sr)
                    if asyncio.iscoroutine(out):
                        await out
                await self._checkpoint(plan)
                return sr
            except _SubplanFailed as e:
                # A failed sub-plan is a terminal, non-retryable
                # outcome — the sub-plan already exhausted its
                # own retry budget, so re-running it from the
                # parent would just re-trigger the same failure
                # and overwrite this first attempt's error with
                # an identical copy on attempt 2 and 3.  Bail
                # immediately with the original error.
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "step %s sub-plan failed (non-retryable): %s",
                    step.id, last_error,
                )
                break
            except Exception as e:  # noqa: BLE001
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "step %s attempt %d/%d failed: %s",
                    step.id,
                    attempt,
                    self.max_retries,
                    last_error,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_backoff_s * attempt)

        step.status = StepStatus.FAILED
        step.error = last_error
        step.completed_at = datetime.now(timezone.utc)
        sr = StepExecutionResult(
            step_id=step.id,
            status=StepStatus.FAILED,
            error=last_error,
            duration_ms=int((asyncio.get_event_loop().time() - t0) * 1000),
        )
        if self.on_step_complete is not None:
            out = self.on_step_complete(step, sr)
            if asyncio.iscoroutine(out):
                await out
        await self._checkpoint(plan)
        return sr

    async def _dispatch_step(self, step: PlanStep) -> Any:
        if step.action == "tool":
            if self.tool_dispatcher is None:
                raise RuntimeError(f"no tool_dispatcher for step {step.id}")
            return await self.tool_dispatcher(
                step.tool_name or "", step.tool_args or {}
            )
        if step.action == "llm":
            if self.llm_dispatcher is None:
                raise RuntimeError(f"no llm_dispatcher for step {step.id}")
            return await self.llm_dispatcher(step.prompt or step.description)
        if step.action == "ask_user":
            if self.ask_user_dispatcher is None:
                # In test mode we just return the question as the "answer"
                return step.ask_question or ""
            return await self.ask_user_dispatcher(step.ask_question or step.description)
        if step.action == "wait":
            secs = float(step.wait_seconds or 1.0)
            await asyncio.sleep(min(secs, 60.0))  # cap at 60s in tests
            return f"waited {secs}s"
        if step.action == "subplan":
            return await self._dispatch_subplan(step)
        raise ValueError(f"unknown action: {step.action}")

    async def _dispatch_subplan(self, step: PlanStep) -> Any:
        """Resolve a ``subplan`` step's referenced sub-plan and
        execute it, propagating the sub-plan's result back as
        the parent step's result.

        Failure modes (all raised — the caller in :meth:`_run_step`
        catches them and turns them into step failures):

        * ``step.subplan_id`` is ``None`` or empty → ``ValueError``
        * ``subplan_resolver`` is not wired → ``RuntimeError``
        * the resolver returns ``None`` → ``RuntimeError`` with a
          clear "sub-plan not found" message
        * the resolved sub-plan is malformed (no steps) →
          ``ValueError``

        A sub-plan that reaches a terminal state during execution
        is treated as follows:

        * ``COMPLETED`` → the sub-plan's accumulated result (last
          step's result, or the explicit ``subplan_result`` metadata
          if set) becomes the parent step's ``result``.
        * ``FAILED`` / ``ABANDONED`` → the sub-plan's first FAILED
          step's error is raised, wrapped with the parent step id
          for context.
        """
        subplan_id = (step.subplan_id or "").strip()
        if not subplan_id:
            raise ValueError(
                f"subplan step {step.id!r} has no subplan_id",
            )
        if self.subplan_resolver is None:
            raise RuntimeError(
                f"subplan step {step.id!r} cannot dispatch: "
                "no subplan_resolver wired",
            )
        resolved = self.subplan_resolver(subplan_id)
        if asyncio.iscoroutine(resolved):
            resolved = await resolved
        if resolved is None:
            raise RuntimeError(
                f"subplan step {step.id!r} references unknown "
                f"subplan_id {subplan_id!r}",
            )
        if not isinstance(resolved, TaskPlan):
            raise ValueError(
                f"subplan_resolver returned {type(resolved).__name__} "
                f"for subplan_id {subplan_id!r}; expected TaskPlan",
            )
        if not resolved.steps:
            raise ValueError(
                f"subplan {subplan_id!r} has no steps to execute",
            )
        # Execute the sub-plan.  When a dedicated
        # ``subplan_executor`` is configured, use that — the
        # sub-plan gets its own retry / checkpoint / hook
        # surface.  Otherwise recurse into this executor's
        # ``execute()``, which keeps the sub-plan inside the
        # same checkpoint stream (every sub-plan step also
        # gets persisted via the parent store).
        executor = self.subplan_executor or self
        sub_result = await executor.execute(resolved)
        if sub_result.plan.status == PlanStatus.COMPLETED:
            # Surface a result that is meaningful to the
            # parent plan.  Prefer the explicit
            # ``subplan_result`` metadata if the planner
            # set it; otherwise the last completed step's
            # result; otherwise an empty summary.
            if "subplan_result" in sub_result.plan.metadata:
                return sub_result.plan.metadata["subplan_result"]
            completed = sub_result.plan.completed_steps()
            if completed:
                return completed[-1].result
            return {"status": "completed", "subplan_id": subplan_id}
        # Sub-plan failed — propagate the first failed step's
        # error with the parent step id for context.  Use the
        # ``_SubplanFailed`` sentinel so the parent's retry
        # loop does not re-execute the already-exhausted
        # sub-plan three times (which would just re-trigger
        # the same failure and overwrite the first attempt's
        # error).
        failed = [
            s for s in resolved.steps
            if s.status == StepStatus.FAILED
        ]
        first = failed[0] if failed else None
        reason = (
            f"subplan {subplan_id!r} (executed by step {step.id!r}) "
            f"did not complete (status={sub_result.plan.status.value})"
        )
        if first is not None and first.error:
            reason = f"{reason}; first failure: {first.error}"
        raise _SubplanFailed(reason)

    async def _checkpoint(self, plan: TaskPlan) -> None:
        if self.store is None:
            return
        try:
            await self.store.save(plan)
        except Exception as e:  # noqa: BLE001
            logger.warning("checkpoint failed for plan %s: %s", plan.id, e)


__all__ = ["PlanExecutor", "ExecutionResult", "StepExecutionResult"]
