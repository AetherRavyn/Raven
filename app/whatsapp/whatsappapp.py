# app/whatsapp/whatsappapp.py
"""RAVEN WhatsApp connector via the Baileys HTTP bridge.

Architecture:
  WhatsApp ←→ Baileys (Node.js bridge) ←→ POST /whatsapp/incoming → this module → BotSignal
                                        ←→ POST <bridge>/send ← send_to_target()

The bridge forwards incoming messages to RAVEN via POST /whatsapp/incoming.
Outbound messages are sent by POSTing to the bridge's /send endpoint.

Config:
  WHATSAPP_BRIDGE_URL  URL of the running Baileys bridge (default: http://localhost:3001)
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import FastAPI, Request

from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload

logger = logging.getLogger(__name__)


class WhatsAppBot:
    """WhatsApp connector that bridges to the Baileys Node.js process."""

    def __init__(self, bridge_url: str, orchestrator) -> None:
        self._bridge_url = bridge_url.rstrip("/")
        self._orchestrator = orchestrator
        self._app = FastAPI(title="RAVEN WhatsApp Receiver")
        self._setup_routes()

    # ── FastAPI routes ────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        @self._app.post("/whatsapp/incoming")
        async def incoming(request: Request):
            data = await request.json()
            asyncio.create_task(self._handle_incoming(data))
            return {"status": "queued"}

        @self._app.get("/whatsapp/health")
        async def health():
            return {"status": "ok", "platform": "whatsapp"}

    async def _handle_incoming(self, data: dict) -> None:
        """Process an incoming message forwarded from the Baileys bridge."""
        user_id = str(data.get("user_id", ""))
        chat_id = str(data.get("chat_id", ""))
        text = (data.get("text") or "").strip()

        if not text or not user_id:
            return

        logger.info(
            "WhatsApp incoming  user=%s  chat=%s  text=%r",
            user_id,
            chat_id,
            text[:120],
        )

        request = IncomingRequest(
            platform="whatsapp",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="whatsapp",
                chat_id=chat_id,
            ),
            conversation_id=chat_id or user_id,
        )
        await self._orchestrator.handle(request)

    # ── Outbound sender ───────────────────────────────────────────────────────

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        """Forward a reply to the Baileys bridge for delivery via WhatsApp."""
        text = payload.text or payload.caption or ""
        jid = target.chat_id  # WhatsApp JID e.g. "1234567890@s.whatsapp.net"

        if not text or not jid:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._bridge_url}/send",
                    json={"jid": jid, "text": text},
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("WhatsApp send failed jid=%s: %s", jid, exc)

    def register_output_sender(self, botsignal: BotSignal) -> None:
        """Register this connector as the 'whatsapp' sender on BotSignal."""
        botsignal.register_sender("whatsapp", self.send_to_target)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_bot(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        """Run the FastAPI receiver until cancelled."""
        import uvicorn

        config = uvicorn.Config(self._app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
