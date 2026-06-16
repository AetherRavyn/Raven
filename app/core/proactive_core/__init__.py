"""Proactive core — public API.

Quick start::

    from app.core.proactive_core import (
        ProactiveEngine,
        ProactiveSignal,
        SignalKind,
        Urgency,
    )
    from app.core.models import ReplyTarget, SignalPayload

    signal = ProactiveSignal(
        id="cal-2024-06-12-09:00",
        user_id="swadhin",
        kind=SignalKind.CALENDAR_PREP,
        title="Design review at 09:00",
        body="Standup, then deep work.",
        urgency=Urgency.NORMAL,
        value=0.6,
        confidence=0.9,
        source="calendar_watcher",
    )
    engine = ProactiveEngine.for_user("swadhin")
    decision = await engine.evaluate(signal)
    if decision.verdict.value == "speak":
        ...
"""

from app.core.proactive_core.dispatcher import ChannelDispatcher, DispatcherConfig
from app.core.proactive_core.engine import (
    EngineConfig,
    ProactiveEngine,
    configure_default_engine,
)
from app.core.proactive_core.persistence import (
    InMemoryRateLimitStore,
    RateLimitStore,
)
from app.core.proactive_core.quiet_hours import (
    CalendarProvider,
    QuietHoursResolver,
)
from app.core.proactive_core.silence import (
    AnnoyanceTracker,
    SilenceConfig,
    SilenceEngine,
)
from app.core.proactive_core.types import (
    ChannelPreference,
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    QuietWindow,
    SignalKind,
    Urgency,
)
from app.core.proactive_core.value_gate import GateConfig, ValueGate

__all__ = [
    "AnnoyanceTracker",
    "CalendarProvider",
    "ChannelDispatcher",
    "ChannelPreference",
    "DecisionVerdict",
    "DispatcherConfig",
    "EngineConfig",
    "GateConfig",
    "InMemoryRateLimitStore",
    "ProactiveDecision",
    "ProactiveEngine",
    "ProactiveSignal",
    "QuietHoursResolver",
    "QuietWindow",
    "RateLimitStore",
    "SignalKind",
    "SilenceConfig",
    "SilenceEngine",
    "Urgency",
    "ValueGate",
    "configure_default_engine",
]
