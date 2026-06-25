"""Voice Channel Abstraction Layer — unified interface for all calling platforms.

All voice-enabled platforms (Telegram, WhatsApp, SIP, WebRTC, Discord)
implement this interface for consistent call handling.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class CallState(Enum):
    """Call lifecycle states."""
    IDLE = "idle"
    RINGING = "ringing"
    CONNECTING = "connecting"
    ACTIVE = "active"
    HOLD = "hold"
    ENDED = "ended"
    FAILED = "failed"


class CallDirection(Enum):
    """Call direction."""
    INCOMING = "incoming"
    OUTGOING = "outgoing"


@dataclass
class CallInfo:
    """Complete call information."""
    call_id: str
    platform: str
    direction: CallDirection
    remote_user: str
    remote_name: Optional[str] = None
    state: CallState = CallState.IDLE
    started_at: Optional[str] = None
    connected_at: Optional[str] = None
    ended_at: Optional[str] = None
    audio_format: str = "opus"
    sample_rate: int = 48000
    channels: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "platform": self.platform,
            "direction": self.direction.value,
            "remote_user": self.remote_user,
            "remote_name": self.remote_name,
            "state": self.state.value,
            "started_at": self.started_at,
            "connected_at": self.connected_at,
            "ended_at": self.ended_at,
            "audio_format": self.audio_format,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "metadata": self.metadata,
        }


AudioCallback = Callable[[str, bytes], None]
StateCallback = Callable[[CallInfo], None]
DTMFCallback = Callable[[str, str], None]


class VoiceChannel(ABC):
    """Base class for all voice-enabled communication channels.

    Implementations handle platform-specific signaling and media transport
    while presenting a unified interface to the CallManager.
    """

    def __init__(self) -> None:
        self._audio_callback: Optional[AudioCallback] = None
        self._state_callback: Optional[StateCallback] = None
        self._dtmf_callback: Optional[DTMFCallback] = None
        self._active_calls: dict[str, CallInfo] = {}

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Unique platform identifier (e.g., 'telegram', 'whatsapp', 'sip')."""
        ...

    @abstractmethod
    async def start(self, stop_event: asyncio.Event) -> None:
        """Start the channel listener. Runs until stop_event is set."""
        ...

    @abstractmethod
    async def make_call(self, target: str, **kwargs) -> CallInfo:
        """Initiate an outbound call to target.

        Args:
            target: Platform-specific identifier (username, phone number, SIP URI)
            **kwargs: Platform-specific options

        Returns:
            CallInfo for the initiated call
        """
        ...

    @abstractmethod
    async def answer_call(self, call_id: str) -> None:
        """Answer an incoming call."""
        ...

    @abstractmethod
    async def hangup_call(self, call_id: str) -> None:
        """End an active call."""
        ...

    @abstractmethod
    async def hold_call(self, call_id: str) -> None:
        """Place call on hold."""
        ...

    @abstractmethod
    async def resume_call(self, call_id: str) -> None:
        """Resume a held call."""
        ...

    @abstractmethod
    async def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Send audio bytes to the call.

        Audio should be in the format specified by CallInfo (default Opus 48kHz mono).
        """
        ...

    @abstractmethod
    async def send_dtmf(self, call_id: str, digits: str) -> None:
        """Send DTMF tones."""
        ...

    def on_audio_received(self, callback: AudioCallback) -> None:
        """Register callback for incoming audio from calls."""
        self._audio_callback = callback

    def on_call_state_change(self, callback: StateCallback) -> None:
        """Register callback for call state changes."""
        self._state_callback = callback

    def on_dtmf_received(self, callback: DTMFCallback) -> None:
        """Register callback for received DTMF tones."""
        self._dtmf_callback = callback

    def _emit_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Internal: emit received audio to registered callback."""
        if self._audio_callback:
            try:
                self._audio_callback(call_id, audio_bytes)
            except Exception:
                pass  # Don't let callback errors crash the channel

    def _emit_state_change(self, info: CallInfo) -> None:
        """Internal: emit call state change to registered callback."""
        self._active_calls[info.call_id] = info
        if self._state_callback:
            try:
                self._state_callback(info)
            except Exception:
                pass

    def _emit_dtmf(self, call_id: str, digit: str) -> None:
        """Internal: emit received DTMF to registered callback."""
        if self._dtmf_callback:
            try:
                self._dtmf_callback(call_id, digit)
            except Exception:
                pass

    def get_call(self, call_id: str) -> Optional[CallInfo]:
        """Get call info by ID."""
        return self._active_calls.get(call_id)

    def list_calls(self) -> list[CallInfo]:
        """List all active calls."""
        return list(self._active_calls.values())

    @staticmethod
    def generate_call_id(prefix: str = "") -> str:
        """Generate a unique call ID."""
        import uuid
        return f"{prefix}{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        """Current UTC time as ISO string."""
        return datetime.now(timezone.utc).isoformat()
