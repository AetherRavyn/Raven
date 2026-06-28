"""LINE channel — send/receive via LINE Messaging API.

Architecture:
    - Uses flask to receive webhooks from LINE Platform
    - Uses line-bot-sdk to send messages via Messaging API
    - Registers sender with BotSignal

Usage:
    async with LineApp(botsignal, orchestrator) as app:
        await app.start_bot()

Requires:
    - line-bot-sdk
    - LINE_CHANNEL_ACCESS_TOKEN env var
    - LINE_CHANNEL_SECRET env var
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LineApp:
    """LINE Messaging API integration."""

    def __init__(
        self,
        botsignal: Any,
        orchestrator: Any,
    ) -> None:
        self._botsignal = botsignal
        self._orchestrator = orchestrator
        self._running = False
        self._task: asyncio.Task | None = None
        self._line_bot_api = None
        self._handler = None
        self._webhook_task: asyncio.Task | None = None

    async def send_to_target(self, target: Any, payload: Any) -> bool:
        """Send a LINE message via Messaging API."""
        text = payload.text if hasattr(payload, "text") else str(payload)
        user_id = target.chat_id if hasattr(target, "chat_id") else str(target)

        if self._line_bot_api is None:
            return False

        try:
            from linebot.models import TextSendMessage

            self._line_bot_api.push_message(user_id, TextSendMessage(text=text))
            return True
        except Exception as e:
            logger.error("LINE send error: %s", e)
            return False

    async def start_bot(self) -> None:
        if self._running:
            return

        access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        channel_secret = os.environ.get("LINE_CHANNEL_SECRET")

        if not access_token or not channel_secret:
            logger.warning("LINE_CHANNEL_ACCESS_TOKEN/SECRET not set — LINE unavailable")
            return

        try:
            from linebot import LineBotApi, WebhookHandler

            self._line_bot_api = LineBotApi(access_token)
            self._handler = WebhookHandler(channel_secret)

            @self._handler.add("message")
            def handle_message(event):
                from linebot.models import TextMessage

                if not isinstance(event.message, TextMessage):
                    return

                text = event.message.text
                user_id = event.source.user_id
                conversation_id = event.source.group_id or event.source.room_id or user_id

                asyncio.create_task(
                    self._process_message(text, user_id, conversation_id),
                )

            self._running = True
            # LINE requires a webhook endpoint running on a public URL
            logger.info("LINE webhook handler registered (start webhook server separately)")
        except ImportError:
            logger.warning("line-bot-sdk not installed — LINE channel unavailable")
        except Exception as e:
            logger.error("LINE init error: %s", e)

    async def _process_message(
        self,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        from app.core.models import IncomingRequest, ReplyTarget

        request = IncomingRequest(
            platform="line",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="line",
                chat_id=user_id,
            ),
            conversation_id=conversation_id,
        )
        await self._orchestrator.handle(request)

    async def handle_webhook(self, body: str, signature: str) -> bool:
        """Process an incoming LINE webhook request.

        Called by the web framework on POST /webhook/line.
        """
        if self._handler is None:
            return False
        try:
            self._handler.handle(body, signature)
            return True
        except Exception as e:
            logger.error("LINE webhook error: %s", e)
            return False

    async def stop_bot(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @classmethod
    def bind_runtime(cls, botsignal: Any, orchestrator: Any) -> "LineApp":
        app = cls(botsignal, orchestrator)
        botsignal.register_sender("line", app.send_to_target)
        return app

    async def __aenter__(self) -> "LineApp":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop_bot()
