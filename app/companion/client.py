"""Companion Client Library — For native apps (macOS, iOS, Android, Desktop).

Provides a Python reference implementation. Native apps should port this
to Swift (iOS/macOS), Kotlin (Android), or their platform language.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import websockets

logger = logging.getLogger(__name__)


@dataclass
class CompanionConfig:
    """Configuration for companion client."""
    server_url: str = "ws://localhost:8090/ws/companion"
    device_id: str = ""
    device_type: str = "desktop"  # macos_menu, ios, android, desktop_overlay, web
    platform: str = "python"
    app_version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=lambda: ["text", "notifications", "approvals"])
    user_id: str = "default"
    auto_reconnect: bool = True
    reconnect_interval: float = 5.0
    heartbeat_interval: float = 30.0


class RavenCompanionClient:
    """Client for connecting to Raven daemon as a companion device."""
    
    def __init__(self, config: CompanionConfig) -> None:
        self.config = config
        if not self.config.device_id:
            self.config.device_id = f"{config.device_type}_{uuid.uuid4().hex[:8]}"
        
        self.websocket: websockets.WebSocketClientProtocol | None = None
        self.connected = False
        self.authenticated = False
        self._handlers: dict[str, list[Callable]] = {}
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._server_state: dict[str, Any] = {}
        self._pending_requests: dict[str, asyncio.Future] = {}
    
    def on(self, event: str, handler: Callable) -> None:
        """Register event handler."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)
    
    def off(self, event: str, handler: Callable) -> None:
        """Unregister event handler."""
        if event in self._handlers:
            self._handlers[event].remove(handler)
    
    async def _emit(self, event: str, data: Any) -> None:
        """Emit event to handlers."""
        if event in self._handlers:
            for handler in self._handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Handler error for {event}: {e}")
    
    async def connect(self) -> bool:
        """Connect to Raven daemon."""
        try:
            self.websocket = await websockets.connect(self.config.server_url)
            self.connected = True
            
            # Send auth message
            await self._send({
                "type": "auth",
                "payload": {
                    "device_id": self.config.device_id,
                    "device_type": self.config.device_type,
                    "platform": self.config.platform,
                    "app_version": self.config.app_version,
                    "capabilities": self.config.capabilities,
                    "user_id": self.config.user_id,
                }
            })
            
            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            await self._emit("connected", {})
            logger.info(f"Connected to Raven daemon as {self.config.device_id}")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.connected = False
            if self.config.auto_reconnect:
                self._schedule_reconnect()
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from daemon."""
        self.connected = False
        
        if self._receive_task:
            self._receive_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        await self._emit("disconnected", {})
    
    async def _send(self, message: dict[str, Any]) -> bool:
        """Send message to server."""
        if not self.websocket or not self.connected:
            return False
        
        try:
            await self.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Send failed: {e}")
            self.connected = False
            if self.config.auto_reconnect:
                self._schedule_reconnect()
            return False
    
    async def _receive_loop(self) -> None:
        """Main receive loop."""
        try:
            async for message in self.websocket:
                if not self.connected:
                    break
                
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON")
                except Exception as e:
                    logger.error(f"Message handling error: {e}")
        
        except websockets.ConnectionClosed:
            logger.info("Connection closed by server")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self.connected = False
            self.authenticated = False
            await self._emit("disconnected", {})
            
            if self.config.auto_reconnect:
                self._schedule_reconnect()
    
    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming message from server."""
        msg_type = data.get("type")
        payload = data.get("payload", {})
        
        if msg_type == "welcome":
            self.authenticated = True
            self._server_state = payload.get("state", {})
            await self._emit("ready", payload)
        
        elif msg_type == "state_response":
            self._server_state = payload.get("state", {})
            await self._emit("state_update", payload.get("state", {}))
        
        elif msg_type == "state_update":
            self._server_state = payload.get("state", {})
            await self._emit("state_update", payload.get("state", {}))
        
        elif msg_type == "notification":
            await self._emit("notification", payload)
        
        elif msg_type == "approval_request":
            await self._emit("approval_request", payload)
        
        elif msg_type == "approval_response":
            await self._emit("approval_response", payload)
        
        elif msg_type == "device_joined":
            await self._emit("device_joined", payload)
        
        elif msg_type == "device_left":
            await self._emit("device_left", payload)
        
        elif msg_type == "pong":
            # Heartbeat response
            pass
        
        elif msg_type == "text_response":
            # Response to text message we sent
            request_id = payload.get("request_id")
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                future.set_result(payload)
        
        else:
            logger.debug(f"Unhandled message type: {msg_type}")
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self.connected:
            await asyncio.sleep(self.config.heartbeat_interval)
            if self.connected:
                await self._send({"type": "ping"})
    
    def _schedule_reconnect(self) -> None:
        """Schedule reconnection attempt."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
        self._reconnect_task = asyncio.create_task(self._reconnect())
    
    async def _reconnect(self) -> None:
        """Attempt to reconnect."""
        await asyncio.sleep(self.config.reconnect_interval)
        if not self.connected:
            logger.info("Attempting reconnection...")
            await self.connect()
    
    # ── High-level API ─────────────────────────────────────────────
    
    async def send_text(self, text: str, conversation_id: str | None = None) -> dict[str, Any] | None:
        """Send text message to Raven."""
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future
        
        await self._send({
            "type": "text",
            "payload": {
                "text": text,
                "conversation_id": conversation_id,
                "request_id": request_id
            }
        })
        
        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            return None
    
    async def start_voice(self) -> bool:
        """Start voice listening."""
        return await self._send({"type": "voice_start"})
    
    async def stop_voice(self) -> bool:
        """Stop voice listening."""
        return await self._send({"type": "voice_stop"})
    
    async def send_audio_chunk(self, audio_data: bytes) -> bool:
        """Send audio chunk for streaming STT."""
        # Would send binary data over WebSocket
        return False
    
    async def respond_to_approval(self, approval_id: str, approved: bool) -> bool:
        """Respond to approval request."""
        return await self._send({
            "type": "approval_response",
            "payload": {
                "approval_id": approval_id,
                "approved": approved
            }
        })
    
    async def dismiss_notification(self, notification_id: str) -> bool:
        """Dismiss a notification."""
        return await self._send({
            "type": "notification_dismissed",
            "payload": {"notification_id": notification_id}
        })
    
    async def request_state(self) -> bool:
        """Request current state from server."""
        return await self._send({"type": "state_request"})
    
    @property
    def state(self) -> dict[str, Any]:
        """Get cached server state."""
        return self._server_state.copy()
    
    @property
    def is_ready(self) -> bool:
        """Check if connected and authenticated."""
        return self.connected and self.authenticated


# Convenience function for quick integration
async def create_companion(
    device_type: str = "desktop",
    server_url: str = "ws://localhost:8090/ws/companion",
    user_id: str = "default",
    on_notification: Callable | None = None,
    on_approval: Callable | None = None,
    on_state_update: Callable | None = None
) -> RavenCompanionClient:
    """Create and connect a companion client with common handlers."""
    config = CompanionConfig(
        server_url=server_url,
        device_type=device_type,
        user_id=user_id
    )
    
    client = RavenCompanionClient(config)
    
    if on_notification:
        client.on("notification", on_notification)
    if on_approval:
        client.on("approval_request", on_approval)
    if on_state_update:
        client.on("state_update", on_state_update)
    
    await client.connect()
    return client