"""IRC channel adapter — Bridges AetherRavyn to IRC via irc.client (irclib).

Requires the `irc` package:
    uv pip install irc

Usage:
    export IRC_SERVER=irc.libera.chat
    export IRC_PORT=6667
    export IRC_NICK=aetherravyn
    export IRC_CHANNELS="#aetherravyn,#bot"
    # Optional:
    export IRC_PASSWORD=your_password
    export IRC_USE_SSL=false
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
from dataclasses import dataclass, field
from typing import Any

from app.core.models import IncomingRequest, ReplyTarget

logger = logging.getLogger(__name__)


@dataclass
class IRCConfig:
    """IRC adapter configuration."""
    server: str = os.getenv("IRC_SERVER", "")
    port: int = int(os.getenv("IRC_PORT", "6667"))
    nick: str = os.getenv("IRC_NICK", "aetherravyn")
    channels: list[str] = field(default_factory=lambda: [
        c.strip() for c in os.getenv("IRC_CHANNELS", "").split(",") if c.strip()
    ])
    password: str = os.getenv("IRC_PASSWORD", "")
    use_ssl: bool = os.getenv("IRC_USE_SSL", "false").lower() in {"true", "1", "yes"}
    enabled: bool = bool(os.getenv("IRC_SERVER"))


class IRCChannel:
    """Receive and send messages via IRC using the irc library.

    Supports:
    - Multiple channels
    - SSL/TLS connections
    - NickServ authentication
    - Auto-reconnect on disconnect
    """

    def __init__(self, orchestrator: Any, config: IRCConfig | None = None) -> None:
        self._orchestrator = orchestrator
        self._config = config or IRCConfig()
        self._running = False
        self._client: Any = None
        self._reactor: Any = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._config.server)

    async def start(self) -> None:
        """Connect to IRC and start listening."""
        if not self.enabled:
            logger.info("IRC channel disabled (IRC_SERVER not set)")
            return

        try:
            import irc.client
        except ImportError:
            logger.error("irc package not installed. Run: uv pip install irc")
            return

        logger.info(
            "Starting IRC channel: %s@%s:%d channels=%s",
            self._config.nick,
            self._config.server,
            self._config.port,
            self._config.channels,
        )

        self._running = True
        self._reactor = irc.client.Reactor()
        self._client = self._reactor.server()

        # Register event handlers
        self._client.add_global_handler("welcome", self._on_welcome)
        self._client.add_global_handler("pubmsg", self._on_pubmsg)
        self._client.add_global_handler("privmsg", self._on_privmsg)
        self._client.add_global_handler("disconnect", self._on_disconnect)

        # Connect
        try:
            connect_params: dict[str, Any] = {
                "server": self._config.server,
                "port": self._config.port,
                "nickname": self._config.nick,
            }
            if self._config.password:
                connect_params["password"] = self._config.password
            if self._config.use_ssl:
                connect_params["ssl"] = ssl.create_default_context()

            self._client.connect(**connect_params)
            logger.info("IRC connecting to %s:%d", self._config.server, self._config.port)

            # Run the IRC loop in a thread
            while self._running:
                self._reactor.process_once(timeout=0.2)
                await asyncio.sleep(0.1)

        except irc.client.ServerConnectionError as exc:
            logger.error("IRC connection failed: %s", exc)
        except Exception as exc:
            logger.error("IRC error: %s", exc)
        finally:
            if self._client and self._client.is_connected():
                self._client.disconnect("Shutting down")

    async def stop(self) -> None:
        """Stop the IRC channel."""
        self._running = False
        if self._client and self._client.is_connected():
            self._client.disconnect("Shutting down")
        logger.info("IRC channel stopped")

    def _on_welcome(self, connection: Any, event: Any) -> None:
        """Handle successful connection — join channels."""
        logger.info("IRC connected to %s", self._config.server)

        # NickServ authentication
        if self._config.password:
            connection.privmsg("NickServ", f"IDENTIFY {self._config.password}")

        # Join channels
        for channel in self._config.channels:
            if channel:
                connection.join(channel)
                logger.info("IRC joined channel: %s", channel)

    def _on_pubmsg(self, connection: Any, event: Any) -> None:
        """Handle public channel messages."""
        channel = event.target
        nick = event.source.nick
        message = " ".join(event.arguments).strip()

        if not message:
            return

        # Only respond if mentioned or in configured channels
        bot_mention = f"{self._config.nick}:"
        is_mention = message.lower().startswith(bot_mention.lower())
        is_direct = message.startswith("!")

        if not (is_mention or is_direct or channel in self._config.channels):
            return

        # Strip the mention prefix
        if is_mention:
            message = message[len(bot_mention):].strip()
        elif is_direct:
            message = message[1:].strip()

        logger.info("IRC pubmsg [%s] %s: %s", channel, nick, message[:50])

        reply_target = ReplyTarget(platform="irc", chat_id=channel)
        incoming = IncomingRequest(
            platform="irc",
            user_id=nick,
            text=message,
            reply_target=reply_target,
            conversation_id=channel,
        )

        asyncio.create_task(
            self._orchestrator.handle(incoming),
            name=f"irc-{nick}",
        )

    def _on_privmsg(self, connection: Any, event: Any) -> None:
        """Handle private messages."""
        nick = event.source.nick
        message = " ".join(event.arguments).strip()

        if not message:
            return

        logger.info("IRC privmsg from %s: %s", nick, message[:50])

        reply_target = ReplyTarget(platform="irc", chat_id=nick)
        incoming = IncomingRequest(
            platform="irc",
            user_id=nick,
            text=message,
            reply_target=reply_target,
            conversation_id=f"dm:{nick}",
        )

        asyncio.create_task(
            self._orchestrator.handle(incoming),
            name=f"irc-dm-{nick}",
        )

    def _on_disconnect(self, connection: Any, event: Any) -> None:
        """Handle disconnection — log and potentially reconnect."""
        logger.warning("IRC disconnected from %s", self._config.server)
        if self._running:
            logger.info("IRC will attempt reconnect on next cycle")

    async def send_message(self, target: str, text: str) -> bool:
        """Send a message to a channel or user.

        Args:
            target: Channel name (e.g., "#bot") or nick for DM
            text: Message text
        """
        if not self._client or not self._client.is_connected():
            logger.warning("IRC client not connected")
            return False

        try:
            # Split long messages
            max_len = 400  # IRC messages have ~512 byte limit
            lines = text.split("\n")
            for line in lines:
                while line:
                    chunk = line[:max_len]
                    line = line[max_len:]
                    self._client.privmsg(target, chunk)
            return True
        except Exception as exc:
            logger.error("IRC send failed: %s", exc)
            return False
