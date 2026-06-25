//! Tauri tray + native menu bar.
//!
//! v36 (2026-06-23): the shell exposes a system tray with quick
//! actions and a real native menu bar (File / Edit / View / Cowork
//! / Window / Help) on macOS, with appropriate platform fallbacks
//! for Windows / Linux.
//!
//! Wire model
//! ----------
//! Menu items are tagged with an ``id``; when the user clicks one
//! we ``emit("shell://menu", { id })`` to the webview, which is
//! responsible for turning the click into a navigation (e.g.
//! ``navigate("/page/cowork")``) or a Cowork command
//! (``POST /api/cowork/sessions/{id}/pause``).  The dashboard
//! is the single source of truth — the menu is just a launcher.
#[cfg(feature = "tauri-runtime")]
use tauri::{
    menu::{Menu, MenuEvent, MenuItem, MenuItemBuilder, PredefinedMenuItem, Submenu},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, Runtime,
};

/// Identifier for the "Open dashboard" menu item.
pub const ID_OPEN_DASHBOARD: &str = "open_dashboard";
/// Identifier for the "New Cowork session…" item.
pub const ID_COWORK_NEW: &str = "cowork_new";
/// Identifier for the "Pause active session" item.
pub const ID_COWORK_PAUSE: &str = "cowork_pause";
/// Identifier for the "Resume active session" item.
pub const ID_COWORK_RESUME: &str = "cowork_resume";
/// Identifier for the "Stop active session" item.
pub const ID_COWORK_STOP: &str = "cowork_stop";
/// Identifier for the "Approve all pending steps" item.
pub const ID_COWORK_APPROVE_ALL: &str = "cowork_approve_all";
/// Identifier for the "Quit RAVEN" item.
pub const ID_QUIT: &str = "quit";

/// Build the native menu bar.  The returned :struct:`CoworkMenu`
/// holds handles to the Cowork submenu items so the boot screen
/// can enable/disable them based on whether a session is active.
#[cfg(feature = "tauri-runtime")]
pub fn build_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<CoworkMenu<R>> {
    // File
    let file = Submenu::with_items(
        app,
        "File",
        true,
        &[
            &MenuItem::with_id(app, ID_OPEN_DASHBOARD, "Open Dashboard", true, Some("CmdOrCtrl+1"))?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(
                app,
                ID_COWORK_NEW,
                "New Cowork Session…",
                true,
                Some("CmdOrCtrl+N"),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, ID_QUIT, "Quit RAVEN", true, Some("CmdOrCtrl+Q"))?,
        ],
    )?;

    // Edit — standard predefined items so the OS handles cut/copy/paste.
    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;

    // View
    let view = Submenu::with_items(
        app,
        "View",
        true,
        &[
            &MenuItem::with_id(app, "view_chat", "Chat", true, Some("CmdOrCtrl+2"))?,
            &MenuItem::with_id(
                app,
                "view_cowork",
                "Cowork",
                true,
                Some("CmdOrCtrl+3"),
            )?,
            &MenuItem::with_id(
                app,
                "view_providers",
                "Providers",
                true,
                Some("CmdOrCtrl+4"),
            )?,
            &MenuItem::with_id(
                app,
                "view_personality",
                "Personality",
                true,
                Some("CmdOrCtrl+5"),
            )?,
            &MenuItem::with_id(
                app,
                "view_knowledge_graph",
                "Knowledge Graph",
                true,
                Some("CmdOrCtrl+6"),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::fullscreen(app, None)?,
        ],
    )?;

    // Cowork — quick actions on the active session.  Each item is
    // built with ``enabled = false`` initially and toggled when
    // the supervisor learns the session state.
    let cowork_pause = MenuItemBuilder::with_id(ID_COWORK_PAUSE, "Pause Active")
        .accelerator("CmdOrCtrl+.")
        .enabled(false)
        .build(app)?;
    let cowork_resume = MenuItemBuilder::with_id(ID_COWORK_RESUME, "Resume Active")
        .accelerator("CmdOrCtrl+>")
        .enabled(false)
        .build(app)?;
    let cowork_stop = MenuItemBuilder::with_id(ID_COWORK_STOP, "Stop Active")
        .enabled(false)
        .build(app)?;
    let cowork_approve_all = MenuItemBuilder::with_id(ID_COWORK_APPROVE_ALL, "Approve All Pending")
        .accelerator("CmdOrCtrl+Shift+A")
        .enabled(false)
        .build(app)?;

    let cowork = Submenu::with_items(
        app,
        "Cowork",
        true,
        &[
            &MenuItem::with_id(app, ID_COWORK_NEW, "New Session…", true, Some("CmdOrCtrl+N"))?,
            &PredefinedMenuItem::separator(app)?,
            &cowork_pause,
            &cowork_resume,
            &cowork_stop,
            &PredefinedMenuItem::separator(app)?,
            &cowork_approve_all,
        ],
    )?;

    // Window — standard predefined window management.
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;

    // Help
    let help = Submenu::with_items(
        app,
        "Help",
        true,
        &[
            &MenuItem::with_id(app, "help_docs", "Documentation…", true, None::<&str>)?,
            &MenuItem::with_id(app, "help_about", "About RAVEN", true, None::<&str>)?,
        ],
    )?;

    let menu = Menu::with_items(app, &[&file, &edit, &view, &cowork, &window, &help])?;
    // Install the menu on the app.  Tauri v2 takes ownership, so
    // we don't need to return the Menu (we just need the CoworkMenu
    // handles for state toggling).
    app.set_menu(menu)?;
    Ok(CoworkMenu {
        pause: cowork_pause,
        resume: cowork_resume,
        stop: cowork_stop,
        approve_all: cowork_approve_all,
    })
}

/// Holds handles to the menu items that should be enabled/disabled
/// based on the active cowork session state.  Stored in app state
/// so the supervisor can update them as the backend reports changes.
#[cfg(feature = "tauri-runtime")]
pub struct CoworkMenu<R: Runtime> {
    /// Pause-execution menu item.
    pub pause: tauri::menu::MenuItem<R>,
    /// Resume-execution menu item.
    pub resume: tauri::menu::MenuItem<R>,
    /// Stop-execution menu item.
    pub stop: tauri::menu::MenuItem<R>,
    /// Approve-all-pending-steps menu item.
    pub approve_all: tauri::menu::MenuItem<R>,
}

/// Compute which menu items should be enabled for the given
/// cowork session state.  Returns a tuple ``(pause, resume, stop, approve_all)``.
#[cfg(feature = "tauri-runtime")]
pub fn menu_enabled_for_state(state: Option<&str>) -> (bool, bool, bool, bool) {
    match state {
        Some("executing") | Some("awaiting_approval") => (true, false, true, true),
        Some("paused") => (false, true, true, false),
        Some("planning") | Some("approved") => (false, false, true, false),
        _ => (false, false, false, false),
    }
}

/// Apply the per-item enabled flags to a :class:`CoworkMenu`.
/// Idempotent — safe to call on every state update.
#[cfg(feature = "tauri-runtime")]
pub fn apply_menu_state<R: Runtime>(menu: &CoworkMenu<R>, state: Option<&str>) {
    let (pause, resume, stop, approve_all) = menu_enabled_for_state(state);
    let _ = menu.pause.set_enabled(pause);
    let _ = menu.resume.set_enabled(resume);
    let _ = menu.stop.set_enabled(stop);
    let _ = menu.approve_all.set_enabled(approve_all);
    tracing::debug!(
        "cowork menu state={:?} → pause={} resume={} stop={} approve={}",
        state, pause, resume, stop, approve_all
    );
}

/// Build the system tray icon + context menu.  Returns a
/// :struct:`CoworkMenu` so the supervisor can toggle the
/// pause/resume/stop/approve items based on session state.
#[cfg(feature = "tauri-runtime")]
pub fn build_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<CoworkMenu<R>> {
    let cowork_pause = MenuItemBuilder::with_id(ID_COWORK_PAUSE, "Pause Active Session")
        .enabled(false)
        .build(app)?;
    let cowork_resume = MenuItemBuilder::with_id(ID_COWORK_RESUME, "Resume Active Session")
        .enabled(false)
        .build(app)?;
    let cowork_approve_all = MenuItemBuilder::with_id(ID_COWORK_APPROVE_ALL, "Approve All Pending")
        .enabled(false)
        .build(app)?;
    let cowork_stop = MenuItemBuilder::with_id(ID_COWORK_STOP, "Stop Active Session")
        .enabled(false)
        .build(app)?;

    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, ID_OPEN_DASHBOARD, "Open Dashboard", true, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, ID_COWORK_NEW, "New Cowork Session…", true, None::<&str>)?,
            &cowork_pause,
            &cowork_resume,
            &cowork_stop,
            &cowork_approve_all,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, ID_QUIT, "Quit RAVEN", true, None::<&str>)?,
        ],
    )?;

    let _ = TrayIconBuilder::with_id("main-tray")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| {
            forward_menu_event(app, &event);
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                if let Some(window) = tray.app_handle().get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        })
        .build(app)?;
    Ok(CoworkMenu {
        pause: cowork_pause,
        resume: cowork_resume,
        stop: cowork_stop,
        approve_all: cowork_approve_all,
    })
}

/// Map a menu event to a webview event.  The dashboard's JS
/// listens for ``shell://menu`` and reacts accordingly.
#[cfg(feature = "tauri-runtime")]
pub fn forward_menu_event<R: Runtime>(app: &AppHandle<R>, event: &MenuEvent) {
    let id = event.id.as_ref();
    match id {
        ID_OPEN_DASHBOARD => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/"}));
            show_main_window(app);
        }
        "view_chat" => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/chat"}));
        }
        "view_cowork" => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/cowork"}));
        }
        "view_providers" => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/provider-manage"}));
        }
        "view_personality" => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/personality"}));
        }
        "view_knowledge_graph" => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/knowledge-graph"}));
        }
        ID_COWORK_NEW => {
            let _ = app.emit("shell://navigate", serde_json::json!({"path": "/cowork"}));
        }
        ID_COWORK_PAUSE | ID_COWORK_RESUME | ID_COWORK_STOP | ID_COWORK_APPROVE_ALL => {
            // Forward the click as a Cowork intent — the dashboard
            // JS knows how to translate these into API calls.
            let _ = app.emit(
                "shell://menu",
                serde_json::json!({"id": id, "kind": "cowork"}),
            );
        }
        "help_about" => {
            let _ = app.emit(
                "shell://menu",
                serde_json::json!({"id": id, "kind": "about"}),
            );
        }
        "help_docs" => {
            let _ = app.emit(
                "shell://menu",
                serde_json::json!({"id": id, "kind": "docs"}),
            );
        }
        ID_QUIT => {
            app.exit(0);
        }
        _ => {}
    }
}

#[cfg(feature = "tauri-runtime")]
fn show_main_window<R: Runtime>(app: &AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
