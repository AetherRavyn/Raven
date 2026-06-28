"""WeChat channel — send/receive via itchat (Web protocol).

Architecture:
    - Uses itchat to authenticate via QR code
    - Registers message handlers for text messages
    - Registers sender with BotSignal

Usage:
    async with WeChatApp(botsignal, orchestrator) as app:
        await app.start_bot()

Requires:
    - itchat
    - QR code display (terminal or GUI) for login
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class WeChatApp:
    """WeChat integration via itchat."""

    def __init__(
        self,
        botsignal: Any,
        orchestrator: Any,
    ) -> None:
        self._botsignal = botsignal
        self._orchestrator = orchestrator
        self._running = False
        self._task: asyncio.Task | None = None
        self._itchat = None

    async def send_to_target(self, target: Any, payload: Any) -> bool:
        """Send a WeChat message."""
        text = payload.text if hasattr(payload, "text") else str(payload)
        user_id = target.chat_id if hasattr(target, "chat_id") else str(target)

        if self._itchat is None:
            return False

        try:
            self._itchat.send(text, toUserName=user_id)
            return True
        except Exception as e:
            logger.error("WeChat send error: %s", e)
            return False

    async def start_bot(self) -> None:
        if self._running:
            return

        try:
            import itchat

            self._itchat = itchat

            # Register text handler
            @itchat.msg_register("Text")
            def handle_text(msg):
                text = msg["Text"]
                user_id = msg["FromUserName"]
                conversation_id = msg.get("FromUserName", user_id)

                # Schedule async handling in the event loop
                asyncio.create_task(self._handle_message(text, user_id, conversation_id))

            # Start itchat in a thread (it's blocking)
            self._running = True
            self._task = asyncio.create_task(self._run_itchat())
        except ImportError:
            logger.warning("itchat not installed — WeChat channel unavailable")
        except Exception as e:
            logger.error("WeChat init error: %s", e)

    async def _handle_message(
        self,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        from app.core.models import IncomingRequest, ReplyTarget

        request = IncomingRequest(
            platform="wechat",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="wechat",
                chat_id=user_id,
            ),
            conversation_id=conversation_id,
        )
        await self._orchestrator.handle(request)

    async def _run_itchat(self) -> None:
        """Run itchat in a thread-safe manner."""
        if self._itchat is None:
            return
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._itchat.auto_login, True)
            await loop.run_in_executor(None, self._itchat.run)
        except Exception as e:
            logger.error("WeChat run error: %s", e)

    async def stop_bot(self) -> None:
        self._running = False
        if self._itchat:
            try:
                self._itchat.logout()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @classmethod
    def bind_runtime(cls, botsignal: Any, orchestrator: Any) -> "WeChatApp":
        app = cls(botsignal, orchestrator)
        botsignal.register_sender("wechat", app.send_to_target)
        return app

    async def __aenter__(self) -> "WeChatApp":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop_bot()
