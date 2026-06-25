# app/tools/resilience.py
"""Tool Resilience Layer — standardized retry, fallback, and error reporting.

Provides decorators and utilities for making tool execution robust:
  - @with_retry: Automatic retry with exponential backoff
  - @with_fallback: Try primary, fall back to secondary on failure
  - @with_timeout: Abort if tool takes too long
  - standardize_error: Consistent error dict format

Usage in any tool:
    from app.tools.resilience import with_retry, standardize_error

    class MyTool(BaseTool):
        @with_retry(max_attempts=3, backoff_base=1.5)
        async def execute(self, **kwargs):
            ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import traceback
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def standardize_error(
    tool_name: str,
    error: Exception,
    context: str = "",
    recoverable: bool = True,
) -> Dict[str, Any]:
    """Create a consistent error response dict for any tool failure."""
    return {
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__,
        "tool": tool_name,
        "context": context,
        "recoverable": recoverable,
        "suggestion": _get_suggestion(error),
    }


def _get_suggestion(error: Exception) -> str:
    """Generate a user-friendly suggestion based on error type."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    if "timeout" in error_str or "timed out" in error_str:
        return "The service is slow. Try again in a moment."
    elif "connection" in error_str or "connect" in error_str:
        return "Cannot reach the service. Check network connectivity."
    elif "401" in error_str or "403" in error_str or "unauthorized" in error_str:
        return "Authentication failed. Check API keys or credentials."
    elif "404" in error_str or "not found" in error_str:
        return "The requested resource was not found."
    elif "rate" in error_str or "limit" in error_str or "429" in error_str:
        return "Rate limited. Wait a moment before retrying."
    elif "permission" in error_str or "denied" in error_str:
        return "Permission denied. Check access rights."
    elif error_type in ("FileNotFoundError", "OSError"):
        return "File system error. Check paths and permissions."
    elif error_type == "JSONDecodeError":
        return "Received invalid response data."
    else:
        return "An unexpected error occurred. It may resolve on retry."


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 1.5,
    retry_on: tuple = (Exception,),
    skip_on: tuple = (KeyboardInterrupt, SystemExit, asyncio.CancelledError),
) -> Callable:
    """Decorator: retry async tool execution with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        backoff_base: Base for exponential backoff (seconds).
        retry_on: Exception types to retry on.
        skip_on: Exception types to never retry on.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except skip_on:
                    raise
                except retry_on as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        delay = backoff_base ** (attempt - 1)
                        logger.warning(
                            "Tool retry %d/%d after %.1fs — %s: %s",
                            attempt,
                            max_attempts,
                            delay,
                            type(exc).__name__,
                            str(exc)[:100],
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "Tool exhausted %d retries — %s: %s",
                            max_attempts,
                            type(exc).__name__,
                            str(exc)[:200],
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


def with_timeout(seconds: float = 30.0) -> Callable:
    """Decorator: abort tool execution if it exceeds a timeout."""
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                tool_name = getattr(args[0], "get_name", lambda: "unknown")()
                raise TimeoutError(
                    f"Tool '{tool_name}' timed out after {seconds}s"
                )
        return wrapper  # type: ignore[return-value]
    return decorator


def with_fallback(fallback_fn: Callable) -> Callable:
    """Decorator: if the primary tool fails, try the fallback function.

    Args:
        fallback_fn: An async callable with the same signature.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "Tool primary failed (%s), trying fallback — %s",
                    type(exc).__name__,
                    str(exc)[:100],
                )
                return await fallback_fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


class ToolCircuitBreaker:
    """Circuit breaker pattern for tools — stop calling a broken service.

    States:
        CLOSED  — normal operation, requests flow through
        OPEN    — too many failures, requests are blocked for a cooldown period
        HALF_OPEN — cooldown expired, allow one test request
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._last_failure_time = 0.0
        self._state = "CLOSED"

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.time() - self._last_failure_time > self._cooldown_seconds:
                self._state = "HALF_OPEN"
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state
        if state == "CLOSED":
            return True
        elif state == "HALF_OPEN":
            return True  # Allow test request
        else:
            return False

    def record_success(self) -> None:
        """Record a successful call — reset failure count."""
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._state = "OPEN"
            logger.warning(
                "Circuit breaker OPEN — %d consecutive failures, cooldown %.0fs",
                self._failure_count,
                self._cooldown_seconds,
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "failure_count": self._failure_count,
            "threshold": self._failure_threshold,
            "cooldown_seconds": self._cooldown_seconds,
        }


# ── Self-Correction ──────────────────────────────────────────────


class SelfCorrector:
    """FRIDAY-style self-correction: when a tool fails, try alternative strategies.

    Each strategy is a callable that modifies the tool call parameters.
    The corrector tries strategies in order until one succeeds.
    """

    def __init__(self) -> None:
        self._strategies: list[tuple[str, Callable]] = []

    def add_strategy(self, name: str, modifier: Callable) -> None:
        """Register a correction strategy.

        The modifier takes (tool_name, kwargs, error) and returns
        modified kwargs. Return None to skip this strategy.
        """
        self._strategies.append((name, modifier))

    async def correct(
        self,
        tool_fn: Callable,
        tool_name: str,
        kwargs: Dict[str, Any],
        error: Exception,
    ) -> Any | None:
        """Try each strategy until one succeeds.

        Returns the successful result, or None if all strategies fail.
        """
        for strategy_name, modifier in self._strategies:
            try:
                modified = modifier(tool_name, kwargs, error)
                if modified is None:
                    continue
                logger.info("Self-correction: trying strategy '%s' for %s", strategy_name, tool_name)
                result = await tool_fn(**modified)
                if result and isinstance(result, dict) and result.get("success"):
                    logger.info("Self-correction succeeded with strategy '%s'", strategy_name)
                    return result
            except Exception:
                continue
        return None


# Default self-correction strategies
def _relax_parameters(tool_name: str, kwargs: Dict[str, Any], error: Exception) -> Dict[str, Any] | None:
    """If tool failed due to strict params, try relaxing them."""
    error_str = str(error).lower()
    if "invalid" in error_str or "required" in error_str or "missing" in error_str:
        # Remove optional parameters that might be causing issues
        relaxed = {k: v for k, v in kwargs.items() if v is not None}
        return relaxed if relaxed != kwargs else None
    return None


def _simplify_query(tool_name: str, kwargs: Dict[str, Any], error: Exception) -> Dict[str, Any] | None:
    """If search/query failed, try a simpler query."""
    error_str = str(error).lower()
    if "no results" in error_str or "empty" in error_str or "not found" in error_str:
        query = kwargs.get("query", "")
        if query and len(query.split()) > 3:
            # Take first 3 words
            return {**kwargs, "query": " ".join(query.split()[:3])}
    return None


def _add_timeout(tool_name: str, kwargs: Dict[str, Any], error: Exception) -> Dict[str, Any] | None:
    """If tool timed out, try with a shorter timeout or limit."""
    error_str = str(error).lower()
    if "timeout" in error_str or "timed out" in error_str:
        # Reduce any 'limit' or 'max' parameters
        modified = dict(kwargs)
        for key in ("limit", "max_results", "top_k", "max_chars"):
            if key in modified and isinstance(modified[key], (int, float)):
                modified[key] = max(1, int(modified[key] * 0.5))
        return modified if modified != kwargs else None
    return None


def _switch_provider(tool_name: str, kwargs: Dict[str, Any], error: Exception) -> Dict[str, Any] | None:
    """If LLM provider failed, suggest switching (can't auto-switch but logs the suggestion)."""
    error_str = str(error).lower()
    if "rate" in error_str or "429" in error_str or "overloaded" in error_str:
        logger.warning("Provider rate-limited — consider switching to another provider")
    return None


# Default corrector instance
_default_corrector = SelfCorrector()
_default_corrector.add_strategy("relax_params", _relax_parameters)
_default_corrector.add_strategy("simplify_query", _simplify_query)
_default_corrector.add_strategy("add_timeout", _add_timeout)
_default_corrector.add_strategy("switch_provider", _switch_provider)


def get_self_corrector() -> SelfCorrector:
    """Return the default self-corrector instance."""
    return _default_corrector
