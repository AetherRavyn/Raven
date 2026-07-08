#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# raven-daemon.sh — Self-locating wrapper for Raven daemon.
#
# Auto-detects:
#   - Project root (where this script lives, or $RAVEN_HOME)
#   - Python venv (.venv/ in project root)
#   - .env file (project root)
#   - raven binary (venv/bin/raven or fallback to PATH)
#
# Usage:
#   ./scripts/raven-daemon.sh [--voice]
#
# Works from ANY install location on ANY device.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

# ── 1. Find project root ─────────────────────────────────────────
if [[ -n "${RAVEN_HOME:-}" ]]; then
    PROJECT_ROOT="$RAVEN_HOME"
elif [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    PROJECT_ROOT="$(pwd)"
fi

# Verify this looks like a Raven install
if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    echo "ERROR: Cannot find pyproject.toml in $PROJECT_ROOT" >&2
    echo "Set RAVEN_HOME to your Raven installation directory." >&2
    exit 1
fi

export RAVEN_HOME="$PROJECT_ROOT"
cd "$PROJECT_ROOT"

# ── 2. Find Python venv ──────────────────────────────────────────
VENV_PYTHON=""
for candidate in \
    "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/venv/bin/python" \
    "$PROJECT_ROOT/.venv/Scripts/python.exe" \
; do
    if [[ -x "$candidate" ]]; then
        VENV_PYTHON="$candidate"
        break
    fi
done

if [[ -z "$VENV_PYTHON" ]]; then
    echo "WARNING: No Python venv found in $PROJECT_ROOT" >&2
    echo "Attempting to use system python3..." >&2
    VENV_PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
    if [[ -z "$VENV_PYTHON" ]]; then
        echo "ERROR: No Python found. Install Python 3.12+ first." >&2
        exit 1
    fi
fi

# ── 3. Find raven binary ─────────────────────────────────────────
RAVEN_BIN=""
VENV_DIR="$(dirname "$VENV_PYTHON")"
for candidate in \
    "$VENV_DIR/raven" \
    "$PROJECT_ROOT/.venv/bin/raven" \
    "$PROJECT_ROOT/venv/bin/raven" \
; do
    if [[ -x "$candidate" ]]; then
        RAVEN_BIN="$candidate"
        break
    fi
done

# ── 4. Load .env if present ──────────────────────────────────────
ENV_FILE="$PROJECT_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# ── 5. Determine run mode ────────────────────────────────────────
RARGS=("run" "--no-voice")
for arg in "$@"; do
    case "$arg" in
        --voice) RARGS=("run") ;;
        --daemon) RARGS=("run" "--no-voice") ;;
        *) RARGS+=("$arg") ;;
    esac
done

# ── 6. Launch ────────────────────────────────────────────────────
echo "┌─────────────────────────────────────────┐"
echo "│  Raven AI Agent — Starting daemon...     │"
echo "│  Project: $PROJECT_ROOT"
echo "│  Python:  $VENV_PYTHON"
echo "└─────────────────────────────────────────┘"

if [[ -n "$RAVEN_BIN" ]]; then
    exec "$RAVEN_BIN" "${RARGS[@]}"
else
    exec "$VENV_PYTHON" -m app.cli.main "${RARGS[@]}"
fi
