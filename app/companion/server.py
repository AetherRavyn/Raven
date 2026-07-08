"""Companion App Foundation — Native app connectivity layer.

Provides WebSocket-based real-time communication for:
- macOS menu bar app
- iOS/Android companions  
- Desktop overlay/HUD
- Web dashboard (existing)

All companions connect via WebSocket to the main Raven daemon for:
- Real-time message streaming
- State synchronization
- Voice audio streaming
- Presence/awareness
- Proactive notifications
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompanionDevice:
    """A connected companion device."""
    device_id: str
    device_type: str  # macos_menu, ios, android, desktop_overlay, web
    platform: str
    app_version: str
    capabilities: list[str] = field(default_factory=list)
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompanionMessage:
    """Message exchanged between daemon and companion."""
    message_id: str
    type: str  # text, voice, state, notification, command, ping, pong, auth
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_device: str | None = None  # None = broadcast
    source_device: str = "daemon"


@dataclass(slots=True)
class CompanionState:
    """Synchronized state across all companions."""
    user_id: str
    active_conversation_id: str | None = None
    current_context: dict[str, Any] = field(default_factory=dict)
    voice_active: bool = False
    listening: bool = False
    speaking: bool = False
    notifications: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    device_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CompanionConnectionManager:
    """Manages WebSocket connections for companion devices."""
    
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.devices: dict[str, CompanionDevice] = {}
        self.message_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self.state = CompanionState(user_id="")
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, device_info: dict[str, Any]) -> str:
        """Register a new companion connection."""
        device_id = device_info.get("device_id", f"device_{uuid.uuid4().hex[:8]}")
        
        device = CompanionDevice(
            device_id=device_id,
            device_type=device_info.get("device_type", "unknown"),
            platform=device_info.get("platform", "unknown"),
            app_version=device_info.get("app_version", "1.0.0"),
            capabilities=device_info.get("capabilities", []),
            user_id=device_info.get("user_id", "default"),
            metadata=device_info.get("metadata", {})
        )
        
        self.active_connections[device_id] = websocket
        self.devices[device_id] = device
        self.message_queues[device_id] = asyncio.Queue()
        self.state.user_id = device.user_id
        self.state.device_states[device_id] = {
            "connected": True,
            "last_seen": device.last_seen,
            "capabilities": device.capabilities
        }
        
        logger.info(f"Companion connected: {device_id} ({device.device_type})")
        
        # Send welcome message with current state
        await self.send_to_device(device_id, CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="welcome",
            payload={
                "device_id": device_id,
                "state": asdict(self.state),
                "server_time": datetime.now(timezone.utc).isoformat()
            }
        ))
        
        # Broadcast device joined
        await self.broadcast(CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="device_joined",
            payload={"device": asdict(device)}
        ), exclude=device_id)
        
        return device_id
    
    async def disconnect(self, device_id: str) -> None:
        """Handle companion disconnection."""
        if device_id in self.active_connections:
            del self.active_connections[device_id]
        if device_id in self.devices:
            device = self.devices[device_id]
            logger.info(f"Companion disconnected: {device_id} ({device.device_type})")
            del self.devices[device_id]
        if device_id in self.message_queues:
            del self.message_queues[device_id]
        
        self.state.device_states[device_id] = {
            "connected": False,
            "last_seen": datetime.now(timezone.utc).isoformat()
        }
        
        await self.broadcast(CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="device_left",
            payload={"device_id": device_id}
        ))
    
    async def send_to_device(self, device_id: str, message: CompanionMessage) -> bool:
        """Send message to specific device."""
        if device_id not in self.active_connections:
            # Queue for later delivery
            if device_id in self.message_queues:
                await self.message_queues[device_id].put(message)
            return False
        
        websocket = self.active_connections[device_id]
        try:
            await websocket.send_text(json.dumps(asdict(message)))
            return True
        except Exception as e:
            logger.error(f"Failed to send to {device_id}: {e}")
            return False
    
    async def broadcast(self, message: CompanionMessage, exclude: str | None = None) -> int:
        """Broadcast message to all connected devices."""
        sent = 0
        for device_id in list(self.active_connections.keys()):
            if device_id != exclude:
                if await self.send_to_device(device_id, message):
                    sent += 1
        return sent
    
    async def broadcast_to_user(self, user_id: str, message: CompanionMessage) -> int:
        """Broadcast to all devices for a specific user."""
        sent = 0
        for device_id, device in self.devices.items():
            if device.user_id == user_id:
                if await self.send_to_device(device_id, message):
                    sent += 1
        return sent
    
    def get_connected_devices(self, user_id: str | None = None) -> list[CompanionDevice]:
        """Get list of connected devices."""
        devices = list(self.devices.values())
        if user_id:
            devices = [d for d in devices if d.user_id == user_id]
        return devices
    
    def update_device_heartbeat(self, device_id: str) -> None:
        """Update device last seen timestamp."""
        if device_id in self.devices:
            self.devices[device_id].last_seen = datetime.now(timezone.utc).isoformat()
            self.state.device_states[device_id]["last_seen"] = self.devices[device_id].last_seen
    
    def update_state(self, updates: dict[str, Any]) -> None:
        """Update shared state and broadcast to all devices."""
        for key, value in updates.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Broadcast state update
        asyncio.create_task(self.broadcast(CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="state_update",
            payload={"state": asdict(self.state)}
        )))


# Global connection manager
_connection_manager: CompanionConnectionManager | None = None


def get_connection_manager() -> CompanionConnectionManager:
    """Get global connection manager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = CompanionConnectionManager()
    return _connection_manager


def create_companion_app() -> FastAPI:
    """Create FastAPI app with WebSocket endpoints for companions."""
    app = FastAPI(title="Raven Companion API")
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    manager = get_connection_manager()
    
    @app.websocket("/ws/companion")
    async def companion_websocket(websocket: WebSocket):
        """WebSocket endpoint for companion devices."""
        await websocket.accept()
        
        # Wait for auth/device info message
        try:
            init_msg = await websocket.receive_text()
            init_data = json.loads(init_msg)
            
            if init_data.get("type") != "auth":
                await websocket.close(code=4001, reason="First message must be auth")
                return
            
            device_info = init_data.get("payload", {})
            device_id = await manager.connect(websocket, device_info)
            
            # Send queued messages
            queue = manager.message_queues.get(device_id)
            if queue:
                while not queue.empty():
                    msg = await queue.get()
                    await manager.send_to_device(device_id, msg)
            
            # Message loop
            while True:
                try:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    
                    # Update heartbeat
                    manager.update_device_heartbeat(device_id)
                    
                    # Handle message types
                    msg_type = msg.get("type")
                    
                    if msg_type == "ping":
                        await manager.send_to_device(device_id, CompanionMessage(
                            message_id=f"msg_{uuid.uuid4().hex[:8]}",
                            type="pong",
                            payload={"server_time": datetime.now(timezone.utc).isoformat()}
                        ))
                    
                    elif msg_type == "state_request":
                        await manager.send_to_device(device_id, CompanionMessage(
                            message_id=f"msg_{uuid.uuid4().hex[:8]}",
                            type="state_response",
                            payload={"state": asdict(manager.state)}
                        ))
                    
                    elif msg_type == "text":
                        # Forward to orchestrator for processing
                        await handle_companion_text(device_id, msg.get("payload", {}))
                    
                    elif msg_type == "voice_start":
                        manager.update_state({"voice_active": True, "listening": True})
                    
                    elif msg_type == "voice_stop":
                        manager.update_state({"voice_active": False, "listening": False})
                    
                    elif msg_type == "approval_response":
                        # Handle approval response
                        await handle_approval_response(device_id, msg.get("payload", {}))
                    
                    elif msg_type == "notification_dismissed":
                        # Remove notification
                        notif_id = msg.get("payload", {}).get("notification_id")
                        manager.state.notifications = [
                            n for n in manager.state.notifications 
                            if n.get("id") != notif_id
                        ]
                        manager.state.updated_at = datetime.now(timezone.utc).isoformat()
                    
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error handling message from {device_id}: {e}")
        
        except Exception as e:
            logger.error(f"Companion connection error: {e}")
        finally:
            await manager.disconnect(device_id)
    
    @app.get("/api/companion/devices")
    async def list_devices(user_id: str = "default"):
        """List connected companion devices."""
        devices = manager.get_connected_devices(user_id)
        return {"devices": [asdict(d) for d in devices]}
    
    @app.get("/api/companion/state")
    async def get_state(user_id: str = "default"):
        """Get current synchronized state."""
        if manager.state.user_id != user_id:
            return {"error": "User not connected"}
        return asdict(manager.state)
    
    @app.post("/api/companion/notify")
    async def send_notification(user_id: str, notification: dict[str, Any]):
        """Send notification to all user's devices."""
        notification["id"] = notification.get("id", f"notif_{uuid.uuid4().hex[:8]}")
        notification["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        manager.state.notifications.append(notification)
        manager.state.updated_at = datetime.now(timezone.utc).isoformat()
        
        await manager.broadcast_to_user(user_id, CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="notification",
            payload=notification
        ))
        
        return {"success": True, "notification_id": notification["id"]}
    
    @app.post("/api/companion/approval")
    async def request_approval(user_id: str, approval: dict[str, Any]):
        """Request approval from user on all devices."""
        approval["id"] = approval.get("id", f"approval_{uuid.uuid4().hex[:8]}")
        approval["timestamp"] = datetime.now(timezone.utc).isoformat()
        approval["status"] = "pending"
        
        manager.state.pending_approvals.append(approval)
        manager.state.updated_at = datetime.now(timezone.utc).isoformat()
        
        await manager.broadcast_to_user(user_id, CompanionMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            type="approval_request",
            payload=approval
        ))
        
        return {"success": True, "approval_id": approval["id"]}
    
    return app


async def handle_companion_text(device_id: str, payload: dict[str, Any]) -> None:
    """Handle text message from companion - forward to orchestrator."""
    # This will be wired to the message orchestrator
    logger.info(f"Text from companion {device_id}: {payload.get('text', '')[:50]}")


async def handle_approval_response(device_id: str, payload: dict[str, Any]) -> None:
    """Handle approval response from companion."""
    manager = get_connection_manager()
    approval_id = payload.get("approval_id")
    approved = payload.get("approved", False)
    
    # Update pending approvals
    for approval in manager.state.pending_approvals:
        if approval.get("id") == approval_id:
            approval["status"] = "approved" if approved else "rejected"
            approval["responded_at"] = datetime.now(timezone.utc).isoformat()
            approval["responded_by"] = device_id
            break
    
    manager.state.updated_at = datetime.now(timezone.utc).isoformat()
    
    # Broadcast response
    await manager.broadcast(CompanionMessage(
        message_id=f"msg_{uuid.uuid4().hex[:8]}",
        type="approval_response",
        payload={"approval_id": approval_id, "approved": approved, "device_id": device_id}
    ))