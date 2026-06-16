"""Proactive engine — the orchestrator that decides SPEAK/SILENCE/DEFER.

A :class:`ProactiveEngine` runs each incoming :class:`ProactiveSignal`
through a four-stage pipeline:

1. **DND** — quiet hours, focus mode, calendar busy? → DEFER
2. **Value gate** — score ``value * confidence - interruption_cost``;
   below threshold → SILENCE
3. **Silence** — anti-spam, dedup, annoyance → SILENCE
4. **Dispatch** — pick (channel, target) → SPEAK (or SILENCE if
   no target is registered)

The engine is per-user.  All four stages are pluggable, so tests
can substitute deterministic fakes.

The engine never *sends* — it just produces a
:class:`ProactiveDecision`.  A separate delivery layer (e.g. the
existing :mod:`app.core.proactive` helpers) consumes the decision
and talks to BotSignal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.proactive_core.dispatcher import ChannelDispatcher, DispatcherConfig
from app.core.proactive_core.quiet_hours import CalendarProvider, QuietHoursResolver
from app.core.proactive_core.silence import (
    InMemoryRateLimitStore,
    RateLimitStore,
    SilenceConfig,
    SilenceEngine,
)
from app.core.proactive_core.types import (
    ChannelPreference,
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    QuietWindow,
)
from app.core.proactive_core.value_gate import GateConfig, ValueGate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EngineConfig:
    """Top-level config for the proactive engine.

    All nested configs can be overridden individually; the default
    values match what we believe is sensible for a personal
    assistant that should mostly stay silent.
    """

    quiet_hours_windows: list[QuietWindow] = field(default_factory=list)
    channel_preferences: list[ChannelPreference] = field(default_factory=list)
    gate: GateConfig = field(default_factory=GateConfig)
    silence: SilenceConfig = field(default_factory=SilenceConfig)
    dispatcher: DispatcherConfig = field(default_factory=DispatcherConfig)
    focus_mode: bool = False


class ProactiveEngine:
    """Run the four-stage pipeline and produce a decision."""

    def __init__(
        self,
        user_id: str,
        *,
        quiet_hours: QuietHoursResolver | None = None,
        value_gate: ValueGate | None = None,
        silence: SilenceEngine | None = None,
        dispatcher: ChannelDispatcher | None = None,
        config: EngineConfig | None = None,
        calendar: CalendarProvider | None = None,
    ) -> None:
        self.user_id = user_id
        self._config = config or EngineConfig()
        self.quiet_hours = quiet_hours or QuietHoursResolver(
            user_windows=self._config.quiet_hours_windows,
            focus_mode=self._config.focus_mode,
        )
        self.value_gate = value_gate or ValueGate(self._config.gate)
        self.silence = silence or SilenceEngine(
            config=self._config.silence,
        )
        self.dispatcher = dispatcher or ChannelDispatcher(
            preferences=self._config.channel_preferences,
            config=self._config.dispatcher,
        )
        self._calendar = calendar

    # ---------------------------------------------------------------
    # Convenience constructors
    # ---------------------------------------------------------------

    @classmethod
    def for_user(
        cls,
        user_id: str,
        *,
        config: EngineConfig | None = None,
        store: RateLimitStore | None = None,
        calendar: CalendarProvider | None = None,
    ) -> "ProactiveEngine":
        """Build an engine for a single user with sensible defaults."""
        return cls(
            user_id,
            config=config or EngineConfig(),
            silence=SilenceEngine(store=store or InMemoryRateLimitStore()),
            calendar=calendar,
        )

    # ---------------------------------------------------------------
    # Runtime knobs
    # ---------------------------------------------------------------

    def set_focus_mode(self, on: bool) -> None:
        self.quiet_hours.set_focus_mode(on)

    def add_quiet_window(self, window: QuietWindow) -> None:
        self.quiet_hours.add_user_window(window)

    def register_target(self, channel: str, chat_id: str) -> None:
        self.dispatcher.register_user_channel(self.user_id, channel, chat_id)

    def report_user_feedback(self, signal: ProactiveSignal) -> None:
        """Call when the user replies "stop" / "annoying" to a signal."""
        self.silence.annoyance.report(self.user_id, signal)

    # ---------------------------------------------------------------
    # Decision pipeline
    # ---------------------------------------------------------------

    async def evaluate(self, signal: ProactiveSignal) -> ProactiveDecision:
        if signal.user_id != self.user_id:
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.DROP,
                stage="engine",
                reason=f"engine_for_user:{self.user_id}_got:{signal.user_id}",
            )

        # 1) DND
        dnd_decision = self.quiet_hours.evaluate(signal, calendar=self._calendar)
        if dnd_decision is not None:
            return dnd_decision

        # 2) Value gate
        silence_decision, score = self.value_gate.evaluate(signal)
        if silence_decision is not None:
            return silence_decision

        # 3) Silence (rate limit / dedup / annoyance)
        silence_decision = self.silence.evaluate(signal)
        if silence_decision is not None:
            return silence_decision

        # 4) Dispatch
        dispatch_decision = self.dispatcher.evaluate(signal)
        if dispatch_decision is None:  # pragma: no cover — defensive
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.SILENCE,
                stage="dispatch",
                score=score,
                reason="dispatch_returned_none",
            )
        if dispatch_decision.verdict == DecisionVerdict.SILENCE:
            return dispatch_decision

        # Commit delivery bookkeeping (rate limit + dedup) on SPEAK.
        self.silence.commit(signal)
        return ProactiveDecision(
            signal=signal,
            verdict=DecisionVerdict.SPEAK,
            stage="accepted",
            score=score,
            channel=dispatch_decision.channel,
            target=dispatch_decision.target,
            reason="",
        )

    # ---------------------------------------------------------------
    # Diagnostics
    # ---------------------------------------------------------------

    def explain(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "focus_mode": self._config.focus_mode,
            "value_gate": {
                "threshold": self.value_gate.config.base_threshold,
                "urgency": {
                    u.value: v for u, v in self.value_gate.config.threshold_by_urgency.items()
                },
            },
            "silence": {
                "max_per_hour": self._config.silence.max_per_hour,
                "dedup_window_s": self._config.silence.dedup_window_s,
            },
            "dispatcher": self.dispatcher.explain(),
        }


def configure_default_engine(
    user_id: str,
    *,
    chat_id: str = "",
    channel: str = "telegram",
    quiet_window: QuietWindow | None = None,
    focus_mode: bool = False,
) -> ProactiveEngine:
    """Build a ProactiveEngine with the defaults we ship in production.

    Used by :mod:`app.core.proactive_bootstrap` and the bootstrap
    routine tests.
    """
    windows: list[QuietWindow] = []
    if quiet_window is not None:
        windows.append(quiet_window)
    config = EngineConfig(
        quiet_hours_windows=windows,
        focus_mode=focus_mode,
    )
    engine = ProactiveEngine.for_user(user_id, config=config)
    if chat_id:
        engine.register_target(channel, chat_id)
    return engine
