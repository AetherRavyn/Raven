"""Proactive core — types.

A :class:`ProactiveSignal` is an internal trigger produced by a
routine (calendar watcher, anomaly detector, etc.) that the engine
may choose to surface to the user.

A :class:`ProactiveDecision` is the engine's verdict after running
the four-stage pipeline (DND → value gate → silence → dispatch).
Decisions are auditable: the engine never deletes them.

This module is dependency-free (no DB, no network) so it can be
unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.core.models import ReplyTarget, SignalPayload


class SignalKind(str, Enum):
    """Categories the engine can route differently."""

    CALENDAR_PREP = "calendar_prep"  # meeting in N minutes
    ANOMALY = "anomaly"  # something out of pattern
    FORECAST = "forecast"  # pre-fetched info from habits
    FOLLOW_UP = "follow_up"  # tracked commitment
    ROUTINE = "routine"  # morning briefing, evening review
    OPPORTUNITY = "opportunity"  # time / cost / learning win
    REMINDER = "reminder"  # user-scheduled reminder
    URGENT = "urgent"  # immediate action required (escalation)


class Urgency(str, Enum):
    """How time-critical the signal is."""

    LOW = "low"  # nice-to-have; can wait hours
    NORMAL = "normal"  # normal
    HIGH = "high"  # act soon
    CRITICAL = "critical"  # always speak, even in DND


class DecisionVerdict(str, Enum):
    """The four possible outcomes of a proactive decision."""

    SPEAK = "speak"  # send it
    DEFER = "defer"  # wait for a later window, then retry
    SILENCE = "silence"  # don't send (filtered)
    DROP = "drop"  # never retry (e.g., superseded, invalid)


@dataclass(slots=True)
class ProactiveSignal:
    """An internal trigger the engine may surface to the user.

    The engine treats this as a pure data object: the producer is
    responsible for filling in ``value`` and ``confidence``; the
    engine is responsible for the rest.
    """

    id: str
    user_id: str
    kind: SignalKind
    title: str
    body: str
    urgency: Urgency = Urgency.NORMAL
    # 0.0–1.0 — how useful this is *if* the user reads it.
    value: float = 0.5
    # 0.0–1.0 — how confident we are in the signal itself.
    confidence: float = 0.7
    # 0.0–1.0 — how much it would interrupt the user right now
    # (context, channel, frequency).  Computed by the value gate.
    interruption_cost: float = 0.3
    # Source routine (for audit / suppression tracking).
    source: str = "unknown"
    # Optional payload already formatted for delivery.
    payload: SignalPayload | None = None
    # Free-form metadata (entity ids, refs, etc.).
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def final_value(self) -> float:
        """Value the engine actually uses: utility × confidence.

        The ``interruption_cost`` is applied later by the value
        gate, not here, so the engine can show both numbers in
        the audit log.
        """
        return max(0.0, min(1.0, self.value * self.confidence))


@dataclass(slots=True)
class QuietWindow:
    """A span of time during which normal signals should be muted."""

    start_hour: int  # 0–23, local hour
    start_minute: int  # 0–59
    end_hour: int
    end_minute: int
    label: str = "quiet"
    # If True, only CRITICAL signals are allowed through.
    allow_critical: bool = True


@dataclass(slots=True)
class ChannelPreference:
    """User's preferred channel for a given signal kind."""

    kind: SignalKind
    channel: str  # "telegram" | "discord" | "web" | "voice" | "email"
    # 0.0–1.0 — how much the user likes this channel for this kind.
    preference_score: float = 0.7
    # If True, this is the *exclusive* channel (don't fall back).
    exclusive: bool = False


@dataclass(slots=True)
class ProactiveDecision:
    """The engine's verdict on a single signal.

    Decisions are auditable.  ``stage`` records which pipeline
    stage produced the final verdict (so a future operator can
    tell why something was suppressed).
    """

    signal: ProactiveSignal
    verdict: DecisionVerdict
    stage: str  # "dnd" | "value" | "silence" | "dispatch" | "accepted"
    # Computed score (if the value gate ran).
    score: float = 0.0
    # Target channel + reply target, populated when verdict is SPEAK.
    channel: str | None = None
    target: ReplyTarget | None = None
    # If verdict is DEFER, when to retry.
    defer_until: datetime | None = None
    # If verdict is SILENCE or DROP, the reason.
    reason: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal.id,
            "user_id": self.signal.user_id,
            "kind": self.signal.kind.value,
            "urgency": self.signal.urgency.value,
            "value": self.signal.value,
            "confidence": self.signal.confidence,
            "interruption_cost": self.signal.interruption_cost,
            "verdict": self.verdict.value,
            "stage": self.stage,
            "score": self.score,
            "channel": self.channel,
            "target": (
                {"platform": self.target.platform, "chat_id": self.target.chat_id}
                if self.target is not None
                else None
            ),
            "defer_until": (self.defer_until.isoformat() if self.defer_until is not None else None),
            "reason": self.reason,
            "decided_at": self.decided_at.isoformat(),
            "source": self.signal.source,
            "title": self.signal.title,
        }
