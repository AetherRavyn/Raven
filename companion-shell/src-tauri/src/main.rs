// raven-companion — Tauri v2 binary entry point.
//
// This file is intentionally small.  The heavy lifting lives in
// `lib.rs` (protocol + client) and the WebSocket loop is wired
// into the Tauri runtime in the `commands` submodule below.  On
// platforms without webkit2gtk (CI on Linux), the binary won't
// build — that's expected; the library and its tests do.

#![cfg_attr(
    all(not(debug_assertions), target_os = "macos"),
    windows_subsystem = "windows"
)]

fn main() {
    raven_companion_lib::run();
}