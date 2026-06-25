#!/usr/bin/env bash
# Build the RAVEN desktop app:
#   1. Bundle the Python backend with PyInstaller → `raven-backend`
#   2. Drop it into the Tauri shell's `binaries/` dir
#   3. Run `cargo tauri build` to produce the platform bundle
#      (mac .app / win .exe / linux .AppImage / .deb / .rpm)
#
# Usage
# -----
#   bash scripts/build-desktop.sh                 # full release build
#   bash scripts/build-desktop.sh --debug         # debug build (faster)
#   bash scripts/build-desktop.sh --sidecar-only  # only build the backend
#   bash scripts/build-desktop.sh --shell-only    # only build the Tauri shell
#
# Outputs
# -------
#   companion-shell/src-tauri/binaries/raven-backend
#   companion-shell/src-tauri/binaries/raven-backend.exe  (Windows)
#   companion-shell/src-tauri/target/release/bundle/...   (Tauri bundle)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SHELL_DIR="$ROOT/companion-shell"
TAURI_DIR="$SHELL_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
SPEC="$SHELL_DIR/raven-backend.spec"

# Platform-aware output name
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
  SIDE_BIN="raven-backend.exe"
else
  SIDE_BIN="raven-backend"
fi

SIDE_ONLY=0
SHELL_ONLY=0
DEBUG=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG=1; shift ;;
    --sidecar-only) SIDE_ONLY=1; shift ;;
    --shell-only) SHELL_ONLY=1; shift ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf "\033[1;33m[build]\033[0m %s\n" "$*"; }

# 1. PyInstaller — bundle the Python backend
if [[ $SHELL_ONLY -eq 0 ]]; then
  log "Building sidecar with PyInstaller → $SIDE_BIN"
  if ! command -v pyinstaller >/dev/null 2>&1; then
    log "pyinstaller not on PATH; trying 'uv run pyinstaller'"
    PYINSTALLER=(uv run pyinstaller)
  else
    PYINSTALLER=(pyinstaller)
  fi
  (cd "$ROOT" && "${PYINSTALLER[@]}" "$SPEC")
  mkdir -p "$BINARIES_DIR"
  # PyInstaller writes to `dist/raven-backend` (or `dist/raven-backend.exe`).
  if [[ -f "$ROOT/dist/$SIDE_BIN" ]]; then
    cp "$ROOT/dist/$SIDE_BIN" "$BINARIES_DIR/$SIDE_BIN"
    chmod +x "$BINARIES_DIR/$SIDE_BIN"
    log "Sidecar installed at $BINARIES_DIR/$SIDE_BIN"
  else
    log "ERROR: $ROOT/dist/$SIDE_BIN not found after PyInstaller run"
    exit 1
  fi
fi

# 2. Tauri — bundle the shell + sidecar into the OS app bundle
if [[ $SIDE_ONLY -eq 0 ]]; then
  log "Building Tauri shell"
  cd "$TAURI_DIR"
  if [[ $DEBUG -eq 1 ]]; then
    cargo tauri build --debug
  else
    cargo tauri build
  fi
  log "Bundle written to: $TAURI_DIR/target/release/bundle/"
fi

log "Done."
