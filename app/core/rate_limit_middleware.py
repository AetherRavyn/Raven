"""Rate-limit middleware — unified subscription + rate-limiter for LLM calls.

Wires :class:`SubscriptionManager` (monthly token budgets) and
:class:`RateLimiter` (sliding-window request rate) into a single
pre-LLM-call check, with a ``RAVEN_RATE_LIMIT`` env-var toggle.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.subscription_proxy import RateLimiter, SubscriptionManager

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when a user has exceeded their rate limit or token budget."""

    def __init__(self, reason: str, retry_after: int = 0, reset_at: str = "") -> None:
        self.reason = reason
        self.retry_after = retry_after
        self.reset_at = reset_at
        super().__init__(reason)


class RateLimitMiddleware:
    """Unified rate-limiting and subscription enforcement for LLM calls.

    Usage in runtime::

        self._rate_mw = RateLimitMiddleware()

        # Before LLM call:
        result = await self._rate_mw.check(user_id, input_tokens, output_tokens)
        if not result["allowed"]:
            return {"success": False, "error": result["reason"], ...}

        # After LLM call (on success):
        await self._rate_mw.record(user_id, tokens_consumed)
    """

    def __init__(
        self,
        subscription_db: str | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._subscription = SubscriptionManager(subscription_db or "workspace/memory/subscriptions.db")
        self._rate_limiter = rate_limiter or RateLimiter()
        self._enabled = os.environ.get("RAVEN_RATE_LIMIT", "true").strip().lower() in (
            "true",
            "1",
            "yes",
        )

    async def check(
        self,
        user_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        """Check whether an LLM call is allowed for *user_id*.

        Returns::

            {"allowed": True}
            {"allowed": False, "reason": "rate_limited",
             "retry_after": 30, "reset_at": "..."}
            {"allowed": False, "reason": "budget_exceeded",
             "tokens_remaining": 0}

        When *enabled* is ``False`` the check always passes.
        """
        if not self._enabled:
            return {"allowed": True}

        # 1. Sliding-window rate check (requests per minute)
        rate_status = await self._rate_limiter.check_rate_limit(user_id)
        if not rate_status.allowed:
            logger.info("Rate limit hit for user=%s (retry_after=%ds)", user_id, rate_status.retry_after)
            return {
                "allowed": False,
                "reason": "rate_limited",
                "retry_after": rate_status.retry_after,
                "reset_at": rate_status.reset_at,
            }

        # 2. Monthly token budget check
        total_needed = input_tokens + output_tokens
        if total_needed > 0:
            has_tokens = self._subscription.has_tokens(user_id, total_needed)
            if not has_tokens:
                sub = self._subscription.get_subscription(user_id)
                remaining = sub.tokens_remaining if sub else 0
                logger.info("Budget exceeded for user=%s (remaining=%d)", user_id, remaining)
                return {
                    "allowed": False,
                    "reason": "budget_exceeded",
                    "tokens_remaining": remaining,
                }

        return {"allowed": True}

    async def record(
        self,
        user_id: str,
        tokens_consumed: int,
        action: str = "llm_call",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record token consumption after a successful LLM call.

        Updates both the subscription usage ledger and the rate-limiter
        sliding window.  This is a no-op when the middleware is disabled.
        """
        if not self._enabled:
            return
        if tokens_consumed > 0:
            self._subscription.consume_tokens(user_id, tokens_consumed)
        self._subscription.record_usage(user_id, action, tokens_consumed, metadata)
        await self._rate_limiter.consume(user_id, tokens_consumed)

    @property
    def usage_summary(self) -> dict[str, Any]:
        """Return current usage summary (total subscriptions, active, etc.)."""
        active = self._subscription.list_active_subscriptions()
        return {
            "enabled": self._enabled,
            "active_users": len(active),
            "total_subscriptions": len(active),
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
