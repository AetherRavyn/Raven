"""Anti-spam, dedup, and annoyance tracking for the proactive engine.

A signal that clears the value gate can still be silenced by:

* **Rate limit** — N signals per hour per user (defaults to 1/h
  for low-value, 5/h for everything).
* **Dedup** — the same (kind, source, target_id) within the last
  ``dedup_window_s`` seconds.
* **Annoyance** — if the user has replied "stop" or "annoying"
  to a given kind/source combination recently, suppress that
  combination for a cool-down period (default 24h).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.proactive_core.types import (
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    Urgency,
)

logger = logging.getLogger(__name__)


class RateLimitStore(Protocol):
    """Persistent record of when the user last received what.

    The default in-memory implementation is fine for single-process
    tests.  Production should plug in SQLite or Redis to survive
    restarts and share state across workers.
    """

    def last_delivered(self, user_id: str) -> list[float]:  # pragma: no cover
        """Timestamps (epoch seconds) of the user's last deliveries."""
        ...

    def record(self, user_id: str, ts: float) -> None:  # pragma: no cover
        ...

    def seen(self, user_id: str, fingerprint: str, within_s: float) -> bool:  # pragma: no cover
        ...

    def mark_seen(self, user_id: str, fingerprint: str, ts: float) -> None:  # pragma: no cover
        ...

    def feedback_count(
        self, user_id: str, kind_source: str, since: float
    ) -> int:  # pragma: no cover
        ...

    def record_feedback(
        self, user_id: str, kind_source: str, ts: float
    ) -> None:  # pragma: no cover
        ...


@dataclass
class InMemoryRateLimitStore:
    """Default :class:`RateLimitStore` for tests and single-process use."""

    _deliveries: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _seen: dict[tuple[str, str], float] = field(default_factory=dict)
    _feedback: dict[tuple[str, str], list[float]] = field(default_factory=lambda: defaultdict(list))
    # Don't keep more than 24h of history in memory.
    _max_age_s: float = 86400.0

    def _prune(self, user_id: str, now: float) -> None:
        cutoff = now - self._max_age_s
        dq = self._deliveries.get(user_id)
        if dq is not None:
            while dq and dq[0] < cutoff:
                dq.popleft()
        for key, ts in list(self._seen.items()):
            if ts < cutoff and key[0] == user_id:
                self._seen.pop(key, None)
        for key, stamps in list(self._feedback.items()):
            if key[0] != user_id:
                continue
            self._feedback[key] = [t for t in stamps if t >= cutoff]
            if not self._feedback[key]:
                self._feedback.pop(key, None)

    def last_delivered(self, user_id: str) -> list[float]:
        now = time.time()
        self._prune(user_id, now)
        return list(self._deliveries.get(user_id) or [])

    def record(self, user_id: str, ts: float) -> None:
        self._deliveries[user_id].append(ts)

    def seen(self, user_id: str, fingerprint: str, within_s: float) -> bool:
        ts = self._seen.get((user_id, fingerprint))
        if ts is None:
            return False
        return (time.time() - ts) <= within_s

    def mark_seen(self, user_id: str, fingerprint: str, ts: float) -> None:
        self._seen[(user_id, fingerprint)] = ts

    def feedback_count(self, user_id: str, kind_source: str, since: float) -> int:
        stamps = self._feedback.get((user_id, kind_source), [])
        return sum(1 for t in stamps if t >= since)

    def record_feedback(self, user_id: str, kind_source: str, ts: float) -> None:
        self._feedback[(user_id, kind_source)].append(ts)


def fingerprint(signal: ProactiveSignal) -> str:
    """Stable hash for dedup.

    Two signals with the same (kind, source, target) are considered
    duplicates.  The metadata ``target_id`` is the canonical anchor
    (e.g. an event id, an anomaly id, an entity id).
    """
    target_id = signal.metadata.get("target_id", signal.id)
    return f"{signal.kind.value}|{signal.source}|{target_id}"


def kind_source_key(signal: ProactiveSignal) -> str:
    return f"{signal.kind.value}|{signal.source}"


@dataclass(slots=True)
class SilenceConfig:
    """Tuning knobs for the silence engine."""

    # Per-user max non-critical signals per hour.
    max_per_hour: int = 5
    # CRITICAL signals are exempt from rate limit.
    critical_exempt: bool = True
    # Dedup window in seconds.
    dedup_window_s: float = 900.0
    # Annoyance cool-down: if the user has complained N times
    # in ``annoyance_window_s`` seconds, mute the (kind, source)
    # for ``annoyance_cooldown_s`` seconds.
    annoyance_threshold: int = 2
    annoyance_window_s: float = 3600.0
    annoyance_cooldown_s: float = 86400.0


class AnnoyanceTracker:
    """Convenience wrapper around :class:`RateLimitStore` for user feedback."""

    def __init__(self, store: RateLimitStore, config: SilenceConfig | None = None) -> None:
        self._store = store
        self._config = config or SilenceConfig()

    def report(self, user_id: str, signal: ProactiveSignal) -> None:
        self._store.record_feedback(user_id, kind_source_key(signal), time.time())

    def is_annoying(self, user_id: str, signal: ProactiveSignal) -> bool:
        since = time.time() - self._config.annoyance_window_s
        n = self._store.feedback_count(user_id, kind_source_key(signal), since)
        if n < self._config.annoyance_threshold:
            return False
        # We *are* annoying — but is the cool-down over?
        feedback = self._store._feedback.get(  # type: ignore[attr-defined]
            (user_id, kind_source_key(signal)), []
        )
        if not feedback:
            return False
        last_fb = max(feedback)
        return (time.time() - last_fb) < self._config.annoyance_cooldown_s


class SilenceEngine:
    """Apply rate-limit, dedup, and annoyance checks."""

    def __init__(
        self,
        store: RateLimitStore | None = None,
        config: SilenceConfig | None = None,
        clock: Any | None = None,
    ) -> None:
        self._store: RateLimitStore = store or InMemoryRateLimitStore()
        self._config = config or SilenceConfig()
        self._clock = clock or time.time
        self._annoyance = AnnoyanceTracker(self._store, self._config)

    @property
    def store(self) -> RateLimitStore:
        return self._store

    @property
    def annoyance(self) -> AnnoyanceTracker:
        return self._annoyance

    def evaluate(self, signal: ProactiveSignal) -> ProactiveDecision | None:
        """Return a SILENCE decision if any check fires, else None."""
        if self._config.critical_exempt and signal.urgency == Urgency.CRITICAL:
            return None

        # 1) Annoyance: user complained about this kind/source recently.
        if self._annoyance.is_annoying(signal.user_id, signal):
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.SILENCE,
                stage="silence",
                reason="annoyance_cooldown",
            )

        # 2) Rate limit: too many in the last hour?
        now = self._clock()
        window = 3600.0
        recent = [t for t in self._store.last_delivered(signal.user_id) if (now - t) <= window]
        if len(recent) >= self._config.max_per_hour:
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.SILENCE,
                stage="silence",
                reason=f"rate_limit:{len(recent)}/{self._config.max_per_hour}_per_hour",
            )

        # 3) Dedup: same fingerprint within the window?
        fp = fingerprint(signal)
        if self._store.seen(signal.user_id, fp, self._config.dedup_window_s):
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.SILENCE,
                stage="silence",
                reason=f"dedup:{fp}",
            )
        return None

    def commit(self, signal: ProactiveSignal) -> None:
        """Record that a signal was delivered (rate limit + dedup)."""
        ts = self._clock()
        self._store.record(signal.user_id, ts)
        self._store.mark_seen(signal.user_id, fingerprint(signal), ts)
