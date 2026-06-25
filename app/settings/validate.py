# app/settings/validate.py
"""Startup configuration validation and reporting."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PlatformStatus:
    name: str
    enabled: bool
    reason: str


def validate_config() -> list[PlatformStatus]:
    """Check all platform tokens and return a status list.

    Logs a formatted table at INFO level.
    """
    from app.settings.config import Config

    statuses: list[PlatformStatus] = []

    def check(name: str, *tokens: str | None) -> PlatformStatus:
        if not all(tokens):
            return PlatformStatus(
                name=name, enabled=False, reason="token(s) missing from .env"
            )
        return PlatformStatus(name=name, enabled=True, reason="ready")

    # Required platform connectors
    statuses.append(check("Telegram", Config.TELEGRAM_BOT_TOKEN))
    statuses.append(check("Discord", Config.DISCORD_BOT_TOKEN))
    statuses.append(check("Slack", Config.SLACK_BOT_TOKEN, Config.SLACK_APP_TOKEN))

    # Optional API keys — always included but flagged as optional when missing
    for key, name in [
        (Config.GEMINI_API_KEY, "Gemini/Google"),
        (Config.OPENAI_API_KEY, "OpenAI"),
        (Config.XAI_API_KEY, "xAI"),
        (Config.VIRUSTOTAL_API_KEY, "VirusTotal"),
        (Config.DEEPGRAM_API_KEY, "Deepgram"),
        (getattr(Config, "OPENWEATHERMAP_API_KEY", None), "OpenWeatherMap"),
    ]:
        level = "ready" if key else "missing (optional)"
        statuses.append(PlatformStatus(name=name, enabled=bool(key), reason=level))

    # v33 voice stack — whisper.cpp + Piper-TTS autherRaven
    import os as _os
    piper_model = getattr(Config, "PIPER_VOICE_MODEL", "")
    whisper_model = getattr(Config, "WHISPER_CPP_MODEL", "")
    statuses.append(PlatformStatus(
        name="Piper-TTS",
        enabled=bool(piper_model and _os.path.exists(piper_model)),
        reason=(
            f"ready (voice={getattr(Config, 'PIPER_VOICE_NAME', 'autherRaven')})"
            if piper_model and _os.path.exists(piper_model)
            else f"missing model: {piper_model!r}"
        ),
    ))
    statuses.append(PlatformStatus(
        name="whisper.cpp",
        enabled=bool(whisper_model and _os.path.exists(whisper_model)),
        reason=(
            f"ready (lang={getattr(Config, 'WHISPER_CPP_LANGUAGE', 'en')})"
            if whisper_model and _os.path.exists(whisper_model)
            else f"missing model: {whisper_model!r}"
        ),
    ))

    # Print table
    logger.info("=" * 52)
    logger.info("RAVEN Startup Configuration")
    logger.info("=" * 52)
    for s in statuses:
        icon = "[OK]" if s.enabled else "[--]"
        logger.info("  %s  %-22s %s", icon, s.name, s.reason)
    logger.info("=" * 52)

    return statuses
