from __future__ import annotations

from app.core.models import IncomingRequest, ReplyTarget, SignalPayload
from app.core.multimodal import MultimodalContextBuilder, MultimodalEvent


def test_multimodal_context_prioritizes_request_and_images() -> None:
    builder = MultimodalContextBuilder(max_chars=400)
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="describe this",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
        conversation_id="u1",
        image_urls=["https://example.com/a.png"],
    )
    ctx = builder.from_request(
        request,
        sensor_state={"room/temp": {"temperature": 21}},
        memory_snippets=["user likes concise answers"],
        event_payloads=[{"event_type": "camera_alert", "risk_level": "high"}],
    )
    rendered = ctx.render()
    assert "Multimodal Context" in rendered
    assert "image[1]" in rendered
    assert "room/temp" in rendered
    assert "camera_alert" in rendered


def test_signal_payload_converts_to_multimodal_events() -> None:
    payload = SignalPayload(
        text="hello",
        audio_path="/tmp/audio.wav",
        video_path="/tmp/video.mp4",
        file_path="/tmp/file.txt",
        source_kind="web",
    )
    events = MultimodalContextBuilder.from_signal_payload(payload)
    modalities = [event.modality for event in events]
    assert modalities == ["text", "audio", "video", "file"]


def test_pack_events_respects_budget() -> None:
    events = [
        MultimodalEvent(modality="text", content="A" * 200, priority=100),
        MultimodalEvent(modality="image", content="B" * 200, priority=90),
    ]
    packed = MultimodalContextBuilder.pack_events(events, max_chars=250)
    assert len(packed) == 1
