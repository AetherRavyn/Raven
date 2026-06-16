"""Channel dispatcher — pick the right channel for each signal.

The dispatcher uses a :class:`ChannelPreference` table to choose
where to send a signal.  Falls back to ``default_channel`` if no
preference matches.

Per :class:`SignalKind` preferences are loaded at construction
time.  The dispatcher is intentionally side-effect free — it only
*selects* the channel, it does not send.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.proactive_core.types import (
    ChannelPreference,
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    SignalKind,
    Urgency,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatcherConfig:
    """Tuning knobs for the dispatcher."""

    default_channel: str = "telegram"
    # Channel overrides by urgency: CRITICAL always uses voice
    # (or whatever is configured) regardless of preference.
    channel_by_urgency: dict[Urgency, str] = field(
        default_factory=lambda: {
            Urgency.CRITICAL: "voice",
        }
    )
    # Map chat_id per channel per user.  When a target isn't
    # registered for a channel, we fall back to default.
    user_channels: dict[str, dict[str, str]] = field(default_factory=dict)


class ChannelDispatcher:
    """Pick (channel, target) for a signal."""

    def __init__(
        self,
        preferences: Iterable[ChannelPreference] | None = None,
        config: DispatcherConfig | None = None,
    ) -> None:
        self._preferences: dict[SignalKind, ChannelPreference] = {}
        for p in preferences or []:
            self._preferences[p.kind] = p
        self._config = config or DispatcherConfig()

    def add_preference(self, pref: ChannelPreference) -> None:
        self._preferences[pref.kind] = pref

    def register_user_channel(self, user_id: str, channel: str, chat_id: str) -> None:
        self._config.user_channels.setdefault(user_id, {})[channel] = chat_id

    def _pick_channel(self, signal: ProactiveSignal) -> str:
        if signal.urgency in self._config.channel_by_urgency:
            return self._config.channel_by_urgency[signal.urgency]
        pref = self._preferences.get(signal.kind)
        if pref is not None:
            return pref.channel
        return self._config.default_channel

    def _target_for(self, user_id: str, channel: str) -> tuple[str, str] | None:
        chat_id = self._config.user_channels.get(user_id, {}).get(channel)
        if chat_id is None:
            return None
        return channel, chat_id

    def evaluate(self, signal: ProactiveSignal) -> ProactiveDecision | None:
        """Pick (channel, target) and produce a SPEAK decision.

        When no target is registered for the chosen channel
        (or the default fallback), the dispatcher returns a
        SPEAK decision with ``target=None`` and the engine
        propagates it.  The delivery adapter is responsible
        for resolving a real target — that's where the
        continuity resolver plugs in.  This split lets a user
        receive proactive messages on whatever device they
        happen to be using, not just the device that
        registered the engine.
        """
        from app.core.models import ReplyTarget

        channel = self._pick_channel(signal)
        target_pair = self._target_for(signal.user_id, channel)
        if target_pair is None and channel != self._config.default_channel:
            # Try the default channel as a fallback.
            fallback = self._target_for(signal.user_id, self._config.default_channel)
            if fallback is not None:
                target_pair = fallback

        if target_pair is None:
            # No target registered anywhere.  Return SPEAK
            # with no target — adapter's resolver will fill
            # it in (or downgrade to SILENCE if it can't).
            return ProactiveDecision(
                signal=signal,
                verdict=DecisionVerdict.SPEAK,
                stage="dispatch",
                channel=channel,
                target=None,
                reason="no_target_registered",
            )

        resolved_channel, chat_id = target_pair
        return ProactiveDecision(
            signal=signal,
            verdict=DecisionVerdict.SPEAK,
            stage="dispatch",
            channel=resolved_channel,
            target=ReplyTarget(platform=resolved_channel, chat_id=chat_id),
        )

    def explain(self) -> dict[str, Any]:
        return {
            "default_channel": self._config.default_channel,
            "preferences": {k.value: v.channel for k, v in self._preferences.items()},
            "urgency_overrides": {k.value: v for k, v in self._config.channel_by_urgency.items()},
        }
