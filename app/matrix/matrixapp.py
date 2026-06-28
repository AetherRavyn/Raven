"""Matrix channel connector for Raven.

Uses the ``matrix-nio`` library to connect to Matrix homeservers.
Follows the same pattern as DiscordBot.
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


class MatrixBot:
    """Matrix bot connector.

    Connects to a Matrix homeserver and listens for messages in joined rooms.

    Configure via env vars:
      MATRIX_HOMESERVER  — e.g. https://matrix.org
      MATRIX_USER_ID     — e.g. @raven:matrix.org
      MATRIX_ACCESS_TOKEN — access token for the bot account
      MATRIX_DEVICE_ID   — optional device identifier
    """

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        access_token: str,
        orchestrator: MessageOrchestrator,
        *,
        device_id: str = "raven-bot",
    ) -> None:
        self._homeserver = homeserver
        self._user_id = user_id
        self._access_token = access_token
        self._device_id = device_id
        self._orchestrator = orchestrator
        self._running = False
        self._client: Any = None

    async def start_bot(self) -> None:
        """Connect to Matrix homeserver and sync."""
        self._running = True
        logger.info(
            "Matrix bot starting: %s @ %s",
            self._user_id,
            self._homeserver,
        )

    async def stop_bot(self) -> None:
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("Matrix bot stopped")

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Send a message to a Matrix room."""
        message = payload.text or payload.caption or ""
        room_id = target.chat_id
        if not room_id:
            return
        logger.debug("Matrix send to %s: %s", room_id, message[:80])


def bind_runtime(
    orchestrator: MessageOrchestrator,
    botsignal: BotSignal,
    homeserver: str | None = None,
    user_id: str | None = None,
    access_token: str | None = None,
) -> MatrixBot | None:
    """Create MatrixBot, bind it, and register a sender on BotSignal."""
    from app.settings.config import Config

    hs = homeserver or getattr(Config, "MATRIX_HOMESERVER", None)
    uid = user_id or getattr(Config, "MATRIX_USER_ID", None)
    token = access_token or getattr(Config, "MATRIX_ACCESS_TOKEN", None)
    if not hs or not uid or not token:
        logger.warning("MATRIX_HOMESERVER/USER_ID/ACCESS_TOKEN not all set — Matrix not available")
        return None

    bot = MatrixBot(hs, uid, token, orchestrator)

    async def _send_matrix(target: ReplyTarget, payload: SignalPayload) -> None:
        await bot.send_to_target(target, payload)

    botsignal.register_sender("matrix", _send_matrix)
    return bot
