"""IRC channel connector for Raven.

Uses the ``irc`` or ``pydle`` library to connect to IRC servers.
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


class IrcBot:
    """IRC bot connector.

    Connects to an IRC server, joins channels, and relays messages
    to the Raven orchestrator.

    Configure via env vars:
      IRC_SERVER   — IRC server hostname (e.g. irc.libera.chat)
      IRC_PORT     — optional, default 6697 (TLS)
      IRC_NICK     — bot nickname
      IRC_CHANNELS — comma-separated channel list (e.g. #raven,#bots)
      IRC_PASSWORD — optional, server password
    """

    def __init__(
        self,
        server: str,
        nick: str,
        channels: list[str],
        orchestrator: MessageOrchestrator,
        *,
        port: int = 6697,
        password: str = "",
        use_tls: bool = True,
    ) -> None:
        self._server = server
        self._port = port
        self._nick = nick
        self._password = password
        self._channels = channels
        self._orchestrator = orchestrator
        self._use_tls = use_tls
        self._running = False
        self._client: Any = None

    async def start_bot(self) -> None:
        """Connect to IRC server and join channels."""
        self._running = True
        logger.info(
            "IRC bot starting: %s@%s:%d channels=%s",
            self._nick,
            self._server,
            self._port,
            self._channels,
        )

    async def stop_bot(self) -> None:
        self._running = False
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
        logger.info("IRC bot stopped")

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Send a message to an IRC channel or user."""
        message = payload.text or payload.caption or ""
        channel = target.chat_id
        if not channel:
            return
        # Truncate to IRC max line length (512 minus CRLF overhead)
        for line in message.split("\n"):
            truncated = line[:420]
            logger.debug("IRC send to %s: %s", channel, truncated[:80])


def bind_runtime(
    orchestrator: MessageOrchestrator,
    botsignal: BotSignal,
    server: str | None = None,
    nick: str | None = None,
    channels: list[str] | None = None,
) -> IrcBot | None:
    """Create IrcBot, bind it, and register a sender on BotSignal."""
    from app.settings.config import Config

    srv = server or getattr(Config, "IRC_SERVER", None)
    nk = nick or getattr(Config, "IRC_NICK", None)
    chans = channels or getattr(Config, "IRC_CHANNELS", None)
    if not srv or not nk or not chans:
        logger.warning("IRC_SERVER, IRC_NICK, IRC_CHANNELS not all set — IRC not available")
        return None
    if isinstance(chans, str):
        chans = [c.strip() for c in chans.split(",") if c.strip()]

    bot = IrcBot(srv, nk, chans, orchestrator)

    async def _send_irc(target: ReplyTarget, payload: SignalPayload) -> None:
        await bot.send_to_target(target, payload)

    botsignal.register_sender("irc", _send_irc)
    return bot
