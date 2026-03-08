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

    # Print table
    logger.info("=" * 52)
    logger.info("SARAS Startup Configuration")
    logger.info("=" * 52)
    for s in statuses:
        icon = "[OK]" if s.enabled else "[--]"
        logger.info("  %s  %-22s %s", icon, s.name, s.reason)
    logger.info("=" * 52)

    return statuses
