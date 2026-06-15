"""Pre-execution cost estimation for plans and steps.

The estimator is intentionally simple — a static table of model + tool
costs, no live API calls. It produces a ``CostEstimate`` that the router
and executor can use to budget the plan, fail-fast on cost-cap breaches,
and surface a cost dashboard.

Cost tables are configurable; the defaults are sane for mid-2026 pricing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Default model cost table (USD per 1K tokens).  Overridable via config.
DEFAULT_MODEL_COSTS: dict[str, dict[str, float]] = {
    "tiny": {"input": 0.0001, "output": 0.0002},
    "small": {"input": 0.0005, "output": 0.0015},
    "medium": {"input": 0.003, "output": 0.015},
    "large": {"input": 0.015, "output": 0.075},
    "premium": {"input": 0.060, "output": 0.300},
}

# Tool cost: USD per call.  Tools that scale with payload use ``cost_per_byte``.
# Tools with no entry are treated as free.
DEFAULT_TOOL_COSTS: dict[str, float] = {
    "web_search": 0.001,
    "web_fetch": 0.001,
    "file_read": 0.0,
    "file_write": 0.0,
    "exec": 0.002,
    "git_op": 0.0,
    "image_gen": 0.020,
    "embedding": 0.0001,
    "tts": 0.005,
    "stt": 0.003,
}


@dataclass(slots=True)
class CostEstimate:
    """Total estimated cost for a plan or step."""

    tokens: int = 0
    usd: float = 0.0
    latency_ms: int = 0
    risk: str = "low"  # low | medium | high | critical

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "usd": self.usd,
            "latency_ms": self.latency_ms,
            "risk": self.risk,
        }

    def __iadd__(self, other: "CostEstimate") -> "CostEstimate":
        self.tokens += other.tokens
        self.usd += other.usd
        self.latency_ms += other.latency_ms
        # worst-of
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if order[other.risk] > order[self.risk]:
            self.risk = other.risk
        return self


@dataclass(slots=True)
class CostEstimator:
    """Static cost table; produces a ``CostEstimate`` for a step or plan."""

    model_costs: dict[str, dict[str, float]] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_COSTS)
    )
    tool_costs: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TOOL_COSTS)
    )
    # Per-tool latency budget (ms) used when no real measurement is available.
    tool_latency_ms: dict[str, int] = field(
        default_factory=lambda: {
            "web_search": 800,
            "web_fetch": 1500,
            "file_read": 50,
            "file_write": 100,
            "exec": 5000,
            "image_gen": 8000,
            "embedding": 200,
            "tts": 400,
            "stt": 800,
        }
    )

    # ------------------------------------------------------------------
    # Per-step
    # ------------------------------------------------------------------

    def estimate_step(
        self,
        *,
        action: str,
        tool_name: str | None = None,
        prompt: str | None = None,
        model_tier: str = "small",
    ) -> CostEstimate:
        """Estimate cost for a single step.

        ``model_tier`` is one of ``tiny|small|medium|large|premium``.
        """
        cost = CostEstimate()

        if action == "tool" and tool_name:
            cost.usd += self.tool_costs.get(tool_name, 0.0)
            cost.latency_ms += self.tool_latency_ms.get(tool_name, 200)
        elif action == "llm":
            # rough token estimate: 1 token per 4 chars
            prompt_tokens = max(1, len(prompt or "") // 4)
            output_tokens = 256  # heuristic
            cost.tokens = prompt_tokens + output_tokens
            tier_costs = self.model_costs.get(model_tier, self.model_costs["small"])
            cost.usd = (prompt_tokens / 1000) * tier_costs["input"] + (
                output_tokens / 1000
            ) * tier_costs["output"]
            cost.latency_ms = 2000 if model_tier in {"medium", "large"} else 500
        elif action == "ask_user":
            cost.latency_ms = 30_000  # wait for human
            cost.risk = "medium"
        elif action == "wait":
            cost.latency_ms = 1000  # default
        elif action == "subplan":
            # sub-plans are estimated by their own children
            pass

        # risk scoring: tool name heuristics
        if tool_name:
            if tool_name.startswith("docker_exec") or "exec" in tool_name:
                cost.risk = "high" if "sudo" in (prompt or "") else "medium"
            elif tool_name in {"rm", "delete", "drop"}:
                cost.risk = "high"
            elif tool_name in {"send_email", "send_message", "git_push"}:
                cost.risk = "medium"
        if action == "ask_user":
            cost.risk = "medium"
        if model_tier in {"large", "premium"} and cost.risk == "low":
            cost.risk = "medium"

        return cost

    # ------------------------------------------------------------------
    # Per-plan
    # ------------------------------------------------------------------

    def estimate_plan(self, plan: Any) -> CostEstimate:
        """Sum cost across all steps in a ``TaskPlan`` (avoids circular import)."""
        total = CostEstimate()
        for step in plan.steps:  # type: ignore[attr-defined]
            est = self.estimate_step(
                action=step.action,
                tool_name=step.tool_name,
                prompt=step.prompt,
            )
            total += est
            step.cost_estimate = est.to_dict()
        plan.cost_total = total.to_dict()  # type: ignore[attr-defined]
        return total

    # ------------------------------------------------------------------
    # Budget gates
    # ------------------------------------------------------------------

    def within_budget(
        self,
        estimate: CostEstimate,
        *,
        per_request_usd: float | None = None,
        per_step_usd: float | None = None,
    ) -> bool:
        if per_request_usd is not None and estimate.usd > per_request_usd:
            logger.warning(
                "cost estimate $%.4f exceeds per-request cap $%.4f",
                estimate.usd,
                per_request_usd,
            )
            return False
        if per_step_usd is not None and estimate.usd > per_step_usd:
            return False
        return True


__all__ = [
    "CostEstimate",
    "CostEstimator",
    "DEFAULT_MODEL_COSTS",
    "DEFAULT_TOOL_COSTS",
]
