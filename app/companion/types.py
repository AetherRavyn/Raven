"""Typed contract for the RAVEN companion.

The companion is a thin renderer of the orchestrator's event bus.  It
runs as a native shell (Tauri desktop / Capacitor mobile) but speaks a
language-agnostic JSON-over-WebSocket protocol.  This module defines
the wire format as Python dataclasses so:

  * the reference Python client can exercise every endpoint;
  * tests can pin the contract down (round-trip JSON, version
    negotiation, ack semantics);
  * the future Rust/Swift/Kotlin ports have a stable spec to target.

Wire shape (every frame is one of):

  client → server:  {"kind": "hello", ...}
                   {"kind": "ping", "ts": <epoch>}
                   {"kind": "subscribe", "channels": [...]}
                   {"kind": "command", "id": ..., "intent": ..., "args": {...}}
                   {"kind": "ack", "id": ..., "ok": true|false}

  server → client:  {"kind": "welcome", "protocol_version": "1.0", ...}
                   {"kind": "pong", "ts": ..., "server_ts": ...}
                   {"kind": "status", "snapshot": {...}}
                   {"kind": "event", "id": ..., "channel": ..., "payload": {...}}
                   {"kind": "response", "id": ..., "ok": ..., "result": ...}

Every message carries a ``kind`` discriminator so a single JSON frame
is self-describing.  All times are epoch milliseconds.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


PROTOCOL_VERSION = "1.0"


class MessageKind(str, Enum):
    """Discriminator for every frame on the wire."""

    # client → server
    HELLO = "hello"
    PING = "ping"
    SUBSCRIBE = "subscribe"
    COMMAND = "command"
    ACK = "ack"
    # server → client
    WELCOME = "welcome"
    PONG = "pong"
    STATUS = "status"
    EVENT = "event"
    RESPONSE = "response"
    # shared
    ERROR = "error"


@dataclass
class Hello:
    """Sent by the client as the first frame after connect."""

    client: str = "raven-companion"
    platform: str = "unknown"  # "macos" | "windows" | "linux" | "ios" | "android"
    build: str = ""
    capabilities: list[str] = field(default_factory=list)
    auth_token: str = ""
    kind: str = "hello"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "client": self.client,
            "platform": self.platform,
            "build": self.build,
            "capabilities": list(self.capabilities),
            "auth_token": self.auth_token,
            "ts": _now_ms(),
        }


@dataclass
class Welcome:
    """Server's reply to Hello.  Pins the protocol version."""

    protocol_version: str = PROTOCOL_VERSION
    server: str = "raven-orchestrator"
    session_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    kind: str = "welcome"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "protocol_version": self.protocol_version,
            "server": self.server,
            "session_id": self.session_id or _new_id(),
            "capabilities": list(self.capabilities),
            "ts": _now_ms(),
        }


@dataclass
class Ping:
    ts: int = 0
    kind: str = "ping"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ts": self.ts or _now_ms()}


@dataclass
class Pong:
    ts: int = 0
    server_ts: int = 0
    kind: str = "pong"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ts": self.ts,
            "server_ts": self.server_ts or _now_ms(),
        }


@dataclass
class Subscribe:
    """Ask the server to start pushing events on these channels."""

    channels: list[str] = field(default_factory=list)
    kind: str = "subscribe"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "channels": list(self.channels)}


@dataclass
class Command:
    """User-issued intent routed through the orchestrator."""

    intent: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    kind: str = "command"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id or _new_id(),
            "intent": self.intent,
            "args": dict(self.args),
            "ts": _now_ms(),
        }


@dataclass
class Response:
    """Server's reply to a Command."""

    id: str = ""
    ok: bool = True
    result: Any = None
    error: str = ""
    kind: str = "response"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "ts": _now_ms(),
        }


@dataclass
class Ack:
    """Client confirms it processed a server-pushed event."""

    id: str = ""
    ok: bool = True
    note: str = ""
    kind: str = "ack"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "ok": self.ok,
            "note": self.note,
        }


@dataclass
class Status:
    """A snapshot of orchestrator health pushed on demand or on change."""

    cpu_pct: float = 0.0
    ram_pct: float = 0.0
    queue_depth: int = 0
    last_action: str = ""
    last_error: str = ""
    uptime_s: int = 0
    timestamp: int = 0
    kind: str = "status"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "cpu_pct": self.cpu_pct,
            "ram_pct": self.ram_pct,
            "queue_depth": self.queue_depth,
            "last_action": self.last_action,
            "last_error": self.last_error,
            "uptime_s": self.uptime_s,
            "ts": self.timestamp or _now_ms(),
        }


@dataclass
class Event:
    """Server-pushed event.  The companion renders this as a notification,
       tray update, or live-status change depending on the channel."""

    channel: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    priority: str = "normal"  # "low" | "normal" | "high"
    kind: str = "event"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id or _new_id(),
            "channel": self.channel,
            "priority": self.priority,
            "payload": dict(self.payload),
            "ts": _now_ms(),
        }


@dataclass
class ErrorFrame:
    """A protocol error (malformed frame, auth failed, etc.)."""

    code: str = ""
    message: str = ""
    kind: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": self.code,
            "message": self.message,
            "ts": _now_ms(),
        }


# ── helpers ──────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex


# Registry used by ``parse_frame`` — single source of truth for both
# the encoder and the decoder.
_FRAME_REGISTRY: dict[str, type] = {
    "hello": Hello,
    "welcome": Welcome,
    "ping": Ping,
    "pong": Pong,
    "subscribe": Subscribe,
    "command": Command,
    "response": Response,
    "ack": Ack,
    "status": Status,
    "event": Event,
    "error": ErrorFrame,
}


def parse_frame(data: dict[str, Any]) -> Any:
    """Decode a wire frame into its typed dataclass.

    Raises ``ValueError`` if the frame is missing a ``kind`` or the
    ``kind`` is unknown.  Unknown fields are silently dropped; callers
    that want strict validation should use :func:`parse_frame_strict`.
    """
    if not isinstance(data, dict):
        raise ValueError("frame must be a JSON object")
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValueError("frame missing 'kind' discriminator")
    cls = _FRAME_REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"unknown frame kind: {kind!r}")
    # Build the dataclass from the known fields.  Unknown fields are
    # silently dropped — the strict variant rejects them.
    known_fields = set(getattr(cls, "__dataclass_fields__", {}).keys())
    obj = cls()  # type: ignore[call-arg]
    extras: list[str] = []
    for k, v in data.items():
        if k == "kind":
            continue
        if k in known_fields:
            setattr(obj, k, v)
        else:
            extras.append(k)
    # Stash the unknown-field list on a non-slots attribute via a
    # subclass-free trick: use object.__setattr__ to bypass slots.
    if extras:
        object.__setattr__(obj, "extras", extras)
    return obj


def parse_frame_strict(data: dict[str, Any]) -> Any:
    """Like ``parse_frame`` but rejects any unknown field."""
    obj = parse_frame(data)
    extras = getattr(obj, "extras", None)
    if extras:
        raise ValueError(f"unknown fields in frame: {extras}")
    return obj


def encode(obj: Any) -> dict[str, Any]:
    """Encode a typed frame to a JSON-ready dict."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    raise TypeError(f"object of type {type(obj).__name__} is not a frame")


__all__ = [
    "PROTOCOL_VERSION",
    "MessageKind",
    "Hello",
    "Welcome",
    "Ping",
    "Pong",
    "Subscribe",
    "Command",
    "Response",
    "Ack",
    "Status",
    "Event",
    "ErrorFrame",
    "parse_frame",
    "parse_frame_strict",
    "encode",
]