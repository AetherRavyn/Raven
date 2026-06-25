"""Signal channel adapter — Bridges AetherRavyn to Signal via signal-cli.

Requires signal-cli (https://github.com/AsamK/signal-cli) to be installed
and configured with a registered phone number.

Usage:
    export SIGNAL_CLI_PATH=/usr/local/bin/signal-cli
    export SIGNAL_PHONE=+1234567890
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.models import IncomingRequest, ReplyTarget

logger = logging.getLogger(__name__)


@dataclass
class SignalConfig:
    """Signal adapter configuration."""
    cli_path: str = os.getenv("SIGNAL_CLI_PATH", "signal-cli")
    phone: str = os.getenv("SIGNAL_PHONE", "")
    data_dir: str = os.getenv("SIGNAL_DATA_DIR", "")
    poll_interval: float = 2.0
    enabled: bool = bool(os.getenv("SIGNAL_PHONE"))


class SignalChannel:
    """Receive and send messages via Signal using signal-cli.

    Operates in JSON-RPC mode (signal-cli daemon) or polling mode
    (signal-cli receive) depending on availability.
    """

    def __init__(self, orchestrator: Any, config: SignalConfig | None = None) -> None:
        self._orchestrator = orchestrator
        self._config = config or SignalConfig()
        self._running = False
        self._daemon_process: subprocess.Popen | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(self._config.phone)

    async def start(self) -> None:
        """Start the Signal polling loop."""
        if not self.enabled:
            logger.info("Signal channel disabled (SIGNAL_PHONE not set)")
            return

        logger.info("Starting Signal channel for %s", self._config.phone)
        self._running = True

        # Try daemon mode first (signal-cli daemon --json)
        if await self._try_daemon_mode():
            return

        # Fallback to polling mode
        await self._poll_loop()

    async def stop(self) -> None:
        """Stop the Signal channel."""
        self._running = False
        if self._daemon_process:
            self._daemon_process.terminate()
            self._daemon_process = None
        logger.info("Signal channel stopped")

    async def _try_daemon_mode(self) -> bool:
        """Try to connect to an existing signal-cli daemon."""
        try:
            result = subprocess.run(
                [self._config.cli_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                logger.warning("signal-cli not available: %s", result.stderr)
                return False
            logger.info("signal-cli found: %s", result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("signal-cli not found at %s", self._config.cli_path)
            return False
        return False  # Use polling mode for now

    async def _poll_loop(self) -> None:
        """Poll for new messages using signal-cli receive."""
        while self._running:
            try:
                await self._receive_messages()
            except Exception as exc:
                logger.error("Signal receive error: %s", exc)
            await asyncio.sleep(self._config.poll_interval)

    async def _receive_messages(self) -> None:
        """Run signal-cli receive and process incoming messages."""
        cmd = [self._config.cli_path, "-a", self._config.phone, "receive", "--json"]
        if self._config.data_dir:
            cmd.extend(["--config", self._config.data_dir])

        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return
        except FileNotFoundError:
            self._running = False
            logger.error("signal-cli not found, disabling Signal channel")
            return

        if not result.stdout.strip():
            return

        for line in result.stdout.strip().splitlines():
            try:
                envelope = json.loads(line)
                await self._handle_envelope(envelope)
            except json.JSONDecodeError:
                continue

    async def _handle_envelope(self, envelope: dict[str, Any]) -> None:
        """Process a single Signal envelope."""
        data_msg = envelope.get("envelope", {}).get("dataMessage")
        if not data_msg:
            return

        body = data_msg.get("message", "").strip()
        if not body:
            return

        sender = envelope.get("envelope", {}).get("source", "unknown")
        group_id = data_msg.get("groupInfo", {}).get("groupId")
        chat_id = group_id or sender

        logger.info("Signal message from %s: %s", sender, body[:50])

        reply_target = ReplyTarget(platform="signal", chat_id=chat_id)
        incoming = IncomingRequest(
            platform="signal",
            user_id=sender,
            text=body,
            reply_target=reply_target,
            conversation_id=chat_id,
        )

        asyncio.create_task(
            self._orchestrator.handle(incoming),
            name=f"signal-{sender}",
        )

    async def send_message(
        self, recipient: str, text: str, group: bool = False
    ) -> bool:
        """Send a message via Signal."""
        cmd = [self._config.cli_path, "-a", self._config.phone, "send"]
        if group:
            cmd.extend(["-g", recipient])
        else:
            cmd.extend([recipient])
        cmd.extend(["-m", text])

        if self._config.data_dir:
            cmd.extend(["--config", self._config.data_dir])

        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                logger.error("Signal send error: %s", result.stderr)
                return False
            return True
        except Exception as exc:
            logger.error("Signal send failed: %s", exc)
            return False
