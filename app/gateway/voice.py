"""Voice channel registration — registers voice-enabled channels with the GatewayDaemon.

Call this during daemon startup to wire up Telegram, WhatsApp, and SIP voice channels.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.gateway.daemon import GatewayDaemon
from app.settings.config import Config

logger = logging.getLogger(__name__)


def register_voice_channels(
    daemon: GatewayDaemon,
    call_manager: Any,
) -> None:
    """Register all configured voice channels with the gateway daemon.

    Args:
        daemon: The GatewayDaemon instance
        call_manager: The CallManager instance (from app.voice.call_manager)
    """
    # ── Telegram Voice ──────────────────────────────────────────────
    if Config.TELEGRAM_BOT_TOKEN:
        try:
            from app.voice.channels.telegram import TelegramVoiceChannel

            tg_channel = TelegramVoiceChannel(
                bot_token=Config.TELEGRAM_BOT_TOKEN,
                api_id=Config.TELEGRAM_API_ID or 0,
                api_hash=Config.TELEGRAM_API_HASH or "",
                phone_number=Config.TELEGRAM_PHONE or "",
            )

            call_manager.register_channel(tg_channel, is_default=True)

            # Register with gateway daemon
            async def _run_telegram(stop_event: asyncio.Event) -> None:
                await tg_channel.start(stop_event)

            daemon.register_channel(
                "telegram_voice",
                "telegram",
                _run_telegram,
                config={"bot_token": "***"},
            )
            logger.info("Voice: Telegram voice channel registered")
        except Exception as exc:
            logger.warning("Voice: Telegram channel init failed: %s", exc)
    else:
        logger.debug("Voice: TELEGRAM_BOT_TOKEN not set — skipping Telegram voice")

    # ── WhatsApp Voice ──────────────────────────────────────────────
    if Config.WHATSAPP_WHAPI_TOKEN or Config.WHATSAPP_BRIDGE_URL:
        try:
            from app.voice.channels.whatsapp import WhatsAppVoiceChannel

            wa_channel = WhatsAppVoiceChannel(
                bridge_url=Config.WHATSAPP_BRIDGE_URL or "",
                whapi_token=Config.WHATSAPP_WHAPI_TOKEN or "",
                phone_number_id=Config.WHATSAPP_PHONE_ID or "",
            )

            call_manager.register_channel(wa_channel)

            async def _run_whatsapp(stop_event: asyncio.Event) -> None:
                await wa_channel.start(stop_event)

            daemon.register_channel(
                "whatsapp_voice",
                "whatsapp",
                _run_whatsapp,
                config={"bridge_url": Config.WHATSAPP_BRIDGE_URL or "whapi"},
            )
            logger.info("Voice: WhatsApp voice channel registered")
        except Exception as exc:
            logger.warning("Voice: WhatsApp channel init failed: %s", exc)
    else:
        logger.debug("Voice: WhatsApp not configured — skipping")

    # ── SIP / Phone Voice ───────────────────────────────────────────
    if Config.TWILIO_ACCOUNT_SID or Config.PLIVO_AUTH_ID or Config.SIP_URI:
        try:
            from app.voice.channels.sip import SIPVoiceChannel

            sip_channel = SIPVoiceChannel(
                twilio_account_sid=Config.TWILIO_ACCOUNT_SID or "",
                twilio_auth_token=Config.TWILIO_AUTH_TOKEN or "",
                twilio_phone_number=Config.TWILIO_PHONE_NUMBER or "",
                plivo_auth_id=Config.PLIVO_AUTH_ID or "",
                plivo_auth_token=Config.PLIVO_AUTH_TOKEN or "",
                plivo_phone_number=Config.PLIVO_PHONE_NUMBER or "",
                sip_uri=Config.SIP_URI or "",
                sip_user=Config.SIP_USER or "",
                sip_password=Config.SIP_PASSWORD or "",
                sip_realm=Config.SIP_REALM or "",
                webhook_base_url=Config.CALL_WEBHOOK_URL or "",
            )

            call_manager.register_channel(sip_channel)

            async def _run_sip(stop_event: asyncio.Event) -> None:
                await sip_channel.start(stop_event)

            daemon.register_channel(
                "phone",
                "sip",
                _run_sip,
                config={
                    "provider": "twilio" if Config.TWILIO_ACCOUNT_SID else "plivo" if Config.PLIVO_AUTH_ID else "sip",
                },
            )
            logger.info("Voice: SIP/Phone channel registered")
        except Exception as exc:
            logger.warning("Voice: SIP channel init failed: %s", exc)
    else:
        logger.debug("Voice: No phone provider configured — skipping SIP")

    logger.info(
        "Voice: %d channels registered with gateway",
        len(daemon._channels) if hasattr(daemon, "_channels") else 0,
    )
