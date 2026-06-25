//! RAVEN Companion — wire protocol types + offline queue.
//!
//! This crate mirrors the Python protocol in
//! `app/companion/types.py` and the queue semantics in
//! `app/companion/cache.py`.  Every frame on the wire is a JSON
//! object with a `kind` discriminator; we re-declare the small
//! subset the shell actually uses (Hello, Welcome, Ping, Pong,
//! Subscribe, Command, Status, Event, Response, Ack, Error).
//!
//! The crate is split into two layers:
//!
//!   * [`protocol`] — pure data types.  No I/O, no async.
//!   * [`client`]   — the WebSocket client + offline queue.  The
//!                    library form does not depend on Tauri's
//!                    runtime, so it can be unit-tested without
//!                    webkit2gtk.
//!
//! The binary (`src/main.rs`) wires this library into a Tauri
//! window so the JS frontend can invoke Rust commands via
//! `tauri::command`.

#![deny(missing_docs)]
#![deny(rust_2018_idioms)]

pub mod client;
pub mod notify;
pub mod protocol;
pub mod sidecar;
pub mod tray;

pub use client::{CompanionClient, CompanionEvent, ClientConfig, ConnectionState};
pub use notify::CoworkEventPayload;
#[cfg(feature = "tauri-runtime")]
pub use notify::maybe_notify;
pub use protocol::{
    Command, ErrorFrame, Event, Frame, Hello, MessageKind, Ping, Pong, Response, Status,
    StatusMode, Subscribe, Welcome,
};
pub use sidecar::{BackendHandle, BackendState, BackendStatus, SIDECAR_NAME};

/// Tauri runtime entry point.  On a system with webkit2gtk (or
/// WebKit on macOS) this builds the window and wires the
/// WebSocket loop into the event bus.  On a system without
/// webkit2gtk (CI on Linux), this falls back to a no-op so the
/// library still compiles for unit tests.
///
/// Splitting the entry point like this lets the dev workflow
/// stay simple: ``cargo test --lib`` runs without ever touching
/// Tauri, and ``cargo tauri dev`` (in the project root) does the
/// full build.
#[cfg(feature = "tauri-runtime")]
pub fn run() {
    tauri_build_window();
}

/// No-op fallback for CI on hosts without webkit2gtk.
///
/// The library form of the crate is intended for unit tests and
/// for headless deployments.  When you build with
/// ``--features tauri-runtime`` on a host with webkit2gtk / WebKit,
/// this stub is replaced by the real ``tauri_app::run`` entry
/// point that opens a window and wires the WebSocket loop into
/// the event bus.
#[cfg(not(feature = "tauri-runtime"))]
pub fn run() {
    eprintln!(
        "raven-companion built without tauri-runtime feature; \
         this is the library stub.  Run via `cargo tauri dev` \
         on a host with webkit2gtk (Linux) or WebKit (macOS) to \
         launch the window."
    );
}

#[cfg(feature = "tauri-runtime")]
fn tauri_build_window() {
    // The full Tauri wiring lives in `tauri_app.rs` so the
    // webkit2gtk-heavy import is gated behind a feature flag.
    #[path = "tauri_app.rs"]
    mod tauri_app;
    tauri_app::run();
}
