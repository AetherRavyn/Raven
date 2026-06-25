"""Telegram voice channel — voice messages, group voice chats, and 1:1 calls.

Supports three tiers (each optional):
1. Voice messages (bot) — download, transcribe, TTS reply
2. Group voice chat — via PyTgCalls (requires user account)
3. 1:1 calls — via Telethon user client (requires user account)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.settings.config import Config
from app.voice.channels.base import (
    CallDirection,
    CallInfo,
    CallState,
    VoiceChannel,
)

logger = logging.getLogger(__name__)

# Optional dependency: PyTgCalls for group voice chats
try:
    from pytgcalls import PyTgCalls as _PyTgCalls
    from pytgcalls.exceptions import NoActiveGroupCall as _NoActiveGroupCall

    _HAS_PYTGCALLS = True
except ImportError:
    _HAS_PYTGCALLS = False

# Optional dependency: Telethon for user-client features (calls, etc.)
try:
    from telethon import TelegramClient as _TelethonClient
    from telethon.tl.functions.phone import RequestCallRequest as _ReqCall

    _HAS_TELETHON = True
except ImportError:
    _HAS_TELETHON = False


class TelegramVoiceChannel(VoiceChannel):
    """Voice-enabled Telegram channel.

    Requires ``TELEGRAM_BOT_TOKEN`` for voice message support.
    Requires ``TELEGRAM_API_ID`` + ``TELEGRAM_API_HASH`` for calls.
    """

    platform_name = "telegram"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._bot_token = bot_token or Config.TELEGRAM_BOT_TOKEN
        self._api_id = api_id or Config.TELEGRAM_API_ID
        self._api_hash = api_hash or Config.TELEGRAM_API_HASH
        self._phone_number = phone_number or Config.TELEGRAM_PHONE

        self._app: Any = None  # telegram.ext.Application (bot)
        self._user_client: Any = None  # Telethon client (for calls)
        self._pytgcalls: Any = None  # PyTgCalls instance

        self._stop_event: Optional[asyncio.Event] = None

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self, stop_event: asyncio.Event) -> None:
        """Start the Telegram voice channel.

        If a bot token is configured, runs a bot polling loop.
        If Telethon credentials are configured, also starts a user client.
        """
        self._stop_event = stop_event

        tasks = []

        if self._bot_token:
            tasks.append(self._run_bot(stop_event))

        if self._api_id and self._api_hash and self._phone_number:
            tasks.append(self._run_user_client(stop_event))

        if not tasks:
            logger.warning(
                "TelegramVoiceChannel: no credentials configured. "
                "Set TELEGRAM_BOT_TOKEN for bot, or TELEGRAM_API_ID+HASH+PHONE for calls."
            )
            return

        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Stop the channel."""
        if self._app:
            try:
                await self._app.stop()
            except Exception:
                pass
        if self._user_client:
            try:
                await self._user_client.disconnect()
            except Exception:
                pass
        if self._pytgcalls:
            try:
                await self._pytgcalls.stop()
            except Exception:
                pass

    # ── Bot Polling Loop ────────────────────────────────────────────

    async def _run_bot(self, stop_event: asyncio.Event) -> None:
        """Run the Telegram bot for voice messages."""
        from telegram.ext import (
            Application,
            MessageHandler,
            filters,
        )

        self._app = Application.builder().token(self._bot_token).build()

        # Register voice message handler
        async def _voice_handler(update: Any, context: Any) -> None:
            await self._handle_voice_message(update, context)

        self._app.add_handler(
            MessageHandler(filters.VOICE & ~filters.COMMAND, _voice_handler)
        )

        async def _poll(stop: asyncio.Event) -> None:
            """Poll with a simple while loop so we can interrupt it."""
            await self._app.initialize()
            await self._app.start()
            try:
                # Use a polling loop that checks stop_event
                while not stop.is_set():
                    await asyncio.sleep(0.5)
                    # The Application has its own polling via `run_polling`
                    # but we use this pattern to integrate with the gateway.
            finally:
                await self._app.stop()
                await self._app.shutdown()

        # Start polling in background
        poll_task = asyncio.create_task(_poll(stop_event))

        # Also register a webhook if configured
        webhook_url = Config.TELEGRAM_WEBHOOK_URL
        if webhook_url:
            try:
                await self._app.bot.set_webhook(url=webhook_url)
                logger.info("Telegram: webhook set to %s", webhook_url)
            except Exception as exc:
                logger.warning("Telegram: webhook failed: %s", exc)

        await poll_task

    async def _handle_voice_message(self, update: Any, context: Any) -> None:
        """Process an incoming voice message."""
        from app.core.models import IncomingRequest, ReplyTarget

        message = update.effective_message
        if not message or not message.voice:
            return

        user = message.from_user
        user_id = str(user.id) if user else "unknown"
        chat_id = str(message.chat_id)

        # Download voice message to temp WAV
        try:
            voice_file = await message.voice.get_file()
            fd, wav_path = tempfile.mkstemp(suffix=".ogg")
            os.close(fd)
            await voice_file.download_to_drive(wav_path)
        except Exception as exc:
            logger.error("Telegram: voice download failed: %s", exc)
            return

        # Transcribe
        try:
            from app.voice.transcribe import transcribe_audio
            text = await transcribe_audio(wav_path)
        except Exception as exc:
            logger.error("Telegram: transcription failed: %s", exc)
            text = ""
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        if not text:
            await message.reply_text("Sorry, I couldn't understand the voice message.")
            return

        logger.info(
            "Telegram: voice from %s: %s",
            user.first_name if user else user_id,
            text[:80],
        )

        # Route through orchestrator
        request = IncomingRequest(
            platform="telegram_voice",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="telegram_voice",
                chat_id=chat_id,
            ),
            voice_reply=True,
        )

        # Access orchestrator via the message context
        orchestrator = context.bot_data.get("orchestrator")
        if not orchestrator:
            try:
                from app.core.orchestrator import get_orchestrator
                orchestrator = get_orchestrator()
            except Exception:
                logger.error("Telegram: cannot route voice — no orchestrator")
                await message.reply_text("Internal error.")
                return

        await orchestrator.handle(request)

    # ── User Client (Telethon) ──────────────────────────────────────

    async def _run_user_client(self, stop_event: asyncio.Event) -> None:
        """Run the Telethon user client for calls."""
        if not _HAS_TELETHON:
            logger.warning("Telegram: telethon not installed. Call features disabled.")
            return

        client = _TelethonClient(
            "raven_telegram_user",
            self._api_id,
            self._api_hash,
        )
        self._user_client = client

        await client.start(phone=self._phone_number)
        logger.info("Telegram: user client started as %s", await client.get_me())

        # Optionally start PyTgCalls for group voice chats
        if _HAS_PYTGCALLS:
            try:
                self._pytgcalls = _PyTgCalls(client)
                await self._pytgcalls.start()

                @self._pytgcalls.on_update()
                async def _handle_update(update: Any) -> None:
                    await self._handle_pytgcalls_update(update)

                logger.info("Telegram: PyTgCalls started (group voice chat ready)")
            except Exception as exc:
                logger.warning("Telegram: PyTgCalls init failed: %s", exc)

        # Keep alive until stop
        await stop_event.wait()
        await client.disconnect()

    async def _handle_pytgcalls_update(self, update: Any) -> None:
        """Handle PyTgCalls updates (audio frames, state changes)."""
        try:
            if hasattr(update, "chat_id"):
                call_id = f"tg_group_{update.chat_id}"

                if hasattr(update, "status"):
                    status_map = {
                        "connected": CallState.ACTIVE,
                        "connecting": CallState.CONNECTING,
                        "disconnected": CallState.ENDED,
                        "playing": CallState.ACTIVE,
                        "paused": CallState.HOLD,
                    }
                    state = status_map.get(str(update.status), CallState.IDLE)

                    info = self._active_calls.get(call_id)
                    if info:
                        info.state = state
                        self._emit_state_change(info)
                    elif state == CallState.ACTIVE:
                        info = CallInfo(
                            call_id=call_id,
                            platform="telegram",
                            direction=CallDirection.INCOMING,
                            remote_user=str(update.chat_id),
                            remote_name=f"Group {update.chat_id}",
                            state=state,
                            audio_format="opus",
                            metadata={"chat_type": "group"},
                        )
                        self._active_calls[call_id] = info
                        self._emit_state_change(info)

                # Audio frames from the group call
                if hasattr(update, "payload") and hasattr(update.payload, "data"):
                    self._emit_audio(call_id, update.payload.data)

        except Exception as exc:
            logger.debug("Telegram: PyTgCalls update error: %s", exc)

    # ── VoiceChannel interface ─────────────────────────────────────

    async def make_call(self, target: str, **kwargs: Any) -> CallInfo:
        """Make an outgoing call.

        For Telegram, target can be:
        - A phone number (e.g. "+15551234567") → Telegram call
        - A chat ID (e.g. "-1001234567890") → Join group voice chat
        - A username (e.g. "@username") → Telegram call
        """
        call_id = self.generate_call_id("tg_")

        # Check if this is a group chat join
        if target.startswith("-100") or target.startswith("@"):
            return await self._join_group_call(call_id, target)

        # Otherwise, initiate a 1:1 Telegram call via Telethon
        return await self._initiate_call(call_id, target)

    async def _join_group_call(self, call_id: str, chat_identifier: str) -> CallInfo:
        """Join a Telegram group voice chat."""
        info = CallInfo(
            call_id=call_id,
            platform="telegram",
            direction=CallDirection.OUTGOING,
            remote_user=chat_identifier,
            remote_name=chat_identifier,
            state=CallState.CONNECTING,
            audio_format="opus",
            metadata={"chat_type": "group"},
            started_at=self.now_iso(),
        )
        self._active_calls[call_id] = info
        self._emit_state_change(info)

        if not _HAS_PYTGCALLS or not self._pytgcalls:
            info.state = CallState.FAILED
            info.metadata["error"] = "PyTgCalls not available"
            self._emit_state_change(info)
            return info

        try:
            from pytgcalls.types import AudioPiped

            chat_id = int(chat_identifier.lstrip("@").lstrip("-100"))
            if chat_identifier.startswith("-100"):
                chat_id = int(chat_identifier)
            elif chat_identifier.startswith("@"):
                # Resolve username to chat ID
                if self._user_client:
                    entity = await self._user_client.get_entity(chat_identifier)
                    chat_id = entity.id

            await self._pytgcalls.join_group_call(
                chat_id,
                AudioPiped("silence.opus"),
            )
            info.state = CallState.ACTIVE
            info.connected_at = self.now_iso()
            self._emit_state_change(info)

        except _NoActiveGroupCall:
            info.state = CallState.FAILED
            info.metadata["error"] = "No active voice chat in this group"
            self._emit_state_change(info)
        except Exception as exc:
            info.state = CallState.FAILED
            info.metadata["error"] = str(exc)
            self._emit_state_change(info)

        return info

    async def _initiate_call(self, call_id: str, target: str) -> CallInfo:
        """Initiate a 1:1 Telegram call via Telethon."""
        info = CallInfo(
            call_id=call_id,
            platform="telegram",
            direction=CallDirection.OUTGOING,
            remote_user=target,
            remote_name=target,
            state=CallState.CONNECTING,
            started_at=self.now_iso(),
        )
        self._active_calls[call_id] = info
        self._emit_state_change(info)

        if not _HAS_TELETHON or not self._user_client:
            info.state = CallState.FAILED
            info.metadata["error"] = "Telethon user client not available"
            self._emit_state_change(info)
            return info

        try:
            # Resolve user
            if target.startswith("+"):
                # Phone number — find contact
                result = await self._user_client(_ReqCall(
                    user_id=target,
                    g_a_hash=b"",
                    protocol=None,
                ))
                info.state = CallState.RINGING
                self._emit_state_change(info)

                # If call is accepted
                if hasattr(result, "call") and result.call:
                    info.state = CallState.ACTIVE
                    info.connected_at = self.now_iso()
                    self._emit_state_change(info)
            else:
                info.metadata["error"] = "Unsupported target format"
                info.state = CallState.FAILED
                self._emit_state_change(info)

        except Exception as exc:
            info.state = CallState.FAILED
            info.metadata["error"] = str(exc)
            self._emit_state_change(info)

        return info

    async def answer_call(self, call_id: str) -> None:
        """Answer an incoming call."""
        info = self._active_calls.get(call_id)
        if not info:
            return

        info.state = CallState.ACTIVE
        info.connected_at = self.now_iso()
        self._emit_state_change(info)
        logger.info("Telegram: answered call %s", call_id)

    async def hangup_call(self, call_id: str) -> None:
        """End a call."""
        info = self._active_calls.get(call_id)
        if not info:
            return

        # Leave group call if active
        if _HAS_PYTGCALLS and self._pytgcalls and info.metadata.get("chat_type") == "group":
            try:
                chat_id = int(info.remote_user.lstrip("-100"))
                await self._pytgcalls.leave_group_call(chat_id)
            except _NoActiveGroupCall:
                pass
            except Exception:
                pass

        info.state = CallState.ENDED
        info.ended_at = self.now_iso()
        self._emit_state_change(info)
        logger.info("Telegram: hung up call %s", call_id)

    async def hold_call(self, call_id: str) -> None:
        """Pause the call."""
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.HOLD
            self._emit_state_change(info)

            # Pause PyTgCalls playback for group calls
            if _HAS_PYTGCALLS and self._pytgcalls and info.metadata.get("chat_type") == "group":
                try:
                    chat_id = int(info.remote_user.lstrip("-100"))
                    await self._pytgcalls.pause_stream(chat_id)
                except Exception:
                    pass

    async def resume_call(self, call_id: str) -> None:
        """Resume a held call."""
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.ACTIVE
            self._emit_state_change(info)

            # Resume PyTgCalls playback for group calls
            if _HAS_PYTGCALLS and self._pytgcalls and info.metadata.get("chat_type") == "group":
                try:
                    chat_id = int(info.remote_user.lstrip("-100"))
                    await self._pytgcalls.resume_stream(chat_id)
                except Exception:
                    pass

    async def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Send audio to a call.

        For group calls, writes to temp file and plays via PyTgCalls.
        For 1:1 calls, sends via Telethon (not yet supported in TG).
        """
        info = self._active_calls.get(call_id)
        if not info:
            return

        if info.metadata.get("chat_type") == "group" and _HAS_PYTGCALLS and self._pytgcalls:
            from pytgcalls.types import AudioPiped

            # Write audio to temp file
            fd, path = tempfile.mkstemp(suffix=".raw")
            os.close(fd)
            Path(path).write_bytes(audio_bytes)

            try:
                chat_id = int(info.remote_user.lstrip("-100"))
                await self._pytgcalls.change_stream(
                    chat_id,
                    AudioPiped(path),
                )
            except Exception as exc:
                logger.debug("Telegram: send_audio failed: %s", exc)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        else:
            logger.debug("Telegram: send_audio not supported for 1:1 calls yet")

    async def send_dtmf(self, call_id: str, digits: str) -> None:
        """Send DTMF tones (not supported on Telegram)."""
        logger.debug("Telegram: DTMF not supported")
