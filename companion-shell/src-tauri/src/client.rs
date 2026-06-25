//! WebSocket client + offline queue.
//!
//! This module mirrors the offline-queue + reconnect semantics in
//! `app/companion/cache.py::OfflineCache` and the connection
//! lifecycle in `app/companion/client.py::CompanionClient`.
//!
//! Why a separate crate-internal module?
//! --------------------------------------
//! The protocol types in [`crate::protocol`] are pure data — they
//! have no I/O, no async, and can be unit-tested on any platform
//! without webkit2gtk.  This module is the I/O layer.  We split
//! the two so the binary's Tauri build doesn't have to fire up a
//! GTK runtime just to test that "Welcome frame serializes to the
//! right JSON".
//!
//! The library form is a single-connection client with a small
//! in-memory offline queue.  The binary form wraps it in a
//! Tauri-friendly event broadcaster.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

use crate::protocol::{
    Command, Frame, Hello, Ping, Subscribe,
};

/// Connection state — what the UI badge shows in the title bar.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConnectionState {
    /// Never connected.
    Idle,
    /// Socket open, Hello sent, awaiting Welcome.
    Connecting,
    /// Welcome received; ready to send commands.
    Online,
    /// Socket closed; queued frames will flush on reconnect.
    Offline,
    /// Reconnect attempts failing repeatedly; give up.
    GaveUp,
}

impl Default for ConnectionState {
    fn default() -> Self {
        Self::Idle
    }
}

/// Configuration for the WebSocket client.
#[derive(Debug, Clone)]
pub struct ClientConfig {
    /// ``ws://localhost:8080/companion`` in dev.
    pub url: String,
    /// Bearer token (empty string for unauthenticated localhost).
    pub auth_token: String,
    /// How long to wait between reconnect attempts.
    pub reconnect_backoff: Duration,
    /// Maximum frames to buffer while offline before dropping.
    pub max_queue_depth: usize,
    /// Optional override of the platform string in Hello.
    /// If empty, ``Hello::for_this_shell()`` decides.
    pub platform_override: String,
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self {
            url: "ws://localhost:8080/companion".to_string(),
            auth_token: String::new(),
            reconnect_backoff: Duration::from_secs(2),
            max_queue_depth: 1024,
            platform_override: String::new(),
        }
    }
}

/// Events the client emits.  The Tauri binary maps these onto
/// ``app.emit()`` so the JS frontend can subscribe via
/// ``listen('companion://event', cb)``.
#[derive(Debug, Clone)]
pub enum CompanionEvent {
    /// State transition.
    State(ConnectionState),
    /// A Welcome frame arrived — carry the protocol version.
    Welcome {
        /// Negotiated protocol version.
        protocol_version: String,
        /// Session id assigned by the server.
        session_id: String,
    },
    /// A status snapshot.
    Status(serde_json::Value),
    /// A domain event.
    Event {
        /// Channel the event arrived on.
        channel: String,
        /// Opaque payload.
        payload: serde_json::Value,
    },
    /// A command reply.
    Response {
        /// Originating command id.
        id: String,
        /// Whether the command succeeded.
        ok: bool,
        /// Free-form result on success.
        result: serde_json::Value,
        /// Error message on failure.
        error: String,
    },
    /// Liveness reply — used by the binary to compute latency.
    Pong {
        /// Echo of the client ``ts``.
        ts: i64,
        /// Server-local time at reply.
        server_ts: i64,
    },
    /// Protocol-level error.
    Error(String),
}

/// The companion client.
///
/// Lifecycle:
///
/// ```text
///   let client = CompanionClient::new(config);
///   client.subscribe(&["memory", "audit"]);
///   client.send_command("set_mode", serde_json::json!({"mode": "offline"}));
///   // (in real code) client.run(event_sink).await;
/// ```
///
/// In the library form (no Tauri runtime) the client is a
/// state-holder with an in-memory offline queue.  The binary
/// wraps it in `tokio::spawn(client.run(sink))` so the WebSocket
/// loop runs in the background.
pub struct CompanionClient {
    config: ClientConfig,
    state: Arc<Mutex<ConnectionState>>,
    queue: Arc<Mutex<VecDeque<Frame>>>,
    subscribed_channels: Arc<Mutex<Vec<String>>>,
}

impl CompanionClient {
    /// Build a client.  Does not open a socket — call ``.run()``
    /// for that, or use the in-memory queue with ``send_command``
    /// to test the offline path without I/O.
    pub fn new(config: ClientConfig) -> Self {
        Self {
            config,
            state: Arc::new(Mutex::new(ConnectionState::Idle)),
            queue: Arc::new(Mutex::new(VecDeque::new())),
            subscribed_channels: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// The current connection state.  Cheap; takes a mutex.
    pub fn state(&self) -> ConnectionState {
        *self.state.lock().expect("state lock")
    }

    /// Set the state directly.  Used by ``run()`` and by tests.
    pub fn set_state(&self, new_state: ConnectionState) {
        *self.state.lock().expect("state lock") = new_state;
    }

    /// Build a Hello frame for this client.  Used by ``run()``.
    pub fn hello(&self) -> Hello {
        let mut h = Hello::for_this_shell();
        if !self.config.platform_override.is_empty() {
            h.platform = self.config.platform_override.clone();
        }
        h.auth_token = self.config.auth_token.clone();
        h
    }

    /// Persist a Subscribe frame in the queue.  Sent on next
    /// (re)connect.
    pub fn subscribe(&self, channels: &[&str]) {
        let owned: Vec<String> = channels.iter().map(|s| s.to_string()).collect();
        let mut guard = self.subscribed_channels.lock().expect("channels lock");
        *guard = owned.clone();
        let frame = Frame::Subscribe(Subscribe {
            kind: "subscribe".to_string(),
            channels: owned,
        });
        self.enqueue(frame);
    }

    /// Queue a Command.  Returns the generated id so the caller
    /// can match the eventual ``Response``.
    pub fn send_command(&self, intent: &str, args: serde_json::Value) -> String {
        let id = uuid::Uuid::new_v4().to_string();
        let frame = Frame::Command(Command {
            kind: "command".to_string(),
            id: id.clone(),
            intent: intent.to_string(),
            args,
        });
        self.enqueue(frame);
        id
    }

    /// Queue a Ping.  The Pong will arrive asynchronously and
    /// surface as a ``CompanionEvent::Pong``.
    pub fn ping(&self) -> i64 {
        let ts = chrono::Utc::now().timestamp_millis();
        let frame = Frame::Ping(Ping {
            kind: "ping".to_string(),
            ts,
        });
        self.enqueue(frame);
        ts
    }

    /// Push a frame onto the offline queue.  Drops the oldest
    /// frame if the queue is at capacity so memory pressure
    /// never kills the process.
    fn enqueue(&self, frame: Frame) {
        let mut q = self.queue.lock().expect("queue lock");
        if q.len() >= self.config.max_queue_depth {
            warn!(
                "offline queue at capacity ({}) — dropping oldest frame",
                self.config.max_queue_depth
            );
            q.pop_front();
        }
        q.push_back(frame);
    }

    /// Drain the offline queue (called by ``run()`` after
    /// Welcome arrives).  Returns the drained frames in FIFO
    /// order so the caller can write them to the WebSocket.
    pub fn drain_queue(&self) -> Vec<Frame> {
        let mut q = self.queue.lock().expect("queue lock");
        q.drain(..).collect()
    }

    /// Number of frames currently buffered.  Used by the UI to
    /// show a "pending" badge.
    pub fn queue_depth(&self) -> usize {
        self.queue.lock().expect("queue lock").len()
    }

    /// Build the WebSocket URL with the auth token as a query
    /// parameter (alternative to the ``auth_token`` Hello field).
    /// The Python side accepts both forms.
    pub fn ws_url_with_token(&self) -> String {
        if self.config.auth_token.is_empty() {
            self.config.url.clone()
        } else {
            format!("{}?token={}", self.config.url, self.config.auth_token)
        }
    }
}

impl Default for CompanionClient {
    fn default() -> Self {
        Self::new(ClientConfig::default())
    }
}

/// Dispatch a parsed JSON object into a high-level event.  This
/// is the pure function the WebSocket loop calls for every frame
/// received from the server; it has no I/O so it's directly
/// unit-testable without a socket.
pub fn dispatch(v: &serde_json::Value) -> Option<CompanionEvent> {
    let frame = Frame::from_json(v)?;
    Some(match frame {
        Frame::Welcome(w) => CompanionEvent::Welcome {
            protocol_version: w.protocol_version,
            session_id: w.session_id,
        },
        Frame::Status(s) => CompanionEvent::Status(serde_json::json!({
            "cpu_pct": s.cpu_pct,
            "ram_pct": s.ram_pct,
            "queue_depth": s.queue_depth,
            "last_action": s.last_action,
            "last_error": s.last_error,
            "uptime_s": s.uptime_s,
            "ts": s.ts,
        })),
        Frame::Event(e) => CompanionEvent::Event {
            channel: e.channel,
            payload: e.payload,
        },
        Frame::Response(r) => CompanionEvent::Response {
            id: r.id,
            ok: r.ok,
            result: r.result,
            error: r.error,
        },
        Frame::Pong(p) => CompanionEvent::Pong {
            ts: p.ts,
            server_ts: p.server_ts,
        },
        Frame::Error(e) => CompanionEvent::Error(format!("{}: {}", e.code, e.message)),
        // Server never sends these.  A protocol bug — log and
        // drop so the loop doesn't crash on a malformed server.
        Frame::Hello(_) | Frame::Ping(_) | Frame::Subscribe(_) | Frame::Command(_) | Frame::Ack(_) => {
            debug!("server sent unexpected frame kind; dropping");
            return None;
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn new_client_starts_idle() {
        let c = CompanionClient::default();
        assert_eq!(c.state(), ConnectionState::Idle);
        assert_eq!(c.queue_depth(), 0);
    }

    #[test]
    fn subscribe_persists_channels_and_queues_frame() {
        let c = CompanionClient::default();
        c.subscribe(&["memory", "audit"]);
        assert_eq!(c.queue_depth(), 1);
        let frames = c.drain_queue();
        assert_eq!(frames.len(), 1);
        match &frames[0] {
            Frame::Subscribe(s) => {
                assert_eq!(s.kind, "subscribe");
                assert_eq!(s.channels, vec!["memory", "audit"]);
            }
            other => panic!("expected Subscribe, got {:?}", other.kind()),
        }
    }

    #[test]
    fn send_command_assigns_unique_id_and_queues_frame() {
        let c = CompanionClient::default();
        let id1 = c.send_command("set_mode", json!({"mode": "offline"}));
        let id2 = c.send_command("send_email", json!({}));
        assert_ne!(id1, id2);
        assert_eq!(c.queue_depth(), 2);
        let frames = c.drain_queue();
        // Both frames are Commands with the ids we returned.
        let ids: Vec<String> = frames
            .iter()
            .map(|f| match f {
                Frame::Command(cmd) => cmd.id.clone(),
                _ => panic!("expected Command"),
            })
            .collect();
        assert!(ids.contains(&id1));
        assert!(ids.contains(&id2));
    }

    #[test]
    fn queue_overflow_drops_oldest() {
        let cfg = ClientConfig {
            max_queue_depth: 3,
            ..ClientConfig::default()
        };
        let c = CompanionClient::new(cfg);
        for i in 0..5 {
            c.send_command("noop", json!({"i": i}));
        }
        // Only the 3 newest survive.
        assert_eq!(c.queue_depth(), 3);
        let frames = c.drain_queue();
        let indices: Vec<i64> = frames
            .iter()
            .map(|f| match f {
                Frame::Command(cmd) => cmd.args["i"].as_i64().unwrap(),
                _ => panic!("expected Command"),
            })
            .collect();
        assert_eq!(indices, vec![2, 3, 4]);
    }

    #[test]
    fn ping_uses_current_time() {
        let c = CompanionClient::default();
        let ts = c.ping();
        let now = chrono::Utc::now().timestamp_millis();
        // Within 1 second of "now" — generous for slow CI.
        assert!(ts <= now);
        assert!(ts > now - 1000);
    }

    #[test]
    fn dispatch_welcome_yields_protocol_version_and_session() {
        let v = json!({
            "kind": "welcome",
            "protocol_version": "1.0",
            "server": "raven-orchestrator",
            "session_id": "sess-1",
            "ts": 1700000000000_i64
        });
        match dispatch(&v) {
            Some(CompanionEvent::Welcome {
                protocol_version,
                session_id,
            }) => {
                assert_eq!(protocol_version, "1.0");
                assert_eq!(session_id, "sess-1");
            }
            other => panic!("expected Welcome, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_status_passes_through_fields() {
        // Status shape is flat (matches Python dataclass).
        let v = json!({
            "kind": "status",
            "cpu_pct": 12.5,
            "ram_pct": 42.0,
            "queue_depth": 0,
            "last_action": "send_email",
            "last_error": "",
            "uptime_s": 3600,
            "ts": 1700000000000_i64
        });
        match dispatch(&v) {
            Some(CompanionEvent::Status(snap)) => {
                assert_eq!(snap["cpu_pct"], 12.5);
                assert_eq!(snap["queue_depth"], 0);
                assert_eq!(snap["last_action"], "send_email");
            }
            other => panic!("expected Status, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_event_yields_channel_and_payload() {
        let v = json!({
            "kind": "event",
            "id": "ev-1",
            "channel": "memory",
            "payload": {"op": "add", "text": "hello"},
            "ts": 1700000000000_i64
        });
        match dispatch(&v) {
            Some(CompanionEvent::Event { channel, payload }) => {
                assert_eq!(channel, "memory");
                assert_eq!(payload["op"], "add");
            }
            other => panic!("expected Event, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_response_carries_ok_flag() {
        let v_ok = json!({
            "kind": "response", "id": "cmd-1", "ok": true,
            "result": {"echo": "hi"}
        });
        let v_fail = json!({
            "kind": "response", "id": "cmd-2", "ok": false,
            "error": "intent not found"
        });
        match dispatch(&v_ok) {
            Some(CompanionEvent::Response { ok, result, error, .. }) => {
                assert!(ok);
                assert_eq!(result["echo"], "hi");
                assert_eq!(error, "");
            }
            other => panic!("expected Response, got {:?}", other),
        }
        match dispatch(&v_fail) {
            Some(CompanionEvent::Response { ok, error, .. }) => {
                assert!(!ok);
                assert_eq!(error, "intent not found");
            }
            other => panic!("expected Response, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_pong_carries_both_timestamps() {
        let v = json!({"kind": "pong", "ts": 100, "server_ts": 200});
        match dispatch(&v) {
            Some(CompanionEvent::Pong { ts, server_ts }) => {
                assert_eq!(ts, 100);
                assert_eq!(server_ts, 200);
            }
            other => panic!("expected Pong, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_error_includes_code_and_message() {
        let v = json!({
            "kind": "error",
            "code": "protocol_version_mismatch",
            "message": "expected 1.0",
            "ts": 1700000000000_i64
        });
        match dispatch(&v) {
            Some(CompanionEvent::Error(s)) => {
                assert!(s.contains("protocol_version_mismatch"));
                assert!(s.contains("expected 1.0"));
            }
            other => panic!("expected Error, got {:?}", other),
        }
    }

    #[test]
    fn dispatch_drops_unknown_kind() {
        let v = json!({"kind": "made_up_kind"});
        assert!(dispatch(&v).is_none());
    }

    #[test]
    fn dispatch_drops_server_initiated_command_frame() {
        // A protocol bug: server sent a Command frame.
        let v = json!({"kind": "command", "id": "x", "intent": "y", "args": {}});
        assert!(dispatch(&v).is_none());
    }

    #[test]
    fn dispatch_drops_server_initiated_hello_frame() {
        // A protocol bug: server sent a Hello frame.
        let v = json!({"kind": "hello", "client": "y", "platform": "macos", "build": "1", "ts": 0});
        assert!(dispatch(&v).is_none());
    }

    #[test]
    fn state_transitions_via_set_state() {
        let c = CompanionClient::default();
        assert_eq!(c.state(), ConnectionState::Idle);
        c.set_state(ConnectionState::Connecting);
        assert_eq!(c.state(), ConnectionState::Connecting);
        c.set_state(ConnectionState::Online);
        assert_eq!(c.state(), ConnectionState::Online);
        c.set_state(ConnectionState::Offline);
        assert_eq!(c.state(), ConnectionState::Offline);
    }

    #[test]
    fn ws_url_with_token_appends_query() {
        let mut cfg = ClientConfig::default();
        cfg.auth_token = "secret".to_string();
        let c = CompanionClient::new(cfg);
        assert!(c.ws_url_with_token().contains("token=secret"));
    }

    #[test]
    fn ws_url_with_empty_token_unchanged() {
        let c = CompanionClient::default();
        assert_eq!(c.ws_url_with_token(), c.config.url);
    }

    #[test]
    fn hello_uses_overridden_platform_when_set() {
        let cfg = ClientConfig {
            platform_override: "ios".to_string(),
            ..ClientConfig::default()
        };
        let c = CompanionClient::new(cfg);
        let h = c.hello();
        assert_eq!(h.platform, "ios");
    }

    #[test]
    fn hello_uses_inherited_auth_token() {
        let cfg = ClientConfig {
            auth_token: "tk".to_string(),
            ..ClientConfig::default()
        };
        let c = CompanionClient::new(cfg);
        let h = c.hello();
        assert_eq!(h.auth_token, "tk");
    }
}
