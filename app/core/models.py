from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReplyTarget:
    platform: str
    chat_id: str
    reply_to_id: str | None = None


@dataclass(slots=True)
class IncomingRequest:
    platform: str
    user_id: str
    text: str
    reply_target: ReplyTarget
    image_urls: list[str] | None = None
    voice_reply: bool = False  # if True, botsignal uses telegram_voice sender
    conversation_id: str | None = None


@dataclass(slots=True)
class ToolTrace:
    tool_name: str
    action: str
    success: bool
    detail: str | None = None


@dataclass(slots=True)
class SignalPayload:
    text: str | None = None
    caption: str | None = None
    animation_url: str | None = None
    file_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    source_kind: str | None = None
    tool_traces: list[ToolTrace] | None = None
    evidence: list[str] | None = None
