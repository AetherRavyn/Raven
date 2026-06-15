"""Public types for the cost router.

The router is the single point of decision for *which* model handles a
given task, with full awareness of cost, capability, and budget.  It is
deliberately model-agnostic — any provider registered in
``app.provider.factory`` is eligible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    """Coarse task categories used to look up the right capability profile."""

    CHAT = "chat"
    CODE = "code"
    RESEARCH = "research"
    REASONING = "reasoning"
    SUMMARIZE = "summarize"
    CLASSIFY = "classify"
    EXTRACT = "extract"
    EMBED = "embed"
    TRANSCRIBE = "transcribe"
    IMAGE = "image"


class ModelCapability(str, Enum):
    """Features a model may or may not support."""

    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    VISION = "vision"
    LONG_CONTEXT = "long_context"  # ≥100k tokens
    STREAMING = "streaming"
    FUNCTION_CALLING = "function_calling"
    CODE_EXEC = "code_exec"


class ModelTier(str, Enum):
    """Cost/quality bands.

    The router picks a band based on the requested minimum quality and
    the caller's budget, then chooses the cheapest model *within* the
    band that meets all capability requirements.
    """

    NANO = "nano"  # local / sub-1B — near-zero cost, sub-second
    SMALL = "small"  # 7B-13B / cheap cloud — pennies
    MEDIUM = "medium"  # 70B-class — single-digit cents
    LARGE = "large"  # flagship chat — tens of cents
    PREMIUM = "premium"  # opus / o1 / opus-1.5 — dollars per call


@dataclass(slots=True)
class ModelSpec:
    """Static description of a model the router may pick."""

    provider: str
    name: str
    tier: ModelTier
    input_cost_per_1k: float
    output_cost_per_1k: float
    # Quality score per task type in [0.0, 1.0].  0 means "do not use".
    quality: dict[TaskType, float] = field(default_factory=dict)
    # Capabilities.  A request that requires a capability not in this
    # set will never be routed to this model.
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)
    # Maximum context window in tokens.
    max_context: int = 8192
    # Typical latency budget in milliseconds.
    typical_latency_ms: int = 1500
    # Is this a local model (no per-token cost, but slower)?
    is_local: bool = False

    def __hash__(self) -> int:  # type: ignore[override]
        # Exclude ``quality`` (a dict) from the hash so the spec stays
        # hashable; the other fields uniquely identify a model entry.
        return hash(
            (
                self.provider,
                self.name,
                self.tier,
                self.input_cost_per_1k,
                self.output_cost_per_1k,
                self.max_context,
                self.typical_latency_ms,
                self.is_local,
                self.capabilities,
            )
        )

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        if self.is_local:
            return 0.0
        return (input_tokens / 1000.0) * self.input_cost_per_1k + (
            output_tokens / 1000.0
        ) * self.output_cost_per_1k


@dataclass(slots=True)
class RouteRequest:
    """Input to :meth:`CostRouter.route`."""

    task: TaskType
    # Rough prompt size for cost estimation.  The router uses this to
    # filter out models that can't fit the call.
    input_tokens: int
    # Maximum output tokens the caller is willing to wait for.
    max_output_tokens: int
    # Required capabilities (empty = no requirement).
    requires: frozenset[ModelCapability] = field(default_factory=frozenset)
    # Preferred tier floor — the router will not go below this.
    min_tier: ModelTier = ModelTier.NANO
    # Preferred tier ceiling — the router will not go above this.
    max_tier: ModelTier = ModelTier.PREMIUM
    # Per-request cost cap.  Overrides any global limit.
    budget_usd: float | None = None
    # Identifiers used by the ledger for attribution.
    user_id: str | None = None
    plan_id: str | None = None


@dataclass(slots=True)
class RouteDecision:
    """The router's pick plus everything needed to act on it."""

    provider: str
    model: str
    spec: ModelSpec
    tier: ModelTier
    rationale: str
    estimated_cost_usd: float
    fallback_chain: tuple[str, ...] = ()
    # Pre-decision budget snapshot.  Useful for telemetry.
    budget_remaining_usd: float | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier.value,
            "rationale": self.rationale,
            "estimated_cost_usd": self.estimated_cost_usd,
            "fallback_chain": list(self.fallback_chain),
            "budget_remaining_usd": self.budget_remaining_usd,
            "request_id": self.request_id,
        }


@dataclass(slots=True)
class CostRecord:
    """A single spend event, written to the ledger after each call."""

    provider: str
    model: str
    tier: ModelTier
    task: TaskType
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    user_id: str | None = None
    plan_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier.value,
            "task": self.task.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
        }


class BudgetExceededError(RuntimeError):
    """Raised when a call would breach the configured budget."""


class NoRouteAvailableError(RuntimeError):
    """Raised when no model in the catalog satisfies the request."""


__all__ = [
    "TaskType",
    "ModelCapability",
    "ModelTier",
    "ModelSpec",
    "RouteRequest",
    "RouteDecision",
    "CostRecord",
    "BudgetExceededError",
    "NoRouteAvailableError",
]
