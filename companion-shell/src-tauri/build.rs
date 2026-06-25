// build.rs — Tauri v2 build hook.
//
// Optional: this file only runs the Tauri build hook when the
// `tauri-runtime` feature is enabled.  When the library is being
// built without Tauri (e.g. for unit tests on a host without
// webkit2gtk), the hook is skipped.

#[cfg(feature = "tauri-runtime")]
fn main() {
    tauri_build::build();
}

#[cfg(not(feature = "tauri-runtime"))]
fn main() {
    // No-op: the library is being built without Tauri's runtime
    // dependencies.  The binary's window construction lives in
    // src/tauri_app.rs (gated by the same feature flag).
}