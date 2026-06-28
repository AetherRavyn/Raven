"""Learning Health Monitor — detects anomalies in Raven's learning signals.

Tracks key metrics over time and alerts when something unusual happens:

- **Correction spike** — sudden increase in user corrections → user is
  frustrated with something
- **Confidence drop** — average confidence falls below threshold → system
  is struggling
- **Tool failure surge** — a tool starts failing more than usual →
  configuration or API issue
- **Improvement stagnation** — prompt improvements aren't reducing
  corrections → strategy needs adjustment

The monitor produces health reports that can be checked by the inspector
or sent as proactive alerts.
"""

from __future__ import annotations

import logging
import statistics
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Number of recent data points to keep for trend analysis
_WINDOW_SIZE = 50

_TREND_THRESHOLD = 0.03


def _trend_arrow(diff: float) -> str:
    """Return ↑ / ↓ / → based on the magnitude of change."""
    if diff > _TREND_THRESHOLD:
        return "↑"
    if diff < -_TREND_THRESHOLD:
        return "↓"
    return "→"


class LearningHealthMonitor:
    """Tracks learning system health and detects anomalies.

    Each metric maintains a rolling window.  Anomalies are detected
    when the current value deviates significantly from the running
    average.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        # Rolling windows of metric values
        self._correction_counts: deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._confidence_scores: deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._success_rates: deque[float] = deque(maxlen=_WINDOW_SIZE)

    def record_turn(
        self,
        success: bool,
        confidence: float | None = None,
        was_correction: bool = False,
    ) -> dict[str, Any]:
        """Record metrics for a single turn.

        Args:
            success: Whether the turn succeeded.
            confidence: Confidence score (0-1) from UncertaintyEstimator.
            was_correction: Whether the user's message was a correction.

        Returns:
            A health alert dict if an anomaly is detected, else empty.
        """
        self._success_rates.append(1.0 if success else 0.0)

        if confidence is not None:
            self._confidence_scores.append(confidence)

        if was_correction:
            self._correction_counts.append(1.0)
        else:
            self._correction_counts.append(0.0)

        return self._check_alerts()

    # ── Alert Checks ──────────────────────────────────────────────

    def _check_alerts(self) -> dict[str, Any]:
        """Check all metrics for anomalies.

        Returns the first alert found, or empty dict if healthy.
        """
        alerts: list[dict[str, Any]] = []

        for check in [
            self._check_correction_spike,
            self._check_confidence_drop,
            self._check_success_drop,
        ]:
            alert = check()
            if alert:
                alerts.append(alert)

        if alerts:
            return {
                "alert": True,
                "alerts": alerts,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return {}

    def _check_correction_spike(self) -> dict[str, Any] | None:
        """Detect sudden increase in corrections."""
        if len(self._correction_counts) < 10:
            return None

        recent = list(self._correction_counts)
        mid = len(recent) // 2
        older = recent[:mid]
        newer = recent[mid:]

        older_rate = sum(older) / max(len(older), 1)
        newer_rate = sum(newer) / max(len(newer), 1)

        if newer_rate > older_rate * 2 and newer_rate > 0.3:
            return {
                "type": "correction_spike",
                "severity": "warning",
                "message": (
                    f"Correction rate jumped from "
                    f"{older_rate * 100:.0f}% to {newer_rate * 100:.0f}%. "
                    f"User may be frustrated with recent responses."
                ),
                "older_rate": older_rate,
                "newer_rate": newer_rate,
            }

        return None

    def _check_confidence_drop(self) -> dict[str, Any] | None:
        """Detect sustained drop in confidence."""
        if len(self._confidence_scores) < 10:
            return None

        scores = list(self._confidence_scores)
        avg = statistics.mean(scores)
        recent_avg = statistics.mean(scores[-5:]) if len(scores) >= 5 else avg

        if recent_avg < 0.4 and avg >= 0.5:
            return {
                "type": "confidence_drop",
                "severity": "critical",
                "message": (
                    f"Average confidence dropped to {recent_avg:.2f} "
                    f"(overall: {avg:.2f}). System is struggling."
                ),
                "average": avg,
                "recent_average": recent_avg,
            }

        return None

    def _check_success_drop(self) -> dict[str, Any] | None:
        """Detect sustained drop in success rate."""
        if len(self._success_rates) < 10:
            return None

        rates = list(self._success_rates)
        recent_rates = rates[-10:]
        older_rates = rates[:-10] if len(rates) > 10 else rates

        if not older_rates:
            return None

        recent_avg = statistics.mean(recent_rates)
        older_avg = statistics.mean(older_rates)

        if recent_avg < older_avg - 0.2 and recent_avg < 0.6:
            return {
                "type": "success_drop",
                "severity": "warning",
                "message": (
                    f"Success rate dropped from {older_avg * 100:.0f}% "
                    f"to {recent_avg * 100:.0f}%. Tools or provider may be failing."
                ),
                "older_rate": older_avg,
                "recent_rate": recent_avg,
            }

        return None

    # ── Persistence ───────────────────────────────────────────────

    # ── Persistence ───────────────────────────────────────────────

    def _ensure_dir(self) -> Path:
        base = Path(self._workspace_dir or "workspace")
        path = base / "memory" / "health_monitor"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _state_path(self) -> Path:
        return self._ensure_dir() / "state.json"

    def save(self) -> None:
        """Save monitor state to disk."""
        import json

        path = self._state_path()
        data = {
            "correction_counts": list(self._correction_counts),
            "confidence_scores": list(self._confidence_scores),
            "success_rates": list(self._success_rates),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load(self) -> None:
        """Load monitor state from disk, if available."""
        import json

        path = self._state_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._correction_counts = deque(data.get("correction_counts", []), maxlen=_WINDOW_SIZE)
            self._confidence_scores = deque(data.get("confidence_scores", []), maxlen=_WINDOW_SIZE)
            self._success_rates = deque(data.get("success_rates", []), maxlen=_WINDOW_SIZE)
        except Exception as exc:
            logger.debug("Failed to load health monitor state: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Return a full snapshot of current health."""
        alerts = self._check_alerts()
        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correction_rate": (
                sum(self._correction_counts) / max(len(self._correction_counts), 1)
                if self._correction_counts
                else 0.0
            ),
            "avg_confidence": (
                statistics.mean(self._confidence_scores) if self._confidence_scores else 0.0
            ),
            "success_rate": (statistics.mean(self._success_rates) if self._success_rates else 0.0),
            "total_turns_recorded": len(self._success_rates),
            "trends": self._compute_trends(),
        }
        if alerts:
            result["alerts"] = alerts
        return result

    def _compute_trends(self) -> dict[str, str]:
        """Compute trend directions (↑ improving, ↓ degrading, → stable) for each metric."""
        trends: dict[str, str] = {}

        if len(self._success_rates) >= 10:
            rates = list(self._success_rates)
            mid = len(rates) // 2
            old = statistics.mean(rates[:mid]) if mid > 0 else 0.5
            new = statistics.mean(rates[mid:]) if len(rates) > mid else 0.5
            diff = new - old
            trends["success_rate"] = _trend_arrow(diff)

        if len(self._confidence_scores) >= 10:
            scores = list(self._confidence_scores)
            mid = len(scores) // 2
            old = statistics.mean(scores[:mid]) if mid > 0 else 0.5
            new = statistics.mean(scores[mid:]) if len(scores) > mid else 0.5
            diff = new - old
            trends["confidence"] = _trend_arrow(diff)

        if len(self._correction_counts) >= 10:
            counts = list(self._correction_counts)
            mid = len(counts) // 2
            old_rate = statistics.mean(counts[:mid]) if mid > 0 else 0.0
            new_rate = statistics.mean(counts[mid:]) if len(counts) > mid else 0.0
            # Lower correction rate is better → invert the diff
            diff = old_rate - new_rate
            trends["correction_rate"] = _trend_arrow(diff)

        return trends


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_MONITOR: LearningHealthMonitor | None = None


def get_health_monitor(workspace_dir: str | None = None) -> LearningHealthMonitor:
    global _GLOBAL_MONITOR
    if _GLOBAL_MONITOR is None:
        _GLOBAL_MONITOR = LearningHealthMonitor(workspace_dir=workspace_dir)
        _GLOBAL_MONITOR.load()
    return _GLOBAL_MONITOR
