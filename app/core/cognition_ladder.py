"""Cognition Ladder — Phase 3.3.

A 4-step escalation ladder that asks ``tiny`` first, and only escalates
to ``small`` / ``medium`` / ``large`` if the cheaper model's response
fails a confidence check.

Why: FRIDAY-on-a-laptop means the tiny local model should answer 80 %
of requests. Calling Opus for every intent classify wastes seconds,
joules, and cents. The ladder makes the cheap path the default.

Design
------
- Each step is a :class:`LadderStep` (model spec + confidence floor).
- The :meth:`CognitionLadder.run` method takes a ``prompt`` and a
  ``producer`` callable. The producer is called with each step's model
  in turn, and returns ``(text, confidence)``. If confidence is high
  enough, we return immediately; otherwise we escalate.
- The producer is responsible for the *actual model invocation*. The
  ladder is a control-flow shim that decides *when* to call what.
- The ladder never raises; it returns a :class:`LadderResult` even on
  total failure (with ``success=False`` and the last error string).
- **Cache aware** — if a cache key hits, the producer is never called.
- **Failure-aware** — a step that raised is skipped on retry; the
  ladder records the failure and tries the next step.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.core.cache import ResponseCache, get_response_cache, make_cache_key
from app.core.cost_router.types import ModelTier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LadderStep:
    """One rung of the cognition ladder."""

    name: str
    provider: str
    model: str
    tier: ModelTier = ModelTier.NANO
    # Confidence in [0.0, 1.0].  If the producer returns >= this floor,
    # we stop escalating.  A floor of 0.0 means "always accept".
    confidence_floor: float = 0.6
    # If True, this step is "free" (e.g. cached or local).  Used for
    # metrics — not for control flow.
    is_free: bool = False
    # Per-step timeout in seconds.
    timeout_s: float = 8.0


@dataclass(slots=True)
class LadderResult:
    """Outcome of one ladder run."""

    text: str
    confidence: float
    step_name: str
    provider: str
    model: str
    tier: ModelTier
    elapsed_ms: int
    escalated: bool
    from_cache: bool
    success: bool = True
    error: str | None = None
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "step_name": self.step_name,
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier.value,
            "elapsed_ms": self.elapsed_ms,
            "escalated": self.escalated,
            "from_cache": self.from_cache,
            "success": self.success,
            "error": self.error,
            "trace": list(self.trace),
        }


# A producer takes a step and returns (text, confidence).
Producer = Callable[
    [LadderStep],
    Awaitable[tuple[str, float]],
]


# The default 4-step ladder: tiny → small → medium → large.
DEFAULT_LADDER: list[LadderStep] = [
    LadderStep(
        name="tiny",
        provider="ollama",
        model="qwen2.5:3b",
        tier=ModelTier.NANO,
        confidence_floor=0.65,
        timeout_s=4.0,
        is_free=True,
    ),
    LadderStep(
        name="small",
        provider="groq",
        model="llama-3.1-8b-instant",
        tier=ModelTier.SMALL,
        confidence_floor=0.70,
        timeout_s=6.0,
    ),
    LadderStep(
        name="medium",
        provider="anthropic",
        model="claude-haiku-4-5",
        tier=ModelTier.MEDIUM,
        confidence_floor=0.80,
        timeout_s=10.0,
    ),
    LadderStep(
        name="large",
        provider="anthropic",
        model="claude-sonnet-4-5",
        tier=ModelTier.LARGE,
        confidence_floor=0.0,  # accept anything from the top
        timeout_s=20.0,
    ),
]


class CognitionLadder:
    """Escalate through :data:`DEFAULT_LADDER` until confidence is enough."""

    def __init__(
        self,
        steps: list[LadderStep] | None = None,
        *,
        cache: ResponseCache | None = None,
        enable_cache: bool = True,
    ) -> None:
        if steps is None:
            self._steps: list[LadderStep] = list(DEFAULT_LADDER)
        else:
            # Honour an explicitly empty list — do NOT fall back to the
            # default ladder (a `[] or DEFAULT_LADDER` would do exactly
            # that because empty list is falsy).
            self._steps = list(steps)
        self._cache = cache
        self._enable_cache = enable_cache

    @property
    def steps(self) -> list[LadderStep]:
        return list(self._steps)

    def replace_steps(self, steps: list[LadderStep]) -> None:
        self._steps = list(steps)

    async def run(
        self,
        *,
        prompt: str,
        producer: Producer,
        # Optional override for cache TTL.
        cache_ttl_s: float | None = None,
        # Optional extra bits to mix into the cache key (e.g. tool name,
        # user id).  Defaults to using just the prompt.
        cache_key_suffix: str = "",
    ) -> LadderResult:
        """Run the ladder.

        Parameters
        ----------
        prompt
            The user-facing prompt. Used as the cache key.
        producer
            Async callable: ``producer(step) -> (text, confidence)``.
        cache_ttl_s
            Override the cache TTL for this call.
        cache_key_suffix
            Extra key material; usually ``tool_name`` or ``user_id``.
        """
        if not self._steps:
            return LadderResult(
                text="",
                confidence=0.0,
                step_name="none",
                provider="",
                model="",
                tier=ModelTier.NANO,
                elapsed_ms=0,
                escalated=False,
                from_cache=False,
                success=False,
                error="ladder has no steps",
            )

        cache = self._cache
        if cache is None and self._enable_cache:
            cache = get_response_cache()

        started = time.monotonic()
        last_error: str | None = None

        for idx, step in enumerate(self._steps):
            # Cache lookup keyed on (model, prompt, suffix).  We do NOT
            # cache a generic prompt across tiers — a cached "tiny"
            # response may not be acceptable for "large".
            key: str | None = None
            if cache is not None:
                key = make_cache_key(
                    model=f"{step.provider}/{step.model}",
                    prompt=prompt,
                    tool_name=cache_key_suffix,
                )
                cached = cache.get(key)
                if cached is not None:
                    text, conf = cached
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    return LadderResult(
                        text=text,
                        confidence=conf,
                        step_name=step.name,
                        provider=step.provider,
                        model=step.model,
                        tier=step.tier,
                        elapsed_ms=elapsed_ms,
                        escalated=idx > 0,
                        from_cache=True,
                        trace=[f"cache-hit@{step.name}"],
                    )

            try:
                text, conf = await asyncio.wait_for(
                    producer(step), timeout=step.timeout_s
                )
            except asyncio.TimeoutError:
                last_error = f"{step.name}: timeout after {step.timeout_s}s"
                logger.debug("ladder: %s", last_error)
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = f"{step.name}: {exc}"
                logger.debug("ladder: %s", last_error)
                continue

            # Store the result so the next identical prompt skips this step.
            if cache is not None and key is not None:
                try:
                    cache.set(key, (text, conf), ttl_s=cache_ttl_s)
                except Exception:  # noqa: BLE001
                    pass

            elapsed_ms = int((time.monotonic() - started) * 1000)
            accepted = conf >= step.confidence_floor
            if accepted:
                return LadderResult(
                    text=text,
                    confidence=conf,
                    step_name=step.name,
                    provider=step.provider,
                    model=step.model,
                    tier=step.tier,
                    elapsed_ms=elapsed_ms,
                    escalated=idx > 0,
                    from_cache=False,
                    trace=[f"{step.name}@{conf:.2f}"],
                )
            # else: confidence too low, escalate.
            logger.debug(
                "ladder: %s returned conf=%.2f < floor %.2f, escalating",
                step.name, conf, step.confidence_floor,
            )

        # Every step failed.
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return LadderResult(
            text="",
            confidence=0.0,
            step_name="exhausted",
            provider="",
            model="",
            tier=ModelTier.LARGE,
            elapsed_ms=elapsed_ms,
            escalated=True,
            from_cache=False,
            success=False,
            error=last_error or "all steps failed",
            trace=[s.name for s in self._steps],
        )


__all__ = [
    "LadderStep",
    "LadderResult",
    "Producer",
    "CognitionLadder",
    "DEFAULT_LADDER",
]