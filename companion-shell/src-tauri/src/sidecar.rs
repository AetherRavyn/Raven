//! Tauri sidecar — spawns the bundled `raven-backend` binary,
//! monitors its health, and tears it down on app close.
//!
//! v36 (2026-06-23): 9router-style card system + cowork desktop
//! integration.  The shell is no longer a thin WebSocket client
//! talking to a separately-running backend — it owns the backend.
//!
//! Behaviour
//! ---------
//! On `setup`, this module:
//!   1. Picks a free localhost port (0 → OS-assigned).
//!   2. Spawnes the sidecar binary with `--port=<p>` env.
//!   3. Polls `http://127.0.0.1:<p>/api/system/status` until 200.
//!   4. Stores the URL in :class:`BackendHandle` so other modules
//!      (the menu, the tray, the boot page) can read it.
//!
//! On `Drop` / app close, the sidecar child is signalled with
//! SIGTERM, then SIGKILL after 5s grace.  No orphan processes.
//!
//! Cross-platform
//! --------------
//! * macOS / Linux: `tokio::process::Command` with `kill_on_drop`.
//! * Windows: same API; SIGTERM is mapped to `TerminateProcess`
//!   by the Rust runtime.
//!
//! The sidecar binary is declared in `tauri.conf.json` as
//! `externalBin: ["binaries/raven-backend"]` — Tauri copies it
//! into the bundle under the platform-specific resource path
//! and exposes it via the `shell-sidecar` API.
use std::net::TcpListener;
#[cfg(feature = "tauri-runtime")]
use std::path::PathBuf;
#[cfg(feature = "tauri-runtime")]
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
#[cfg(feature = "tauri-runtime")]
use tauri::{AppHandle, Emitter, Manager, Runtime};
#[cfg(feature = "tauri-runtime")]
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

/// Bundle-relative name of the sidecar (must match the file in
/// `src-tauri/binaries/` and the `externalBin` array in
/// `tauri.conf.json`).
pub const SIDECAR_NAME: &str = "raven-backend";

/// How long we wait for the sidecar to bind its port and answer
/// `/api/system/status` before giving up.
#[cfg_attr(not(feature = "tauri-runtime"), allow(dead_code))]
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);

/// Maximum restart attempts before the supervisor gives up and
/// marks the backend as :enum:`BackendState::Crashed`.  The user
/// can then click "Retry" on the boot screen to call
/// :meth:`spawn` again from scratch.
#[cfg_attr(not(feature = "tauri-runtime"), allow(dead_code))]
const MAX_RESTARTS: u32 = 5;

/// Cap for the exponential backoff between restart attempts.
#[cfg_attr(not(feature = "tauri-runtime"), allow(dead_code))]
const MAX_BACKOFF: Duration = Duration::from_secs(30);

/// State of the bundled backend.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BackendState {
    /// Sidecar not yet spawned.
    Starting,
    /// Health check returned 200; ready to use.
    Ready,
    /// Sidecar is shutting down (signal sent).
    Stopping,
    /// Sidecar exited unexpectedly; supervisor is restarting it.
    Restarting,
    /// Sidecar exited and the supervisor gave up (crash loop).
    Crashed,
    /// Sidecar failed to start at all (binary missing, permission, etc.).
    Failed(String),
}

/// Snapshot of the sidecar's lifecycle state.  Returned to
/// the JS frontend by ``invoke('backend_status')`` and emitted
/// on the ``backend://status`` event channel.
#[derive(Clone, Debug, Serialize)]
pub struct BackendStatus {
    /// Current state machine value.
    pub state: BackendState,
    /// ``http://127.0.0.1:<port>`` once ``state == Running``.
    pub url: String,
    /// OS process id of the sidecar (when known).
    pub pid: Option<u32>,
    /// Last error message (cleared on next successful state).
    pub last_error: String,
}

impl Default for BackendStatus {
    fn default() -> Self {
        Self {
            state: BackendState::Starting,
            url: String::new(),
            pid: None,
            last_error: String::new(),
        }
    }
}

/// Owns the sidecar child + its current status.  Held in a
/// ``Mutex`` so multiple Tauri commands can call ``status()``
/// concurrently.
#[derive(Clone)]
pub struct BackendHandle {
    inner: Arc<Mutex<BackendInner>>,
}

struct BackendInner {
    #[cfg(feature = "tauri-runtime")]
    child: Option<Child>,
    status: BackendStatus,
}

impl BackendHandle {
    /// Build a new, unstarted ``BackendHandle``.  The sidecar
    /// is spawned separately via :meth:`spawn`.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(BackendInner {
                #[cfg(feature = "tauri-runtime")]
                child: None,
                status: BackendStatus::default(),
            })),
        }
    }

    /// Read the current ``BackendStatus`` snapshot.
    pub async fn status(&self) -> BackendStatus {
        self.inner.lock().await.status.clone()
    }

    /// Resolve a free TCP port on 127.0.0.1 by asking the OS.
    /// ``port = 0`` → kernel picks; we read the assigned port back.
    ///
    /// Uses a transient ``TcpListener`` that is dropped before
    /// the sidecar binds — there's a tiny TOCTOU window but it's
    /// acceptable for a desktop app.
    #[cfg_attr(not(feature = "tauri-runtime"), allow(dead_code))]
    fn pick_free_port() -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind 127.0.0.1:0");
        let port = listener.local_addr().expect("local_addr").port();
        drop(listener);
        port
    }

    /// Resolve the on-disk path of the sidecar binary.
    ///
    /// In dev (cargo tauri dev), the binary lives next to
    /// ``Cargo.toml`` in ``binaries/``.  In a release build, Tauri
    /// places it under the bundle's resource dir; the runtime
    /// surfaces that path through ``app.path()``.
    #[cfg(feature = "tauri-runtime")]
    fn sidecar_path<R: Runtime>(app: &AppHandle<R>) -> PathBuf {
        // 1) Look in the dev location first.
        let dev_path = std::env::current_dir()
            .ok()
            .map(|d| d.join("src-tauri").join("binaries").join(SIDECAR_NAME));
        if let Some(p) = dev_path {
            if p.exists() {
                return p;
            }
        }
        // 2) Fall back to the bundle's resource dir.
        if let Ok(resource_dir) = app.path().resource_dir() {
            let bundle_path = resource_dir.join(SIDECAR_NAME);
            if bundle_path.exists() {
                return bundle_path;
            }
            // Windows: binaries get a .exe suffix in the bundle.
            #[cfg(target_os = "windows")]
            {
                let bundle_path_exe = resource_dir.join(format!("{SIDECAR_NAME}.exe"));
                if bundle_path_exe.exists() {
                    return bundle_path_exe;
                }
            }
        }
        PathBuf::from(SIDECAR_NAME)
    }

    /// Spawn the sidecar, write the assigned port into its env,
    /// then poll ``/api/system/status`` until 200.  If the child
    /// exits while we're still inside this call (e.g. binary
    /// missing or refuses to start), the future returns the OS
    /// error from :meth:`tokio::process::Command::spawn`.
    ///
    /// A separate supervisor task (started inside this method)
    /// watches the child after startup.  If the sidecar crashes
    /// mid-session, the supervisor restarts it with exponential
    /// backoff up to :data:`MAX_RESTARTS` attempts, then marks
    /// the backend :enum:`BackendState::Crashed`.  The boot page
    /// shows the crash state and a retry button.
    #[cfg(feature = "tauri-runtime")]
    pub async fn spawn<R: Runtime>(&self, app: &AppHandle<R>) -> anyhow::Result<String> {
        let port = Self::pick_free_port();
        let url = format!("http://127.0.0.1:{port}");
        let path = Self::sidecar_path(app);
        tracing::info!(
            "spawning sidecar at {} on {} (port {})",
            path.display(),
            url,
            port
        );

        // Initial spawn — fail loudly if the binary is missing.
        let child = Self::spawn_child(&path, port)?;
        let pid = child.id();

        {
            let mut inner = self.inner.lock().await;
            inner.child = Some(child);
            inner.status = BackendStatus {
                state: BackendState::Starting,
                url: url.clone(),
                pid,
                last_error: String::new(),
            };
        }
        let _ = app.emit("backend://status", self.status().await);

        // Spawn the supervisor + health probe.
        self.spawn_supervisor(app.clone(), path.clone(), port, url.clone())
            .await;

        Ok(url)
    }

    /// Spawn the sidecar child with the desktop env.  Returns
    /// ``Err`` if the binary can't be launched — the caller surfaces
    /// that to the boot page.
    #[cfg(feature = "tauri-runtime")]
    fn spawn_child(path: &std::path::Path, port: u16) -> anyhow::Result<Child> {
        let mut cmd = Command::new(path);
        cmd.env("RAVEN_WEB_DASHBOARD_HOST", "127.0.0.1")
            .env("RAVEN_WEB_DASHBOARD_PORT", port.to_string())
            .env("RAVEN_WEB_DASHBOARD_ENABLED", "true")
            .env("RAVEN_TELEGRAM_ENABLED", "false")
            .env("RAVEN_DISCORD_ENABLED", "false")
            .env("RAVEN_SLACK_ENABLED", "false")
            .env("RAVEN_WHATSAPP_ENABLED", "false")
            .env("RAVEN_DAEMON", "desktop")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        Ok(cmd.spawn()?)
    }

    /// Background task: probe health until Ready, then watch the
    /// child for unexpected exit.  Restarts on crash with backoff.
    #[cfg(feature = "tauri-runtime")]
    async fn spawn_supervisor<R: Runtime>(
        &self,
        app: AppHandle<R>,
        path: std::path::PathBuf,
        port: u16,
        url: String,
    ) {
        let inner = self.inner.clone();
        let health_url = format!("{url}/api/system/status");
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .expect("reqwest client");

        tauri::async_runtime::spawn(async move {
            // Phase 1: wait for the first successful health probe.
            let startup_deadline = std::time::Instant::now() + STARTUP_TIMEOUT;
            loop {
                if std::time::Instant::now() > startup_deadline {
                    let mut guard = inner.lock().await;
                    guard.status.state = BackendState::Failed("startup timeout".into());
                    guard.status.last_error =
                        format!("backend did not respond within {STARTUP_TIMEOUT:?}");
                    let snapshot = guard.status.clone();
                    drop(guard);
                    let _ = app.emit("backend://status", snapshot);
                    return;
                }
                match client.get(&health_url).send().await {
                    Ok(r) if r.status().is_success() => {
                        let mut guard = inner.lock().await;
                        guard.status.state = BackendState::Ready;
                        let snapshot = guard.status.clone();
                        drop(guard);
                        tracing::info!("sidecar ready at {url}");
                        let _ = app.emit("backend://status", snapshot);
                        break;
                    }
                    _ => {
                        tokio::time::sleep(Duration::from_millis(500)).await;
                    }
                }
            }

            // Phase 2: watch the child for unexpected exit; restart on crash.
            let mut backoff = Duration::from_secs(1);
            let mut restarts: u32 = 0;
            loop {
                tokio::time::sleep(Duration::from_millis(500)).await;
                let mut guard = inner.lock().await;
                // If the user asked to stop, exit the supervisor.
                if matches!(guard.status.state, BackendState::Stopping | BackendState::Crashed | BackendState::Failed(_)) {
                    return;
                }
                let Some(child) = guard.child.as_mut() else {
                    return;
                };
                match child.try_wait() {
                    Ok(Some(status)) => {
                        drop(guard);
                        tracing::error!("sidecar exited unexpectedly: {status}");
                        restarts += 1;
                        if restarts > MAX_RESTARTS {
                            let mut guard = inner.lock().await;
                            guard.status.state = BackendState::Crashed;
                            guard.status.last_error = format!(
                                "sidecar crashed {restarts} times — giving up"
                            );
                            let snapshot = guard.status.clone();
                            drop(guard);
                            let _ = app.emit("backend://status", snapshot);
                            return;
                        }
                        // Restart with backoff.
                        {
                            let mut guard = inner.lock().await;
                            guard.status.state = BackendState::Restarting;
                            guard.status.last_error =
                                format!("restarting (attempt {restarts}/{MAX_RESTARTS})");
                            let snapshot = guard.status.clone();
                            drop(guard);
                            let _ = app.emit("backend://status", snapshot);
                        }
                        tracing::warn!(
                            "restarting sidecar in {backoff:?} (attempt {restarts})"
                        );
                        tokio::time::sleep(backoff).await;
                        backoff = (backoff * 2).min(MAX_BACKOFF);

                        match Self::spawn_child(&path, port) {
                            Ok(new_child) => {
                                let mut guard = inner.lock().await;
                                guard.child = Some(new_child);
                                guard.status.state = BackendState::Starting;
                                guard.status.pid = guard.child.as_ref().and_then(|c| c.id());
                                guard.status.last_error = String::new();
                                let snapshot = guard.status.clone();
                                drop(guard);
                                let _ = app.emit("backend://status", snapshot);
                                // Re-probe health for the new instance.
                                let probe_deadline =
                                    std::time::Instant::now() + STARTUP_TIMEOUT;
                                let mut ready = false;
                                while std::time::Instant::now() < probe_deadline {
                                    match client.get(&health_url).send().await {
                                        Ok(r) if r.status().is_success() => {
                                            ready = true;
                                            break;
                                        }
                                        _ => {
                                            tokio::time::sleep(Duration::from_millis(500)).await;
                                        }
                                    }
                                }
                                if ready {
                                    let mut guard = inner.lock().await;
                                    guard.status.state = BackendState::Ready;
                                    let snapshot = guard.status.clone();
                                    drop(guard);
                                    let _ = app.emit("backend://status", snapshot);
                                    tracing::info!("sidecar restarted");
                                } else {
                                    // Will loop back and try_wait again.
                                    let mut guard = inner.lock().await;
                                    guard.status.state =
                                        BackendState::Restarting;
                                    guard.status.last_error =
                                        "restart did not become healthy".into();
                                    let snapshot = guard.status.clone();
                                    drop(guard);
                                    let _ = app.emit("backend://status", snapshot);
                                }
                            }
                            Err(e) => {
                                let mut guard = inner.lock().await;
                                guard.status.state = BackendState::Failed(format!(
                                    "restart failed: {e}"
                                ));
                                let snapshot = guard.status.clone();
                                drop(guard);
                                let _ = app.emit("backend://status", snapshot);
                                return;
                            }
                        }
                    }
                    Ok(None) => continue,
                    Err(e) => {
                        tracing::warn!("try_wait failed: {e}");
                        continue;
                    }
                }
            }
        })
        .await
        .ok();
    }

    /// Signal the sidecar to exit and wait for it.
    #[cfg(feature = "tauri-runtime")]
    pub async fn stop(&self) {
        let mut inner = self.inner.lock().await;
        if let Some(mut child) = inner.child.take() {
            inner.status.state = BackendState::Stopping;
            tracing::info!("signalling sidecar to stop");
            let _ = child.start_kill();
            // Give the child up to 5s to exit cleanly.
            for _ in 0..50 {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => tokio::time::sleep(Duration::from_millis(100)).await,
                    Err(_) => break,
                }
            }
            // Force-kill if still alive.
            let _ = child.kill().await;
        }
    }
}

#[cfg(feature = "tauri-runtime")]
impl Drop for BackendHandle {
    fn drop(&mut self) {
        // Best-effort: if the runtime is still up, schedule a stop.
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            let inner = self.inner.clone();
            handle.spawn(async move {
                if let Some(mut child) = inner.lock().await.child.take() {
                    let _ = child.start_kill();
                }
            });
        }
    }
}

/// Tauri command: return the sidecar's current URL.
///
/// The boot page calls this once on startup, then waits for
/// ``/api/system/status`` to return 200, then redirects the
/// webview to ``url + "/"``.
#[cfg(feature = "tauri-runtime")]
#[tauri::command]
pub async fn backend_url(handle: tauri::State<'_, BackendHandle>) -> Result<String, String> {
    Ok(handle.status().await.url)
}

/// Tauri command: return the sidecar's status snapshot.
#[cfg(feature = "tauri-runtime")]
#[tauri::command]
pub async fn backend_status(
    handle: tauri::State<'_, BackendHandle>,
) -> Result<BackendStatus, String> {
    Ok(handle.status().await)
}

// The ``retry_backend`` command lives in ``tauri_app.rs`` so it
// can be registered in the same ``generate_handler!`` block as
// the other app-level commands.  This file only owns the
// types + spawn / supervisor / stop logic.
