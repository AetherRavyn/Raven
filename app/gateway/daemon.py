"""Gateway Daemon — Persistent process managing all channel connections.

Replaces the monolithic ``main.py`` startup with a modular daemon that:
- Starts/stops/restarts individual channels independently
- Tracks channel health and auto-reconnects on failure
- Provides status reporting for ``ravyn status`` and ``ravyn doctor``
- Writes PID file for systemd/launchd integration

Usage:
    daemon = GatewayDaemon()
    await daemon.start()     # Starts all configured channels
    await daemon.stop()      # Graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from app.gateway.protocol import ChannelInfo, ChannelStatus

logger = logging.getLogger(__name__)

# Type for channel start functions
ChannelRunner = Callable[[asyncio.Event], Awaitable[None]]


class GatewayDaemon:
    """Persistent gateway daemon managing all channel lifecycle.

    Each channel is a coroutine that runs until a stop_event is set.
    The daemon monitors channels and auto-restarts on failure.
    """

    def __init__(
        self,
        pid_file: str | Path | None = None,
        auto_restart: bool = True,
        restart_delay: float = 5.0,
    ) -> None:
        self._channels: dict[str, ChannelInfo] = {}
        self._runners: dict[str, ChannelRunner] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._global_stop = asyncio.Event()
        self._auto_restart = auto_restart
        self._restart_delay = restart_delay
        self._started_at: str = ""

        if pid_file is None:
            from app.settings.config import Config
            pid_file = Path(Config.MEMORY_ROOT) / "gateway.pid"
        self._pid_file = Path(pid_file)

    # ── Channel Registration ────────────────────────────────────────

    def register_channel(
        self,
        name: str,
        platform: str,
        runner: ChannelRunner,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Register a channel adapter with the gateway.

        Args:
            name: Unique channel name (e.g., "telegram", "discord")
            platform: Platform identifier
            runner: Async function(stop_event) that runs the channel
            config: Optional config dict
        """
        self._channels[name] = ChannelInfo(
            name=name,
            platform=platform,
            status=ChannelStatus.DISCONNECTED,
            config=config or {},
        )
        self._runners[name] = runner
        logger.info("Registered channel: %s (%s)", name, platform)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all registered channels."""
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._write_pid()

        logger.info(
            "Gateway daemon starting with %d channels: %s",
            len(self._channels),
            list(self._channels.keys()),
        )

        # Start all channels
        for name in self._channels:
            await self.start_channel(name)

        # Monitor loop
        if self._auto_restart:
            asyncio.create_task(self._monitor_loop(), name="gateway-monitor")

    async def stop(self) -> None:
        """Graceful shutdown of all channels."""
        logger.info("Gateway daemon shutting down...")
        self._global_stop.set()

        # Signal all channels to stop
        for name, event in self._stop_events.items():
            event.set()

        # Wait for all tasks to finish
        if self._tasks:
            await asyncio.gather(
                *self._tasks.values(), return_exceptions=True
            )

        self._tasks.clear()
        self._stop_events.clear()
        self._remove_pid()

        # Update all channel statuses
        for info in self._channels.values():
            info.status = ChannelStatus.DISCONNECTED

        logger.info("Gateway daemon stopped.")

    async def start_channel(self, name: str) -> bool:
        """Start a single channel."""
        if name not in self._runners:
            logger.error("Channel '%s' not registered", name)
            return False

        if name in self._tasks and not self._tasks[name].done():
            logger.warning("Channel '%s' already running", name)
            return False

        stop_event = asyncio.Event()
        self._stop_events[name] = stop_event

        info = self._channels[name]
        info.status = ChannelStatus.CONNECTING

        task = asyncio.create_task(
            self._run_channel(name, stop_event),
            name=f"gateway-{name}",
        )
        self._tasks[name] = task
        return True

    async def stop_channel(self, name: str) -> bool:
        """Stop a single channel."""
        event = self._stop_events.get(name)
        if event is None:
            return False

        event.set()
        task = self._tasks.get(name)
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._channels[name].status = ChannelStatus.DISCONNECTED
        return True

    async def restart_channel(self, name: str) -> bool:
        """Hot-restart a channel without affecting others."""
        await self.stop_channel(name)
        await asyncio.sleep(0.5)
        return await self.start_channel(name)

    # ── Channel Runner Wrapper ──────────────────────────────────────

    async def _run_channel(self, name: str, stop_event: asyncio.Event) -> None:
        """Wrapper that runs a channel and tracks its status."""
        runner = self._runners[name]
        info = self._channels[name]

        try:
            info.status = ChannelStatus.CONNECTED
            info.connected_at = datetime.now(timezone.utc).isoformat()
            info.error = ""
            logger.info("Channel '%s' started", name)

            await runner(stop_event)

            info.status = ChannelStatus.DISCONNECTED
            logger.info("Channel '%s' stopped cleanly", name)

        except asyncio.CancelledError:
            info.status = ChannelStatus.DISCONNECTED
            logger.info("Channel '%s' cancelled", name)

        except Exception as exc:
            info.status = ChannelStatus.ERROR
            info.error = str(exc)[:200]
            logger.error("Channel '%s' crashed: %s", name, exc)

    # ── Monitor Loop ────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """Monitor channels and auto-restart crashed ones."""
        while not self._global_stop.is_set():
            await asyncio.sleep(self._restart_delay)

            for name, task in list(self._tasks.items()):
                if task.done() and not self._global_stop.is_set():
                    info = self._channels.get(name)
                    if info and info.status == ChannelStatus.ERROR:
                        logger.info(
                            "Auto-restarting crashed channel: %s (after %.1fs)",
                            name, self._restart_delay,
                        )
                        await self.start_channel(name)

    # ── Status ──────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return full gateway status."""
        return {
            "started_at": self._started_at,
            "pid": os.getpid(),
            "auto_restart": self._auto_restart,
            "channels": {
                name: info.to_dict() for name, info in self._channels.items()
            },
            "active_count": sum(
                1 for info in self._channels.values()
                if info.status == ChannelStatus.CONNECTED
            ),
            "total_count": len(self._channels),
        }

    def get_channel_status(self, name: str) -> ChannelInfo | None:
        """Get status of a single channel."""
        return self._channels.get(name)

    # ── PID File ────────────────────────────────────────────────────

    def _write_pid(self) -> None:
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            self._pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to write PID file: %s", exc)

    def _remove_pid(self) -> None:
        try:
            if self._pid_file.exists():
                self._pid_file.unlink()
        except Exception:
            pass


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_DAEMON: GatewayDaemon | None = None


def get_gateway_daemon() -> GatewayDaemon:
    """Get or create the global GatewayDaemon."""
    global _GLOBAL_DAEMON
    if _GLOBAL_DAEMON is None:
        _GLOBAL_DAEMON = GatewayDaemon()
    return _GLOBAL_DAEMON
