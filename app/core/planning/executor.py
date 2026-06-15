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


# Dispatcher signatures
ToolDispatcher = Callable[[str, dict[str, Any]], Awaitable[Any]]
LLMDispatcher = Callable[[str], Awaitable[str]]
AskUserDispatcher = Callable[[str], Awaitable[str]]


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
            # Sub-plans are not in scope for v1.
            raise NotImplementedError("subplan actions are not yet supported")
        raise ValueError(f"unknown action: {step.action}")

    async def _checkpoint(self, plan: TaskPlan) -> None:
        if self.store is None:
            return
        try:
            await self.store.save(plan)
        except Exception as e:  # noqa: BLE001
            logger.warning("checkpoint failed for plan %s: %s", plan.id, e)


__all__ = ["PlanExecutor", "ExecutionResult", "StepExecutionResult"]
