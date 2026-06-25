"""RAVEN companion module.

The companion is a thin client that lives on the user's devices
(desktop / mobile) and renders the orchestrator's event bus.  It
never blocks on the orchestrator — if the bus is down, it shows
"offline" and queues outgoing actions.

This package is a Python reference implementation that doubles as
the contract spec for the future Tauri (desktop) and Capacitor
(mobile) ports.
"""
from app.companion.cache import OfflineCache
from app.companion.client import ClientConfig, CompanionClient, Transport
from app.companion.notifications import (
    MuteRule,
    NotificationDispatcher,
    NotificationPayload,
    NotificationSink,
    parse_mute_rule,
)
from app.companion.palette import (
    DEFAULT_INTENTS,
    CommandPalette,
    IntentEntry,
    Suggestion,
)
from app.companion.status import StatusCollector, StatusSnapshot
from app.companion.types import (
    PROTOCOL_VERSION,
    Ack,
    Command,
    ErrorFrame,
    Event,
    Hello,
    MessageKind,
    Ping,
    Pong,
    Response,
    Status,
    Subscribe,
    Welcome,
    encode,
    parse_frame,
    parse_frame_strict,
)

__all__ = [
    # protocol
    "PROTOCOL_VERSION",
    "MessageKind",
    "Hello",
    "Welcome",
    "Ping",
    "Pong",
    "Subscribe",
    "Command",
    "Response",
    "Ack",
    "Status",
    "Event",
    "ErrorFrame",
    "encode",
    "parse_frame",
    "parse_frame_strict",
    # status tile
    "StatusCollector",
    "StatusSnapshot",
    # palette
    "CommandPalette",
    "IntentEntry",
    "Suggestion",
    "DEFAULT_INTENTS",
    # notifications
    "NotificationDispatcher",
    "NotificationPayload",
    "NotificationSink",
    "MuteRule",
    "parse_mute_rule",
    # offline cache
    "OfflineCache",
    # client
    "CompanionClient",
    "ClientConfig",
    "Transport",
]