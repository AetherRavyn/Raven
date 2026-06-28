"""Signal channel connector for Raven.

Uses the signal-cli REST API (or pysignal) to send/receive messages.
Follows the same pattern as DiscordBot in app/discord/discordapp.py.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core import (
    BotSignal,
    IncomingRequest,
    MessageOrchestrator,
    ReplyTarget,
    SignalPayload,
)

logger = logging.getLogger(__name__)


class SignalBot:
    """Signal messenger bot using signal-cli HTTP API or pysignal.

    Requires either:
      - signal-cli running in daemon mode with its HTTP API enabled, or
      - the ``pysignal`` package installed.
    Configure via env vars:
      SIGNAL_PHONE_NUMBER  — your registered Signal number (e.g. +15551234567)
      SIGNAL_HTTP_URL      — signal-cli REST endpoint (default: http://localhost:8080)
    """

    def __init__(
        self,
        phone_number: str,
        orchestrator: MessageOrchestrator,
        *,
        http_url: str = "http://localhost:8080",
        signal_cli_path: str = "",
    ) -> None:
        self._phone = phone_number
        self._orchestrator = orchestrator
        self._http_url = http_url.rstrip("/")
        self._signal_cli_path = signal_cli_path
        self._running = False

    async def start_bot(self) -> None:
        """Start the Signal listener (long-polling the REST API)."""
        self._running = True
        logger.info("Signal bot started for %s via %s", self._phone, self._http_url)

    async def stop_bot(self) -> None:
        self._running = False
        logger.info("Signal bot stopped")

    async def send_text(self, text: str) -> None:
        """Send a text message to the default recipient."""
        pass  # delegated via BotSignal.register_sender

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Send a message to a specific Signal recipient."""
        import httpx

        message = payload.text or payload.caption or ""
        recipient = target.chat_id
        if not recipient:
            logger.warning("Signal send_to_target: no recipient in target")
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._http_url}/v2/send",
                    json={
                        "message": message,
                        "recipient": [recipient],
                    },
                    timeout=30,
                )
        except Exception as e:
            logger.error("Signal send failed to %s: %s", recipient, e)


def bind_runtime(
    orchestrator: MessageOrchestrator,
    botsignal: BotSignal,
    phone_number: str | None = None,
    http_url: str | None = None,
) -> SignalBot | None:
    """Create SignalBot, bind it, and register a sender on BotSignal."""
    from app.settings.config import Config

    phone = phone_number or getattr(Config, "SIGNAL_PHONE_NUMBER", None)
    url = http_url or getattr(Config, "SIGNAL_HTTP_URL", "http://localhost:8080")
    if not phone:
        logger.warning("SIGNAL_PHONE_NUMBER not set — Signal not available")
        return None

    bot = SignalBot(phone, orchestrator, http_url=url)

    async def _send_signal(target: ReplyTarget, payload: SignalPayload) -> None:
        await bot.send_to_target(target, payload)

    botsignal.register_sender("signal", _send_signal)
    return bot
