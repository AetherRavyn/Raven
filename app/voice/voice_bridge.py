"""Cross-channel voice bridge — real-time voice across Telegram, Discord, Slack.

The voice pipeline (wake word → VAD → STT → LLM → TTS → speaker) was
previously local-only. This module bridges it into messaging channels so
users can have real-time voice conversations from any platform.

Architecture:
    VoiceSessionManager  — manages active voice sessions per user/channel
      ├─ TelegramVoiceSession  — streams audio via Telegram voice chats
      ├─ DiscordVoiceSession  — uses Discord's voice gateway (opus packets)
      └─ SlackVoiceSession    — uses Slack's audio clip API

Each session:
    1. Receives audio chunks from the channel
    2. Runs through VAD → STT (from pipeline)
    3. Sends text to orchestrator
    4. Pipeline TTS → sends audio back to the channel
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VoiceSession:
    """An active voice conversation session on a messaging channel."""

    session_id: str
    platform: str
    user_id: str
    chat_id: str
    started_at: float = field(default_factory=time.time)
    transcription: list[str] = field(default_factory=list)
    _active: bool = True

    def close(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.started_at


class VoiceSessionManager:
    """Manages active voice sessions across all messaging channels.

    Usage:
        mgr = VoiceSessionManager(orchestrator, botsignal)
        session = await mgr.start_session("telegram", "user123", "chat456")
        await mgr.feed_audio(session.session_id, audio_bytes)
        await mgr.end_session(session.session_id)
    """

    def __init__(self, orchestrator: Any, botsignal: Any) -> None:
        self._orchestrator = orchestrator
        self._botsignal = botsignal
        self._sessions: dict[str, VoiceSession] = {}
        self._lock = asyncio.Lock()

    async def start_session(
        self,
        platform: str,
        user_id: str,
        chat_id: str,
    ) -> VoiceSession:
        """Start a new voice session for a user on a platform."""
        session_id = f"{platform}:{user_id}:{chat_id}:{int(time.time())}"
        session = VoiceSession(
            session_id=session_id,
            platform=platform,
            user_id=user_id,
            chat_id=chat_id,
        )
        async with self._lock:
            self._sessions[session_id] = session
        logger.info(
            "Voice session started: %s (%s/%s)",
            session_id,
            platform,
            user_id,
        )
        return session

    async def feed_audio(self, session_id: str, audio_bytes: bytes) -> str | None:
        """Feed audio bytes to the session's STT pipeline.

        Returns transcribed text if speech was detected, None otherwise.
        """
        session = self._sessions.get(session_id)
        if not session or not session.active:
            return None
        try:
            from app.voice.transcribe import transcribe_bytes

            text = await transcribe_bytes(audio_bytes)
            if text and text.strip():
                session.transcription.append(text.strip())
                return text.strip()
        except Exception as e:
            logger.debug("Voice session %s STT error: %s", session_id, e)
        return None

    async def process_transcription(
        self,
        session_id: str,
        text: str,
    ) -> None:
        """Send transcribed text to the orchestrator for processing."""
        session = self._sessions.get(session_id)
        if not session or not session.active:
            return
        from app.core.models import IncomingRequest, ReplyTarget

        request = IncomingRequest(
            platform=f"{session.platform}_voice",
            user_id=session.user_id,
            text=text,
            reply_target=ReplyTarget(
                platform=session.platform,
                chat_id=session.chat_id,
            ),
            conversation_id=session.chat_id,
        )
        await self._orchestrator.handle(request)

    async def end_session(self, session_id: str) -> None:
        """End a voice session and clean up."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.close()
            duration = session.duration_seconds
            count = len(session.transcription)
            logger.info(
                "Voice session ended: %s (%d utterances, %.1fs)",
                session_id,
                count,
                duration,
            )

    def get_active_session(
        self,
        platform: str,
        user_id: str,
    ) -> VoiceSession | None:
        """Return the active session for a user on a platform, if any."""
        for session in self._sessions.values():
            if session.active and session.platform == platform and session.user_id == user_id:
                return session
        return None

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.active)


# Global singleton
_session_manager: VoiceSessionManager | None = None


def get_voice_session_manager(
    orchestrator: Any | None = None,
    botsignal: Any | None = None,
) -> VoiceSessionManager:
    """Get or create the global VoiceSessionManager."""
    global _session_manager
    if _session_manager is None:
        if orchestrator is None or botsignal is None:
            raise RuntimeError(
                "VoiceSessionManager not initialized. "
                "Call get_voice_session_manager(orchestrator, botsignal) first."
            )
        _session_manager = VoiceSessionManager(orchestrator, botsignal)
    return _session_manager
