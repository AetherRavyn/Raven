"""Central call manager — routes calls, manages AI pipeline, tracks state.

Integrates with GatewayDaemon for lifecycle management and
MessageOrchestrator for AI-powered call handling.
"""

from __future__ import annotations

import logging
import tempfile
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.voice.channels.base import (
    CallDirection,
    CallInfo,
    CallState,
    VoiceChannel,
)

logger = logging.getLogger(__name__)


@dataclass
class ActiveCall:
    """Runtime state for an active call."""
    info: CallInfo
    channel: VoiceChannel
    transcript_buffer: list[dict[str, str]] = field(default_factory=list)
    recording_path: Optional[str] = None
    recording_wave: Optional[Any] = None


class CallManager:
    """Central call routing and AI pipeline management.

    Single entry point for all call operations across platforms.
    Routes incoming/outgoing calls through RAVEN's AI pipeline.

    Usage::

        manager = CallManager(orchestrator, botsignal)

        # Register channel adapters
        tg = TelegramVoiceChannel(...)
        manager.register_channel(tg)

        # Make an outbound call
        call_info = await manager.make_call("+15551234567", platform="sip")

        # Hang up
        await manager.hangup_call(call_info.call_id)
    """

    def __init__(
        self,
        orchestrator: Any,
        botsignal: Any,
        workspace_dir: str = "workspace",
    ) -> None:
        self._orchestrator = orchestrator
        self._botsignal = botsignal
        self._workspace_dir = Path(workspace_dir)

        self._channels: dict[str, VoiceChannel] = {}
        self._active_calls: dict[str, ActiveCall] = {}
        self._default_channel: Optional[str] = None

        # Call recording directory
        self._recordings_dir = self._workspace_dir / "call_recordings"
        self._recordings_dir.mkdir(parents=True, exist_ok=True)

    # ── Channel Registration ─────────────────────────────────────────

    def register_channel(
        self,
        channel: VoiceChannel,
        is_default: bool = False,
    ) -> None:
        """Register a VoiceChannel adapter.

        Args:
            channel: VoiceChannel instance
            is_default: Use as default for outbound calls
        """
        name = channel.platform_name
        self._channels[name] = channel

        # Wire audio and state callbacks
        channel.on_audio_received(self._handle_incoming_audio)
        channel.on_call_state_change(self._handle_call_state_change)

        if is_default or self._default_channel is None:
            self._default_channel = name

        logger.info("CallManager: registered channel %s (default=%s)", name, is_default)

    def get_channel(self, platform: str) -> Optional[VoiceChannel]:
        return self._channels.get(platform)

    @property
    def channels(self) -> dict[str, VoiceChannel]:
        return dict(self._channels)

    # ── Call Lifecycle ───────────────────────────────────────────────

    async def make_call(
        self,
        target: str,
        platform: Optional[str] = None,
        **kwargs,
    ) -> CallInfo:
        """Initiate an outbound call.

        Args:
            target: Phone number, username, or SIP URI
            platform: Channel to use (uses default if None)

        Returns:
            CallInfo for the initiated call
        """
        channel = self._resolve_channel(platform)
        call_info = await channel.make_call(target, **kwargs)

        active = ActiveCall(info=call_info, channel=channel)
        self._active_calls[call_info.call_id] = active

        logger.info(
            "CallManager: outbound call %s via %s to %s",
            call_info.call_id, channel.platform_name, target,
        )
        return call_info

    async def answer_call(self, call_id: str) -> None:
        """Answer an incoming call and start the AI pipeline."""
        active = self._active_calls.get(call_id)
        if not active:
            raise ValueError(f"Unknown call: {call_id}")

        active_channel = active.channel
        await active_channel.answer_call(call_id)
        call_info = active.info

        # Register a voice sender so TTS responses route back to this call
        if self._botsignal:
            async def _call_sender(
                target: Any,
                payload: Any,
            ) -> None:
                if payload.text:
                    await self._speak_to_call(call_id, payload.text)
                if payload.audio_path:
                    audio_bytes = Path(payload.audio_path).read_bytes()
                    await active_channel.send_audio(call_id, audio_bytes)

            platform_tag = f"call_{call_info.platform}"
            self._botsignal.register_sender(platform_tag, _call_sender)

        logger.info(
            "CallManager: answered call %s from %s (%s)",
            call_id, call_info.remote_name or call_info.remote_user, call_info.platform,
        )

    async def hangup_call(self, call_id: str) -> None:
        """End an active call and clean up resources."""
        active = self._active_calls.pop(call_id, None)
        if not active:
            return

        await active.channel.hangup_call(call_id)

        # Close recording if active
        if active.recording_wave:
            try:
                active.recording_wave.close()
            except Exception:
                pass

        logger.info("CallManager: hung up call %s", call_id)

    async def hold_call(self, call_id: str) -> None:
        active = self._active_calls.get(call_id)
        if active:
            await active.channel.hold_call(call_id)

    async def resume_call(self, call_id: str) -> None:
        active = self._active_calls.get(call_id)
        if active:
            await active.channel.resume_call(call_id)

    # ── Audio Ingestion ──────────────────────────────────────────────

    async def _handle_incoming_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Process incoming audio from a call: transcribe + route to orchestrator."""
        active = self._active_calls.get(call_id)
        if not active:
            return

        # Transcribe the audio chunk
        text = await self._transcribe_audio(audio_bytes)
        if not text:
            return

        # Append to transcript buffer
        active.transcript_buffer.append({
            "role": "user",
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info("CallManager: transcribed from call %s: %s", call_id, text[:80])

        # Forward to orchestrator as an AI request
        from app.core.models import IncomingRequest, ReplyTarget

        channel = active.channel
        platform_tag = f"call_{channel.platform_name}"

        request = IncomingRequest(
            platform=platform_tag,
            user_id=active.info.remote_user or "caller",
            text=text,
            reply_target=ReplyTarget(
                platform=platform_tag,
                chat_id=call_id,
            ),
            voice_reply=True,
        )
        try:
            await self._orchestrator.handle(request)
        except Exception as exc:
            logger.error("CallManager: orchestrator error: %s", exc)

    async def _handle_call_state_change(self, info: CallInfo) -> None:
        """React to call state transitions."""
        if info.state == CallState.ENDED:
            await self._finalize_call(info.call_id)
        elif info.state == CallState.RINGING and info.direction == CallDirection.INCOMING:
            logger.info(
                "CallManager: incoming call %s from %s",
                info.call_id, info.remote_name or info.remote_user,
            )

    async def _finalize_call(self, call_id: str) -> None:
        """Clean up after a call ends."""
        active = self._active_calls.get(call_id)
        if not active:
            return

        # Save transcript
        if active.transcript_buffer:
            transcript_path = self._recordings_dir / f"call_{call_id}_transcript.json"
            import json
            try:
                transcript_path.write_text(
                    json.dumps(active.transcript_buffer, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.debug("CallManager: failed to save transcript: %s", exc)

        self._active_calls.pop(call_id, None)
        logger.info("CallManager: finalized call %s", call_id)

    # ── TTS Playback ─────────────────────────────────────────────────

    async def _speak_to_call(self, call_id: str, text: str) -> None:
        """Synthesize TTS and send audio to the call."""
        active = self._active_calls.get(call_id)
        if not active:
            return

        try:
            from app.voice.tts import synthesize
            audio_path = await synthesize(text)
            if audio_path:
                audio_bytes = Path(audio_path).read_bytes()
                await active.channel.send_audio(call_id, audio_bytes)

                # Append to transcript
                active.transcript_buffer.append({
                    "role": "assistant",
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as exc:
            logger.error("CallManager: TTS playback failed: %s", exc)

    # ── STT Transcription ────────────────────────────────────────────

    async def _transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe raw audio bytes to text."""
        try:
            from app.voice.transcribe import transcribe_audio

            # Write to temp WAV file
            fd, wav_path = tempfile.mkstemp(suffix=".wav", dir=str(self._workspace_dir))
            import os
            os.close(fd)

            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)

            text = await transcribe_audio(wav_path)

            try:
                os.unlink(wav_path)
            except OSError:
                pass

            return text or ""
        except Exception as exc:
            logger.debug("CallManager: transcription failed: %s", exc)
            return ""

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return call manager status for dashboard."""
        return {
            "active_calls": {
                cid: active.info.to_dict()
                for cid, active in self._active_calls.items()
            },
            "active_count": len(self._active_calls),
            "registered_channels": list(self._channels.keys()),
            "default_channel": self._default_channel,
        }

    def list_calls(self) -> list[CallInfo]:
        """List all active calls."""
        return [active.info for active in self._active_calls.values()]

    # ── Helpers ──────────────────────────────────────────────────────

    def _resolve_channel(self, platform: Optional[str] = None) -> VoiceChannel:
        if platform:
            channel = self._channels.get(platform)
            if not channel:
                raise ValueError(f"Channel not registered: {platform}")
            return channel
        if self._default_channel:
            return self._channels[self._default_channel]
        raise ValueError("No channels registered")


# ── Singleton ────────────────────────────────────────────────────────

_call_manager: Optional[CallManager] = None


def get_call_manager(
    orchestrator: Any = None,
    botsignal: Any = None,
) -> CallManager:
    """Get or create the global CallManager singleton."""
    global _call_manager
    if _call_manager is None:
        if not orchestrator or not botsignal:
            raise RuntimeError(
                "CallManager not initialized. Provide orchestrator and botsignal on first call."
            )
        _call_manager = CallManager(orchestrator, botsignal)
    return _call_manager


def reset_call_manager_for_tests() -> None:
    """Reset singleton (for test teardown)."""
    global _call_manager
    _call_manager = None
