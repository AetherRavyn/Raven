"""Matrix channel adapter — Bridges AetherRavyn to Matrix via matrix-nio.

Requires the `matrix-nio` package:
    uv pip install matrix-nio

Usage:
    export MATRIX_HOMESERVER=https://matrix.org
    export MATRIX_USER=@ravyn:matrix.org
    export MATRIX_PASSWORD=your_password
    # OR
    export MATRIX_ACCESS_TOKEN=your_token
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.core.models import IncomingRequest, ReplyTarget

logger = logging.getLogger(__name__)


class MatrixConfig:
    """Matrix adapter configuration."""
    def __init__(self) -> None:
        self.homeserver: str = os.getenv("MATRIX_HOMESERVER", "https://matrix.org")
        self.user_id: str = os.getenv("MATRIX_USER", "")
        self.password: str = os.getenv("MATRIX_PASSWORD", "")
        self.access_token: str = os.getenv("MATRIX_ACCESS_TOKEN", "")
        self.store_path: str = os.getenv("MATRIX_STORE_PATH", "workspace/matrix_store")
        self.enabled: bool = bool(self.user_id and (self.password or self.access_token))


class MatrixChannel:
    """Receive and send messages via Matrix using matrix-nio.

    Supports:
    - End-to-end encrypted rooms (when olm is available)
    - Text messages, formatted messages (HTML)
    - Room invites (auto-join)
    """

    def __init__(self, orchestrator: Any, config: MatrixConfig | None = None) -> None:
        self._orchestrator = orchestrator
        self._config = config or MatrixConfig()
        self._client: Any = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def start(self) -> None:
        """Connect to Matrix and start syncing."""
        if not self.enabled:
            logger.info("Matrix channel disabled (MATRIX_USER not set)")
            return

        try:
            from nio import AsyncClient, LoginResponse, RoomMessageText, InviteMemberEvent
        except ImportError:
            logger.error(
                "matrix-nio not installed. Run: uv pip install matrix-nio"
            )
            return

        logger.info("Starting Matrix channel as %s", self._config.user_id)

        self._client = AsyncClient(
            self._config.homeserver,
            self._config.user_id,
            store_path=self._config.store_path,
        )

        # Login
        if self._config.access_token:
            self._client.access_token = self._config.access_token
            self._client.user_id = self._config.user_id
        else:
            response = await self._client.login(self._config.password)
            if not isinstance(response, LoginResponse):
                logger.error("Matrix login failed: %s", response)
                return
            logger.info("Matrix login successful")

        # Register callbacks
        self._client.add_event_callback(self._on_message, RoomMessageText)
        self._client.add_event_callback(self._on_invite, InviteMemberEvent)

        # Start syncing
        self._running = True
        try:
            await self._client.sync_forever(timeout=30000, full_state=True)
        except asyncio.CancelledError:
            pass
        finally:
            await self._client.close()

    async def stop(self) -> None:
        """Stop the Matrix channel."""
        self._running = False
        if self._client:
            await self._client.close()
        logger.info("Matrix channel stopped")

    async def _on_message(self, room: Any, event: Any) -> None:
        """Handle incoming room messages."""
        # Ignore our own messages
        if event.sender == self._config.user_id:
            return

        body = event.body.strip()
        if not body:
            return

        logger.info(
            "Matrix message in %s from %s: %s",
            room.room_id, event.sender, body[:50],
        )

        reply_target = ReplyTarget(platform="matrix", chat_id=room.room_id)
        incoming = IncomingRequest(
            platform="matrix",
            user_id=event.sender,
            text=body,
            reply_target=reply_target,
            conversation_id=room.room_id,
        )

        asyncio.create_task(
            self._orchestrator.handle(incoming),
            name=f"matrix-{event.sender}",
        )

    async def _on_invite(self, room: Any, event: Any) -> None:
        """Auto-join rooms we're invited to."""
        if event.membership == "invite" and event.state_key == self._config.user_id:
            logger.info("Auto-joining Matrix room: %s", room.room_id)
            await self._client.join(room.room_id)

    async def send_message(
        self, room_id: str, text: str, html: str | None = None
    ) -> bool:
        """Send a message to a Matrix room."""
        if not self._client:
            logger.warning("Matrix client not connected")
            return False

        try:
            from nio import RoomSendResponse

            content: dict[str, Any] = {
                "msgtype": "m.text",
                "body": text,
            }
            if html:
                content["format"] = "org.matrix.custom.html"
                content["formatted_body"] = html

            response = await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
            if isinstance(response, RoomSendResponse):
                return True
            logger.error("Matrix send error: %s", response)
            return False
        except Exception as exc:
            logger.error("Matrix send failed: %s", exc)
            return False
