# app/core/ratelimit.py
"""In-memory sliding-window rate limiter for per-user request throttling."""

from __future__ import annotations

import time
from collections import defaultdict, deque

_WINDOW_SECONDS = 60  # window duration
_MAX_REQUESTS_PER_WINDOW = 20  # limit per window
_BURST_WINDOW_SECONDS = 5  # short burst window
_MAX_BURST = 5  # max requests in burst window


class RateLimiter:
    """Thread-safe (asyncio-compatible) sliding window rate limiter."""

    def __init__(
        self,
        window_seconds: int = _WINDOW_SECONDS,
        max_requests: int = _MAX_REQUESTS_PER_WINDOW,
        burst_window: int = _BURST_WINDOW_SECONDS,
        max_burst: int = _MAX_BURST,
    ) -> None:
        self._window = window_seconds
        self._limit = max_requests
        self._burst_window = burst_window
        self._burst_limit = max_burst
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, user_key: str) -> tuple[bool, str]:
        """Check if the request is within rate limits.

        Returns (allowed: bool, reason: str).
        reason is empty string if allowed.
        """
        now = time.monotonic()
        history = self._history[user_key]

        # Remove timestamps outside the main window
        while history and now - history[0] > self._window:
            history.popleft()

        # Check burst: requests in the last burst_window seconds
        burst_count = sum(1 for t in history if now - t <= self._burst_window)
        if burst_count >= self._burst_limit:
            retry_after = (
                self._burst_window - (now - history[-self._burst_limit])
                if len(history) >= self._burst_limit
                else self._burst_window
            )
            return (
                False,
                f"Slow down — max {self._burst_limit} requests per {self._burst_window}s. "
                f"Retry in {retry_after:.0f}s.",
            )

        # Check main window
        if len(history) >= self._limit:
            retry_after = self._window - (now - history[0])
            return (
                False,
                f"Rate limit exceeded — max {self._limit} requests per {self._window}s. "
                f"Retry in {retry_after:.0f}s.",
            )

        history.append(now)
        return True, ""


class RedisRateLimiter:
    """Redis-backed sliding-window rate limiter (survives bot restarts).

    Uses a sorted-set per user_key to track request timestamps.
    Falls back silently if Redis is unreachable — returns (True, "").
    """

    def __init__(self, redis_url: str, window: int = 60, limit: int = 20) -> None:
        import redis.asyncio as aioredis  # type: ignore

        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._window = window
        self._limit = limit
        self._redis_down = False

    async def is_allowed_async(self, user_key: str) -> tuple[bool, str]:
        """Async variant — use this from async contexts."""
        import time

        now = time.time()
        pipe_key = f"ratelimit:{user_key}"
        try:
            async with self._redis.pipeline() as pipe:
                pipe.zremrangebyscore(pipe_key, 0, now - self._window)
                pipe.zcard(pipe_key)
                pipe.zadd(pipe_key, {str(now): now})
                pipe.expire(pipe_key, self._window + 1)
                results = await pipe.execute()
            count = results[1]
            if self._redis_down:
                logger.info("RedisRateLimiter reconnected successfully.")
                self._redis_down = False
            if count >= self._limit:
                return False, f"Rate limit: {self._limit} req/{self._window}s"
            return True, ""
        except Exception as exc:
            if not self._redis_down:
                logger.warning(
                    "RedisRateLimiter error (falling back to allow): %s", exc
                )
                self._redis_down = True
            return True, ""

    def is_allowed(self, user_key: str) -> tuple[bool, str]:
        """Sync shim for compatibility with in-memory RateLimiter callers.

        Runs the async check in the current event loop if available,
        otherwise falls back to allow (non-blocking degradation).
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't block a running loop — schedule and permit immediately
                # (rate-limit will take effect on next call once scheduled)
                loop.create_task(self.is_allowed_async(user_key))
                return True, ""
            return loop.run_until_complete(self.is_allowed_async(user_key))
        except Exception:
            return True, ""


import logging as _logging

logger = _logging.getLogger(__name__)

_GLOBAL_RATE_LIMITER: RateLimiter | RedisRateLimiter | None = None


def get_rate_limiter() -> RateLimiter | RedisRateLimiter:
    """Return the rate limiter.

    If REDIS_URL is set, returns a RedisRateLimiter (persistent across restarts).
    Otherwise returns the in-memory RateLimiter.
    """
    global _GLOBAL_RATE_LIMITER
    if _GLOBAL_RATE_LIMITER is not None:
        return _GLOBAL_RATE_LIMITER

    try:
        from app.settings.config import Config

        if Config.REDIS_URL:
            _GLOBAL_RATE_LIMITER = RedisRateLimiter(Config.REDIS_URL)
            return _GLOBAL_RATE_LIMITER
    except Exception:
        pass

    _GLOBAL_RATE_LIMITER = RateLimiter()
    return _GLOBAL_RATE_LIMITER
