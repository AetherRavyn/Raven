"""Anomaly detector — spot deviations from the user's baseline.

The detector is intentionally simple: a sliding window of
:class:`Observation` records per user, plus a handful of
hand-rolled checks (work hours, response latency, spending).
A future commit can plug in a learned model on top of the same
``Observation`` stream.

Each check returns zero or more :class:`Anomaly` objects.  The
:func:`detect_all` helper is the single entry point used by the
proactive engine.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ObservationKind(str, Enum):
    """Categories the detector understands."""

    WORK_HOURS = "work_hours"  # hours at desk / online
    EMAIL_REPLY_LATENCY_S = "email_reply_latency_s"
    SPENDING_USD = "spending_usd"
    HEART_RATE = "heart_rate"  # if a sensor is wired up
    STEPS = "steps"
    # Custom kinds are allowed; the built-in checks only
    # inspect the kinds they care about.


class AnomalySeverity(str, Enum):
    LOW = "low"  # worth noting
    MEDIUM = "medium"  # probably worth a nudge
    HIGH = "high"  # nudge immediately


@dataclass(slots=True)
class Observation:
    """A single data point the detector consumes."""

    id: str
    user_id: str
    kind: ObservationKind
    value: float
    recorded_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        user_id: str,
        kind: ObservationKind,
        value: float,
        **metadata: Any,
    ) -> "Observation":
        return cls(
            id=f"obs-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            kind=kind,
            value=value,
            recorded_at=datetime.now(timezone.utc),
            metadata=dict(metadata),
        )


@dataclass(slots=True)
class Anomaly:
    """A detected deviation worth surfacing."""

    id: str
    user_id: str
    kind: ObservationKind
    severity: AnomalySeverity
    message: str
    observed_value: float
    baseline: float
    recorded_at: datetime
    # Multiplier of the baseline the observed value represents
    # (e.g. 1.30 for "30% above average").  ``None`` for checks
    # that don't compute a ratio (e.g. hard thresholds).
    ratio: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "message": self.message,
            "observed_value": self.observed_value,
            "baseline": self.baseline,
            "ratio": self.ratio,
            "recorded_at": self.recorded_at.isoformat(),
            "metadata": self.metadata,
        }


class ObservationStore(Protocol):
    def record(self, observation: Observation) -> None:  # pragma: no cover
        ...

    def recent(
        self,
        user_id: str,
        kind: ObservationKind,
        window: timedelta,
        *,
        now: datetime | None = None,
    ) -> list[Observation]:  # pragma: no cover
        ...


class InMemoryObservationStore:
    """Bounded per-(user, kind) ring buffer.

    Keeps the last ``max_per_kind`` observations so the detector
    can compute a baseline without blowing up memory.
    """

    def __init__(self, max_per_kind: int = 500) -> None:
        self._max = max_per_kind
        self._items: dict[tuple[str, ObservationKind], deque[Observation]] = defaultdict(
            lambda: deque(maxlen=self._max)
        )

    def record(self, observation: Observation) -> None:
        key = (observation.user_id, observation.kind)
        self._items[key].append(observation)

    def recent(
        self,
        user_id: str,
        kind: ObservationKind,
        window: timedelta,
        *,
        now: datetime | None = None,
    ) -> list[Observation]:
        moment = now or datetime.now(timezone.utc)
        cutoff = moment - window
        dq = self._items.get((user_id, kind))
        if dq is None:
            return []
        return [o for o in dq if o.recorded_at >= cutoff]


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------


def _mean(values: Iterable[float]) -> float:
    seq = list(values)
    if not seq:
        return 0.0
    return statistics.fmean(seq)


def _stdev(values: Iterable[float]) -> float:
    seq = list(values)
    if len(seq) < 2:
        return 0.0
    return statistics.stdev(seq)


def check_work_hours(
    obs: Observation,
    history: list[Observation],
) -> Anomaly | None:
    """Flag a single work-hours observation if it exceeds the baseline by 50%+.

    Work hours are usually reported as cumulative hours per day;
    we compare against the average of the trailing window.
    """
    if obs.kind != ObservationKind.WORK_HOURS:
        return None
    if not history:
        return None
    baseline = _mean(o.value for o in history if o.id != obs.id)
    if baseline <= 0:
        return None
    ratio = obs.value / baseline
    if ratio < 1.5:
        return None
    severity = (
        AnomalySeverity.HIGH
        if ratio >= 2.0
        else AnomalySeverity.MEDIUM
        if ratio >= 1.75
        else AnomalySeverity.LOW
    )
    return Anomaly(
        id=f"anom-{uuid.uuid4().hex[:12]}",
        user_id=obs.user_id,
        kind=obs.kind,
        severity=severity,
        message=(
            f"You've logged {obs.value:.1f}h of work — "
            f"{ratio:.0%} of your usual {baseline:.1f}h. "
            f"Consider a break."
        ),
        observed_value=obs.value,
        baseline=baseline,
        ratio=ratio,
        recorded_at=obs.recorded_at,
    )


def check_email_reply_latency(
    obs: Observation,
    history: list[Observation],
) -> Anomaly | None:
    """Flag a reply latency over 3 days (259200 s) for an important email.

    Importance is encoded in ``obs.metadata["important"]``.
    """
    if obs.kind != ObservationKind.EMAIL_REPLY_LATENCY_S:
        return None
    if not obs.metadata.get("important"):
        return None
    threshold = 3 * 86400
    if obs.value < threshold:
        return None
    days = obs.value / 86400
    severity = (
        AnomalySeverity.HIGH
        if days >= 7
        else AnomalySeverity.MEDIUM
        if days >= 5
        else AnomalySeverity.LOW
    )
    return Anomaly(
        id=f"anom-{uuid.uuid4().hex[:12]}",
        user_id=obs.user_id,
        kind=obs.kind,
        severity=severity,
        message=(f"An important email has been waiting {days:.1f} days for a reply."),
        observed_value=obs.value,
        baseline=threshold / 86400,
        ratio=None,
        recorded_at=obs.recorded_at,
    )


def check_spending_spike(
    obs: Observation,
    history: list[Observation],
) -> Anomaly | None:
    """Flag a spending observation that's 30% above the trailing mean.

    Stdev-aware: small samples get a more lenient threshold
    because one-off bills shouldn't trigger a check-in.
    """
    if obs.kind != ObservationKind.SPENDING_USD:
        return None
    if len(history) < 3:
        return None
    values = [o.value for o in history if o.id != obs.id]
    mean = _mean(values)
    stdev = _stdev(values)
    if mean <= 0:
        return None
    ratio = obs.value / mean
    # Use stdev as a confidence check: noisy series get a bigger
    # bar to clear.
    threshold = 1.30 + min(0.5, stdev / max(mean, 1.0))
    if ratio < threshold:
        return None
    severity = (
        AnomalySeverity.HIGH
        if ratio >= 2.0
        else AnomalySeverity.MEDIUM
        if ratio >= 1.5
        else AnomalySeverity.LOW
    )
    return Anomaly(
        id=f"anom-{uuid.uuid4().hex[:12]}",
        user_id=obs.user_id,
        kind=obs.kind,
        severity=severity,
        message=(
            f"Spending of ${obs.value:.0f} is {ratio:.0%} of your "
            f"usual ${mean:.0f}. Want a quick check-in?"
        ),
        observed_value=obs.value,
        baseline=mean,
        ratio=ratio,
        recorded_at=obs.recorded_at,
    )


# Registry of built-in checks.
_BUILTIN_CHECKS = [
    check_work_hours,
    check_email_reply_latency,
    check_spending_spike,
]


@dataclass(slots=True)
class AnomalyConfig:
    """Knobs for the detector."""

    # How much history to keep when computing baselines.
    baseline_window: timedelta = field(default_factory=lambda: timedelta(days=14))
    # Custom checks; the built-ins are always run.
    extra_checks: list[Any] = field(default_factory=list)


class AnomalyDetector:
    """Run all built-in (and any extra) checks against an observation."""

    def __init__(
        self,
        store: ObservationStore | None = None,
        config: AnomalyConfig | None = None,
    ) -> None:
        self._store: ObservationStore = store or InMemoryObservationStore()
        self._config = config or AnomalyConfig()

    @property
    def store(self) -> ObservationStore:
        return self._store

    def observe(
        self,
        user_id: str,
        kind: ObservationKind,
        value: float,
        **metadata: Any,
    ) -> list[Anomaly]:
        """Record an observation and return any anomalies it triggered."""
        obs = Observation.now(user_id, kind, value, **metadata)
        self._store.record(obs)
        return self.analyze(obs)

    def analyze(self, observation: Observation) -> list[Anomaly]:
        history = self._store.recent(
            observation.user_id,
            observation.kind,
            self._config.baseline_window,
            now=observation.recorded_at,
        )
        results: list[Anomaly] = []
        for check in (*_BUILTIN_CHECKS, *self._config.extra_checks):
            try:
                hit = check(observation, history)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Anomaly check %s failed: %s", check, exc)
                continue
            if hit is not None:
                results.append(hit)
        return results

    def detect_all(
        self,
        user_id: str,
        kind: ObservationKind,
        *,
        window: timedelta | None = None,
        now: datetime | None = None,
    ) -> list[Anomaly]:
        """Run all checks against every observation in a window.

        Useful for the periodic "is anything off?" sweep that
        fires from the scheduler.
        """
        moment = now or datetime.now(timezone.utc)
        win = window or self._config.baseline_window
        history = self._store.recent(user_id, kind, win, now=moment)
        out: list[Anomaly] = []
        for obs in history:
            out.extend(self.analyze(obs))
        # Dedupe by (kind, severity, message).
        seen: set[tuple[str, str, str]] = set()
        unique: list[Anomaly] = []
        for a in out:
            key = (a.kind.value, a.severity.value, a.message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(a)
        return unique


def anomaly_to_signal(anomaly: Anomaly) -> Any:
    """Convert an :class:`Anomaly` to a :class:`ProactiveSignal`.

    Defined in this module to keep the detector decoupled from
    the engine's import path.  Imported lazily by the
    :mod:`anticipation` module.
    """
    from app.core.proactive_core import (
        ProactiveSignal,
        SignalKind,
        Urgency,
    )

    urgency = {
        AnomalySeverity.LOW: Urgency.LOW,
        AnomalySeverity.MEDIUM: Urgency.NORMAL,
        AnomalySeverity.HIGH: Urgency.HIGH,
    }[anomaly.severity]
    return ProactiveSignal(
        id=f"anomaly:{anomaly.id}",
        user_id=anomaly.user_id,
        kind=SignalKind.ANOMALY,
        title=f"Pattern shift: {anomaly.kind.value}",
        body=anomaly.message,
        urgency=urgency,
        value=0.85 if anomaly.severity == AnomalySeverity.HIGH else 0.7,
        confidence=0.85,
        source="anomaly_detector",
        metadata={
            "target_id": anomaly.id,
            "severity": anomaly.severity.value,
            "observed": anomaly.observed_value,
            "baseline": anomaly.baseline,
            "ratio": anomaly.ratio,
        },
    )
