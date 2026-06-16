"""Value gate — should we *want* to send this signal?

The value score is::

    score = utility * confidence - interruption_cost

where each component is in [0, 1].  A signal only "speaks" if the
final score clears a threshold (default 0.35).

Thresholds are configurable per (urgency, kind) via :class:`GateConfig`
so that a CRITICAL anomaly can clear the gate at a low score while a
LOW reminder needs a high score to be worth the user's time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.proactive_core.types import (
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    SignalKind,
    Urgency,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GateConfig:
    """Tuning knobs for the value gate."""

    # Base threshold for a NORMAL signal to clear.
    base_threshold: float = 0.35
    # Per-urgency adjustments.  A negative threshold makes the
    # gate *easier* to clear; a positive one makes it harder.
    threshold_by_urgency: dict[Urgency, float] = field(
        default_factory=lambda: {
            Urgency.LOW: 0.15,
            Urgency.NORMAL: 0.0,
            Urgency.HIGH: -0.15,
            Urgency.CRITICAL: -0.4,
        }
    )
    # Per-kind adjustments (e.g. a forecast should clear easily).
    threshold_by_kind: dict[SignalKind, float] = field(
        default_factory=lambda: {
            SignalKind.CALENDAR_PREP: -0.05,
            SignalKind.ANOMALY: -0.15,
            SignalKind.FORECAST: 0.0,
            SignalKind.FOLLOW_UP: 0.0,
            SignalKind.ROUTINE: 0.1,
            SignalKind.OPPORTUNITY: 0.05,
            SignalKind.REMINDER: 0.0,
            SignalKind.URGENT: -0.3,
        }
    )

    def threshold_for(self, signal: ProactiveSignal) -> float:
        base = self.base_threshold
        base += self.threshold_by_urgency.get(signal.urgency, 0.0)
        base += self.threshold_by_kind.get(signal.kind, 0.0)
        return max(0.0, min(1.0, base))


class ValueGate:
    """Score a signal and decide whether it clears the bar."""

    def __init__(self, config: GateConfig | None = None) -> None:
        self._config = config or GateConfig()

    @property
    def config(self) -> GateConfig:
        return self._config

    def score(self, signal: ProactiveSignal) -> float:
        """Compute ``utility * confidence - interruption_cost``.

        The result is clipped to ``[-1, 1]`` so the caller can
        reason about negative scores (signals actively hurting
        the user experience).
        """
        utility = max(0.0, min(1.0, signal.value * signal.confidence))
        cost = max(0.0, min(1.0, signal.interruption_cost))
        return max(-1.0, min(1.0, utility - cost))

    def evaluate(self, signal: ProactiveSignal) -> tuple[ProactiveDecision | None, float]:
        """Return ``(decision | None, score)``.

        * If the signal clears the gate, returns ``(None, score)``
          and the engine should pass it to the next stage.
        * Otherwise returns a ``SILENCE`` decision with a
          human-readable reason.
        """
        s = self.score(signal)
        threshold = self._config.threshold_for(signal)
        if s < threshold:
            return (
                ProactiveDecision(
                    signal=signal,
                    verdict=DecisionVerdict.SILENCE,
                    stage="value",
                    score=s,
                    reason=(
                        f"score={s:.2f} < threshold={threshold:.2f} "
                        f"(urgency={signal.urgency.value}, kind={signal.kind.value})"
                    ),
                ),
                s,
            )
        return None, s

    def explain(self, signal: ProactiveSignal) -> dict[str, Any]:
        """Return the components of the score for debug / inspector UIs."""
        utility = signal.value * signal.confidence
        return {
            "value": signal.value,
            "confidence": signal.confidence,
            "interruption_cost": signal.interruption_cost,
            "utility": utility,
            "score": self.score(signal),
            "threshold": self._config.threshold_for(signal),
        }
