"""WhatsApp voice channel — voice messages (send/receive) via Baileys bridge.

WhatsApp Business API does not support live 1:1 calls, but we can:
1. Receive voice messages → transcribe → process via orchestrator
2. Send voice messages (TTS) → encode as Opus → send via bridge
3. Future: WhatsApp calling via unofficial bridges
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

from app.voice.channels.base import (
    CallDirection,
    CallInfo,
    CallState,
    VoiceChannel,
)

logger = logging.getLogger(__name__)


class WhatsAppVoiceChannel(VoiceChannel):
    """Voice-enabled WhatsApp channel.

    Relies on the Baileys HTTP bridge for message transport.
    Supports voice message send/receive. Live calls are not supported
    by WhatsApp Business API.

    Config:
        WHATSAPP_BRIDGE_URL (default: http://localhost:3001)
        WHATSAPP_PHONE_ID / WHATSAPP_WHAPI_TOKEN (for Whapi.Cloud)
    """

    platform_name = "whatsapp"

    def __init__(
        self,
        bridge_url: Optional[str] = None,
        whapi_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._bridge_url = (
            bridge_url
            or os.environ.get("WHATSAPP_BRIDGE_URL")
            or "http://localhost:3001"
        )
        self._whapi_token = whapi_token or os.environ.get("WHATSAPP_WHAPI_TOKEN", "")
        self._phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_ID", "")

        self._http_client: Optional[httpx.AsyncClient] = None
        self._server: Any = None  # FastAPI server for webhook

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self, stop_event: asyncio.Event) -> None:
        """Start the WhatsApp voice channel.

        Starts a webhook server to receive incoming voice messages.
        Uses either the Baileys bridge or Whapi.Cloud.
        """
        self._http_client = httpx.AsyncClient(timeout=30.0)

        if self._bridge_url and not self._whapi_token:
            await self._run_baileys_bridge(stop_event)
        elif self._whapi_token:
            await self._run_whapi_webhook(stop_event)
        else:
            logger.warning(
                "WhatsAppVoiceChannel: no credentials. "
                "Set WHATSAPP_BRIDGE_URL or WHATSAPP_WHAPI_TOKEN."
            )

    async def stop(self) -> None:
        """Stop the channel."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # ── Baileys Bridge ─────────────────────────────────────────────

    async def _run_baileys_bridge(self, stop_event: asyncio.Event) -> None:
        """Poll or listen via the Baileys bridge."""
        # Test connectivity
        try:
            r = await self._http_client.get(f"{self._bridge_url}/health", timeout=5)
            if r.status_code != 200:
                logger.warning("WhatsApp Baileys bridge not healthy")
        except httpx.ConnectError:
            logger.warning("WhatsApp Baileys bridge unreachable at %s", self._bridge_url)
            return

        await stop_event.wait()

    async def _run_whapi_webhook(self, stop_event: asyncio.Event) -> None:
        """Start a webhook server for Whapi.Cloud incoming messages."""
        from aiohttp import web

        app = web.Application()

        async def webhook_handler(request: web.Request) -> web.Response:
            try:
                data = await request.json()
                asyncio.create_task(self._handle_whapi_message(data))
            except Exception as exc:
                logger.debug("WhatsApp webhook error: %s", exc)
            return web.Response(status=200)

        app.router.add_post("/webhook/whatsapp", webhook_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 8082)
        await site.start()
        logger.info("WhatsApp: webhook listening on :8082/webhook/whatsapp")

        await stop_event.wait()
        await runner.cleanup()

    async def _handle_whapi_message(self, data: dict[str, Any]) -> None:
        """Handle an incoming Whapi.Cloud message."""
        from app.core.models import IncomingRequest, ReplyTarget

        try:
            msg = data.get("message", {})
            if msg.get("type") != "voice":
                return

            # Extract voice info
            voice = msg.get("voice", {})
            media_id = voice.get("id")
            from_number = msg.get("from", "unknown")
            chat_id = from_number

            if not media_id:
                return

            # Download voice message
            audio_bytes = await self._whapi_download(media_id)

            # Transcribe
            from app.voice.transcribe import transcribe_audio

            fd, wav_path = tempfile.mkstemp(suffix=".ogg")
            os.close(fd)
            Path(wav_path).write_bytes(audio_bytes)
            try:
                text = await transcribe_audio(wav_path)
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

            if not text:
                return

            logger.info("WhatsApp voice from %s: %s", from_number, text[:80])

            # Route through orchestrator
            request = IncomingRequest(
                platform="whatsapp_voice",
                user_id=from_number,
                text=text,
                reply_target=ReplyTarget(
                    platform="whatsapp_voice",
                    chat_id=chat_id,
                ),
                voice_reply=True,
            )

            try:
                from app.core.orchestrator import get_orchestrator
                orchestrator = get_orchestrator()
                await orchestrator.handle(request)
            except Exception as exc:
                logger.error("WhatsApp orchestrator error: %s", exc)

        except Exception as exc:
            logger.error("WhatsApp message handler error: %s", exc)

    async def _whapi_download(self, media_id: str) -> bytes:
        """Download media from Whapi.Cloud."""
        url = f"https://gate.whapi.cloud/media/download/{media_id}"
        headers = {"Authorization": f"Bearer {self._whapi_token}"}
        r = await self._http_client.get(url, headers=headers)
        r.raise_for_status()
        return r.content

    async def _whapi_send_audio(self, to_number: str, audio_bytes: bytes) -> None:
        """Send audio message via Whapi.Cloud."""
        if not self._whapi_token:
            logger.warning("WhatsApp: no Whapi token to send audio")
            return

        # Upload audio first
        upload_url = "https://gate.whapi.cloud/media/upload"
        headers = {"Authorization": f"Bearer {self._whapi_token}"}
        files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
        upload_resp = await self._http_client.post(upload_url, headers=headers, files=files)
        upload_resp.raise_for_status()
        media_id = upload_resp.json().get("id", "")

        # Send as voice message
        send_url = "https://gate.whapi.cloud/messages/audio"
        await self._http_client.post(
            send_url,
            headers=headers,
            json={
                "to": to_number,
                "media": media_id,
            },
        )

    # ── VoiceChannel interface ─────────────────────────────────────

    async def make_call(self, target: str, **kwargs: Any) -> CallInfo:
        """WhatsApp does not support live calls via API.

        Returns a CallInfo with FAILED state.
        """
        call_id = self.generate_call_id("wa_")
        info = CallInfo(
            call_id=call_id,
            platform="whatsapp",
            direction=CallDirection.OUTGOING,
            remote_user=target,
            state=CallState.FAILED,
            metadata={"error": "WhatsApp API does not support live calls"},
            started_at=self.now_iso(),
        )
        self._active_calls[call_id] = info
        self._emit_state_change(info)
        return info

    async def answer_call(self, call_id: str) -> None:
        logger.debug("WhatsApp: answer_call not supported")

    async def hangup_call(self, call_id: str) -> None:
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.ENDED
            info.ended_at = self.now_iso()
            self._emit_state_change(info)

    async def hold_call(self, call_id: str) -> None:
        pass

    async def resume_call(self, call_id: str) -> None:
        pass

    async def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Send an audio voice message to a WhatsApp user."""
        info = self._active_calls.get(call_id)
        if not info:
            return

        try:
            if self._whapi_token:
                await self._whapi_send_audio(info.remote_user, audio_bytes)
            elif self._bridge_url:
                # Send via Baileys bridge
                await self._http_client.post(
                    f"{self._bridge_url}/send",
                    json={
                        "to": info.remote_user,
                        "type": "audio",
                        "audio": audio_bytes.hex(),
                    },
                )
        except Exception as exc:
            logger.error("WhatsApp send_audio failed: %s", exc)

    async def send_dtmf(self, call_id: str, digits: str) -> None:
        logger.debug("WhatsApp: DTMF not supported")
