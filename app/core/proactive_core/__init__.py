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

from app.core.proactive_core.anomaly import (
    Anomaly,
    AnomalyConfig,
    AnomalyDetector,
    AnomalySeverity,
    InMemoryObservationStore,
    Observation,
    ObservationKind,
    ObservationStore,
    anomaly_to_signal,
)
from app.core.proactive_core.anticipation import (
    AnticipationEngine,
    Habit,
    HabitStore,
    HabitTracker,
    InMemoryHabitStore,
    PatternKind,
    Prediction,
    commitment_to_signal,
    generate_signals,
    habit_to_signal,
)
from app.core.proactive_core.bootstrap import (
    ProactiveBootstrapConfig,
    UserProactiveContext,
    all_contexts,
    get_context,
    register_proactive_core,
    reset_registry,
    unregister,
)
from app.core.proactive_core.delivery import (
    DeliveryAdapter,
    DeliverySender,
    build_default_adapter,
)
from app.core.proactive_core.dispatcher import ChannelDispatcher, DispatcherConfig
from app.core.proactive_core.engine import (
    EngineConfig,
    ProactiveEngine,
    configure_default_engine,
)
from app.core.proactive_core.follow_up import (
    Commitment,
    CommitmentKind,
    CommitmentStatus,
    CommitmentStore,
    FollowUpTracker,
    InMemoryCommitmentStore,
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
from app.core.proactive_core.smart_nudges import (
    CalendarEvent,
    EmailSummary,
    TaskSummary,
    WeatherForecast,
    calendar_prep_signal,
    email_urgent_signal,
    task_priority_signal,
    weather_signal,
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
    "Anomaly",
    "AnomalyConfig",
    "AnomalyDetector",
    "AnomalySeverity",
    "AnticipationEngine",
    "CalendarEvent",
    "CalendarProvider",
    "ChannelDispatcher",
    "ChannelPreference",
    "Commitment",
    "CommitmentKind",
    "CommitmentStatus",
    "CommitmentStore",
    "DecisionVerdict",
    "DeliveryAdapter",
    "DeliverySender",
    "DispatcherConfig",
    "EmailSummary",
    "EngineConfig",
    "FollowUpTracker",
    "GateConfig",
    "Habit",
    "HabitStore",
    "HabitTracker",
    "InMemoryCommitmentStore",
    "InMemoryHabitStore",
    "InMemoryObservationStore",
    "InMemoryRateLimitStore",
    "Observation",
    "ObservationKind",
    "ObservationStore",
    "PatternKind",
    "Prediction",
    "ProactiveBootstrapConfig",
    "ProactiveDecision",
    "ProactiveEngine",
    "ProactiveSignal",
    "QuietHoursResolver",
    "QuietWindow",
    "RateLimitStore",
    "SignalKind",
    "SilenceConfig",
    "SilenceEngine",
    "TaskSummary",
    "Urgency",
    "UserProactiveContext",
    "ValueGate",
    "WeatherForecast",
    "all_contexts",
    "anomaly_to_signal",
    "build_default_adapter",
    "calendar_prep_signal",
    "commitment_to_signal",
    "configure_default_engine",
    "email_urgent_signal",
    "generate_signals",
    "get_context",
    "habit_to_signal",
    "register_proactive_core",
    "reset_registry",
    "task_priority_signal",
    "unregister",
    "weather_signal",
]
