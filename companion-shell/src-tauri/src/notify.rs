//! Tauri-side native notifications.
//!
//! v36 (2026-06-23): Cowork desktop integration.  When the
//! backend emits a ``plan_proposed`` / ``approval_needed`` /
//! ``step_done`` / ``session_done`` / ``session_failed`` event,
//! the shell surfaces it as a native OS notification so the
//! user notices even when the window is hidden behind another
//! app or minimised to the tray.
//!
//! Mapping (event kind → title + body):
//!   * plan_proposed        → "Plan ready for review"
//!   * approval_needed      → "Approval needed: <step title>"
//!   * step_done            → "Step done: <title>"   (only if high-risk)
//!   * step_failed          → "Step failed: <title>"
//!   * session_paused       → "Session paused"
//!   * session_resumed      → "Session resumed"
//!   * session_stopped      → "Session stopped"
//!   * session_done         → "Session complete"
//!   * session_failed       → "Session failed"
//!
//! The notification is fired by the same SSE stream the
//! dashboard reads; the shell subscribes to a Tauri-internal
//! ``cowork://event`` channel published by the boot iframe.
use serde::Deserialize;

/// Payload deserialized from the dashboard's ``cowork://event``
/// Tauri event.  Same shape as :class:`app.cowork.session.CoworkEvent`.
#[derive(Debug, Deserialize)]
pub struct CoworkEventPayload {
    /// Event kind, e.g. ``plan_proposed`` / ``approval_needed`` /
    /// ``step_done`` / ``session_done``.
    pub kind: String,
    /// Free-form per-event payload (JSON object).
    pub payload: serde_json::Value,
    /// Session the event belongs to.
    pub session_id: String,
}

#[cfg(feature = "tauri-runtime")]
use tauri::AppHandle;
#[cfg(feature = "tauri-runtime")]
use tauri_plugin_notification::NotificationExt;

/// Build a friendly title + body for *event* and fire a native
/// notification.  Returns ``true`` if the event triggered one.
#[cfg(feature = "tauri-runtime")]
pub fn maybe_notify(app: &AppHandle, event: CoworkEventPayload) -> bool {
    let (title, body) = match event.kind.as_str() {
        "plan_proposed" => (
            "RAVEN — Plan ready for review".to_string(),
            "Open Cowork to approve the steps.".to_string(),
        ),
        "approval_needed" => {
            let step_title = event
                .payload
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("a step");
            (
                "RAVEN — Approval needed".to_string(),
                format!("Step: {step_title}"),
            )
        }
        "step_failed" => {
            let step_title = event
                .payload
                .get("step_id")
                .and_then(|v| v.as_str())
                .unwrap_or("step");
            (
                "RAVEN — Step failed".to_string(),
                format!("Step {step_title} failed."),
            )
        }
        "session_paused" => ("RAVEN — Session paused".to_string(), String::new()),
        "session_resumed" => ("RAVEN — Session resumed".to_string(), String::new()),
        "session_stopped" => ("RAVEN — Session stopped".to_string(), String::new()),
        "session_done" => (
            "RAVEN — Session complete".to_string(),
            "All steps finished.".to_string(),
        ),
        "session_failed" => (
            "RAVEN — Session failed".to_string(),
            "Open the dashboard for details.".to_string(),
        ),
        _ => return false,
    };

    if let Err(e) = app
        .notification()
        .builder()
        .title(title)
        .body(body)
        .show()
    {
        tracing::warn!("notification failed: {e}");
    }
    true
}
