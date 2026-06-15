"""Tests for the planning module.

These tests are self-contained: they do not require HelixDB, the
agent runtime, or any LLM provider.  They use rule-based planning,
in-memory dispatchers, and the in-memory fallback of the PlanStore.
"""

from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio

from app.core.planning import (
    CostEstimate,
    CostEstimator,
    ExecutionResult,
    Goal,
    GoalStatus,
    GoalTracker,
    PlanExecutor,
    Planner,
    PlanStatus,
    PlanStep,
    PlanStore,
    ReplanStrategy,
    Replanner,
    StepAction,
    StepStatus,
    TaskPlan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cost() -> CostEstimator:
    return CostEstimator()


@pytest.fixture
def planner() -> Planner:
    return Planner()


@pytest.fixture
def store() -> PlanStore:
    return PlanStore(helix=None)  # in-memory only


# ---------------------------------------------------------------------------
# Type / invariant tests
# ---------------------------------------------------------------------------


class TestTaskPlan:
    def test_empty_plan_is_well_formed(self) -> None:
        p = TaskPlan()
        assert p.is_well_formed()

    def test_plan_with_linear_deps_is_well_formed(self) -> None:
        p = TaskPlan()
        a = PlanStep(id="a", description="a", action="llm", prompt="hi")
        b = PlanStep(id="b", description="b", action="llm", prompt="there", deps=["a"])
        p.add_step(a)
        p.add_step(b)
        assert p.is_well_formed()
        assert [s.id for s in p.ready_steps()] == ["a"]

    def test_plan_with_cycle_is_malformed(self) -> None:
        p = TaskPlan()
        p.add_step(PlanStep(id="a", description="a", action="llm", prompt="x", deps=["b"]))
        p.add_step(PlanStep(id="b", description="b", action="llm", prompt="y", deps=["a"]))
        assert not p.is_well_formed()

    def test_plan_with_unknown_dep_is_malformed(self) -> None:
        p = TaskPlan()
        p.add_step(PlanStep(id="a", description="a", action="llm", prompt="x", deps=["ghost"]))
        assert not p.is_well_formed()

    def test_parallel_groups_collect(self) -> None:
        p = TaskPlan()
        for i in range(3):
            p.add_step(PlanStep(id=f"s{i}", description=f"s{i}", action="llm", parallel_group=i % 2))
        groups = p.parallel_groups()
        assert len(groups) == 2
        assert [len(g) for g in groups] == [2, 1]

    def test_round_trip_dict(self) -> None:
        p = TaskPlan(goal="hi", user_id="u1")
        p.add_step(PlanStep(id="a", description="a", action="llm", prompt="x"))
        d = p.to_dict()
        p2 = TaskPlan.from_dict(d)
        assert p2.goal == p.goal
        assert p2.user_id == p.user_id
        assert p2.steps[0].id == "a"


# ---------------------------------------------------------------------------
# Cost estimator
# ---------------------------------------------------------------------------


class TestCostEstimator:
    def test_tool_step_cost(self, cost: CostEstimator) -> None:
        e = cost.estimate_step(action="tool", tool_name="web_search")
        assert e.usd >= 0.001
        assert e.latency_ms >= 100

    def test_llm_step_cost_scales_with_tier(self, cost: CostEstimator) -> None:
        small = cost.estimate_step(action="llm", prompt="x" * 1000, model_tier="small")
        premium = cost.estimate_step(action="llm", prompt="x" * 1000, model_tier="premium")
        assert premium.usd > small.usd

    def test_ask_user_is_medium_risk(self, cost: CostEstimator) -> None:
        e = cost.estimate_step(action="ask_user")
        assert e.risk == "medium"

    def test_exec_is_at_least_medium_risk(self, cost: CostEstimator) -> None:
        e = cost.estimate_step(action="tool", tool_name="exec", prompt="sudo rm -rf /")
        assert e.risk in {"high", "critical"}

    def test_plan_estimate_aggregates(self, cost: CostEstimator) -> None:
        p = TaskPlan()
        p.add_step(PlanStep(id="a", description="a", action="tool", tool_name="web_search"))
        p.add_step(PlanStep(id="b", description="b", action="llm", prompt="hello world", deps=["a"]))
        total = cost.estimate_plan(p)
        assert total.tokens > 0
        assert total.usd > 0
        # per-step cost_estimate was populated
        assert p.steps[1].cost_estimate["tokens"] > 0

    def test_within_budget(self, cost: CostEstimator) -> None:
        e = CostEstimate(usd=0.01)
        assert cost.within_budget(e, per_request_usd=0.10)
        assert not cost.within_budget(e, per_request_usd=0.001)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class TestPlanner:
    @pytest.mark.asyncio
    async def test_greeting_produces_ask_user_step(self, planner: Planner) -> None:
        plan = await planner.plan("hello")
        assert plan.metadata["goal_kind"] == "greeting"
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "ask_user"

    @pytest.mark.asyncio
    async def test_time_query(self, planner: Planner) -> None:
        plan = await planner.plan("what time is it?")
        assert plan.metadata["goal_kind"] == "time_query"

    @pytest.mark.asyncio
    async def test_status_query_has_tool_and_llm_steps(self, planner: Planner) -> None:
        plan = await planner.plan("how are you doing today?")
        actions = {s.action for s in plan.steps}
        assert "tool" in actions
        assert "llm" in actions

    @pytest.mark.asyncio
    async def test_code_task_plan(self, planner: Planner) -> None:
        plan = await planner.plan("implement a function that adds two numbers in python")
        assert plan.metadata["goal_kind"] == "code_task"
        assert plan.is_well_formed()
        # Should have at least: research, design, implement, verify
        assert len(plan.steps) >= 4

    @pytest.mark.asyncio
    async def test_research_plan_has_parallel_step(self, planner: Planner) -> None:
        plan = await planner.plan("research the latest AI safety papers")
        assert plan.metadata["goal_kind"] == "research"
        # The fetch step should have a parallel_group
        fetch_steps = [s for s in plan.steps if s.tool_name == "web_fetch"]
        assert fetch_steps
        assert any(s.parallel_group > 0 for s in fetch_steps)

    @pytest.mark.asyncio
    async def test_shell_plan_requires_confirmation(self, planner: Planner) -> None:
        plan = await planner.plan("run the test suite")
        confirm = [s for s in plan.steps if s.action == "ask_user"]
        assert confirm, "shell tasks must have a confirmation step"

    @pytest.mark.asyncio
    async def test_unknown_falls_back_to_single_llm(self, planner: Planner) -> None:
        plan = await planner.plan("xyzzy frobnicate the gibbous")
        assert plan.is_well_formed()
        assert any(s.action == "llm" for s in plan.steps)

    @pytest.mark.asyncio
    async def test_llm_planner_override(self) -> None:
        async def fake_llm(goal: str, msgs: list) -> dict:
            return {
                "steps": [
                    {
                        "id": "s1",
                        "description": "do thing",
                        "action": "tool",
                        "tool_name": "exec",
                        "tool_args": {"command": goal},
                    }
                ]
            }

        p = Planner(llm_planner=fake_llm)
        plan = await p.plan("a very strange goal that the rule classifier cannot handle xyzzy")
        assert plan.metadata["source"] == "llm"
        assert plan.steps[0].tool_name == "exec"

    @pytest.mark.asyncio
    async def test_classifier_confidence(self, planner: Planner) -> None:
        kind, conf = planner.classify("hello there")
        assert kind.value == "greeting"
        assert conf == 1.0

        kind, conf = planner.classify("research quantum computing")
        assert kind.value == "research"
        assert conf >= 0.5


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestExecutor:
    @pytest.mark.asyncio
    async def test_simple_llm_plan_executes(self, planner: Planner, store: PlanStore) -> None:
        async def llm_disp(prompt: str) -> str:
            return f"echo:{prompt}"

        executor = PlanExecutor(llm_dispatcher=llm_disp, store=store)
        plan = await planner.plan("what time is it?")
        # ask_user step needs the dispatcher; override it
        executor.ask_user_dispatcher = lambda q: asyncio.sleep(0, result=q)
        result = await executor.execute(plan)
        assert result.is_success
        assert plan.status == PlanStatus.COMPLETED
        assert any(r.result for r in result.step_results)

    @pytest.mark.asyncio
    async def test_tool_step_executes(self, planner: Planner, store: PlanStore) -> None:
        async def tool_disp(name: str, args: dict) -> str:
            return f"tool:{name}:{args}"

        executor = PlanExecutor(tool_dispatcher=tool_disp, store=store)
        plan = await planner.plan("how are you doing?")  # status_query
        # Convert the trailing ask_user into a tool — easier: add a tool step
        plan.add_step(
            PlanStep(
                id="extra",
                description="extra",
                action="tool",
                tool_name="echo",
                tool_args={"x": 1},
            )
        )
        executor.llm_dispatcher = lambda p: asyncio.sleep(0, result=f"llm:{p}")
        executor.ask_user_dispatcher = lambda q: asyncio.sleep(0, result=q)
        result = await executor.execute(plan)
        assert result.is_success

    @pytest.mark.asyncio
    async def test_failure_marks_plan_failed(self, planner: Planner, store: PlanStore) -> None:
        async def boom(name: str, args: dict) -> str:
            raise RuntimeError("kaboom")

        executor = PlanExecutor(
            tool_dispatcher=boom,
            llm_dispatcher=boom,
            ask_user_dispatcher=boom,
            max_retries=2,
            store=store,
        )
        plan = await planner.plan("how are you?")
        result = await executor.execute(plan)
        assert result.is_failure
        assert plan.status == PlanStatus.FAILED
        assert any(s.error and "kaboom" in s.error for s in plan.steps)

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, planner: Planner, store: PlanStore) -> None:
        attempts = {"n": 0}

        async def flaky(name: str, args: dict) -> str:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("transient")
            return "ok"

        executor = PlanExecutor(
            tool_dispatcher=flaky,
            max_retries=3,
            retry_backoff_s=0.0,
            store=store,
        )
        plan = TaskPlan()
        plan.add_step(PlanStep(id="s1", description="s1", action="tool", tool_name="x"))
        result = await executor.execute(plan)
        assert result.is_success
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_parallel_group_runs_concurrently(self, planner: Planner, store: PlanStore) -> None:
        barriers = [asyncio.Event() for _ in range(2)]

        async def tool_disp(name: str, args: dict) -> str:
            idx = int(args["i"])
            await barriers[idx].wait()
            return f"done-{idx}"

        executor = PlanExecutor(tool_dispatcher=tool_disp, store=store)
        plan = TaskPlan()
        plan.add_step(PlanStep(id="a", description="a", action="tool", tool_name="x", tool_args={"i": 0}, parallel_group=0))
        plan.add_step(PlanStep(id="b", description="b", action="tool", tool_name="x", tool_args={"i": 1}, parallel_group=0))

        async def release() -> None:
            await asyncio.sleep(0.05)
            for b in barriers:
                b.set()

        asyncio.create_task(release())
        t0 = time.perf_counter()
        result = await executor.execute(plan)
        dt = time.perf_counter() - t0
        assert result.is_success
        # Should be ~50ms, not 100ms (sequential would be 100ms)
        assert dt < 0.2

    @pytest.mark.asyncio
    async def test_checkpoint_persists(self, planner: Planner, store: PlanStore) -> None:
        executor = PlanExecutor(
            llm_dispatcher=lambda p: asyncio.sleep(0, result="ok"),
            ask_user_dispatcher=lambda q: asyncio.sleep(0, result=q),
            store=store,
        )
        plan = await planner.plan("hello")
        result = await executor.execute(plan)
        assert result.is_success
        # The store should have it
        loaded = await store.load(plan.id)
        assert loaded is not None
        assert loaded.status == PlanStatus.COMPLETED


# ---------------------------------------------------------------------------
# Replanner
# ---------------------------------------------------------------------------


class TestReplanner:
    @pytest.mark.asyncio
    async def test_substitute_for_web_search(self, store: PlanStore) -> None:
        rp = Replanner()
        plan = TaskPlan()
        step = PlanStep(id="s1", description="s1", action="tool", tool_name="web_search")
        plan.add_step(step)
        result = await rp.on_failure(plan, step)
        assert result.strategy == ReplanStrategy.SUBSTITUTE_TOOL
        assert result.new_step is not None
        assert result.new_step.tool_name == "web_fetch"

    @pytest.mark.asyncio
    async def test_max_replans_aborts(self, store: PlanStore) -> None:
        rp = Replanner(max_replans=0)
        plan = TaskPlan()
        step = PlanStep(id="s1", description="s1", action="tool", tool_name="web_search")
        plan.add_step(step)
        result = await rp.on_failure(plan, step)
        assert result.strategy == ReplanStrategy.ABORT
        assert plan.status == PlanStatus.ABANDONED

    @pytest.mark.asyncio
    async def test_unknown_tool_skips(self, store: PlanStore) -> None:
        rp = Replanner()
        plan = TaskPlan()
        step = PlanStep(id="s1", description="s1", action="tool", tool_name="made_up_tool")
        plan.add_step(step)
        result = await rp.on_failure(plan, step)
        assert result.strategy == ReplanStrategy.SKIP
        assert step.status == StepStatus.SKIPPED


# ---------------------------------------------------------------------------
# Goal tracker
# ---------------------------------------------------------------------------


class TestGoalTracker:
    @pytest.mark.asyncio
    async def test_create_with_no_deadline_creates_one_subplan(self, store: PlanStore) -> None:
        tracker = GoalTracker(store=store)
        goal = await tracker.create("learn rust", user_id="u1")
        assert goal.status == GoalStatus.ACTIVE
        assert len(goal.sub_plans) == 1

    @pytest.mark.asyncio
    async def test_create_with_deadline_creates_n_subplans(self, store: PlanStore) -> None:
        from datetime import datetime, timedelta, timezone

        tracker = GoalTracker(store=store, default_subplan_count=3)
        deadline = datetime.now(timezone.utc) + timedelta(days=9)
        goal = await tracker.create("ship v2", user_id="u1", deadline=deadline)
        assert len(goal.sub_plans) == 3

    @pytest.mark.asyncio
    async def test_create_with_llm_decomposer(self, store: PlanStore) -> None:
        from app.core.planning.types import TaskPlan

        async def dec(goal: Goal) -> list[TaskPlan]:
            return [TaskPlan(goal=f"{goal.title} part {i}", user_id=goal.user_id) for i in range(2)]

        tracker = GoalTracker(store=store, decomposer=dec)
        goal = await tracker.create("test", user_id="u1")
        assert len(goal.sub_plans) == 2

    @pytest.mark.asyncio
    async def test_progress_updates_from_subplans(self, store: PlanStore) -> None:
        tracker = GoalTracker(store=store)
        goal = await tracker.create("quick", user_id="u1")
        # mark one sub-plan completed
        plan_id = goal.sub_plans[0]
        plan = await store.load(plan_id)
        plan.status = PlanStatus.COMPLETED
        await store.save(plan)
        await tracker.update_progress(goal)
        loaded = await store.load_goal(goal.id)
        assert loaded is not None
        assert 0.0 < loaded.progress <= 1.0


# ---------------------------------------------------------------------------
# Integration: planner -> executor -> store
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.mark.asyncio
    async def test_research_plan_end_to_end(self, store: PlanStore) -> None:
        planner = Planner()
        plan = await planner.plan("research the impact of AI on healthcare")
        # Wire dispatchers
        executor = PlanExecutor(
            tool_dispatcher=lambda n, a: asyncio.sleep(0, result=f"tool:{n}"),
            llm_dispatcher=lambda p: asyncio.sleep(0, result=f"llm:{p[:30]}"),
            store=store,
        )
        result = await executor.execute(plan)
        assert result.is_success
        # All steps completed
        assert all(s.status == StepStatus.COMPLETED for s in plan.steps)
        # Plan was persisted
        loaded = await store.load(plan.id)
        assert loaded is not None
        assert loaded.status == PlanStatus.COMPLETED
