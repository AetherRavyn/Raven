// AetherRavyn Desktop — Tauri IPC Commands

use serde::{Deserialize, Serialize};
use std::process::Command;
use tauri::Manager;

#[derive(Serialize, Deserialize)]
pub struct SystemStatus {
    pub online: bool,
    pub uptime: String,
    pub cpu: f64,
    pub memory_used_gb: f64,
    pub memory_total_gb: f64,
    pub tools_count: usize,
    pub agents_count: usize,
}

#[derive(Serialize, Deserialize)]
pub struct Goal {
    pub title: String,
    pub status: String,
    pub priority: String,
}

/// Check if the ravyn daemon is running
#[tauri::command]
fn check_daemon() -> Result<bool, String> {
    let output = Command::new("sh")
        .args(["-c", "curl -s -o /dev/null -w '%{http_code}' http://localhost:8090/status"])
        .output()
        .map_err(|e| e.to_string())?;
    let code = String::from_utf8_lossy(&output.stdout);
    Ok(code.trim() == "200")
}

/// Get system status from the Python backend
#[tauri::command]
async fn get_status() -> Result<String, String> {
    let output = Command::new("sh")
        .args(["-c", "curl -s http://localhost:8090/api/system/status"])
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Send a message to the orchestrator via REST
#[tauri::command]
async fn send_message(text: String) -> Result<String, String> {
    let body = serde_json::json!({
        "user_id": "desktop_user",
        "text": text,
        "platform": "desktop"
    });
    let output = Command::new("sh")
        .args([
            "-c",
            &format!(
                "curl -s -X POST http://localhost:8090/message -H 'Content-Type: application/json' -d '{}'",
                body.to_string().replace('\'', "'\\''")
            ),
        ])
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// List goals from the backend
#[tauri::command]
async fn list_goals() -> Result<String, String> {
    let output = Command::new("sh")
        .args(["-c", "curl -s http://localhost:8090/api/goals"])
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Trigger screen capture + OCR
#[tauri::command]
async fn capture_screen() -> Result<String, String> {
    let output = Command::new("sh")
        .args(["-c", "scrot -o /tmp/ravyn_screen.png && echo 'captured'"])
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Toggle the HUD overlay window
#[tauri::command]
async fn toggle_overlay(app: tauri::AppHandle) -> Result<bool, String> {
    if let Some(window) = app.get_webview_window("overlay") {
        // Overlay exists — toggle visibility
        let visible = window.is_visible().map_err(|e| e.to_string())?;
        if visible {
            window.hide().map_err(|e| e.to_string())?;
            Ok(false)
        } else {
            window.show().map_err(|e| e.to_string())?;
            Ok(true)
        }
    } else {
        // Create the overlay window
        let _overlay = tauri::WebviewWindowBuilder::new(
            &app,
            "overlay",
            tauri::WebviewUrl::App("overlay.html".into()),
        )
        .title("AetherRavyn HUD")
        .inner_size(300.0, 420.0)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .resizable(false)
        .skip_taskbar(true)
        .position(1580.0, 60.0)
        .build()
        .map_err(|e| e.to_string())?;
        Ok(true)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            check_daemon,
            get_status,
            send_message,
            list_goals,
            capture_screen,
            toggle_overlay,
        ])
        .run(tauri::generate_context!())
        .expect("error while running AetherRavyn Desktop");
}
