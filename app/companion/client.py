"""Reference Python companion client.

This is the source-of-truth implementation that:

  * drives the protocol defined in :mod:`app.companion.types`;
  * uses :class:`~app.companion.cache.OfflineCache` to buffer events
    and queue outgoing actions;
  * uses :class:`~app.companion.status.StatusCollector` for the
    Live Status tile;
  * uses :class:`~app.companion.notifications.NotificationDispatcher`
    for OS notifications;
  * uses :class:`~app.companion.palette.CommandPalette` for ⌘K
    routing.

The client is intentionally transport-agnostic — it accepts any
async callable that takes a JSON-ready dict and returns a JSON-ready
dict (or None for a dropped frame).  Production binds that callable
to a WebSocket; tests bind it to an in-memory pipe.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.companion.cache import OfflineCache
from app.companion.notifications import (
    NotificationDispatcher,
    NotificationPayload,
)
from app.companion.palette import CommandPalette, IntentEntry, Suggestion
from app.companion.status import StatusCollector, StatusSnapshot
from app.companion.types import (
    PROTOCOL_VERSION,
    Command,
    Event,
    Hello,
    Ping,
    Response,
    Status,
    Subscribe,
    Welcome,
    encode,
    parse_frame,
)

logger = logging.getLogger(__name__)


# A ``Transport`` is an async callable: input dict, output dict (or
# None if the frame was dropped / connection lost).  The client
# doesn't care whether the transport is a WebSocket, a pipe, or a
# recording in a test.
Transport = Callable[[dict[str, Any]], Awaitable[Optional[dict[str, Any]]]]


@dataclass(slots=True)
class ClientConfig:
    """Knobs for the reference client."""

    client_name: str = "raven-companion"
    platform: str = "python"
    capabilities: list[str] = field(
        default_factory=lambda: ["status", "command_palette", "offline_cache"]
    )
    auth_token: str = ""
    subscribed_channels: list[str] = field(
        default_factory=lambda: ["alerts", "briefing", "anomalies", "intents"]
    )
    ping_interval_s: float = 30.0
    cache_ttl_s: int = 24 * 60 * 60


class CompanionClient:
    """High-level companion client — wraps the transport."""

    def __init__(
        self,
        *,
        config: ClientConfig | None = None,
        transport: Transport | None = None,
        cache: OfflineCache | None = None,
        status: StatusCollector | None = None,
        palette: CommandPalette | None = None,
        notifications: NotificationDispatcher | None = None,
    ) -> None:
        self.config = config or ClientConfig()
        self._transport = transport
        self._cache = cache or OfflineCache(ttl_s=self.config.cache_ttl_s)
        self._status = status or StatusCollector()
        self._palette = palette or CommandPalette()
        self._notifications = notifications or NotificationDispatcher()
        self._connected = False
        self._welcome: Optional[Welcome] = None
        self._lock = asyncio.Lock()
        self._pending_responses: dict[str, asyncio.Future[Response]] = {}

    # ── transport ────────────────────────────────────────────────

    def bind_transport(self, transport: Transport) -> None:
        """Swap the transport (useful for tests reconnecting)."""
        self._transport = transport

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def welcome(self) -> Optional[Welcome]:
        return self._welcome

    @property
    def cache(self) -> OfflineCache:
        return self._cache

    @property
    def status_collector(self) -> StatusCollector:
        return self._status

    @property
    def palette(self) -> CommandPalette:
        return self._palette

    @property
    def notifications(self) -> NotificationDispatcher:
        return self._notifications

    # ── lifecycle ────────────────────────────────────────────────

    async def connect(self) -> Welcome:
        """Handshake: send Hello, receive Welcome."""
        if self._transport is None:
            raise RuntimeError("no transport bound")
        async with self._lock:
            hello = Hello(
                client=self.config.client_name,
                platform=self.config.platform,
                build=PROTOCOL_VERSION,
                capabilities=list(self.config.capabilities),
                auth_token=self.config.auth_token,
            )
            reply_raw = await self._transport(encode(hello))
            if reply_raw is None:
                raise ConnectionError("transport dropped Hello frame")
            reply = parse_frame(reply_raw)
            if not isinstance(reply, Welcome):
                raise ConnectionError(
                    f"expected Welcome, got {type(reply).__name__}"
                )
            self._welcome = reply
            self._connected = True
            # Subscribe to default channels.
            sub = Subscribe(channels=list(self.config.subscribed_channels))
            await self._transport(encode(sub))
            # Drain any queued outgoing actions.
            await self._drain_outgoing()
            return reply

    async def disconnect(self) -> None:
        async with self._lock:
            self._connected = False
            self._welcome = None

    async def ping(self) -> int:
        """Round-trip a Ping.  Returns the round-trip in ms."""
        if self._transport is None:
            raise RuntimeError("no transport bound")
        ts = int(time.time() * 1000)
        reply = await self._transport(encode(Ping(ts=ts)))
        if reply is None:
            raise ConnectionError("transport dropped Ping")
        from app.companion.types import Pong
        pong = parse_frame(reply)
        if not isinstance(pong, Pong):
            raise ConnectionError("expected Pong")
        return pong.server_ts - ts

    async def send_command(
        self,
        intent: str,
        args: dict[str, Any] | None = None,
        *,
        wait: bool = True,
    ) -> Response:
        """Issue a command.  If ``wait`` is True, block for the Response."""
        cmd = Command(intent=intent, args=args or {})
        frame = encode(cmd)
        if not self._connected or self._transport is None:
            # Offline — queue and return a synthetic "queued" response.
            self._cache.queue_action(cmd.id, intent, args or {})
            self._status.record_action(f"queued:{intent}")
            return Response(id=cmd.id, ok=True, result={"queued": True})
        if not wait:
            await self._transport(frame)
            self._status.record_action(intent)
            return Response(id=cmd.id, ok=True, result={"accepted": True})
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Response] = loop.create_future()
        self._pending_responses[cmd.id] = fut
        try:
            reply = await self._transport(frame)
            if reply is None:
                # Lost connection mid-flight → queue + mark dropped.
                self._cache.queue_action(cmd.id, intent, args or {})
                return Response(id=cmd.id, ok=False, error="transport_dropped")
            resp = parse_frame(reply)
            if not isinstance(resp, Response):
                return Response(id=cmd.id, ok=False, error="bad_reply")
            self._status.record_action(intent)
            return resp
        finally:
            self._pending_responses.pop(cmd.id, None)

    async def handle_event(self, raw: dict[str, Any]) -> Optional[Event]:
        """Receive a server-pushed Event frame and fan it out."""
        try:
            event = parse_frame(raw)
        except ValueError as e:
            logger.warning("companion: dropped malformed event: %s", e)
            return None
        if not isinstance(event, Event):
            logger.debug("companion: ignoring non-event frame %s", type(event).__name__)
            return None
        # Buffer for offline replay.
        self._cache.buffer_event(
            event.id, event.channel, event.payload, priority=event.priority
        )
        # Fan out: notifications on high-priority channels.
        if event.priority == "high" or event.channel in {"alerts", "briefing", "anomalies"}:
            self._notifications.notify_event({
                "id": event.id,
                "channel": event.channel,
                "priority": event.priority,
                "payload": event.payload,
            })
        # Update the intents index if the server pushed one.
        if event.channel == "intents" and isinstance(event.payload, dict):
            intents = event.payload.get("intents")
            if isinstance(intents, list):
                self._palette.set_intents(
                    [IntentEntry(**i) for i in intents if isinstance(i, dict)]
                )
        return event

    async def handle_response(self, raw: dict[str, Any]) -> Optional[Response]:
        """Resolve a pending command's future."""
        try:
            resp = parse_frame(raw)
        except ValueError as e:
            logger.warning("companion: dropped malformed response: %s", e)
            return None
        if isinstance(resp, Response):
            fut = self._pending_responses.pop(resp.id, None)
            if fut is not None and not fut.done():
                fut.set_result(resp)
        return resp if isinstance(resp, Response) else None

    async def fetch_status(self) -> StatusSnapshot:
        """Return a freshly-sampled Live Status tile."""
        return self._status.sample()

    def suggest(self, query: str, limit: int = 5) -> list[Suggestion]:
        return self._palette.suggest(query, limit=limit)

    # ── outgoing queue ───────────────────────────────────────────

    async def _drain_outgoing(self) -> int:
        """Try to send every queued action.  Returns number sent."""
        if self._transport is None or not self._connected:
            return 0
        sent = 0
        for action in self._cache.pending_actions():
            cmd = Command(
                id=action["id"],
                intent=action["intent"],
                args=action["args"],
            )
            reply = await self._transport(encode(cmd))
            if reply is None:
                self._cache.mark_action_sent(action["id"], error="transport_dropped")
                break
            self._cache.mark_action_sent(action["id"])
            sent += 1
        return sent


__all__ = ["CompanionClient", "ClientConfig", "Transport"]