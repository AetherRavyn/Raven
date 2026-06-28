"""iMessage channel — send/receive via AppleScript on macOS.

Architecture:
    - Listens for new messages by polling the iMessage chat.db (macOS only)
    - Sends messages via AppleScript (osascript)
    - Registers sender with BotSignal
    - Stub: full implementation requires macOS + iMessage account

Usage:
    async with IMessageApp(botsignal, orchestrator) as app:
        await app.start_bot()

Requires:
    - macOS with iMessage configured
    - Full disk access for the SQLite chat.db
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IMessageApp:
    """iMessage integration (macOS only)."""

    def __init__(
        self,
        botsignal: Any,
        orchestrator: Any,
        poll_interval: float = 15.0,
    ) -> None:
        self._botsignal = botsignal
        self._orchestrator = orchestrator
        self._poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

        # Path to iMessage chat.db (macOS)
        self._db_path = Path.home() / "Library/Messages/chat.db"
        self._last_message_id: int = 0

    async def send_to_target(self, target: Any, payload: Any) -> bool:
        """Send an iMessage via AppleScript."""
        text = payload.text if hasattr(payload, "text") else str(payload)
        phone = target.chat_id if hasattr(target, "chat_id") else str(target)

        script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{phone}" of targetService
            send "{text}" to targetBuddy
        end tell
        '''

        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            logger.warning("osascript not found — not macOS")
            return False
        except Exception as e:
            logger.error("iMessage send error: %s", e)
            return False

    async def _poll(self) -> None:
        """Poll for new iMessages."""
        if not self._db_path.exists():
            return

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ROWID, text, handle_id, date
                FROM message
                WHERE ROWID > ? AND is_from_me = 0
                ORDER BY ROWID ASC
                LIMIT 5
                """,
                (self._last_message_id,),
            )
            rows = cur.fetchall()
            conn.close()

            for row in rows:
                self._last_message_id = max(self._last_message_id, row["ROWID"])
                text = row["text"]
                if not text:
                    continue
                from app.core.models import IncomingRequest, ReplyTarget

                request = IncomingRequest(
                    platform="imessage",
                    user_id=str(row["handle_id"]),
                    text=text,
                    reply_target=ReplyTarget(
                        platform="imessage",
                        chat_id=str(row["handle_id"]),
                    ),
                    conversation_id=str(row["handle_id"]),
                )
                await self._orchestrator.handle(request)
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug("iMessage poll error (expected on non-macOS): %s", e)

    async def start_bot(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop_bot(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        """Main poll loop."""
        while self._running:
            await self._poll()
            await asyncio.sleep(self._poll_interval)

    @classmethod
    def bind_runtime(cls, botsignal: Any, orchestrator: Any) -> "IMessageApp":
        """Create and register this channel with BotSignal."""
        app = cls(botsignal, orchestrator)
        botsignal.register_sender("imessage", app.send_to_target)
        return app

    async def __aenter__(self) -> "IMessageApp":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop_bot()
