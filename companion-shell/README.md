# RAVEN Companion — desktop shell

A Tauri v2 shell that bundles the RAVEN Python backend as a
sidecar and renders the full dashboard in a native window.

## What this shell is

RAVEN's desktop app is a **real** desktop app, not a sidebar
tile.  It:

- spawns the bundled `raven-backend` binary on launch
  (PyInstaller-built, single-file, OS-aware port allocation)
- **monitors the sidecar with a supervisor** that auto-restarts
  on crash with exponential backoff (1s → 30s, max 5 restarts)
- waits for the backend's `/api/system/status` to return 200
- loads the full RAVEN dashboard (chat, cowork, knowledge graph,
  providers, personality, learned skills, …) into a webview
- exposes a native menu bar (File / Edit / View / Cowork /
  Window / Help) **with dynamic items** — pause/resume/stop are
  enabled/disabled based on the active Cowork session state
- exposes a system tray with quick actions (open dashboard,
  pause/resume/stop cowork session, approve all pending)
- fires native OS notifications for Cowork events
  (plan ready, approval needed, step done, session done/failed)
- **persists window state** (position, size, maximized)
  across launches
- **enforces single-instance** — a second launch focuses the
  existing window instead of starting a duplicate process
- **supports `raven://` deep links** — `raven://open/cowork/123`
  navigates the dashboard to the right page
- **checks for updates** via Tauri's official updater plugin
- **manages autostart** at login (LaunchAgent on macOS,
  Registry on Windows, .desktop on Linux)
- kills the backend cleanly on quit

Cross-platform: macOS (.app), Windows (.exe + .msi), Linux
(.AppImage, .deb, .rpm).

## What's in this directory

```
companion-shell/
  package.json             # Tauri CLI helpers
  README.md                # this file
  raven-backend.spec       # PyInstaller spec for the sidecar binary
  src/                     # frontend (vanilla HTML/CSS/JS — no bundler)
    index.html             # boot screen → loads dashboard via iframe
    style.css              # boot screen styles
  src-tauri/               # Rust binary + library
    Cargo.toml             # deps; the `tauri-runtime` feature is off by default
    tauri.conf.json        # window + bundle config
    build.rs               # feature-gated tauri-build hook
    src/
      lib.rs               # library entry point + feature gating
      protocol.rs          # wire types (mirror of app/companion/types.py)
      client.rs            # WebSocket client + offline queue
      sidecar.rs           # spawns + monitors raven-backend binary (NEW v36)
      tray.rs              # system tray + native menu bar (NEW v36)
      notify.rs            # native notifications for Cowork events (NEW v36)
      tauri_app.rs         # Tauri runtime (only compiled with --features tauri-runtime)
      main.rs              # binary entry point
    binaries/              # PyInstaller output goes here (gitignored)
```

## Build

### Library form (any cargo host — no webkit2gtk needed)

```bash
cd src-tauri
cargo test --lib
# 26 passed; 0 failed
```

The library form covers the wire protocol, the offline queue,
and the message-dispatch logic.  CI on any host can verify this.

### Full release build (PyInstaller + Tauri)

```bash
bash scripts/build-desktop.sh
# Output: companion-shell/src-tauri/target/release/bundle/{macos,msi,deb,rpm}/...
```

The script:
1. Runs `pyinstaller raven-backend.spec` → `dist/raven-backend`
2. Copies it into `src-tauri/binaries/`
3. Runs `cargo tauri build` → produces the platform bundle

### Per-target

```bash
bash scripts/build-desktop.sh --sidecar-only    # only build the backend
bash scripts/build-desktop.sh --shell-only     # only build the Tauri shell
bash scripts/build-desktop.sh --debug          # faster, debug builds
```

### Prereqs

Linux:
```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

macOS: Xcode command-line tools.

Windows: MSVC build tools, WebView2 runtime.

All platforms: `pip install pyinstaller` (or `uv tool install pyinstaller`).

## IPC surface (Tauri v2)

The shell exposes the following `invoke` handlers and
`listen` events to the JS frontend:

| Channel | Direction | Purpose |
|---|---|---|
| `invoke('backend_url')` | JS → Rust | sidecar's URL (assigned port) |
| `invoke('backend_status')` | JS → Rust | BackendStatus JSON |
| `invoke('retry_backend')` | JS → Rust | stop + respawn the sidecar (returns new URL) |
| `invoke('check_for_update')` | JS → Rust | query updater plugin (returns `UpdateInfo \| null`) |
| `invoke('set_autostart', {enabled})` | JS → Rust | toggle launch-on-login |
| `invoke('get_autostart')` | JS → Rust | query current autostart state |
| `invoke('open_log_dir')` | JS → Rust | path to the Tauri app log dir |
| `invoke('connection_state')` | JS → Rust | legacy companion WS state |
| `invoke('send_command', {intent, args})` | JS → Rust | legacy companion command |
| `invoke('subscribe', {channels})` | JS → Rust | legacy channel subscribe |
| `invoke('ping')` | JS → Rust | legacy liveness |
| `listen('backend://status')` | Rust → JS | sidecar state changes (Starting/Ready/Restarting/Crashed/Failed) |
| `listen('shell://navigate')` | Rust → JS | menu navigated to a path |
| `listen('shell://menu')` | Rust → JS | raw menu item clicked (id + kind) |
| `listen('shell://deep-link')` | Rust → JS | `raven://...` URL handed off |
| `listen('cowork://state')` | Rust → JS | active cowork session state (polled every 2s) |
| `listen('cowork://event')` | Rust → JS | Cowork event (forwarded from SSE) |
| `listen('companion://state')` | Rust → JS | legacy WS state |
| `listen('companion://frame')` | Rust → JS | legacy WS frame |

### BackendStatus shape

```json
{
  "state": "ready",                  // starting | ready | restarting | crashed | failed | stopping | offline
  "url": "http://127.0.0.1:8090",    // empty string if not yet bound
  "pid": 12345,                      // null if not running
  "last_error": ""                   // populated on crashed/failed
}
```

### Crash recovery

The `BackendHandle` runs a supervisor task that:

1. Spawns the sidecar and probes `/api/system/status` until 200.
2. Watches the child process; on unexpected exit, increments the
   restart counter and respawns with exponential backoff
   (1s → 2s → 4s → 8s → 16s → 30s cap, max 5 attempts).
3. After 5 failed restarts, the state is set to `crashed` and
   the boot page shows a **Retry** button.  Clicking it calls
   `invoke('retry_backend')` which resets the counter and
   re-spawns the sidecar.

### Deep links

`raven://` URLs are registered with the OS on first launch
(Linux + Windows via the `deep-link` plugin's first-run
self-registration, macOS via the bundled `Info.plist`).  The
shell forwards the URL to the dashboard via a `shell://deep-link`
Tauri event; the dashboard is responsible for routing it to the
right page (e.g. `raven://open/cowork/123` → `/page/cowork?session=123`).

### Capabilities

`src-tauri/capabilities/default.json` is the **explicit**
Tauri v2 capability file.  It grants:

- `core:default` (event/app/window/webview)
- `notification:default`, `shell:default`, `window-state:default`
- `deep-link:default`, `updater:default`, `dialog:default`
- `autostart:default`, `fs:default` (scoped to `$WORKSPACE`,
  `$DOCUMENT`, `$DESKTOP`, `$DOWNLOAD`)
- `log:default`

The boot page (`src/index.html`) is the only Tauri view; the
dashboard runs in an `<iframe>` with normal web permissions
(plus `clipboard-read` + `clipboard-write` so the dashboard
can copy model output).  All cross-window IPC goes through the
events listed above.

The dashboard iframe runs the full RAVEN FastAPI server (the
sidecar) and uses the HTTP/JSON/SSE/WebSocket endpoints
directly.  The shell is just a thin wrapper that provides the
native window + menu + tray + notifications.

### Full Tauri build (requires webkit2gtk on Linux, WebKit on macOS)

```bash
cd src-tauri
cargo build --features tauri-runtime --release
# or, with the Tauri CLI:
cd ..
cargo tauri build
```

The first run downloads a few hundred crates and may take
several minutes.  Subsequent builds are incremental.

### Run

```bash
cargo tauri dev
# Launches the window and points it at ws://localhost:8080/companion
```

Make sure the RAVEN orchestrator is running and that the
companion WebSocket endpoint is exposed.  See
`app/api/server.py` and `app/api/companion_router.py` for the
server-side wiring.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `RAVEN_COMPANION_URL` | `ws://localhost:8080/companion` | WebSocket URL |
| `RAVEN_COMPANION_TOKEN` | (empty) | Optional bearer token; appended to URL as `?token=...` |

The frontend never reads these directly; only the Rust binary
consumes them at startup.  Frontend state arrives via the
`companion://*` Tauri events.

## Wire protocol

The shell speaks the JSON protocol documented in
`app/companion/types.py`.  Every frame is a JSON object with a
`kind` discriminator:

```
client → server:  hello, ping, subscribe, command, ack
server → client:  welcome, pong, status, event, response
shared:           error
```

The Rust side of the protocol lives in
`src-tauri/src/protocol.rs`.  The Python side lives in
`app/companion/types.py`.  The two are pinned together by
`tests/test_companion_shell_wire.py` (26 Python tests) and the
26 Rust unit tests in `protocol.rs` + `client.rs`.

A drift between the two — a field renamed on one side — is
caught at CI time by either the Python or the Rust test suite.

## IPC surface (Tauri v2)

The Rust binary exposes the following `invoke` handlers and
`listen` events to the JS frontend:

| Channel | Direction | Payload |
|---|---|---|
| `invoke('connection_state')` | JS → Rust | `ConnectionState` as JSON |
| `invoke('send_command', {intent, args})` | JS → Rust | command id (UUIDv4) |
| `invoke('subscribe', {channels})` | JS → Rust | `true` |
| `invoke('ping')` | JS → Rust | client epoch-ms |
| `listen('companion://state')` | Rust → JS | `ConnectionState` |
| `listen('companion://welcome')` | Rust → JS | `{protocol_version, session_id}` |
| `listen('companion://status')` | Rust → JS | flat status snapshot |
| `listen('companion://event')` | Rust → JS | `{channel, payload}` |
| `listen('companion://response')` | Rust → JS | `{id, ok, result, error}` |
| `listen('companion://pong')` | Rust → JS | `{ts, server_ts}` |
| `listen('companion://error')` | Rust → JS | error string |

## Troubleshooting

**The window opens but the status tile says "offline".**

* Is the RAVEN orchestrator running?  `curl http://localhost:8080/health` should return 200.
* Is the companion WebSocket endpoint exposed?  Check `app/api/server.py` for the route.
* Is `$RAVEN_COMPANION_URL` set?  The default points at `localhost:8080`.

**`cargo tauri build` complains about webkit2gtk.**

On Linux:
```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```
On macOS, Xcode command-line tools are sufficient.

**The command palette says "bad JSON in args".**

The args field is parsed with `JSON.parse`.  Quote strings:
```json
{"mode": "offline"}
```
not
```json
{mode: offline}
```

## Tests

```bash
# Rust library (any cargo host)
cd src-tauri
cargo test --lib

# Wire-format cross-language (any host with python)
cd ..
.venv/bin/python -m pytest tests/test_companion_shell_wire.py -v
```

Both run in CI on every change to either side.  The Rust suite
catches wire-format regressions that the Python suite would miss
(e.g. a Rust-only field added on the client side); the Python
suite catches wire-format regressions that the Rust suite would
miss (e.g. a Python-only field removed from the server side).

## Status

Phase 7.1 scaffolding shipped 2026-06-19.  Closes the wire-format
half of DoD #3 ("Companion installs in < 1 min and survives
sleep/wake").  The native-binary half requires a macOS dev host
to build the `.app` bundle; the library form runs anywhere.