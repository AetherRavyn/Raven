"""Static catalog of models the router may pick.

The catalog is a flat, in-memory list.  The router reads it on every
decision, so lookups stay O(n) with n ≈ 30.  When the catalog grows we
can swap this for a trie or DB-backed index; the public interface will
not change.

Prices are USD per 1K tokens and are the **list prices** as of
mid-2026.  Override them per-deployment with :class:`ModelCatalog`'s
``override`` argument.

Quality scores are *subjective* — derived from public benchmarks
(MMLU, HumanEval, GSM8K) and anecdotal experience.  They are deliberately
coarse: the difference between 0.6 and 0.7 rarely matters, but the
difference between 0.3 and 0.8 does.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Iterable

from app.core.cost_router.types import (
    ModelCapability,
    ModelSpec,
    ModelTier,
    TaskType,
)

logger = logging.getLogger(__name__)


def _specs() -> list[ModelSpec]:
    """Build the default catalog.  One place to keep all pricing data."""
    cap_full = frozenset(
        {
            ModelCapability.TOOL_USE,
            ModelCapability.JSON_MODE,
            ModelCapability.STREAMING,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.LONG_CONTEXT,
        }
    )
    cap_code = frozenset(
        {
            ModelCapability.TOOL_USE,
            ModelCapability.JSON_MODE,
            ModelCapability.STREAMING,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.CODE_EXEC,
        }
    )
    cap_basic = frozenset({ModelCapability.STREAMING})

    return [
        # ------------------------------------------------------------------
        # Local (free at the point of use)
        # ------------------------------------------------------------------
        ModelSpec(
            provider="ollama",
            name="llama3.2:1b",
            tier=ModelTier.NANO,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            quality={
                TaskType.CHAT: 0.4,
                TaskType.CLASSIFY: 0.5,
                TaskType.EXTRACT: 0.5,
                TaskType.SUMMARIZE: 0.3,
            },
            capabilities=cap_basic,
            max_context=8192,
            typical_latency_ms=300,
            is_local=True,
        ),
        ModelSpec(
            provider="ollama",
            name="llama3.2:3b",
            tier=ModelTier.NANO,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            quality={
                TaskType.CHAT: 0.55,
                TaskType.CLASSIFY: 0.65,
                TaskType.EXTRACT: 0.6,
                TaskType.SUMMARIZE: 0.5,
                TaskType.CODE: 0.4,
            },
            capabilities=cap_basic,
            max_context=8192,
            typical_latency_ms=600,
            is_local=True,
        ),
        ModelSpec(
            provider="ollama",
            name="qwen2.5-coder:7b",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            quality={
                TaskType.CODE: 0.78,
                TaskType.CHAT: 0.6,
                TaskType.SUMMARIZE: 0.55,
            },
            capabilities=cap_code,
            max_context=32768,
            typical_latency_ms=1200,
            is_local=True,
        ),
        ModelSpec(
            provider="ollama",
            name="llama3.1:8b",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            quality={
                TaskType.CHAT: 0.65,
                TaskType.SUMMARIZE: 0.6,
                TaskType.EXTRACT: 0.65,
                TaskType.CODE: 0.55,
                TaskType.REASONING: 0.5,
            },
            capabilities=cap_full,
            max_context=128000,
            typical_latency_ms=1500,
            is_local=True,
        ),
        ModelSpec(
            provider="ollama",
            name="qwen2.5:14b",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            quality={
                TaskType.CHAT: 0.7,
                TaskType.REASONING: 0.6,
                TaskType.RESEARCH: 0.6,
                TaskType.CODE: 0.7,
            },
            capabilities=cap_full,
            max_context=128000,
            typical_latency_ms=2000,
            is_local=True,
        ),
        # ------------------------------------------------------------------
        # Cheap cloud (OpenAI / Anthropic / Google small models)
        # ------------------------------------------------------------------
        ModelSpec(
            provider="openai",
            name="gpt-4o-mini",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.00015,
            output_cost_per_1k=0.0006,
            quality={
                TaskType.CHAT: 0.72,
                TaskType.SUMMARIZE: 0.7,
                TaskType.EXTRACT: 0.75,
                TaskType.CLASSIFY: 0.78,
                TaskType.CODE: 0.7,
                TaskType.RESEARCH: 0.65,
            },
            capabilities=cap_full,
            max_context=128000,
            typical_latency_ms=900,
        ),
        ModelSpec(
            provider="anthropic",
            name="claude-3-5-haiku-20241022",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.0008,
            output_cost_per_1k=0.004,
            quality={
                TaskType.CHAT: 0.78,
                TaskType.SUMMARIZE: 0.78,
                TaskType.EXTRACT: 0.8,
                TaskType.CLASSIFY: 0.78,
                TaskType.CODE: 0.74,
                TaskType.RESEARCH: 0.72,
            },
            capabilities=cap_full,
            max_context=200000,
            typical_latency_ms=1100,
        ),
        ModelSpec(
            provider="google",
            name="gemini-1.5-flash",
            tier=ModelTier.SMALL,
            input_cost_per_1k=0.000075,
            output_cost_per_1k=0.0003,
            quality={
                TaskType.CHAT: 0.72,
                TaskType.SUMMARIZE: 0.72,
                TaskType.EXTRACT: 0.75,
                TaskType.CODE: 0.7,
                TaskType.RESEARCH: 0.7,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=1000000,
            typical_latency_ms=700,
        ),
        # ------------------------------------------------------------------
        # Medium tier
        # ------------------------------------------------------------------
        ModelSpec(
            provider="openai",
            name="gpt-4o",
            tier=ModelTier.MEDIUM,
            input_cost_per_1k=0.0025,
            output_cost_per_1k=0.01,
            quality={
                TaskType.CHAT: 0.88,
                TaskType.SUMMARIZE: 0.86,
                TaskType.EXTRACT: 0.88,
                TaskType.CODE: 0.88,
                TaskType.REASONING: 0.84,
                TaskType.RESEARCH: 0.86,
                TaskType.CLASSIFY: 0.88,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=128000,
            typical_latency_ms=1500,
        ),
        ModelSpec(
            provider="anthropic",
            name="claude-3-5-sonnet-20241022",
            tier=ModelTier.MEDIUM,
            input_cost_per_1k=0.003,
            output_cost_per_1k=0.015,
            quality={
                TaskType.CHAT: 0.9,
                TaskType.SUMMARIZE: 0.9,
                TaskType.EXTRACT: 0.9,
                TaskType.CODE: 0.9,
                TaskType.REASONING: 0.88,
                TaskType.RESEARCH: 0.9,
                TaskType.CLASSIFY: 0.88,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=200000,
            typical_latency_ms=2000,
        ),
        # ------------------------------------------------------------------
        # Large / flagship
        # ------------------------------------------------------------------
        ModelSpec(
            provider="openai",
            name="gpt-4.1",
            tier=ModelTier.LARGE,
            input_cost_per_1k=0.010,
            output_cost_per_1k=0.030,
            quality={
                TaskType.CHAT: 0.92,
                TaskType.SUMMARIZE: 0.9,
                TaskType.CODE: 0.93,
                TaskType.REASONING: 0.92,
                TaskType.RESEARCH: 0.92,
                TaskType.EXTRACT: 0.9,
                TaskType.CLASSIFY: 0.9,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=1000000,
            typical_latency_ms=3000,
        ),
        ModelSpec(
            provider="anthropic",
            name="claude-sonnet-4-20250514",
            tier=ModelTier.LARGE,
            input_cost_per_1k=0.003,
            output_cost_per_1k=0.015,
            quality={
                TaskType.CHAT: 0.93,
                TaskType.SUMMARIZE: 0.92,
                TaskType.CODE: 0.93,
                TaskType.REASONING: 0.92,
                TaskType.RESEARCH: 0.93,
                TaskType.EXTRACT: 0.92,
                TaskType.CLASSIFY: 0.9,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=200000,
            typical_latency_ms=2500,
        ),
        # ------------------------------------------------------------------
        # Premium / reasoning
        # ------------------------------------------------------------------
        ModelSpec(
            provider="anthropic",
            name="claude-opus-4-20250514",
            tier=ModelTier.PREMIUM,
            input_cost_per_1k=0.015,
            output_cost_per_1k=0.075,
            quality={
                TaskType.CHAT: 0.95,
                TaskType.SUMMARIZE: 0.95,
                TaskType.CODE: 0.95,
                TaskType.REASONING: 0.96,
                TaskType.RESEARCH: 0.96,
                TaskType.EXTRACT: 0.94,
                TaskType.CLASSIFY: 0.92,
            },
            capabilities=cap_full | {ModelCapability.VISION},
            max_context=200000,
            typical_latency_ms=5000,
        ),
        ModelSpec(
            provider="openai",
            name="o3",
            tier=ModelTier.PREMIUM,
            input_cost_per_1k=0.060,
            output_cost_per_1k=0.240,
            quality={
                TaskType.REASONING: 0.97,
                TaskType.CODE: 0.95,
                TaskType.RESEARCH: 0.95,
                TaskType.CLASSIFY: 0.93,
                TaskType.EXTRACT: 0.93,
                TaskType.CHAT: 0.9,
                TaskType.SUMMARIZE: 0.9,
            },
            capabilities=cap_full,
            max_context=200000,
            typical_latency_ms=15000,
        ),
        # ------------------------------------------------------------------
        # Aggregators / cheap specialty
        # ------------------------------------------------------------------
        ModelSpec(
            provider="openrouter",
            name="meta-llama/llama-3.1-70b-instruct",
            tier=ModelTier.MEDIUM,
            input_cost_per_1k=0.0006,
            output_cost_per_1k=0.0006,
            quality={
                TaskType.CHAT: 0.82,
                TaskType.SUMMARIZE: 0.8,
                TaskType.CODE: 0.78,
                TaskType.RESEARCH: 0.78,
                TaskType.EXTRACT: 0.8,
            },
            capabilities=cap_full,
            max_context=128000,
            typical_latency_ms=2000,
        ),
        ModelSpec(
            provider="openrouter",
            name="qwen/qwen-2.5-coder-32b-instruct",
            tier=ModelTier.MEDIUM,
            input_cost_per_1k=0.0002,
            output_cost_per_1k=0.0002,
            quality={
                TaskType.CODE: 0.86,
                TaskType.CHAT: 0.78,
                TaskType.EXTRACT: 0.78,
            },
            capabilities=cap_code,
            max_context=32000,
            typical_latency_ms=1500,
        ),
    ]


class ModelCatalog:
    """Holds the set of models the router may choose from.

    The catalog supports:
    - adding or replacing specs at runtime (e.g. per-deployment config)
    - overriding prices (e.g. enterprise contract pricing)
    - filtering by provider, tier, capability
    """

    _TIER_ORDER = {
        ModelTier.NANO: 0,
        ModelTier.SMALL: 1,
        ModelTier.MEDIUM: 2,
        ModelTier.LARGE: 3,
        ModelTier.PREMIUM: 4,
    }

    def __init__(self, specs: Iterable[ModelSpec] | None = None) -> None:
        self._specs: list[ModelSpec] = list(specs) if specs is not None else _specs()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, spec: ModelSpec) -> None:
        """Add a spec, replacing any existing entry with the same key."""
        key = (spec.provider, spec.name)
        self._specs = [s for s in self._specs if (s.provider, s.name) != key]
        self._specs.append(spec)

    def override_price(
        self, provider: str, name: str, *, input_cost: float, output_cost: float
    ) -> None:
        for i, s in enumerate(self._specs):
            if s.provider == provider and s.name == name:
                self._specs[i] = replace(
                    s, input_cost_per_1k=input_cost, output_cost_per_1k=output_cost
                )
                return
        raise KeyError(f"unknown model: {provider}/{name}")

    def disable(self, provider: str, name: str) -> None:
        """Remove a model from the catalog (e.g. provider deprecated)."""
        self._specs = [s for s in self._specs if not (s.provider == provider and s.name == name)]

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def all(self) -> list[ModelSpec]:
        return list(self._specs)

    def get(self, provider: str, name: str) -> ModelSpec | None:
        for s in self._specs:
            if s.provider == provider and s.name == name:
                return s
        return None

    def filter(
        self,
        *,
        providers: Iterable[str] | None = None,
        tiers: Iterable[ModelTier] | None = None,
        min_quality: float = 0.0,
        task: TaskType | None = None,
        require: Iterable[ModelCapability] = (),
        is_local: bool | None = None,
        min_context: int = 0,
    ) -> list[ModelSpec]:
        """Return specs that pass every filter."""
        provider_set = {p.lower() for p in providers} if providers else None
        tier_set = set(tiers) if tiers else None
        require_set = frozenset(require)
        out: list[ModelSpec] = []
        for s in self._specs:
            if provider_set and s.provider not in provider_set:
                continue
            if tier_set and s.tier not in tier_set:
                continue
            if is_local is not None and s.is_local != is_local:
                continue
            if min_context and s.max_context < min_context:
                continue
            if not require_set.issubset(s.capabilities):
                continue
            if task is not None and s.quality.get(task, 0.0) < min_quality:
                continue
            out.append(s)
        return out

    def tier_order(self, tier: ModelTier) -> int:
        return self._TIER_ORDER[tier]

    def within_tier_range(
        self, specs: Iterable[ModelSpec], min_t: ModelTier, max_t: ModelTier
    ) -> list[ModelSpec]:
        lo = self._TIER_ORDER[min_t]
        hi = self._TIER_ORDER[max_t]
        return [s for s in specs if lo <= self._TIER_ORDER[s.tier] <= hi]


__all__ = ["ModelCatalog"]
