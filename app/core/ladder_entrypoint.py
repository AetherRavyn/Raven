"""Cognition ladder entry point — Phase 3.2.

A thin façade that turns the cognition ladder + response cache +
degradation detector into a single async function the orchestrator
and runtime can call. The façade:

- Builds / reuses a process-wide :class:`CognitionLadder`.
- Checks :class:`DegradationDetector` and skips the ``tiny`` step
  when local is unhealthy (cloud-only mode).
- Returns the canned reboot banner when fully down.
- Reports the ladder decision back via the in-proc bus (envelope kind
  ``metric``) so a future dashboard can graph the escalation rate.

The entry point **never** calls a real provider — the caller injects
the producer that knows how to invoke their specific provider. This
keeps the module dependency-free and easy to test.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from app.core.cache import ResponseCache
from app.core.cognition_ladder import (
    DEFAULT_LADDER,
    CognitionLadder,
    LadderResult,
    LadderStep,
)
from app.core.cost_router.types import ModelTier
from app.core.degraded_mode import (
    REBOOT_BANNER,
    DegradationDetector,
    DegradationStatus,
)
from app.core.events import EventKind, make_envelope
from app.core.inproc_bus import get_inproc_bus

logger = logging.getLogger(__name__)


Producer = Callable[[LadderStep], Awaitable[tuple[str, float]]]


# ── Process singleton ──────────────────────────────────────────────


_LADDER: CognitionLadder | None = None
_DETECTOR: DegradationDetector | None = None
_LOCK = asyncio.Lock()


def _get_ladder() -> CognitionLadder:
    global _LADDER
    if _LADDER is None:
        _LADDER = CognitionLadder()
    return _LADDER


def _get_detector() -> DegradationDetector:
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = DegradationDetector()
    return _DETECTOR


def configure(
    *,
    ladder: CognitionLadder | None = None,
    detector: DegradationDetector | None = None,
) -> None:
    """Override the singletons — tests use this."""
    global _LADDER, _DETECTOR
    _LADDER = ladder
    _DETECTOR = detector


# ── Main entry point ───────────────────────────────────────────────


async def answer(
    *,
    prompt: str,
    producer: Producer,
    # Optional override for cache TTL.
    cache_ttl_s: float | None = None,
    cache_key_suffix: str = "",
) -> LadderResult:
    """Run the cognition ladder with degraded-mode awareness.

    This is the single entry point Phase 3.2 calls for: ``answer``.
    The orchestrator should call this instead of constructing a
    router or invoking a provider directly.
    """
    ladder = _get_ladder()
    detector = _get_detector()
    status = detector.status()

    # Fully down: return canned banner, don't even try.
    if status.fully_down:
        result = LadderResult(
            text=status.banner or REBOOT_BANNER,
            confidence=0.0,
            step_name="reboot_banner",
            provider="",
            model="",
            tier=ModelTier.LARGE,
            elapsed_ms=0,
            escalated=True,
            from_cache=False,
            success=True,
            error=None,
            trace=["fully_down"],
        )
        await _publish(result, prompt)
        return result

    # Cloud-only: skip the tiny step (local is unhealthy).
    if status.cloud_only:
        steps = [s for s in ladder.steps if s.name != "tiny"]
        if len(steps) == len(ladder.steps):
            # No tiny step to skip — run as normal.
            steps = list(ladder.steps)
        ladder_local = CognitionLadder(steps=steps)
        result = await ladder_local.run(
            prompt=prompt,
            producer=producer,
            cache_ttl_s=cache_ttl_s,
            cache_key_suffix=cache_key_suffix,
        )
    else:
        result = await ladder.run(
            prompt=prompt,
            producer=producer,
            cache_ttl_s=cache_ttl_s,
            cache_key_suffix=cache_key_suffix,
        )

    await _publish(result, prompt)
    return result


async def _publish(result: LadderResult, prompt: str) -> None:
    """Best-effort: publish the result to the in-proc bus."""
    try:
        env = make_envelope(
            kind=EventKind.METRIC,
            source="ladder",
            body={
                "step_name": result.step_name,
                "model": f"{result.provider}/{result.model}",
                "tier": result.tier.value,
                "confidence": result.confidence,
                "elapsed_ms": result.elapsed_ms,
                "escalated": result.escalated,
                "from_cache": result.from_cache,
                "success": result.success,
                "prompt_len": len(prompt),
            },
        )
        await get_inproc_bus().publish("ladder.decision", env)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ladder entrypoint: bus publish failed — %s", exc)


__all__ = [
    "answer",
    "configure",
    "Producer",
]