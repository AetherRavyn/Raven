from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload, ToolTrace

# MessageOrchestrator is lazy-imported to avoid circular imports when agent
# modules reference tools that reference app.core.botsignal.


def __getattr__(name: str):
    if name == "MessageOrchestrator":
        from app.core.orchestrator import MessageOrchestrator

        return MessageOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BotSignal",
    "get_botsignal",
    "IncomingRequest",
    "ReplyTarget",
    "SignalPayload",
    "ToolTrace",
    "MessageOrchestrator",
]
