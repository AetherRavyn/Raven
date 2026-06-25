"""Voice Module — A2A-compliant voice processing module.

Exposes voice capabilities via the Raven Protocol.
Any module can call voice methods without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_synthesize(params: dict[str, Any]) -> dict[str, Any]:
    """Convert text to speech."""
    from app.voice.tts import synthesize
    text = params.get("text", "")
    voice = params.get("voice")
    audio_path = await synthesize(text, voice=voice)
    return {"success": bool(audio_path), "audio_path": audio_path}


async def handle_detect_emotion(params: dict[str, Any]) -> dict[str, Any]:
    """Detect emotional tone from text."""
    from app.voice.emotion import detect_emotion
    text = params.get("text", "")
    emotion = detect_emotion(text)
    return {
        "emotion": emotion.emotion,
        "speed": emotion.speed,
        "pitch": emotion.pitch,
        "energy": emotion.energy,
    }


async def handle_detect_language(params: dict[str, Any]) -> dict[str, Any]:
    """Detect language from text."""
    from app.core.language_detect import detect_language, get_language_name
    text = params.get("text", "")
    result = detect_language(text)
    return {
        "language": result.language,
        "language_name": get_language_name(result.language),
        "confidence": result.confidence,
        "script": result.script,
    }


def create_voice_server() -> ModuleServer:
    """Create and configure the Voice module server."""
    card = AgentCard(
        name="voice",
        description="Voice processing: TTS, emotion detection, language detection",
        version="1.0.0",
        skills=[
            Skill(name="synthesize", description="Text to speech", tags=["tts", "speech"]),
            Skill(name="detect_emotion", description="Detect emotional tone", tags=["emotion", "sentiment"]),
            Skill(name="detect_language", description="Detect language", tags=["language", "i18n"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("voice.synthesize", handle_synthesize)
    server.register_method("voice.detect_emotion", handle_detect_emotion)
    server.register_method("voice.detect_language", handle_detect_language)

    return server
