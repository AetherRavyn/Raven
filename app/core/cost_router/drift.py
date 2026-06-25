"""Cost router drift detection.

Drift here means: the cost router's recent decisions (which tier it
chose, how long it took) have shifted noticeably from a recorded
baseline.  This catches:

  * a model provider silently swapping to a different model family
    (cost drops → drift; output shape diverges → drift);
  * a price change in the catalog (cost per call jumps);
  * a stuck rule that always picks the same tier regardless of input.

The detector is intentionally lightweight:

  1. Sample decisions into a rolling window.
  2. Compare the window against a cached baseline (a JSON file or
     in-memory dict).
  3. If the JS-divergence of the tier histogram exceeds ``threshold``,
     or the mean latency moves > ``latency_drift_pct``, raise a
     :class:`DriftAlert`.

The detector never blocks routing — it just emits a signal that
``raven doctor`` and the Grafana exporter can surface.
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RoutingDecision:
    """One row in the drift detector's input."""

    tier: str  # "nano" | "small" | "medium" | "large" | "premium"
    latency_ms: int = 0
    cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class DriftBaseline:
    """A snapshot of "what the router used to do"."""

    tier_histogram: dict[str, float]  # tier → fraction
    mean_latency_ms: float
    mean_cost_usd: float
    captured_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier_histogram": dict(self.tier_histogram),
            "mean_latency_ms": self.mean_latency_ms,
            "mean_cost_usd": self.mean_cost_usd,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DriftBaseline":
        return cls(
            tier_histogram=dict(d.get("tier_histogram", {})),
            mean_latency_ms=float(d.get("mean_latency_ms", 0.0)),
            mean_cost_usd=float(d.get("mean_cost_usd", 0.0)),
            captured_at=d.get("captured_at", ""),
        )


@dataclass(slots=True)
class DriftAlert:
    """Raised when current behaviour diverges from the baseline."""

    kind: str  # "tier_histogram" | "latency" | "cost"
    severity: str  # "info" | "warn" | "critical"
    detail: str
    delta: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "delta": self.delta,
        }


class DriftDetector:
    """Sliding-window drift detector for the cost router.

    The detector is parameterised by:
      * ``window`` — number of recent decisions to keep (default 200).
      * ``tier_threshold`` — max JS divergence of the tier histogram
        before an alert is raised (default 0.10).
      * ``latency_drift_pct`` — max mean-latency change (as a fraction
        of the baseline) before an alert (default 0.25 = 25%).
      * ``cost_drift_pct`` — same for mean cost (default 0.50).
    """

    def __init__(
        self,
        *,
        window: int = 200,
        tier_threshold: float = 0.10,
        latency_drift_pct: float = 0.25,
        cost_drift_pct: float = 0.50,
    ) -> None:
        self._window = window
        self._tier_threshold = tier_threshold
        self._latency_drift_pct = latency_drift_pct
        self._cost_drift_pct = cost_drift_pct
        self._samples: deque[RoutingDecision] = deque(maxlen=window)
        self._baseline: Optional[DriftBaseline] = None

    # ── configuration ────────────────────────────────────────────

    def set_baseline(self, baseline: DriftBaseline) -> None:
        self._baseline = baseline

    def load_baseline(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            logger.debug("drift: no baseline file at %s", p)
            return
        try:
            data = json.loads(p.read_text())
            self._baseline = DriftBaseline.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("drift: bad baseline file %s: %s", p, e)

    def save_baseline(self, path: str | Path) -> None:
        if self._baseline is None:
            self._baseline = self.capture_baseline()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._baseline.to_dict(), indent=2))

    def baseline(self) -> Optional[DriftBaseline]:
        return self._baseline

    # ── sampling ─────────────────────────────────────────────────

    def record(self, decision: RoutingDecision) -> None:
        self._samples.append(decision)

    def sample_count(self) -> int:
        return len(self._samples)

    def clear(self) -> None:
        self._samples.clear()

    # ── analysis ─────────────────────────────────────────────────

    def capture_baseline(self) -> DriftBaseline:
        """Snapshot the current window as the baseline."""
        return _baseline_from_samples(list(self._samples))

    def check(self) -> list[DriftAlert]:
        """Compare the current window against the baseline."""
        if self._baseline is None or not self._samples:
            return []
        current = _baseline_from_samples(list(self._samples))
        alerts: list[DriftAlert] = []
        # Tier histogram drift (JS divergence).
        js = _js_divergence(
            self._baseline.tier_histogram, current.tier_histogram
        )
        if js > self._tier_threshold:
            severity = "critical" if js > 2 * self._tier_threshold else "warn"
            alerts.append(DriftAlert(
                kind="tier_histogram",
                severity=severity,
                detail=(
                    f"tier histogram drifted JS={js:.3f} "
                    f"(threshold {self._tier_threshold})"
                ),
                delta=js,
            ))
        # Mean latency drift.
        if self._baseline.mean_latency_ms > 0:
            ratio = (
                (current.mean_latency_ms - self._baseline.mean_latency_ms)
                / self._baseline.mean_latency_ms
            )
            if abs(ratio) > self._latency_drift_pct:
                severity = "warn"
                alerts.append(DriftAlert(
                    kind="latency",
                    severity=severity,
                    detail=(
                        f"mean latency moved {ratio:+.1%} "
                        f"(baseline {self._baseline.mean_latency_ms:.0f}ms, "
                        f"current {current.mean_latency_ms:.0f}ms)"
                    ),
                    delta=ratio,
                ))
        # Mean cost drift.
        if self._baseline.mean_cost_usd > 0:
            ratio = (
                (current.mean_cost_usd - self._baseline.mean_cost_usd)
                / self._baseline.mean_cost_usd
            )
            if abs(ratio) > self._cost_drift_pct:
                alerts.append(DriftAlert(
                    kind="cost",
                    severity="info",
                    detail=(
                        f"mean cost moved {ratio:+.1%} "
                        f"(baseline ${self._baseline.mean_cost_usd:.6f}, "
                        f"current ${current.mean_cost_usd:.6f})"
                    ),
                    delta=ratio,
                ))
        return alerts


# ── Helpers ─────────────────────────────────────────────────────────


def _baseline_from_samples(samples: list[RoutingDecision]) -> DriftBaseline:
    if not samples:
        return DriftBaseline(
            tier_histogram={},
            mean_latency_ms=0.0,
            mean_cost_usd=0.0,
            captured_at="",
        )
    counter = Counter(s.tier for s in samples)
    total = sum(counter.values())
    hist = {tier: count / total for tier, count in counter.items()}
    mean_lat = sum(s.latency_ms for s in samples) / total
    mean_cost = sum(s.cost_usd for s in samples) / total
    return DriftBaseline(
        tier_histogram=hist,
        mean_latency_ms=mean_lat,
        mean_cost_usd=mean_cost,
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def _js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen–Shannon divergence between two discrete distributions.

    Returns a value in [0, 1] (we use log2 so the bound is the
    square-root of the natural log, capped at 1 for our thresholds).
    Both ``p`` and ``q`` are sparse histograms; missing keys are
    treated as zero.
    """
    keys = set(p) | set(q)
    p_full = [p.get(k, 0.0) for k in keys]
    q_full = [q.get(k, 0.0) for k in keys]
    # Renormalise (defensive).
    sp = sum(p_full) or 1.0
    sq = sum(q_full) or 1.0
    p_full = [x / sp for x in p_full]
    q_full = [x / sq for x in q_full]
    m = [(a + b) / 2 for a, b in zip(p_full, q_full)]
    def _kl(a: list[float], b: list[float]) -> float:
        s = 0.0
        for ai, bi in zip(a, b):
            if ai > 0 and bi > 0:
                s += ai * math.log2(ai / bi)
        return s
    js = 0.5 * _kl(p_full, m) + 0.5 * _kl(q_full, m)
    # JS divergence is bounded by ln(2); normalise to [0, 1].
    return max(0.0, min(1.0, js / math.log(2)))


__all__ = [
    "RoutingDecision",
    "DriftBaseline",
    "DriftAlert",
    "DriftDetector",
]