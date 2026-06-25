"""Gateway Protocol — Standardized message format for all channels.

Defines the canonical message types used between channels, the gateway
daemon, and the orchestrator. All channel adapters convert their native
message format to/from GatewayMessage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """Types of gateway messages."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    COMMAND = "command"
    REACTION = "reaction"
    SYSTEM = "system"


class ChannelStatus(str, Enum):
    """Status of a channel connection."""

    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(slots=True)
class Attachment:
    """A file attachment on a message."""

    url: str = ""
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    local_path: str = ""


@dataclass(slots=True)
class GatewayMessage:
    """Standardized message format for all channels.

    Every channel adapter converts its native message format into this
    canonical representation. The gateway routes it to the orchestrator,
    and responses are converted back to the native format for delivery.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    platform: str = ""
    channel_id: str = ""
    user_id: str = ""
    text: str = ""
    message_type: MessageType = MessageType.TEXT
    attachments: list[Attachment] = field(default_factory=list)
    reply_to: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_incoming_request(self) -> Any:
        """Convert to IncomingRequest for the orchestrator."""
        from app.core.models import IncomingRequest, ReplyTarget

        return IncomingRequest(
            platform=self.platform,
            user_id=self.user_id,
            text=self.text,
            reply_target=ReplyTarget(
                platform=self.platform,
                chat_id=self.channel_id,
                reply_to_id=self.reply_to,
            ),
            image_urls=[a.url for a in self.attachments if a.mime_type.startswith("image")],
            conversation_id=self.thread_id,
        )


@dataclass(slots=True)
class GatewayResponse:
    """Response from the orchestrator back to a channel."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    request_id: str = ""
    platform: str = ""
    channel_id: str = ""
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class ChannelInfo:
    """Registration info for a channel adapter."""

    name: str
    platform: str
    status: ChannelStatus = ChannelStatus.DISCONNECTED
    connected_at: str = ""
    message_count: int = 0
    error: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "platform": self.platform,
            "status": self.status.value,
            "connected_at": self.connected_at,
            "message_count": self.message_count,
            "error": self.error,
        }
