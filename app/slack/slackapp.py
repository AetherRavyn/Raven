"""app/slack/slackapp.py — SARAS Slack bot connector.

Uses Slack Bolt (AsyncApp) + Socket Mode so no public HTTP endpoint is needed.

Required env vars:
  SLACK_BOT_TOKEN  xoxb-...   Bot User OAuth Token
  SLACK_APP_TOKEN  xapp-...   App-Level Token (with connections:write scope)

Required bot token scopes (set in api.slack.com):
  channels:history, groups:history, im:history, mpim:history
  channels:read
  chat:write
  files:write
  app_mentions:read
  reactions:write   (optional, for typing indicator)

Enable in your Slack App settings:
  • Socket Mode → ON
  • Event Subscriptions → ON, subscribe to bot events:
      message.channels  message.groups  message.im  message.mpim
      app_mention

Usage pattern mirrors DiscordBot exactly:
  bot = SlackBot(bot_token, app_token, orchestrator)
  bot.register_output_sender(botsignal)
  await bot.start_bot()          # runs until cancelled
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload
from app.core.render import to_slack_mrkdwn

logger = logging.getLogger(__name__)

# Slack mrkdwn text limit per section block; above this we send a file.
_SLACK_TEXT_LIMIT = 3000
# Slack chat.postMessage top-level text limit (used as notification fallback).
_SLACK_MSG_LIMIT = 40_000


class SlackBot:
    """Async Slack bot that mirrors the DiscordBot API.

    Receives messages from Slack via Socket Mode, dispatches them to the
    shared MessageOrchestrator, and can send replies back via BotSignal.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        orchestrator,  # MessageOrchestrator or duck-typed equivalent
    ) -> None:
        self._app_token = app_token
        self._orchestrator = orchestrator
        self._bot_user_id: str | None = None

        # AsyncApp validates the bot_token on first API call, not at init.
        self._app = AsyncApp(
            token=bot_token,
            # Disable the default Bolt logger noise; we handle logging ourselves.
            logger=logging.getLogger("slack_bolt"),
        )
        self._client = self._app.client

        # Register event listeners
        self._app.event("message")(self._handle_message_event)
        self._app.event("app_mention")(self._handle_app_mention_event)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def start_bot(self) -> None:
        """Connect via Socket Mode and run until cancelled."""
        # Resolve our own bot user ID so we can skip self-messages.
        try:
            resp = await self._client.auth_test()
            self._bot_user_id = resp.get("user_id")
            logger.info(
                "Slack bot authenticated as %s (%s)",
                resp.get("user"),
                self._bot_user_id,
            )
        except Exception as exc:
            logger.warning("Slack auth_test failed: %s", exc)

        handler = AsyncSocketModeHandler(self._app, self._app_token)
        await handler.start_async()

    # ──────────────────────────────────────────────────────────────────────────
    # Incoming message handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _dispatch(self, event: dict) -> None:
        """Build an IncomingRequest and hand it to the orchestrator."""
        user_id = event.get("user") or ""
        channel = event.get("channel") or ""
        ts = event.get("ts") or ""  # message timestamp — used as reply-in-thread anchor
        text = (event.get("text") or "").strip()

        # Skip bot messages early
        if event.get("bot_id"):
            return
        if self._bot_user_id and user_id == self._bot_user_id:
            return

        # If there are audio file attachments, transcribe first
        files = event.get("files") or []
        for f in files:
            mimetype = f.get("mimetype", "")
            if mimetype.startswith("audio"):
                url_private = f.get("url_private_download") or f.get("url_private")
                if url_private:
                    transcribed = await self._transcribe_slack_audio(url_private)
                    if transcribed:
                        text = transcribed
                        break  # use the first successfully transcribed file

        if not text:
            return

        # Strip the @mention prefix that Slack injects in app_mention events
        # e.g. "<@U0123ABC> hello" → "hello"
        if self._bot_user_id:
            mention = f"<@{self._bot_user_id}>"
            text = text.replace(mention, "").strip()
        if not text:
            return

        logger.info(
            "Slack incoming  user=%s  channel=%s  text=%r",
            user_id,
            channel,
            text[:120],
        )

        request = IncomingRequest(
            platform="slack",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="slack",
                chat_id=channel,
                reply_to_id=ts,  # used as thread_ts to keep replies threaded
            ),
            conversation_id=f"{channel}:{ts}" if ts else channel,
        )
        await self._orchestrator.handle(request)

    async def _transcribe_slack_audio(self, url_private: str) -> str:
        """Download a Slack private audio URL and transcribe it."""
        from app.voice.transcribe import transcribe_audio

        headers = {"Authorization": f"Bearer {self._app.client.token}"}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url_private, headers=headers, follow_redirects=True
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to download Slack audio: %s", exc)
            return ""

        fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        try:
            with open(tmp_path, "wb") as fh:
                fh.write(resp.content)
            return await transcribe_audio(tmp_path)
        finally:
            os.unlink(tmp_path)

    async def _handle_message_event(self, event: dict) -> None:
        """Handle Slack ``message`` events (all channel types)."""
        # Ignore message subtypes (edits, deletions, bot_messages, etc.)
        if event.get("subtype"):
            return
        await self._dispatch(event)

    async def _handle_app_mention_event(self, event: dict) -> None:
        """Handle ``app_mention`` events (bot tagged in a channel)."""
        await self._dispatch(event)

    # ──────────────────────────────────────────────────────────────────────────
    # Outgoing message sender
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Send a reply back to the Slack channel/thread that sent the message."""
        channel = target.chat_id
        # Use thread_ts to reply in-thread; keeps channels clean.
        thread_ts = target.reply_to_id or None

        temp_file_path: str | None = None

        try:
            # ── File payloads ────────────────────────────────────────────────
            if payload.file_path or payload.audio_path or payload.video_path:
                file_path = (
                    payload.file_path or payload.audio_path or payload.video_path
                )
                caption = to_slack_mrkdwn(payload.caption or payload.text or "")[
                    :_SLACK_TEXT_LIMIT
                ]
                await self._client.files_upload_v2(
                    channel=channel,
                    file=file_path,
                    initial_comment=caption or None,
                    thread_ts=thread_ts,
                )
                return

            content_text = payload.text or payload.caption or ""

            # ── Long text → upload as a snippet ─────────────────────────────
            if len(content_text) > _SLACK_TEXT_LIMIT and not payload.animation_url:
                fd, temp_file_path = tempfile.mkstemp(
                    prefix="saras_output_", suffix=".txt", text=True
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(content_text)
                await self._client.files_upload_v2(
                    channel=channel,
                    file=temp_file_path,
                    filename="saras_response.txt",
                    title="SARAS Response",
                    initial_comment="Output exceeded message limit — sent as file.",
                    thread_ts=thread_ts,
                )
                return

            # ── Regular text ─────────────────────────────────────────────────
            mrkdwn_text = to_slack_mrkdwn(content_text)
            if payload.animation_url:
                mrkdwn_text = f"{mrkdwn_text}\n{payload.animation_url}".strip()

            if not mrkdwn_text:
                return

            await self._client.chat_postMessage(
                channel=channel,
                text=mrkdwn_text,  # top-level text = notification fallback
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": mrkdwn_text[:_SLACK_TEXT_LIMIT],
                        },
                    }
                ],
                thread_ts=thread_ts,
                mrkdwn=True,
            )

        except Exception as exc:
            logger.error("Slack send_to_target failed channel=%s: %s", channel, exc)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def register_output_sender(self, botsignal: BotSignal) -> None:
        """Register this bot's sender with the shared BotSignal hub."""
        botsignal.register_sender("slack", self.send_to_target)
