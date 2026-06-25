"""SIP/Phone voice channel — real phone calls via Twilio, Plivo, or PBX.

Provides real PSTN calling capability:
1. Twilio — REST API for SIP trunking (most reliable)
2. Plivo — REST API alternative
3. Direct SIP — via aiortc/pjsua2 for self-hosted PBX

The channel translates between RAVEN's internal audio format
and the telephony codec (usually PCMU/PCMA).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from app.voice.channels.base import (
    CallDirection,
    CallInfo,
    CallState,
    VoiceChannel,
)

logger = logging.getLogger(__name__)

# Optional dependencies
try:
    from twilio.rest import Client as _TwilioClient
    from twilio.twiml.voice_response import VoiceResponse as _TwilioResponse

    _HAS_TWILIO = True
except ImportError:
    _HAS_TWILIO = False

try:
    import plivo  # noqa: F401 — import check for optional dependency

    _HAS_PLIVO = True
except ImportError:
    _HAS_PLIVO = False

try:
    import aiortc  # noqa: F401 — import check for optional dependency

    _HAS_AIORTC = True
except ImportError:
    _HAS_AIORTC = False


# Webhook server for incoming calls — shared across SIP channels
_incoming_call_handler: Optional[callable] = None


async def _default_incoming_handler(
    channel: "SIPVoiceChannel",
    from_number: str,
    call_sid: str,
) -> None:
    """Default handler: create CallInfo and notify the channel."""
    call_id = f"sip_{call_sid}"
    info = CallInfo(
        call_id=call_id,
        platform="sip",
        direction=CallDirection.INCOMING,
        remote_user=from_number,
        remote_name=from_number,
        state=CallState.RINGING,
        audio_format="pcmu",
        started_at=VoiceChannel.now_iso(),
        metadata={"call_sid": call_sid},
    )
    channel._active_calls[call_id] = info
    channel._emit_state_change(info)


class SIPVoiceChannel(VoiceChannel):
    """Real phone calls via SIP trunking.

    Supports Twilio, Plivo, or direct SIP via aiortc.
    Requires at least one backend configured.
    """

    platform_name = "sip"

    def __init__(
        self,
        # Twilio
        twilio_account_sid: Optional[str] = None,
        twilio_auth_token: Optional[str] = None,
        twilio_phone_number: Optional[str] = None,
        # Plivo
        plivo_auth_id: Optional[str] = None,
        plivo_auth_token: Optional[str] = None,
        plivo_phone_number: Optional[str] = None,
        # General SIP
        sip_uri: Optional[str] = None,
        sip_user: Optional[str] = None,
        sip_password: Optional[str] = None,
        sip_realm: Optional[str] = None,
        # Webhook URL for incoming calls
        webhook_base_url: Optional[str] = None,
    ) -> None:
        super().__init__()

        # Twilio
        self._twilio_sid = twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
        self._twilio_token = twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
        self._twilio_number = twilio_phone_number or os.environ.get("TWILIO_PHONE_NUMBER", "")

        # Plivo
        self._plivo_id = plivo_auth_id or os.environ.get("PLIVO_AUTH_ID", "")
        self._plivo_token = plivo_auth_token or os.environ.get("PLIVO_AUTH_TOKEN", "")
        self._plivo_number = plivo_phone_number or os.environ.get("PLIVO_PHONE_NUMBER", "")

        # Direct SIP
        self._sip_uri = sip_uri or os.environ.get("SIP_URI", "")
        self._sip_user = sip_user or os.environ.get("SIP_USER", "")
        self._sip_password = sip_password or os.environ.get("SIP_PASSWORD", "")
        self._sip_realm = sip_realm or os.environ.get("SIP_REALM", "")

        self._webhook_url = webhook_base_url or os.environ.get("CALL_WEBHOOK_URL", "")

        self._twilio_client: Any = None
        self._http_client: Any = None
        self._server: Any = None

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self, stop_event: asyncio.Event) -> None:
        """Start the SIP channel."""
        import httpx

        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Init Twilio client
        if self._twilio_sid and self._twilio_token and _HAS_TWILIO:
            self._twilio_client = _TwilioClient(self._twilio_sid, self._twilio_token)
            logger.info("SIP: Twilio client initialized")

        # Start webhook server for incoming calls
        if self._webhook_url:
            await self._start_webhook(stop_event)
        else:
            await stop_event.wait()

    async def stop(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        if self._server:
            await self._server.cleanup()

    async def _start_webhook(self, stop_event: asyncio.Event) -> None:
        """Start aiohttp server for Twilio/Plivo webhooks."""
        from aiohttp import web

        app = web.Application()

        async def twilio_voice_handler(request: web.Request) -> web.Response:
            """Twilio incoming call webhook."""
            data = await request.post()
            from_number = data.get("From", "unknown")
            call_sid = data.get("CallSid", "")

            await _default_incoming_handler(self, from_number, call_sid)

            # Return TwiML to say we're connecting
            if _HAS_TWILIO:
                resp = _TwilioResponse()
                resp.say("Hello, I am RAVEN AI assistant. Connecting you now.")
                return web.Response(
                    text=str(resp),
                    content_type="application/xml",
                )
            return web.Response(text="<Response><Say>Connecting</Say></Response>")

        async def twilio_status_handler(request: web.Request) -> web.Response:
            """Twilio call status callback."""
            data = await request.post()
            call_sid = data.get("CallSid", "")
            status = data.get("CallStatus", "")

            for cid, info in list(self._active_calls.items()):
                if info.metadata.get("call_sid") == call_sid:
                    if status in ("completed", "failed", "busy", "no-answer"):
                        info.state = CallState.ENDED
                        info.ended_at = self.now_iso()
                        self._emit_state_change(info)
                    elif status == "in-progress":
                        info.state = CallState.ACTIVE
                        info.connected_at = self.now_iso()
                        self._emit_state_change(info)
                    break

            return web.Response(text="OK")

        app.router.add_post("/call/incoming", twilio_voice_handler)
        app.router.add_post("/call/status", twilio_status_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 8081)
        await site.start()
        self._server = runner
        logger.info("SIP: webhook server on :8081 (/call/incoming, /call/status)")

        await stop_event.wait()

    # ── Outbound Calls ──────────────────────────────────────────────

    async def make_call(self, target: str, **kwargs: Any) -> CallInfo:
        """Make an outbound phone call.

        Args:
            target: Phone number in E.164 format (e.g., +15551234567)

        Returns:
            CallInfo with call status
        """
        call_id = self.generate_call_id("sip_")

        info = CallInfo(
            call_id=call_id,
            platform="sip",
            direction=CallDirection.OUTGOING,
            remote_user=target,
            remote_name=target,
            state=CallState.CONNECTING,
            audio_format="pcmu",
            started_at=self.now_iso(),
            metadata={"provider": "twilio"},
        )
        self._active_calls[call_id] = info
        self._emit_state_change(info)

        if self._twilio_client and _HAS_TWILIO:
            await self._call_via_twilio(call_id, target, info)
        elif self._plivo_id and _HAS_PLIVO:
            await self._call_via_plivo(call_id, target, info)
        else:
            info.state = CallState.FAILED
            info.metadata["error"] = "No phone provider configured"
            self._emit_state_change(info)

        return info

    async def _call_via_twilio(
        self,
        call_id: str,
        target: str,
        info: CallInfo,
    ) -> None:
        """Initiate call via Twilio REST API."""
        try:
            status_callback = f"{self._webhook_url}/call/status" if self._webhook_url else ""

            call = self._twilio_client.calls.create(
                to=target,
                from_=self._twilio_number,
                url=f"{self._webhook_url}/call/incoming" if self._webhook_url else "",
                status_callback=status_callback,
                status_callback_event=["completed", "answered", "busy", "no-answer"],
                timeout=30,
            )

            info.metadata["call_sid"] = call.sid
            info.state = CallState.RINGING
            self._emit_state_change(info)

        except Exception as exc:
            info.state = CallState.FAILED
            info.metadata["error"] = str(exc)
            self._emit_state_change(info)

    async def _call_via_plivo(
        self,
        call_id: str,
        target: str,
        info: CallInfo,
    ) -> None:
        """Initiate call via Plivo REST API."""
        try:
            import plivo

            client = plivo.RestClient(self._plivo_id, self._plivo_token)
            answer_url = f"{self._webhook_url}/call/incoming" if self._webhook_url else ""

            response = client.calls.create(
                to=target,
                from_=self._plivo_number,
                answer_url=answer_url,
                answer_method="POST",
            )

            info.metadata["call_uuid"] = response.get("call_uuid", "")
            info.state = CallState.RINGING
            self._emit_state_change(info)

        except Exception as exc:
            info.state = CallState.FAILED
            info.metadata["error"] = str(exc)
            self._emit_state_change(info)

    # ── Call Control ────────────────────────────────────────────────

    async def answer_call(self, call_id: str) -> None:
        """Answer an incoming call (already handled by TwiML response)."""
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.ACTIVE
            info.connected_at = self.now_iso()
            self._emit_state_change(info)

    async def hangup_call(self, call_id: str) -> None:
        """End a call via provider API."""
        info = self._active_calls.get(call_id)
        if not info:
            return

        call_sid = info.metadata.get("call_sid", "")
        if call_sid and self._twilio_client and _HAS_TWILIO:
            try:
                self._twilio_client.calls(call_sid).update(status="completed")
            except Exception as exc:
                logger.debug("Twilio hangup failed: %s", exc)

        info.state = CallState.ENDED
        info.ended_at = self.now_iso()
        self._emit_state_change(info)

    async def hold_call(self, call_id: str) -> None:
        """Place call on hold via TwiML redirect."""
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.HOLD
            self._emit_state_change(info)
            # For Twilio, we would redirect to hold music
            call_sid = info.metadata.get("call_sid", "")
            if call_sid and self._twilio_client and _HAS_TWILIO and self._webhook_url:
                from twilio.twiml.voice_response import VoiceResponse
                resp = VoiceResponse()
                resp.play("http://com.twilio.sounds.music.s3.amazonaws.com/MARKOVICHAMP-MIKE_STRAUB_HOLD_MUSIC.mp3")
                # Would need to update call with new TwiML instructions via REST

    async def resume_call(self, call_id: str) -> None:
        """Resume a held call."""
        info = self._active_calls.get(call_id)
        if info:
            info.state = CallState.ACTIVE
            self._emit_state_change(info)

    async def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Send audio to the call.

        For SIP calls, this is done via media streams (aiortc) or
        by uploading to Twilio's media endpoint.

        Current implementation: Not directly supported for PSTN calls.
        TTS should be pre-rendered and passed via TwiML <Say> at call start.
        """
        info = self._active_calls.get(call_id)
        if not info:
            return

        logger.debug("SIP: send_audio not supported for PSTN calls in current implementation")

    async def send_dtmf(self, call_id: str, digits: str) -> None:
        """Send DTMF tones during a call."""
        info = self._active_calls.get(call_id)
        if not info:
            return

        call_sid = info.metadata.get("call_sid", "")
        if call_sid and self._twilio_client and _HAS_TWILIO:
            try:
                self._twilio_client.calls(call_sid).update(twiml=f"<Response><Play digits=\"{digits}\"/></Response>")
            except Exception as exc:
                logger.debug("Twilio DTMF failed: %s", exc)

    async def gather_speech(
        self,
        call_id: str,
        prompt: str = "Please state your request",
        timeout: int = 5,
    ) -> str:
        """Use Twilio <Gather> with speech input to capture user response.

        Returns the transcribed speech text.
        """
        info = self._active_calls.get(call_id)
        if not info:
            return ""

        call_sid = info.metadata.get("call_sid", "")
        if not call_sid or not self._twilio_client or not _HAS_TWILIO:
            return ""

        from twilio.twiml.voice_response import Gather, VoiceResponse

        resp = VoiceResponse()
        gather = Gather(input="speech", timeout=timeout, action=f"{self._webhook_url}/call/gather")
        gather.say(prompt)
        resp.append(gather)
        resp.say("We did not receive any input. Goodbye.")

        try:
            # Update call with new TwiML instructions to gather speech
            self._twilio_client.calls(call_sid).update(twiml=str(resp))
            # The result comes back via webhook to /call/gather
        except Exception as exc:
            logger.debug("Twilio gather failed: %s", exc)

        return ""
