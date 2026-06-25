//! Wire protocol types — mirror of `app/companion/types.py`.
//!
//! The shapes here are pinned to match the Python dataclasses
//! exactly.  If you change one side, change the other in the
//! same commit; the round-trip tests in
//! `tests/test_companion_shell_wire.py` will catch a drift.
//!
//! Wire format
//! -----------
//! Every frame is a JSON object with a `kind` discriminator.
//! Client → server: hello, ping, subscribe, command, ack.
//! Server → client: welcome, pong, status, event, response.
//! Shared: error.

use serde::{Deserialize, Serialize};

/// The 11 frame kinds documented in `app/companion/types.py`.
///
/// Each variant's ``as_str()`` matches the Python ``MessageKind``
/// enum value byte-for-byte.  A new kind added on one side
/// without the other is a contract break.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum MessageKind {
    /// Client opens a session.
    Hello,
    /// Server acknowledges the open.
    Welcome,
    /// Liveness probe (client → server).
    Ping,
    /// Liveness reply (server → client).
    Pong,
    /// Subscribe to one or more event channels.
    Subscribe,
    /// Client issues an intent.
    Command,
    /// Server pushes a status snapshot.
    Status,
    /// Server pushes a domain event.
    Event,
    /// Server returns a command result.
    Response,
    /// Client acknowledges receipt of a server frame.
    Ack,
    /// Either side reports a protocol-level error.
    Error,
}

impl MessageKind {
    /// Render the kind as it appears in the JSON ``kind`` field.
    pub fn as_str(&self) -> &'static str {
        match self {
            MessageKind::Hello => "hello",
            MessageKind::Welcome => "welcome",
            MessageKind::Ping => "ping",
            MessageKind::Pong => "pong",
            MessageKind::Subscribe => "subscribe",
            MessageKind::Command => "command",
            MessageKind::Status => "status",
            MessageKind::Event => "event",
            MessageKind::Response => "response",
            MessageKind::Ack => "ack",
            MessageKind::Error => "error",
        }
    }

    /// Parse the kind back from its wire form.  Unknown values
    /// return ``None`` so the caller can decide whether to drop
    /// or surface the frame.
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "hello" => Some(Self::Hello),
            "welcome" => Some(Self::Welcome),
            "ping" => Some(Self::Ping),
            "pong" => Some(Self::Pong),
            "subscribe" => Some(Self::Subscribe),
            "command" => Some(Self::Command),
            "status" => Some(Self::Status),
            "event" => Some(Self::Event),
            "response" => Some(Self::Response),
            "ack" => Some(Self::Ack),
            "error" => Some(Self::Error),
            _ => None,
        }
    }
}

/// The current system mode — pin a small enum so the JS frontend
/// can colour the status tile without parsing free-form strings.
///
/// Mirrors ``app.runtime.mode.Mode`` from the Python side.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StatusMode {
    /// Full functionality.
    Online,
    /// Reduced functionality, network-dependent paths paused.
    Degraded,
    /// Cached-only; outbound messages queued in the outbox.
    Offline,
    /// Operator override in effect.
    Manual,
}

impl StatusMode {
    /// Parse from the free-form ``status.snapshot.mode`` field.
    /// Defaults to ``Offline`` so an unknown value still yields
    /// a renderable UI state.
    pub fn from_str_or_default(s: &str) -> Self {
        match s.to_ascii_lowercase().as_str() {
            "online" => Self::Online,
            "degraded" => Self::Degraded,
            "offline" => Self::Offline,
            "manual" => Self::Manual,
            _ => Self::Offline,
        }
    }
}

/// First frame the client sends after the WebSocket opens.
///
/// Mirrors ``app.companion.types.Hello``.  ``ts`` is the local
/// epoch-ms at send time; the server's ``Welcome`` carries the
/// matching ``server_ts``.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hello {
    /// Must be ``"hello"``.
    pub kind: String,
    /// A human-readable client id (e.g. ``"raven-companion"``).
    pub client: String,
    /// ``"macos" | "windows" | "linux" | "ios" | "android"``.
    pub platform: String,
    /// Build tag from the Cargo ``CARGO_PKG_VERSION``.
    pub build: String,
    /// Free-form capability list (e.g. ``["status", "palette"]``).
    #[serde(default)]
    pub capabilities: Vec<String>,
    /// Bearer token; empty string for unauthenticated localhost.
    #[serde(default)]
    pub auth_token: String,
    /// Local epoch-ms at send time.
    pub ts: i64,
}

impl Hello {
    /// Build a Hello frame for the current shell.  ``platform``
    /// is determined at compile time via ``cfg!(target_os = ...)``.
    pub fn for_this_shell() -> Self {
        let platform = if cfg!(target_os = "macos") {
            "macos"
        } else if cfg!(target_os = "ios") {
            "ios"
        } else if cfg!(target_os = "windows") {
            "windows"
        } else if cfg!(target_os = "android") {
            "android"
        } else {
            "linux"
        };
        Self {
            kind: "hello".to_string(),
            client: "raven-companion".to_string(),
            platform: platform.to_string(),
            build: env!("CARGO_PKG_VERSION").to_string(),
            capabilities: vec!["status".to_string(), "palette".to_string()],
            auth_token: String::new(),
            ts: chrono::Utc::now().timestamp_millis(),
        }
    }
}

/// Server's reply to Hello.  Pins the protocol version.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Welcome {
    /// Must be ``"welcome"``.
    pub kind: String,
    /// ``"1.0"`` for the current protocol.
    pub protocol_version: String,
    /// ``"raven-orchestrator"`` for the production server.
    pub server: String,
    /// Opaque session id used in subsequent logs.
    pub session_id: String,
    /// Capabilities the server exposes (e.g. ``["tool", "memory"]``).
    #[serde(default)]
    pub capabilities: Vec<String>,
    /// Server-local epoch-ms at send time.
    pub ts: i64,
}

/// Liveness probe.  The server replies with a Pong that mirrors
/// the client ``ts`` and adds ``server_ts``.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ping {
    /// Must be ``"ping"``.
    pub kind: String,
    /// Local epoch-ms at send time.
    pub ts: i64,
}

/// Liveness reply.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Pong {
    /// Must be ``"pong"``.
    pub kind: String,
    /// Echo of the client ``ts``.
    pub ts: i64,
    /// Server-local epoch-ms at send time.
    pub server_ts: i64,
}

/// Subscribe to one or more event channels (e.g. ``"memory"``,
/// ``"audit"``, ``"tool"``).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subscribe {
    /// Must be ``"subscribe"``.
    pub kind: String,
    /// Channel names.
    pub channels: Vec<String>,
}

/// User-issued intent routed through the orchestrator.
///
/// ``id`` is a UUIDv4 generated client-side so a server reply can
/// be matched to the original command even if multiple are
/// in-flight.  This mirrors the Python ``Command.id`` field.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Command {
    /// Must be ``"command"``.
    pub kind: String,
    /// Unique id; UUIDv4 in production.
    pub id: String,
    /// Intent name (e.g. ``"send_email"``, ``"set_mode"``).
    pub intent: String,
    /// Free-form intent arguments.
    #[serde(default)]
    pub args: serde_json::Value,
}

/// Server's status snapshot.  Flat shape — pinned to
/// `app.companion.types.Status` field-for-field.  The orchestrator
/// sends these as the "current health" frame; the shell renders
/// them as the headline status tile.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Status {
    /// Must be ``"status"``.
    pub kind: String,
    /// CPU usage percentage.
    #[serde(default)]
    pub cpu_pct: f64,
    /// RAM usage percentage.
    #[serde(default)]
    pub ram_pct: f64,
    /// Number of frames currently buffered in the offline queue.
    #[serde(default)]
    pub queue_depth: i64,
    /// Last user-facing action the orchestrator performed.
    #[serde(default)]
    pub last_action: String,
    /// Last error message, if any.
    #[serde(default)]
    pub last_error: String,
    /// Process uptime in seconds.
    #[serde(default)]
    pub uptime_s: i64,
    /// Server-local epoch-ms at send time.  The Python dataclass
    /// names this ``timestamp``; we accept both via a serde alias.
    #[serde(default, alias = "timestamp")]
    pub ts: i64,
}

/// Server-pushed domain event.  ``payload`` is opaque.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    /// Must be ``"event"``.
    pub kind: String,
    /// Unique event id.
    pub id: String,
    /// Channel name (matches one of the subscribed channels).
    pub channel: String,
    /// Opaque event payload.
    pub payload: serde_json::Value,
    /// Server-local epoch-ms at send time.
    pub ts: i64,
}

/// Server's reply to a Command.  ``ok=false`` means the command
/// failed — ``error`` carries a human-readable reason.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    /// Must be ``"response"``.
    pub kind: String,
    /// Echo of the originating Command's ``id``.
    pub id: String,
    /// Whether the command succeeded.
    pub ok: bool,
    /// Free-form result on success.
    #[serde(default)]
    pub result: serde_json::Value,
    /// Human-readable error message on failure.
    #[serde(default)]
    pub error: String,
}

/// Client's ack of a server frame.  The server uses acks for
/// at-most-once delivery of ``Event`` and ``Status`` frames.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ack {
    /// Must be ``"ack"``.
    pub kind: String,
    /// Echo of the originating frame's id.
    pub id: String,
    /// ``true`` for success, ``false`` for parse error etc.
    pub ok: bool,
}

/// Either side's report of a protocol-level error.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorFrame {
    /// Must be ``"error"``.
    pub kind: String,
    /// Short code (e.g. ``"protocol_version_mismatch"``).
    pub code: String,
    /// Human-readable detail.
    pub message: String,
    /// Server-local epoch-ms at send time.
    pub ts: i64,
}

/// All wire frames in one enum.  Useful for tests and for the
/// log-stream consumer in `client::CompanionClient`.
#[derive(Debug, Clone)]
pub enum Frame {
    /// Client opens a session.
    Hello(Hello),
    /// Server → client welcome.
    Welcome(Welcome),
    /// Server → client pong.
    Pong(Pong),
    /// Server → client status snapshot.
    Status(Status),
    /// Server → client domain event.
    Event(Event),
    /// Server → client command reply.
    Response(Response),
    /// Client → server ping.
    Ping(Ping),
    /// Client → server subscribe.
    Subscribe(Subscribe),
    /// Client → server command.
    Command(Command),
    /// Client → server ack.
    Ack(Ack),
    /// Shared error frame.
    Error(ErrorFrame),
}

impl Frame {
    /// Dispatch a parsed JSON object to the right struct.
    ///
    /// Returns ``None`` for unknown ``kind`` values so the caller
    /// can decide to drop or log.  Unknown fields are tolerated
    /// (the protocol is additive); missing required fields are
    /// a hard error and surface as ``None`` so the wire loop
    /// sees a drop rather than a panic.
    pub fn from_json(v: &serde_json::Value) -> Option<Self> {
        let kind = v.get("kind")?.as_str()?;
        match MessageKind::from_str(kind)? {
            MessageKind::Hello => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Hello),
            MessageKind::Welcome => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Welcome),
            MessageKind::Pong => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Pong),
            MessageKind::Status => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Status),
            MessageKind::Event => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Event),
            MessageKind::Response => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Response),
            MessageKind::Ping => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Ping),
            MessageKind::Subscribe => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Subscribe),
            MessageKind::Command => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Command),
            MessageKind::Ack => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Ack),
            MessageKind::Error => serde_json::from_value(v.clone())
                .ok()
                .map(Frame::Error),
        }
    }

    /// The frame's discriminator string.
    pub fn kind(&self) -> &'static str {
        match self {
            Frame::Hello(_) => "hello",
            Frame::Welcome(_) => "welcome",
            Frame::Pong(_) => "pong",
            Frame::Status(_) => "status",
            Frame::Event(_) => "event",
            Frame::Response(_) => "response",
            Frame::Ping(_) => "ping",
            Frame::Subscribe(_) => "subscribe",
            Frame::Command(_) => "command",
            Frame::Ack(_) => "ack",
            Frame::Error(_) => "error",
        }
    }

    /// Serialize back to JSON.  Used by the test suite and by the
    /// offline queue (which writes pending frames to disk as JSON
    /// Lines so a crash mid-send doesn't lose them).
    pub fn to_json(&self) -> serde_json::Value {
        match self {
            Frame::Hello(f) => serde_json::to_value(f).expect("hello"),
            Frame::Welcome(f) => serde_json::to_value(f).expect("welcome"),
            Frame::Pong(f) => serde_json::to_value(f).expect("pong"),
            Frame::Status(f) => serde_json::to_value(f).expect("status"),
            Frame::Event(f) => serde_json::to_value(f).expect("event"),
            Frame::Response(f) => serde_json::to_value(f).expect("response"),
            Frame::Ping(f) => serde_json::to_value(f).expect("ping"),
            Frame::Subscribe(f) => serde_json::to_value(f).expect("subscribe"),
            Frame::Command(f) => serde_json::to_value(f).expect("command"),
            Frame::Ack(f) => serde_json::to_value(f).expect("ack"),
            Frame::Error(f) => serde_json::to_value(f).expect("error"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The wire format is contractually frozen — every kind has
    /// exactly one stable string.  A drift here surfaces as a
    /// Python-side parse error on the first Welcome frame.
    #[test]
    fn kind_strings_match_python_enum() {
        assert_eq!(MessageKind::Hello.as_str(), "hello");
        assert_eq!(MessageKind::Welcome.as_str(), "welcome");
        assert_eq!(MessageKind::Ping.as_str(), "ping");
        assert_eq!(MessageKind::Pong.as_str(), "pong");
        assert_eq!(MessageKind::Subscribe.as_str(), "subscribe");
        assert_eq!(MessageKind::Command.as_str(), "command");
        assert_eq!(MessageKind::Status.as_str(), "status");
        assert_eq!(MessageKind::Event.as_str(), "event");
        assert_eq!(MessageKind::Response.as_str(), "response");
        assert_eq!(MessageKind::Ack.as_str(), "ack");
        assert_eq!(MessageKind::Error.as_str(), "error");
    }

    #[test]
    fn kind_round_trips_through_str() {
        for k in [
            MessageKind::Hello,
            MessageKind::Welcome,
            MessageKind::Ping,
            MessageKind::Pong,
            MessageKind::Subscribe,
            MessageKind::Command,
            MessageKind::Status,
            MessageKind::Event,
            MessageKind::Response,
            MessageKind::Ack,
            MessageKind::Error,
        ] {
            assert_eq!(MessageKind::from_str(k.as_str()), Some(k));
        }
        assert_eq!(MessageKind::from_str("nonsense"), None);
    }

    #[test]
    fn status_mode_default_is_offline() {
        // Unknown modes must NOT crash — they downgrade to
        // Offline so the UI still renders.
        assert_eq!(
            StatusMode::from_str_or_default("nonsense"),
            StatusMode::Offline
        );
        assert_eq!(StatusMode::from_str_or_default("online"), StatusMode::Online);
        assert_eq!(
            StatusMode::from_str_or_default("DEGRADED"),
            StatusMode::Degraded
        );
    }

    #[test]
    fn hello_for_this_shell_has_platform_string() {
        let h = Hello::for_this_shell();
        assert_eq!(h.kind, "hello");
        assert_eq!(h.client, "raven-companion");
        // One of the five documented platform strings.
        assert!(
            ["macos", "windows", "linux", "ios", "android"].contains(&h.platform.as_str()),
            "unexpected platform: {}",
            h.platform
        );
        assert!(h.ts > 0);
    }

    #[test]
    fn frame_dispatch_drops_unknown_kind() {
        let v = serde_json::json!({"kind": "totally_new_kind"});
        assert!(Frame::from_json(&v).is_none());
    }

    #[test]
    fn frame_dispatch_drops_missing_kind() {
        let v = serde_json::json!({"foo": "bar"});
        assert!(Frame::from_json(&v).is_none());
    }

    #[test]
    fn welcome_round_trips() {
        let v = serde_json::json!({
            "kind": "welcome",
            "protocol_version": "1.0",
            "server": "raven-orchestrator",
            "session_id": "sess-123",
            "capabilities": ["tool", "memory"],
            "ts": 1700000000000_i64
        });
        let f = Frame::from_json(&v).expect("welcome dispatch");
        match &f {
            Frame::Welcome(w) => {
                assert_eq!(w.protocol_version, "1.0");
                assert_eq!(w.server, "raven-orchestrator");
                assert_eq!(w.session_id, "sess-123");
            }
            _ => panic!("expected Welcome, got {:?}", f.kind()),
        }
        // and back out
        let back = serde_json::to_value(match f {
            Frame::Welcome(w) => w,
            _ => unreachable!(),
        })
        .unwrap();
        assert_eq!(back, v);
    }
}