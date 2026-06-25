"""Fallback Tier System — smart provider routing like 9Router.

Routes LLM requests through tiers:
- Tier 1: Subscription (Claude Code, Codex, Copilot)
- Tier 2: Cheap (GLM, MiniMax, DeepSeek)
- Tier 3: Free (Kiro, OpenCode, Vertex)

Auto-fallbacks when quota is exhausted or provider fails.
Tracks usage and costs per tier.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProviderTier:
    """A tier of LLM providers."""
    name: str
    priority: int  # Lower = higher priority
    providers: list[dict[str, str]] = field(default_factory=list)  # [{name, model, cost}]
    max_daily_cost: float = 0.0  # 0 = unlimited
    max_daily_requests: int = 0  # 0 = unlimited
    daily_cost: float = 0.0
    daily_requests: int = 0
    last_reset: float = 0.0


class FallbackTierSystem:
    """FRIDAY-style smart provider routing.

    Routes requests through priority tiers, auto-fallbacks
    when quota is exhausted, tracks usage and costs.
    """

    def __init__(self) -> None:
        self._tiers: list[ProviderTier] = []
        self._current_tier_index = 0
        self._setup_default_tiers()

    def _setup_default_tiers(self) -> None:
        """Setup default tier configuration."""
        self._tiers = [
            ProviderTier(
                name="subscription",
                priority=1,
                providers=[
                    {"name": "anthropic", "model": "claude-sonnet-4-20250514", "cost": "subscription"},
                    {"name": "openai", "model": "gpt-4o", "cost": "subscription"},
                    {"name": "google", "model": "gemini-2.0-flash", "cost": "subscription"},
                ],
                max_daily_cost=50.0,
                max_daily_requests=1000,
            ),
            ProviderTier(
                name="cheap",
                priority=2,
                providers=[
                    {"name": "9router", "model": "glm/glm-5.1", "cost": "$0.6/1M"},
                    {"name": "9router", "model": "minimax/MiniMax-M2.7", "cost": "$0.2/1M"},
                    {"name": "9router", "model": "glm/glm-4.7", "cost": "$0.6/1M"},
                ],
                max_daily_cost=5.0,
                max_daily_requests=500,
            ),
            ProviderTier(
                name="free",
                priority=3,
                providers=[
                    {"name": "9router", "model": "kr/claude-sonnet-4.5", "cost": "free"},
                    {"name": "9router", "model": "kr/glm-5", "cost": "free"},
                    {"name": "9router", "model": "oc/autonomous", "cost": "free"},
                ],
                max_daily_cost=0.0,
                max_daily_requests=0,
            ),
        ]

    def get_current_provider(self) -> dict[str, str] | None:
        """Get the best available provider from the current tier."""
        self._check_reset()

        for tier in self._tiers:
            if self._tier_available(tier):
                if tier.providers:
                    return tier.providers[0]
                continue

        # All tiers exhausted — return the cheapest available
        for tier in reversed(self._tiers):
            if tier.providers:
                return tier.providers[0]
        return None

    def record_usage(self, cost: float = 0.0) -> None:
        """Record usage for the current tier."""
        self._check_reset()
        if self._current_tier_index < len(self._tiers):
            tier = self._tiers[self._current_tier_index]
            tier.daily_cost += cost
            tier.daily_requests += 1

    def move_to_next_tier(self) -> bool:
        """Move to the next tier (called when current tier is exhausted)."""
        if self._current_tier_index < len(self._tiers) - 1:
            self._current_tier_index += 1
            logger.info("Fallback: moved to tier '%s'", self._tiers[self._current_tier_index].name)
            return True
        return False

    def reset_tiers(self) -> None:
        """Reset all tier counters (called daily)."""
        for tier in self._tiers:
            tier.daily_cost = 0.0
            tier.daily_requests = 0
        self._current_tier_index = 0

    def _tier_available(self, tier: ProviderTier) -> bool:
        """Check if a tier has budget remaining."""
        if tier.max_daily_cost > 0 and tier.daily_cost >= tier.max_daily_cost:
            return False
        if tier.max_daily_requests > 0 and tier.daily_requests >= tier.max_daily_requests:
            return False
        return True

    def _check_reset(self) -> None:
        """Reset daily counters if it's a new day."""
        now = time.time()
        today = int(now / 86400)
        for tier in self._tiers:
            if int(tier.last_reset / 86400) < today:
                tier.daily_cost = 0.0
                tier.daily_requests = 0
                tier.last_reset = now

    def get_status(self) -> dict[str, Any]:
        """Get the current status of all tiers."""
        self._check_reset()
        return {
            "current_tier": self._tiers[self._current_tier_index].name if self._current_tier_index < len(self._tiers) else "none",
            "tiers": [
                {
                    "name": tier.name,
                    "priority": tier.priority,
                    "available": self._tier_available(tier),
                    "daily_cost": tier.daily_cost,
                    "daily_requests": tier.daily_requests,
                    "max_cost": tier.max_daily_cost,
                    "max_requests": tier.max_daily_requests,
                }
                for tier in self._tiers
            ],
        }


# Singleton
_tier_system: FallbackTierSystem | None = None


def get_fallback_tiers() -> FallbackTierSystem:
    global _tier_system
    if _tier_system is None:
        _tier_system = FallbackTierSystem()
    return _tier_system
