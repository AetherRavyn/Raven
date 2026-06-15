"""Hierarchical planner for AetherRavyn.

This package contains the *real* planner (Phase A1 of PLAN_v3.md), replacing
the 132-line stub in ``app/core/planner.py``. It is intentionally
model-agnostic and self-contained: rule-based decomposition by default,
with optional LLM-augmented planning when a model provider is configured.

Sub-modules:

- ``types``         — dataclasses for ``TaskPlan``, ``PlanStep``, ``StepStatus`` …
- ``cost_estimator`` — pre-execution cost (tokens, USD, latency_ms, risk)
- ``planner``       — turns a goal into a ``TaskPlan``
- ``executor``      — runs a plan, handles retries, checkpoints
- ``replanner``     — on step failure, propose alternate strategies
- ``goal_tracker``  — long-horizon goals with deadlines
- ``store``         — HelixDB persistence for plans + checkpoints
"""

from __future__ import annotations

from app.core.planning.cost_estimator import CostEstimator, CostEstimate
from app.core.planning.executor import PlanExecutor, ExecutionResult
from app.core.planning.goal_tracker import Goal, GoalStatus, GoalTracker
from app.core.planning.planner import Planner
from app.core.planning.replanner import ReplanResult, Replanner, ReplanStrategy
from app.core.planning.store import PlanStore
from app.core.planning.types import (
    PlanStatus,
    PlanStep,
    StepAction,
    StepStatus,
    TaskPlan,
)

__all__ = [
    "CostEstimate",
    "CostEstimator",
    "ExecutionResult",
    "Goal",
    "GoalStatus",
    "GoalTracker",
    "PlanExecutor",
    "PlanStatus",
    "PlanStep",
    "Planner",
    "ReplanResult",
    "ReplanStrategy",
    "Replanner",
    "StepAction",
    "PlanStore",
    "StepStatus",
    "TaskPlan",
]
