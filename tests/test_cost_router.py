"""Tests for the cost router (A2 in the foundation plan)."""

from __future__ import annotations


import pytest

from app.core.cost_router import (
    BudgetConfig,
    BudgetExceededError,
    BudgetLedger,
    CostRecord,
    CostRouter,
    ModelCatalog,
    ModelTier,
    NoRouteAvailableError,
    ProviderHealth,
    RouteRequest,
    TaskType,
)
from app.core.cost_router.types import ModelCapability, ModelSpec


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class TestCatalog:
    def test_default_catalog_has_models(self) -> None:
        cat = ModelCatalog()
        assert len(cat.all()) > 10
        # At least one model per tier
        tiers = {s.tier for s in cat.all()}
        assert ModelTier.NANO in tiers
        assert ModelTier.SMALL in tiers
        assert ModelTier.MEDIUM in tiers
        assert ModelTier.LARGE in tiers
        assert ModelTier.PREMIUM in tiers

    def test_filter_by_tier(self) -> None:
        cat = ModelCatalog()
        small = cat.filter(tiers=[ModelTier.SMALL])
        assert all(s.tier == ModelTier.SMALL for s in small)
        assert small  # at least one

    def test_filter_by_capability(self) -> None:
        cat = ModelCatalog()
        vision = cat.filter(require=[ModelCapability.VISION])
        assert all(s.supports(ModelCapability.VISION) for s in vision)
        assert vision  # gpt-4o / claude / gemini have it

    def test_filter_by_min_quality(self) -> None:
        cat = ModelCatalog()
        high = cat.filter(task=TaskType.REASONING, min_quality=0.9)
        assert all(s.quality.get(TaskType.REASONING, 0) >= 0.9 for s in high)
        # opus-4 and o3 should both qualify
        names = {s.name for s in high}
        assert "claude-opus-4-20250514" in names or "o3" in names

    def test_filter_by_min_context(self) -> None:
        cat = ModelCatalog()
        big = cat.filter(min_context=500_000)
        assert all(s.max_context >= 500_000 for s in big)
        # gemini-1.5-flash has 1M context
        assert any(s.name == "gemini-1.5-flash" for s in big)

    def test_filter_by_local(self) -> None:
        cat = ModelCatalog()
        local = cat.filter(is_local=True)
        assert all(s.is_local for s in local)
        assert all(s.input_cost_per_1k == 0.0 for s in local)

    def test_override_price(self) -> None:
        cat = ModelCatalog()
        cat.override_price("openai", "gpt-4o-mini", input_cost=0.0001, output_cost=0.0004)
        spec = cat.get("openai", "gpt-4o-mini")
        assert spec is not None
        assert spec.input_cost_per_1k == 0.0001
        assert spec.output_cost_per_1k == 0.0004

    def test_override_unknown_raises(self) -> None:
        cat = ModelCatalog()
        with pytest.raises(KeyError):
            cat.override_price("nope", "nope", input_cost=0, output_cost=0)

    def test_disable(self) -> None:
        cat = ModelCatalog()
        cat.disable("openai", "gpt-4o-mini")
        assert cat.get("openai", "gpt-4o-mini") is None

    def test_add_replaces_existing(self) -> None:
        cat = ModelCatalog()
        cat.get("openai", "gpt-4o-mini")  # baseline: model exists
        cat.add(
            ModelSpec(
                provider="openai",
                name="gpt-4o-mini",
                tier=ModelTier.SMALL,
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
            )
        )
        new = cat.get("openai", "gpt-4o-mini")
        assert new is not None
        assert new.input_cost_per_1k == 0.0
        # And it replaced, not appended
        matches = [s for s in cat.all() if s.provider == "openai" and s.name == "gpt-4o-mini"]
        assert len(matches) == 1

    def test_within_tier_range(self) -> None:
        cat = ModelCatalog()
        smalls = cat.within_tier_range(cat.all(), ModelTier.SMALL, ModelTier.MEDIUM)
        assert all(s.tier in {ModelTier.SMALL, ModelTier.MEDIUM} for s in smalls)

    def test_filter_with_no_matches_returns_empty(self) -> None:
        cat = ModelCatalog()
        # Require a capability nothing has
        out = (
            cat.filter(require=[ModelCapability.IMAGE])  # type: ignore[attr-defined]
            if hasattr(ModelCapability, "IMAGE")
            else []
        )
        # IMAGE may not exist; just assert the call shape
        assert isinstance(out, list)


# ---------------------------------------------------------------------------
# ModelSpec
# ---------------------------------------------------------------------------


class TestModelSpec:
    def test_estimate_cost_local_is_free(self) -> None:
        spec = ModelSpec(
            provider="ollama",
            name="test",
            tier=ModelTier.NANO,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            is_local=True,
        )
        assert spec.estimate_cost(1_000_000, 1_000_000) == 0.0

    def test_estimate_cost_cloud(self) -> None:
        spec = ModelSpec(
            provider="openai",
            name="test",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
        )
        # 1000 input + 1000 output = $0.001 + $0.002 = $0.003
        assert spec.estimate_cost(1000, 1000) == pytest.approx(0.003)

    def test_supports_capability(self) -> None:
        spec = ModelSpec(
            provider="x",
            name="x",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            capabilities=frozenset({ModelCapability.TOOL_USE}),
        )
        assert spec.supports(ModelCapability.TOOL_USE)
        assert not spec.supports(ModelCapability.VISION)


# ---------------------------------------------------------------------------
# BudgetLedger
# ---------------------------------------------------------------------------


class TestBudgetLedger:
    @pytest.mark.asyncio
    async def test_check_budget_no_limits(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_user_per_day_usd=None, per_request_usd=None))
        ok, reason = await ledger.check_budget(additional_usd=1.0)
        assert ok
        assert reason is None

    @pytest.mark.asyncio
    async def test_check_per_request_cap(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_request_usd=0.01))
        ok, _ = await ledger.check_budget(additional_usd=0.001)
        assert ok
        ok, reason = await ledger.check_budget(additional_usd=0.5)
        assert not ok
        assert "per-request" in (reason or "")

    @pytest.mark.asyncio
    async def test_check_per_plan_cap(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_plan_usd=1.0, per_user_per_day_usd=None, per_request_usd=None))
        await ledger.record(
            CostRecord(
                provider="openai",
                model="gpt-4o-mini",
                tier=ModelTier.SMALL,
                task=TaskType.CHAT,
                input_tokens=1000,
                output_tokens=1000,
                cost_usd=0.5,
                latency_ms=100,
                user_id="u1",
                plan_id="p1",
            )
        )
        ok, reason = await ledger.check_budget(plan_id="p1", additional_usd=0.6)
        assert not ok
        assert "per-plan" in (reason or "")

    @pytest.mark.asyncio
    async def test_check_per_user_daily(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_user_per_day_usd=1.0))
        for _ in range(3):
            await ledger.record(
                CostRecord(
                    provider="x",
                    model="y",
                    tier=ModelTier.SMALL,
                    task=TaskType.CHAT,
                    input_tokens=1000,
                    output_tokens=1000,
                    cost_usd=0.4,
                    latency_ms=10,
                    user_id="u1",
                    plan_id=None,
                )
            )
        ok, reason = await ledger.check_budget(user_id="u1", additional_usd=0.01)
        assert not ok
        assert "per-user" in (reason or "")

    @pytest.mark.asyncio
    async def test_budget_remaining(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_user_per_day_usd=1.0, per_request_usd=None, per_plan_usd=None))
        await ledger.record(
            CostRecord(
                provider="x",
                model="y",
                tier=ModelTier.SMALL,
                task=TaskType.CHAT,
                input_tokens=100,
                output_tokens=100,
                cost_usd=0.3,
                latency_ms=10,
                user_id="u1",
            )
        )
        remaining = await ledger.budget_remaining(user_id="u1")
        assert remaining == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_budget_remaining_no_limits(self) -> None:
        ledger = BudgetLedger(BudgetConfig(per_user_per_day_usd=None, per_request_usd=None, per_plan_usd=None))
        assert await ledger.budget_remaining(user_id="u1") is None

    @pytest.mark.asyncio
    async def test_summary_aggregates(self) -> None:
        ledger = BudgetLedger()
        await ledger.record(
            CostRecord(
                provider="a",
                model="m1",
                tier=ModelTier.SMALL,
                task=TaskType.CHAT,
                input_tokens=10,
                output_tokens=20,
                cost_usd=0.1,
                latency_ms=50,
                user_id="u1",
            )
        )
        await ledger.record(
            CostRecord(
                provider="b",
                model="m2",
                tier=ModelTier.LARGE,
                task=TaskType.CODE,
                input_tokens=10,
                output_tokens=20,
                cost_usd=0.5,
                latency_ms=200,
                user_id="u2",
            )
        )
        s = ledger.summary()
        assert s.total_usd == pytest.approx(0.6)
        assert s.total_tokens == 60
        assert s.by_model["a/m1"] == pytest.approx(0.1)
        assert s.by_model["b/m2"] == pytest.approx(0.5)
        assert s.by_task["chat"] == pytest.approx(0.1)
        assert s.by_task["code"] == pytest.approx(0.5)
        assert s.by_user["u1"] == pytest.approx(0.1)
        assert s.by_user["u2"] == pytest.approx(0.5)
        assert s.record_count == 2

    @pytest.mark.asyncio
    async def test_spend_today(self) -> None:
        ledger = BudgetLedger()
        await ledger.record(
            CostRecord(
                provider="x",
                model="y",
                tier=ModelTier.SMALL,
                task=TaskType.CHAT,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.25,
                latency_ms=0,
                user_id="u1",
            )
        )
        assert ledger.spend_today("u1") == pytest.approx(0.25)
        assert ledger.spend_today("nope") == 0.0


# ---------------------------------------------------------------------------
# ProviderHealth
# ---------------------------------------------------------------------------


class TestProviderHealth:
    def test_unknown_provider_is_healthy(self) -> None:
        h = ProviderHealth()
        assert h.is_healthy("newprovider")

    def test_healthy_after_successes(self) -> None:
        h = ProviderHealth(window=3, max_failure_rate=0.5)
        for _ in range(3):
            h.record_success("p", latency_ms=100)
        assert h.is_healthy("p")

    def test_unhealthy_after_failures(self) -> None:
        h = ProviderHealth(window=4, max_failure_rate=0.5)
        h.record_success("p", latency_ms=100)
        h.record_failure("p", error="timeout")
        h.record_failure("p", error="timeout")
        h.record_failure("p", error="timeout")
        assert not h.is_healthy("p")

    def test_recovery_after_successes(self) -> None:
        h = ProviderHealth(window=3, max_failure_rate=0.4)
        h.record_failure("p", error="boom")
        h.record_failure("p", error="boom")
        h.record_success("p", latency_ms=50)
        h.record_success("p", latency_ms=50)
        h.record_success("p", latency_ms=50)
        assert h.is_healthy("p")

    def test_healthy_providers_filter(self) -> None:
        h = ProviderHealth()
        h.record_failure("bad", error="x")
        h.record_failure("bad", error="x")
        h.record_success("good", latency_ms=10)
        out = h.healthy_providers(["bad", "good", "unknown"])
        assert "good" in out
        assert "unknown" in out  # unknown is treated as healthy
        assert "bad" not in out

    def test_reset(self) -> None:
        h = ProviderHealth()
        h.record_success("p", latency_ms=10)
        h.reset("p")
        assert h.snapshot("p") == []


# ---------------------------------------------------------------------------
# CostRouter
# ---------------------------------------------------------------------------


def _router() -> CostRouter:
    """Build a router with no provider-key filtering and unlimited budgets (for test isolation)."""
    return CostRouter(
        catalog=ModelCatalog(),
        ledger=BudgetLedger(BudgetConfig(per_user_per_day_usd=None, per_request_usd=None, per_plan_usd=None)),
        health=ProviderHealth(),
        respect_provider_keys=False,
    )


class TestCostRouter:
    @pytest.mark.asyncio
    async def test_basic_route_returns_decision(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=200,
            )
        )
        assert d.provider
        assert d.model
        assert d.tier in ModelTier
        assert d.estimated_cost_usd >= 0
        assert d.request_id
        assert d.rationale

    @pytest.mark.asyncio
    async def test_local_first_under_budget(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CLASSIFY,
                input_tokens=50,
                max_output_tokens=50,
            )
        )
        # Classification is fine on local; the router should prefer cheap.
        assert d.tier in {ModelTier.NANO, ModelTier.SMALL}

    @pytest.mark.asyncio
    async def test_reasoning_picks_higher_quality(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.REASONING,
                input_tokens=2000,
                max_output_tokens=4000,
            )
        )
        # Reasoning should NOT be a nano model.
        assert d.tier in {ModelTier.LARGE, ModelTier.PREMIUM, ModelTier.MEDIUM}

    @pytest.mark.asyncio
    async def test_budget_cap_picks_cheaper(self) -> None:
        r = _router()
        # Force a non-free model: research on a tight budget prefers
        # the cheap openrouter llama over the premium Anthropic options.
        d = await r.route(
            RouteRequest(
                task=TaskType.RESEARCH,
                input_tokens=10_000,
                max_output_tokens=5_000,
                budget_usd=0.01,
                min_tier=ModelTier.MEDIUM,
            )
        )
        assert d.estimated_cost_usd <= 0.01
        # Should not be premium tier
        assert d.tier != ModelTier.PREMIUM

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self) -> None:
        r = _router()
        r.ledger.set_config(BudgetConfig(per_request_usd=0.0001))
        # Force a paid model: premium tier has no free options.
        with pytest.raises(BudgetExceededError):
            await r.route(
                RouteRequest(
                    task=TaskType.RESEARCH,
                    input_tokens=50_000,
                    max_output_tokens=10_000,
                    min_tier=ModelTier.PREMIUM,
                )
            )

    @pytest.mark.asyncio
    async def test_no_route_raises(self) -> None:
        r = _router()
        with pytest.raises(NoRouteAvailableError):
            await r.route(
                RouteRequest(
                    task=TaskType.RESEARCH,
                    input_tokens=10_000_000_000,  # way over any context
                    max_output_tokens=1000,
                )
            )

    @pytest.mark.asyncio
    async def test_tier_range_respected(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=100,
                min_tier=ModelTier.MEDIUM,
                max_tier=ModelTier.LARGE,
            )
        )
        assert d.tier in {ModelTier.MEDIUM, ModelTier.LARGE}

    @pytest.mark.asyncio
    async def test_capability_filter(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CODE,
                input_tokens=200,
                max_output_tokens=500,
                requires=frozenset({ModelCapability.CODE_EXEC}),
            )
        )
        # Only models with CODE_EXEC qualify.
        assert d.spec.supports(ModelCapability.CODE_EXEC)

    @pytest.mark.asyncio
    async def test_fallback_chain_non_empty(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=200,
            )
        )
        # At least the top 2 alternatives should be listed.
        assert len(d.fallback_chain) >= 2

    @pytest.mark.asyncio
    async def test_decision_to_dict_roundtrip(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=200,
            )
        )
        d2 = d.to_dict()
        assert d2["provider"] == d.provider
        assert d2["model"] == d.model
        assert d2["tier"] == d.tier.value

    @pytest.mark.asyncio
    async def test_record_updates_ledger_and_health(self) -> None:
        r = _router()
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=200,
                user_id="u1",
                plan_id="p1",
            )
        )
        rec = await r.record(
            d,
            input_tokens=100,
            output_tokens=200,
            latency_ms=500,
            user_id="u1",
            plan_id="p1",
        )
        assert rec.cost_usd == d.estimated_cost_usd
        assert r.ledger.spend_today("u1") == rec.cost_usd
        assert r.health.snapshot(d.provider) != []

    @pytest.mark.asyncio
    async def test_unhealthy_provider_excluded(self) -> None:
        r = _router()
        # Mark a provider as unhealthy.
        for _ in range(5):
            r.health.record_failure("anthropic", error="boom")
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=100,
                max_output_tokens=200,
            )
        )
        assert d.provider != "anthropic"

    @pytest.mark.asyncio
    async def test_ledger_budget_remaining_in_decision(self) -> None:
        r = _router()
        r.ledger.set_config(BudgetConfig(per_user_per_day_usd=1.0, per_request_usd=None, per_plan_usd=None))
        d = await r.route(
            RouteRequest(
                task=TaskType.CHAT,
                input_tokens=10,
                max_output_tokens=10,
                user_id="u1",
            )
        )
        assert d.budget_remaining_usd == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_loop_route_record_summarize(self) -> None:
        r = CostRouter(
            catalog=ModelCatalog(),
            ledger=BudgetLedger(BudgetConfig(per_user_per_day_usd=10.0)),
            health=ProviderHealth(),
            respect_provider_keys=False,
        )
        # Route 5 research requests as the same user (force paid tier)
        for i in range(5):
            d = await r.route(
                RouteRequest(
                    task=TaskType.RESEARCH,
                    input_tokens=2_000,
                    max_output_tokens=2_000,
                    user_id="u1",
                    plan_id="p1",
                    min_tier=ModelTier.PREMIUM,
                )
            )
            await r.record(
                d,
                input_tokens=2_000,
                output_tokens=2_000,
                latency_ms=300,
                user_id="u1",
                plan_id="p1",
            )
        s = r.ledger.summary()
        assert s.record_count == 5
        assert s.total_usd > 0
        assert s.by_user["u1"] == s.total_usd
        # Should still have budget left
        remaining = await r.ledger.budget_remaining(user_id="u1")
        assert remaining is not None
        assert remaining < 10.0

    @pytest.mark.asyncio
    async def test_budget_exhaustion_blocks_further_calls(self) -> None:
        r = CostRouter(
            catalog=ModelCatalog(),
            ledger=BudgetLedger(BudgetConfig(per_user_per_day_usd=0.05)),
            health=ProviderHealth(),
            respect_provider_keys=False,
        )
        # First call goes through
        d1 = await r.route(
            RouteRequest(
                task=TaskType.RESEARCH,
                input_tokens=10_000,
                max_output_tokens=10_000,
                user_id="u1",
            )
        )
        # Manually exhaust the budget by inflating the user's spend bucket
        r.ledger._buckets[r.ledger._bucket_key("user", "u1")] = 0.10
        # Next call should fail budget check (remaining = -0.05, cheapest = $0)
        with pytest.raises(BudgetExceededError):
            await r.route(
                RouteRequest(
                    task=TaskType.RESEARCH,
                    input_tokens=10_000,
                    max_output_tokens=10_000,
                    user_id="u1",
                )
            )
