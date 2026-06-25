"""Source trust registry — Phase 5.4.

A per-source trust score in ``[0.0, 1.0]``.  The cost router caps the
model tier it picks based on the source's trust:

  - trust ≥ 0.7  → all tiers (NANO … PREMIUM)
  - trust 0.4–0.7 → up to LARGE (no PREMIUM)
  - trust 0.1–0.4 → up to MEDIUM
  - trust < 0.1  → up to SMALL only (or NANO if task is "summarize")

The registry is the **only** place trust lives.  Sources are added
explicitly (e.g. by the citation manager when a citation is created
from a known-trusted channel) or by an operator via the admin CLI.

A default trust of 0.5 is used for unknown sources — the middle of
the road.  The registry never raises on unknown sources; that's a
fragility contract: the router must always have *some* answer.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from app.core.cost_router.types import ModelTier

logger = logging.getLogger(__name__)


# Trust thresholds (inclusive lower bound) per max-tier.
# A source with trust score in [lo, next_lo) is capped to ``cap``.
# Anything ≥ the highest lo is allowed up to PREMIUM.
TIER_CAPS: list[tuple[float, ModelTier]] = [
    (0.0, ModelTier.NANO),
    (0.1, ModelTier.SMALL),
    (0.4, ModelTier.MEDIUM),
    (0.7, ModelTier.LARGE),
]


def tier_cap_for(trust: float) -> ModelTier:
    """Return the highest tier a source with this trust score may use.

    The cap is *conservative*: a source with trust 0.5 maps to
    MEDIUM (the 0.4–0.7 band).  An unknown source (default 0.5) also
    lands at MEDIUM, so we never accidentally fan out to large /
    premium models for unauthenticated content.  Sources with
    trust ≥ 0.7 may go up to LARGE; trust ≥ 0.9 (i.e. the next band
    above 0.7) is allowed up to PREMIUM.  We use a single-step jump
    from LARGE to PREMIUM at the 0.9 boundary so a trust of 0.85
    does not yet grant PREMIUM access.
    """
    if trust >= 0.9:
        return ModelTier.PREMIUM
    last = ModelTier.LARGE
    for lo, cap in TIER_CAPS:
        if trust >= lo:
            last = cap
    return last


@dataclass(slots=True)
class SourceTrust:
    """A single source's trust record."""

    source: str
    score: float
    reason: str = ""
    added_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    use_count: int = 0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "score": self.score,
            "tier_cap": tier_cap_for(self.score).value,
            "reason": self.reason,
            "added_at": self.added_at,
            "updated_at": self.updated_at,
            "use_count": self.use_count,
        }


class SourceTrustRegistry:
    """In-memory trust registry.  Replace with KV in production."""

    DEFAULT_SCORE: float = 0.5  # middle of the road for unknowns

    def __init__(self, *, default_score: float = 0.5) -> None:
        self._lock = threading.RLock()
        self._sources: Dict[str, SourceTrust] = {}
        self._default = max(0.0, min(1.0, float(default_score)))

    def set(self, source: str, score: float, *, reason: str = "") -> SourceTrust:
        """Set the trust score for ``source`` (clamped to [0, 1])."""
        score = max(0.0, min(1.0, float(score)))
        with self._lock:
            now = time.time()
            existing = self._sources.get(source)
            if existing:
                existing.score = score
                existing.reason = reason or existing.reason
                existing.updated_at = now
                return existing
            entry = SourceTrust(
                source=source,
                score=score,
                reason=reason,
                added_at=now,
                updated_at=now,
            )
            self._sources[source] = entry
            return entry

    def get(self, source: str) -> SourceTrust:
        """Return the trust record for ``source``, or a default."""
        with self._lock:
            entry = self._sources.get(source)
            if entry is not None:
                entry.use_count += 1
                return entry
            return SourceTrust(source=source, score=self._default)

    def score_for(self, source: str) -> float:
        """Just the score — convenience for the cost router."""
        return self.get(source).score

    def tier_cap_for(self, source: str) -> ModelTier:
        """Highest tier the router may pick for this source."""
        return tier_cap_for(self.score_for(source))

    def forget(self, source: str) -> bool:
        """Drop a source from the registry."""
        with self._lock:
            return self._sources.pop(source, None) is not None

    def all(self) -> list[SourceTrust]:
        with self._lock:
            return list(self._sources.values())

    def reset(self) -> None:
        with self._lock:
            self._sources.clear()


# ── Process singleton ──────────────────────────────────────────────


_REGISTRY: SourceTrustRegistry | None = None
_LOCK = threading.RLock()


def get_source_trust() -> SourceTrustRegistry:
    """Return the process-wide trust registry."""
    global _REGISTRY
    with _LOCK:
        if _REGISTRY is None:
            _REGISTRY = SourceTrustRegistry()
            # Seed a few well-known sources so a fresh install has
            # sensible defaults without the user configuring anything.
            _REGISTRY.set("user", 0.95, reason="owner")
            _REGISTRY.set("user_input", 0.95, reason="owner direct")
            _REGISTRY.set("rss", 0.4, reason="untrusted public feed")
            _REGISTRY.set("web", 0.3, reason="unverified web content")
            _REGISTRY.set("email", 0.6, reason="known correspondent")
            _REGISTRY.set("telegram", 0.6, reason="paired device")
            _REGISTRY.set("discord", 0.5, reason="public guild")
            _REGISTRY.set("slack", 0.6, reason="workspace")
            _REGISTRY.set("system", 0.95, reason="trusted internal")
        return _REGISTRY


def set_source_trust(registry: SourceTrustRegistry | None) -> None:
    global _REGISTRY
    with _LOCK:
        _REGISTRY = registry


def reset_source_trust() -> None:
    set_source_trust(None)


__all__ = [
    "SourceTrust",
    "SourceTrustRegistry",
    "TIER_CAPS",
    "tier_cap_for",
    "get_source_trust",
    "set_source_trust",
    "reset_source_trust",
]