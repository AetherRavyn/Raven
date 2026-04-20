from __future__ import annotations

from app.core.botsignal import BotSignal
from app.core.models import ReplyTarget, SignalPayload, ToolTrace


def test_botsignal_annotations_include_evidence() -> None:
    signal = BotSignal()
    payload = SignalPayload(
        text="Answer",
        source_kind="prompt",
        tool_traces=[ToolTrace(tool_name="memory", action="lookup", success=True)],
        evidence=["profile:Alex", "graph:nodes=3 edges=2"],
    )
    annotated = signal._payload_with_annotations(payload)
    assert "[evidence] profile:Alex" in (annotated.text or "")
