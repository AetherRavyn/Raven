//! Tauri v2 wiring for the RAVEN desktop shell.
//!
//! v36 (2026-06-23): this module is the **real** desktop app.
//! It owns the Python backend (spawned as a Tauri sidecar with
//! automatic crash recovery), builds a native menu bar + system
//! tray, fires native notifications, persists window state,
//! enforces single-instance, supports ``raven://`` deep links,
//! checks for updates, and renders the full RAVEN dashboard
//! inside a webview.
//!
//! Architecture
//! ------------
//! On ``setup`` we:
//!  - read :class:`sidecar::BackendHandle` from state;
//!  - spawn the bundled ``raven-backend`` binary and wait for it
//!    to answer ``/api/system/status``; a supervisor restarts it
//!    on crash (with exponential backoff, capped);
//!  - build the native menu bar + system tray;
//!  - start a poller that hits ``/api/cowork/sessions/current``
//!    every 2s and toggles the Cowork menu items based on the
//!    active session's state;
//!  - wire the legacy companion WebSocket loop so the dashboard
//!    can still use the legacy protocol for low-latency control
//!    commands.
//! 2. Tauri events:
//!    * ``backend://status``     → BackendStatus snapshots
//!    * ``shell://navigate``     → dashboard navigation
//!    * ``shell://menu``         → cowork intents / about / docs
//!    * ``shell://deep-link``    → ``raven://`` URL payloads
//!    * ``companion://state``    → legacy WS state
//!    * ``companion://frame``    → legacy WS frames
//!    * ``cowork://event``       → forwarded Cowork events
//! 3. On close, the sidecar is signalled and killed cleanly.
//! 4. macOS: window-close hides to tray; Linux/Windows: quit.
//!
//! IPC surface
//! -----------
//! - ``invoke('backend_url')``     → string
//! - ``invoke('backend_status')``  → BackendStatus
//! - ``invoke('retry_backend')``   → string (new URL)
//! - ``invoke('connection_state')``→ ConnectionState (legacy)
//! - ``invoke('send_command', ...)``→ command id (legacy WS)
//! - ``invoke('check_for_update')``→ UpdateInfo | null
//! - ``invoke('set_autostart', {enabled})`` → bool

use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::client::{ClientConfig, CompanionClient, ConnectionState};
use crate::sidecar::{BackendHandle, BackendStatus};
use crate::tray;

#[cfg(feature = "tauri-runtime")]
pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info,raven_companion_lib=debug")),
        )
        .init();

    let backend = BackendHandle::new();

    // Legacy companion WS client (kept for the protocol round-trip
    // tests; new shells should call the FastAPI server over HTTP).
    let url = std::env::var("RAVEN_COMPANION_URL")
        .unwrap_or_else(|_| "ws://localhost:8080/companion".to_string());
    let auth_token = std::env::var("RAVEN_COMPANION_TOKEN").unwrap_or_default();
    let ws_client = Arc::new(CompanionClient::new(ClientConfig {
        url,
        auth_token,
        ..ClientConfig::default()
    }));

    tauri::Builder::default()
        // Single-instance: focus the existing window when the user
        // launches a second copy (e.g. by double-clicking the icon
        // while we're already running).  The ``deep-link`` feature
        // means URLs passed on the command line are forwarded here.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            tracing::info!("second instance launched with: {argv:?}");
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
            // Forward any raven:// URLs from the second instance.
            for arg in argv.iter().skip(1) {
                if let Some(url) = parse_deep_link(arg) {
                    let _ = app.emit("shell://deep-link", url);
                }
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--autostarted"]),
        ))
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_log::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::default().build())
        .manage(backend)
        .manage(AppState {
            client: ws_client.clone(),
        })
        .setup(move |app| {
            let handle = app.handle().clone();

            // 1. Spawn the bundled backend (with supervisor).
            //    The async block needs its own AppHandle clone so
            //    the future is 'static.
            let spawn_handle = handle.clone();
            let backend_for_spawn = BackendHandle::from_state(&handle);
            tauri::async_runtime::spawn(async move {
                if let Err(e) = backend_for_spawn.spawn(&spawn_handle).await {
                    tracing::error!("failed to spawn sidecar: {e:?}");
                }
            });

            // 2. Build menu + tray.
            let cowork_menu = match tray::build_menu(&handle) {
                Ok(m) => Some(m),
                Err(e) => {
                    tracing::warn!("build_menu: {e:?}");
                    None
                }
            };
            if let Err(e) = tray::build_tray(&handle) {
                tracing::warn!("build_tray: {e:?}");
            }
            if let Some(m) = cowork_menu {
                app.manage(m);
            }

            // 3. Start the cowork-state poller.
            let poller_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                run_cowork_state_poller(poller_handle).await;
            });

            // 4. Wire the legacy companion WS loop.
            let handle2 = handle.clone();
            tauri::async_runtime::spawn(async move {
                run_websocket_loop(ws_client, handle2).await;
            });

            // 5. Register the deep-link handler on Linux/Windows.
            #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                let handle_for_dl = handle.clone();
                app.deep_link().on_open_url(move |event| {
                    for url in event.urls() {
                        let _ = handle_for_dl.emit("shell://deep-link", url.to_string());
                    }
                });
            }
            Ok(())
        })
        .on_menu_event(|app, event| {
            tray::forward_menu_event(app, &event);
        })
        .invoke_handler(tauri::generate_handler![
            backend_url,
            backend_status,
            retry_backend,
            connection_state,
            send_command,
            subscribe,
            ping,
            check_for_update,
            set_autostart,
            get_autostart,
            open_log_dir,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Hide instead of quit on close (macOS convention) so
                // the user can keep the backend running in the tray.
                #[cfg(target_os = "macos")]
                {
                    let _ = window.hide();
                    api.prevent_close();
                }
                #[cfg(not(target_os = "macos"))]
                {
                    // On Linux/Windows, exit cleanly so the sidecar
                    // is killed by the Drop handler.
                    let _ = window;
                    let _ = api;
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running raven");
}

#[cfg(feature = "tauri-runtime")]
struct AppState {
    client: Arc<CompanionClient>,
}

// ── BackendHandle convenience accessor ────────────────────────────

#[cfg(feature = "tauri-runtime")]
impl BackendHandle {
    /// Get a handle from Tauri's managed state.  Used inside
    /// ``setup`` to bridge between ``.manage(backend)`` and the
    /// async spawn closure.
    pub fn from_state(app: &tauri::AppHandle) -> Self {
        use tauri::Manager;
        let state: tauri::State<'_, BackendHandle> = app.state();
        state.inner().clone()
    }
}

// ── Cowork state poller ──────────────────────────────────────────

#[cfg(feature = "tauri-runtime")]
async fn run_cowork_state_poller(app: AppHandle) {
    use std::time::Duration;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("reqwest client");
    loop {
        // Get the backend URL from managed state.
        let backend = {
            use tauri::Manager;
            let state: tauri::State<'_, BackendHandle> = app.state();
            state.inner().clone()
        };
        let url = backend.status().await.url;
        let state = if url.is_empty() {
            None
        } else {
            match client.get(format!("{url}/api/cowork/sessions/current")).send().await {
                Ok(r) if r.status().is_success() => {
                    if let Ok(json) = r.json::<serde_json::Value>().await {
                        json.get("session")
                            .and_then(|s| s.get("state"))
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string())
                    } else {
                        None
                    }
                }
                _ => None,
            }
        };

        // Update menu state.
        if let Some(menu) = app.try_state::<tray::CoworkMenu<tauri::Wry>>() {
            tray::apply_menu_state(menu.inner(), state.as_deref());
        }

        // Forward the state change to the dashboard via the existing
        // shell://navigate / shell://menu channels? No — we use a
        // dedicated cowork://state event so the dashboard can react
        // without parsing menu events.
        let _ = app.emit("cowork://state", state.as_deref().unwrap_or(""));

        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

// ── Deep-link parsing ────────────────────────────────────────────

#[cfg(feature = "tauri-runtime")]
fn parse_deep_link(arg: &str) -> Option<String> {
    if arg.starts_with("raven://") {
        Some(arg.to_string())
    } else {
        None
    }
}

// ── Legacy companion WS handlers (kept for wire-format tests) ──

#[tauri::command]
fn connection_state(state: State<'_, AppState>) -> serde_json::Value {
    serde_json::to_value(state.client.state()).expect("ConnectionState is serializable")
}

#[tauri::command]
fn send_command(
    intent: String,
    args: serde_json::Value,
    state: State<'_, AppState>,
) -> String {
    state.client.send_command(&intent, args)
}

#[tauri::command]
fn subscribe(channels: Vec<String>, state: State<'_, AppState>) -> bool {
    let refs: Vec<&str> = channels.iter().map(|s| s.as_str()).collect();
    state.client.subscribe(&refs);
    true
}

#[tauri::command]
fn ping(state: State<'_, AppState>) -> i64 {
    state.client.ping()
}

// ── Tauri commands (sidecar) ────────────────────────────────────
//
// The ``backend_url`` / ``backend_status`` / ``retry_backend``
// commands have to be defined in **this** module so the
// ``tauri::generate_handler!`` macro can see the per-command
// ``__cmd__<name>`` symbols that ``#[tauri::command]`` generates.

#[tauri::command]
async fn backend_url(
    handle: State<'_, BackendHandle>,
) -> Result<String, String> {
    Ok(handle.status().await.url)
}

#[tauri::command]
async fn backend_status(
    handle: State<'_, BackendHandle>,
) -> Result<BackendStatus, String> {
    Ok(handle.status().await)
}

#[tauri::command]
async fn retry_backend(
    handle: State<'_, BackendHandle>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    use tauri::Emitter;
    // ``stop()`` signals the child + force-kills if needed, but
    // leaves the status in ``Stopping``.  We then re-spawn; the
    // supervisor flips status back to ``Starting`` / ``Ready``
    // and ``spawn()`` emits a fresh ``backend://status`` event.
    handle.stop().await;
    handle
        .spawn(&app)
        .await
        .map_err(|e| format!("{e:?}"))?;
    // Defensive: re-emit the current status so the boot page
    // gets a confirmed state even if spawn() raced past us.
    let status = handle.status().await;
    let _ = app.emit("backend://status", &status);
    Ok(status.url)
}

// ── Updater commands ────────────────────────────────────────────

#[cfg(feature = "tauri-runtime")]
#[tauri::command]
async fn check_for_update(app: tauri::AppHandle) -> Result<Option<serde_json::Value>, String> {
    use tauri_plugin_updater::UpdaterExt;
    // Tauri v2's ``app.updater()`` returns ``Result<Updater>``;
    // ``Updater::check()`` then returns ``Result<Option<Update>>``.
    let updater = app.updater().map_err(|e| format!("{e}"))?;
    match updater.check().await {
        Ok(Some(u)) => Ok(Some(serde_json::json!({
            "version": u.version,
            "notes": u.body,
            "available": true,
        }))),
        Ok(None) => Ok(None),
        Err(e) => Err(format!("{e}")),
    }
}

// ── Autostart commands ──────────────────────────────────────────

#[cfg(feature = "tauri-runtime")]
#[tauri::command]
fn set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    let manager = app.autolaunch();
    if enabled {
        manager.enable().map_err(|e| format!("{e}"))?;
    } else {
        manager.disable().map_err(|e| format!("{e}"))?;
    }
    Ok(enabled)
}

#[cfg(feature = "tauri-runtime")]
#[tauri::command]
fn get_autostart(app: tauri::AppHandle) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    app.autolaunch().is_enabled().map_err(|e| format!("{e}"))
}

// ── Log dir opener ──────────────────────────────────────────────

#[cfg(feature = "tauri-runtime")]
#[tauri::command]
fn open_log_dir(app: tauri::AppHandle) -> Result<String, String> {
    use tauri::Manager;
    let dir = app
        .path()
        .app_log_dir()
        .map_err(|e| format!("{e}"))?;
    Ok(dir.to_string_lossy().to_string())
}

// ── WebSocket loop (legacy companion protocol) ──────────────────

#[cfg(feature = "tauri-runtime")]
async fn run_websocket_loop(client: Arc<CompanionClient>, app: AppHandle) {
    use futures_util::{SinkExt, StreamExt};
    use std::time::Duration;
    use tokio_tungstenite::connect_async;
    use tungstenite::Message;

    let url = client.ws_url_with_token();
    let backoff = Duration::from_secs(2);

    loop {
        client.set_state(ConnectionState::Connecting);
        let _ = app.emit("companion://state", client.state());

        let connect = connect_async(&url).await;
        let (mut ws, _resp) = match connect {
            Ok(pair) => pair,
            Err(e) => {
                tracing::warn!("ws connect failed: {e}; sleeping {backoff:?}");
                client.set_state(ConnectionState::Offline);
                let _ = app.emit("companion://state", client.state());
                tokio::time::sleep(backoff).await;
                continue;
            }
        };

        let hello_json = serde_json::to_string(&client.hello()).expect("hello");
        if let Err(e) = ws.send(Message::Text(hello_json)).await {
            tracing::warn!("ws send Hello failed: {e}");
            continue;
        }

        for frame in client.drain_queue() {
            let json = serde_json::to_string(&frame.to_json()).expect("frame json");
            if let Err(e) = ws.send(Message::Text(json)).await {
                tracing::warn!("ws drain send failed: {e}");
                break;
            }
        }

        client.set_state(ConnectionState::Online);
        let _ = app.emit("companion://state", client.state());

        while let Some(msg) = ws.next().await {
            match msg {
                Ok(Message::Text(t)) => {
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&t) {
                        let _ = app.emit("companion://frame", parsed);
                    }
                }
                Ok(Message::Close(_)) => break,
                Ok(_) => {}
                Err(e) => {
                    tracing::warn!("ws read error: {e}");
                    break;
                }
            }
        }

        client.set_state(ConnectionState::Offline);
        let _ = app.emit("companion://state", client.state());
        tokio::time::sleep(backoff).await;
    }
}
