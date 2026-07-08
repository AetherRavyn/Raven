from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload, ToolTrace

# MessageOrchestrator is lazy-imported to avoid circular imports when agent
# modules reference tools that reference app.core.botsignal.


def __getattr__(name: str):
    if name == "MessageOrchestrator":
        from app.core.orchestrator import MessageOrchestrator
        return MessageOrchestrator
    if name == "PredictionOrchestrator":
        from app.core.prediction.orchestrator import PredictionOrchestrator
        return PredictionOrchestrator
    if name == "UnifiedMultimodalIntegration":
        from app.core.unified_multimodal_integration import UnifiedMultimodalIntegration
        return UnifiedMultimodalIntegration
    if name == "get_unified_multimodal_integration":
        from app.core.unified_multimodal_integration import get_unified_multimodal_integration
        return get_unified_multimodal_integration
    if name == "UnifiedMultimodalContextBuilder":
        from app.core.unified_multimodal import UnifiedMultimodalContextBuilder
        return UnifiedMultimodalContextBuilder
    if name == "get_unified_context_builder":
        from app.core.unified_multimodal import get_unified_context_builder
        return get_unified_context_builder
    if name == "MultimodalConnectorHub":
        from app.core.multimodal_connectors import MultimodalConnectorHub
        return MultimodalConnectorHub
    if name == "get_connector_hub":
        from app.core.multimodal_connectors import get_connector_hub
        return get_connector_hub
    if name == "AgentReachAdapter":
        from app.core.agent_reach_adapter import AgentReachAdapter
        return AgentReachAdapter
    if name == "get_agent_reach_adapter":
        from app.core.agent_reach_adapter import get_agent_reach_adapter
        return get_agent_reach_adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BotSignal",
    "get_botsignal",
    "IncomingRequest",
    "ReplyTarget",
    "SignalPayload",
    "ToolTrace",
    "MessageOrchestrator",
    "PredictionOrchestrator",
    "UnifiedMultimodalIntegration",
    "get_unified_multimodal_integration",
    "UnifiedMultimodalContextBuilder",
    "get_unified_context_builder",
    "MultimodalConnectorHub",
    "get_connector_hub",
    "AgentReachAdapter",
    "get_agent_reach_adapter",
]
