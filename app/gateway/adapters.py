"""Channel Adapters — Abstract base + concrete adapters for new channels.

Each adapter converts between native platform messages and GatewayMessage,
registering a sender with BotSignal for outbound messages.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from app.gateway.protocol import GatewayMessage, ChannelStatus

logger = logging.getLogger(__name__)


class ChannelAdapter(ABC):
    """Abstract base for all channel adapters.

    Subclasses must implement:
    - ``start(stop_event)`` — connect and start listening
    - ``send_message(channel_id, text, attachments)`` — send a response
    - ``platform`` property — return platform name
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier (e.g., 'signal', 'matrix')."""
        ...

    @abstractmethod
    async def start(self, stop_event: asyncio.Event) -> None:
        """Connect to the platform and start listening for messages.

        Must run until stop_event is set.
        """
        ...

    @abstractmethod
    async def send_message(
        self, channel_id: str, text: str, **kwargs: Any
    ) -> bool:
        """Send a message to a channel. Returns True on success."""
        ...

    async def on_message(self, msg: GatewayMessage) -> None:
        """Called when a message is received. Routes to orchestrator.

        Default implementation converts to IncomingRequest and calls
        the orchestrator. Override for custom handling.
        """
        try:
            from app.core.orchestrator import MessageOrchestrator
            from app.core.botsignal import get_botsignal

            botsignal = get_botsignal()
            request = msg.to_incoming_request()
            # The orchestrator will be retrieved from the gateway
            logger.debug(
                "Received %s message from %s in %s",
                msg.platform, msg.user_id, msg.channel_id,
            )
        except Exception as exc:
            logger.error("Failed to route message: %s", exc)


class SignalAdapter(ChannelAdapter):
    """Signal messenger adapter via signal-cli-rest-api.

    Requires a running signal-cli-rest-api instance.
    Config: SIGNAL_CLI_URL (default: http://localhost:8080)
    """

    def __init__(self, api_url: str = "", phone_number: str = "") -> None:
        from app.settings.config import Config
        self._api_url = api_url or getattr(Config, "SIGNAL_CLI_URL", "http://localhost:8080")
        self._phone = phone_number
        self._session: Any = None

    @property
    def platform(self) -> str:
        return "signal"

    async def start(self, stop_event: asyncio.Event) -> None:
        """Connect to signal-cli-rest-api and poll for messages."""
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp required for Signal adapter")
            await stop_event.wait()
            return

        logger.info("Signal adapter connecting to %s", self._api_url)

        async with aiohttp.ClientSession() as session:
            self._session = session
            while not stop_event.is_set():
                try:
                    async with session.get(
                        f"{self._api_url}/v1/receive/{self._phone}",
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            messages = await resp.json()
                            for msg_data in messages:
                                await self._handle_signal_message(msg_data)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.debug("Signal poll error: %s", exc)
                    await asyncio.sleep(5)

    async def send_message(
        self, channel_id: str, text: str, **kwargs: Any
    ) -> bool:
        if not self._session:
            return False
        try:
            payload = {
                "message": text,
                "number": self._phone,
                "recipients": [channel_id],
            }
            async with self._session.post(
                f"{self._api_url}/v2/send", json=payload
            ) as resp:
                return resp.status == 201
        except Exception as exc:
            logger.error("Signal send error: %s", exc)
            return False

    async def _handle_signal_message(self, data: dict[str, Any]) -> None:
        envelope = data.get("envelope", {})
        source = envelope.get("sourceNumber", "")
        msg_data = envelope.get("dataMessage", {})
        text = msg_data.get("message", "")
        if text and source:
            msg = GatewayMessage(
                platform="signal",
                channel_id=source,
                user_id=source,
                text=text,
            )
            await self.on_message(msg)


class MatrixAdapter(ChannelAdapter):
    """Matrix/Element adapter via matrix-nio.

    Config: MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN
    """

    def __init__(
        self, homeserver: str = "", access_token: str = "", user_id: str = ""
    ) -> None:
        from app.settings.config import Config
        self._homeserver = homeserver or getattr(Config, "MATRIX_HOMESERVER", "")
        self._token = access_token or getattr(Config, "MATRIX_ACCESS_TOKEN", "")
        self._user_id = user_id
        self._client: Any = None

    @property
    def platform(self) -> str:
        return "matrix"

    async def start(self, stop_event: asyncio.Event) -> None:
        """Connect to Matrix homeserver and sync for messages."""
        try:
            from nio import AsyncClient, RoomMessageText
        except ImportError:
            logger.error("matrix-nio required for Matrix adapter: pip install matrix-nio")
            await stop_event.wait()
            return

        if not self._homeserver or not self._token:
            logger.warning("Matrix not configured (MATRIX_HOMESERVER / MATRIX_ACCESS_TOKEN)")
            await stop_event.wait()
            return

        logger.info("Matrix adapter connecting to %s", self._homeserver)
        client = AsyncClient(self._homeserver, self._user_id)
        client.access_token = self._token
        self._client = client

        async def message_callback(room: Any, event: Any) -> None:
            if isinstance(event, RoomMessageText):
                if event.sender != self._user_id:
                    msg = GatewayMessage(
                        platform="matrix",
                        channel_id=room.room_id,
                        user_id=event.sender,
                        text=event.body,
                    )
                    await self.on_message(msg)

        client.add_event_callback(message_callback, RoomMessageText)

        try:
            while not stop_event.is_set():
                await client.sync(timeout=30000)
        except asyncio.CancelledError:
            pass
        finally:
            await client.close()

    async def send_message(
        self, channel_id: str, text: str, **kwargs: Any
    ) -> bool:
        if not self._client:
            return False
        try:
            await self._client.room_send(
                channel_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": text},
            )
            return True
        except Exception as exc:
            logger.error("Matrix send error: %s", exc)
            return False


class IRCAdapter(ChannelAdapter):
    """IRC adapter using raw asyncio sockets.

    Config: IRC_SERVER, IRC_PORT, IRC_NICK, IRC_CHANNELS
    """

    def __init__(
        self,
        server: str = "",
        port: int = 6667,
        nick: str = "Ravyn",
        channels: list[str] | None = None,
    ) -> None:
        self._server = server
        self._port = port
        self._nick = nick
        self._channels = channels or []
        self._writer: asyncio.StreamWriter | None = None

    @property
    def platform(self) -> str:
        return "irc"

    async def start(self, stop_event: asyncio.Event) -> None:
        if not self._server:
            logger.warning("IRC not configured — skipping")
            await stop_event.wait()
            return

        logger.info("IRC connecting to %s:%d as %s", self._server, self._port, self._nick)

        try:
            reader, writer = await asyncio.open_connection(self._server, self._port)
            self._writer = writer

            writer.write(f"NICK {self._nick}\r\n".encode())
            writer.write(f"USER {self._nick} 0 * :AetherRavyn\r\n".encode())
            await writer.drain()

            for channel in self._channels:
                writer.write(f"JOIN {channel}\r\n".encode())
            await writer.drain()

            while not stop_event.is_set():
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.startswith("PING"):
                    pong = decoded.replace("PING", "PONG", 1)
                    writer.write(f"{pong}\r\n".encode())
                    await writer.drain()
                elif "PRIVMSG" in decoded:
                    await self._handle_privmsg(decoded)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("IRC error: %s", exc)
        finally:
            if self._writer:
                self._writer.close()

    async def send_message(
        self, channel_id: str, text: str, **kwargs: Any
    ) -> bool:
        if not self._writer:
            return False
        try:
            for line in text.split("\n")[:10]:
                self._writer.write(f"PRIVMSG {channel_id} :{line}\r\n".encode())
            await self._writer.drain()
            return True
        except Exception:
            return False

    async def _handle_privmsg(self, line: str) -> None:
        """Parse IRC PRIVMSG and route to gateway."""
        try:
            prefix, _, rest = line.partition(" PRIVMSG ")
            channel, _, text = rest.partition(" :")
            nick = prefix.split("!")[0].lstrip(":")
            if nick and text:
                msg = GatewayMessage(
                    platform="irc",
                    channel_id=channel,
                    user_id=nick,
                    text=text,
                )
                await self.on_message(msg)
        except Exception:
            pass
