"""Cost-aware model router.

The router is the single point of decision for *which* model handles a
given task.  It is called once per LLM turn by the executor and once
per plan by the planner.  It is deliberately:

- **Model-agnostic** — works with any provider registered in
  :mod:`app.provider.factory`.  Adding a new provider means adding
  specs to the catalog and a branch in the factory.
- **Cost-aware** — every decision includes a USD estimate and is
  checked against the active budget ledger.
- **Quality-aware** — every spec carries a per-task quality score; the
  router refuses to pick a model that would fall below the request's
  minimum quality bar.
- **Capability-aware** — a request that requires tool use, vision, or
  long context will never be routed to a model that lacks that
  capability.
- **Resilient** — every decision includes a fallback chain; the
  executor can step through it on failure.

The router does **not** call the model.  It only picks.  The executor
is responsible for invoking the chosen provider with retries, fallbacks,
and the resilience layer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.cost_router.catalog import ModelCatalog
from app.core.cost_router.health import HealthSnapshot, ProviderHealth
from app.core.cost_router.ledger import BudgetLedger
from app.core.cost_router.types import (
    BudgetExceededError,
    CostRecord,
    ModelSpec,
    ModelTier,
    NoRouteAvailableError,
    RouteDecision,
    RouteRequest,
)

logger = logging.getLogger(__name__)


# Default quality floor per task when the caller doesn't specify one.
_DEFAULT_QUALITY_FLOOR = {
    "chat": 0.5,
    "code": 0.6,
    "research": 0.6,
    "reasoning": 0.6,
    "summarize": 0.5,
    "classify": 0.6,
    "extract": 0.6,
    "embed": 0.5,
    "transcribe": 0.5,
    "image": 0.5,
}


class CostRouter:
    """Picks the best model for a :class:`RouteRequest`.

    The router is stateless except for the catalog, ledger, and health
    tracker it owns.  Multiple routers can coexist (e.g. one per
    tenant) without coordination.
    """

    def __init__(
        self,
        *,
        catalog: ModelCatalog | None = None,
        ledger: BudgetLedger | None = None,
        health: ProviderHealth | None = None,
        # If True, models the user has not enabled (no API key) are
        # filtered out.  Detection is best-effort: we look at env vars
        # via ``app.settings.config.Config``.  If False, all catalog
        # models are eligible.
        respect_provider_keys: bool = True,
    ) -> None:
        self.catalog = catalog or ModelCatalog()
        self.ledger = ledger or BudgetLedger()
        self.health = health or ProviderHealth()
        self.respect_provider_keys = respect_provider_keys

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    async def route(self, request: RouteRequest) -> RouteDecision:
        """Pick the cheapest model that satisfies the request.

        Raises :class:`BudgetExceededError` if the request would breach
        a budget, and :class:`NoRouteAvailableError` if no model in
        the catalog is eligible.
        """
        budget_remaining = await self.ledger.budget_remaining(
            user_id=request.user_id, plan_id=request.plan_id
        )

        # Estimate worst-case cost for the cheapest candidate up front,
        # so we can fail fast on the per-request cap.
        candidates = self._candidates(request)
        if not candidates:
            raise NoRouteAvailableError(
                f"no model in catalog matches task={request.task.value}, "
                f"tier=[{request.min_tier.value}..{request.max_tier.value}], "
                f"requires={sorted(c.value for c in request.requires)}"
            )

        # Pre-compute the cheapest candidate's estimate and use it to
        # budget-gate the whole request.
        cheapest = min(
            candidates,
            key=lambda s: s.estimate_cost(
                request.input_tokens, request.max_output_tokens
            ),
        )
        cheapest_estimate = cheapest.estimate_cost(
            request.input_tokens, request.max_output_tokens
        )
        # Effective cap = the tighter of per-request and remaining budget.
        effective_budget = self._effective_budget(request, budget_remaining)
        if effective_budget is not None and cheapest_estimate > effective_budget:
            raise BudgetExceededError(
                f"cheapest candidate ({cheapest.provider}/{cheapest.name}) "
                f"estimates ${cheapest_estimate:.4f} which exceeds the "
                f"effective budget ${effective_budget:.4f}"
            )

        # Score and rank candidates.
        scored = self._score_candidates(candidates, request)
        if not scored:
            raise NoRouteAvailableError(
                f"no candidate met the quality floor for {request.task.value}"
            )

        # Post-score budget filter: if the caller imposed a per-request
        # budget, drop every candidate that would breach it.  We do
        # this after scoring so quality ranking still informs the order
        # of the fallback chain.
        if effective_budget is not None:
            affordable = [
                (s, sc)
                for s, sc in scored
                if s.estimate_cost(request.input_tokens, request.max_output_tokens)
                <= effective_budget
            ]
            if not affordable:
                raise BudgetExceededError(
                    f"no candidate fits the effective budget ${effective_budget:.4f}"
                )
            scored = affordable

        # Pick the best (lowest score = best).
        best_spec, best_score = scored[0]
        rationale = self._explain(best_spec, best_score, request)
        estimated = best_spec.estimate_cost(
            request.input_tokens, request.max_output_tokens
        )

        # Build the fallback chain (everything else, in score order).
        fallback = tuple(
            f"{s.provider}/{s.name}" for s, _ in scored[1 : min(4, len(scored))]
        )

        return RouteDecision(
            provider=best_spec.provider,
            model=best_spec.name,
            spec=best_spec,
            tier=best_spec.tier,
            rationale=rationale,
            estimated_cost_usd=estimated,
            fallback_chain=fallback,
            budget_remaining_usd=budget_remaining,
            request_id=uuid.uuid4().hex,
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record(
        self,
        decision: RouteDecision,
        *,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        success: bool = True,
        error: str | None = None,
        user_id: str | None = None,
        plan_id: str | None = None,
        task: Any = None,
    ) -> CostRecord:
        """Record actual spend + outcome for a routed call.

        The router updates its health tracker, ledger, and (optionally)
        writes to HelixDB — but does **not** retry.  The executor is
        responsible for the actual call and its retry policy.
        """
        # Health tracking
        if success:
            self.health.record_success(decision.provider, latency_ms=latency_ms)
        else:
            self.health.record_failure(
                decision.provider, latency_ms=latency_ms, error=error
            )

        actual_cost = decision.spec.estimate_cost(input_tokens, output_tokens)
        from app.core.cost_router.types import TaskType

        rec = CostRecord(
            provider=decision.provider,
            model=decision.model,
            tier=decision.tier,
            task=task if isinstance(task, TaskType) else (task or TaskType.CHAT),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=actual_cost,
            latency_ms=latency_ms,
            user_id=user_id or decision.spec and None,
            plan_id=plan_id,
            success=success,
            error=error,
        )
        await self.ledger.record(rec)
        return rec

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _candidates(self, request: RouteRequest) -> list[ModelSpec]:
        """Filter the catalog down to models that *could* handle this request."""
        # 1. Hard structural filters
        allowed_tiers = list(ModelTier)  # default: all tiers
        in_range = self.catalog.within_tier_range(
            self.catalog.all(), request.min_tier, request.max_tier
        )
        if in_range:
            allowed_tiers = [s.tier for s in in_range]
        candidates = self.catalog.filter(
            tiers=allowed_tiers,
            require=request.requires,
            task=request.task,
            min_context=request.input_tokens + request.max_output_tokens,
        )
        if not candidates:
            return []
        # 2. Provider health
        if any(self.health.snapshot(p) for p in {s.provider for s in candidates}):
            healthy = {
                s.provider for s in candidates if self.health.is_healthy(s.provider)
            }
            if healthy:  # don't filter to empty if we have nothing recorded
                candidates = [s for s in candidates if s.provider in healthy]
        # 3. API-key availability
        if self.respect_provider_keys:
            enabled = self._enabled_providers()
            if enabled is not None:
                candidates = [s for s in candidates if s.provider in enabled]
        # 4. Local models need an Ollama server to be reachable; we
        #    can't probe that here cheaply, so we just include them
        #    and let the call fail loudly if ollama is down.
        return candidates

    def _enabled_providers(self) -> set[str] | None:
        """Return the set of providers with an API key configured.

        ``None`` means "we couldn't tell" (e.g. Config not importable) —
        callers should treat that as "all providers enabled".
        """
        try:
            from app.settings.config import Config  # type: ignore
        except Exception:  # noqa: BLE001
            return None
        keys = {
            "anthropic": bool(getattr(Config, "ANTHROPIC_API_KEY", None)),
            "openai": bool(getattr(Config, "OPENAI_API_KEY", None)),
            "google": bool(
                getattr(Config, "GOOGLE_API_KEY", None)
                or getattr(Config, "GEMINI_API_KEY", None)
            ),
            "openrouter": bool(getattr(Config, "OPENROUTER_API_KEY", None)),
            "groq": bool(getattr(Config, "GROQ_API_KEY", None)),
            "xai": bool(getattr(Config, "XAI_API_KEY", None)),
            "ollama": True,  # local; reachability handled at call time
            "opencode_api": bool(getattr(Config, "OPENCODE_API_KEY", None)),
        }
        # If nothing is configured at all, return None (don't filter).
        if not any(keys.values()):
            return None
        return {p for p, ok in keys.items() if ok}

    def _score_candidates(
        self, candidates: list[ModelSpec], request: RouteRequest
    ) -> list[tuple[ModelSpec, float]]:
        """Score each candidate.  Lower is better.

        Score = cost − (quality × 10) + (latency_ms / 1000)

        Quality is weighted heavily so the router prefers the *right*
        model, not just the cheapest one.  The exact constants are
        tuning knobs.
        """
        min_quality = _DEFAULT_QUALITY_FLOOR.get(request.task.value, 0.5)
        scored: list[tuple[ModelSpec, float]] = []
        for s in candidates:
            q = s.quality.get(request.task, 0.0)
            if q < min_quality:
                continue
            cost = s.estimate_cost(request.input_tokens, request.max_output_tokens)
            # Latency: only matters if the request has a tight budget
            latency_penalty = s.typical_latency_ms / 1000.0
            # We want low cost, low latency, high quality → subtract quality.
            score = cost + latency_penalty - (q * 0.10)
            scored.append((s, score))
        scored.sort(key=lambda pair: pair[1])
        return scored

    def _effective_budget(
        self, request: RouteRequest, remaining: float | None
    ) -> float | None:
        """Return the tighter of the per-request cap and the remaining budget."""
        candidates: list[float] = []
        if request.budget_usd is not None:
            candidates.append(request.budget_usd)
        if self.ledger.config.per_request_usd is not None:
            candidates.append(self.ledger.config.per_request_usd)
        if remaining is not None:
            candidates.append(remaining)
        return min(candidates) if candidates else None

    def _explain(self, spec: ModelSpec, score: float, request: RouteRequest) -> str:
        q = spec.quality.get(request.task, 0.0)
        return (
            f"tier={spec.tier.value} quality={q:.2f} "
            f"cost=${spec.estimate_cost(request.input_tokens, request.max_output_tokens):.4f} "
            f"local={spec.is_local}"
        )


__all__ = ["CostRouter", "HealthSnapshot"]
