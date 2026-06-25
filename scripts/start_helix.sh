#!/usr/bin/env bash
# Start HelixDB alongside AetherRavyn.
#
# Tries the helix CLI first (port 6969). If that fails because Docker
# bridge networking is blocked in the current environment, falls back to
# running the ghcr.io/helixdb/enterprise-dev image directly with
# --network host (port 8080).
#
# The Python client (app/db/helix.py) tries 6969 first, then 8080, so
# either mode works transparently.
set -euo pipefail

HELIX_BIN="${HELIX_BIN:-$HOME/.local/bin/helix}"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
IMAGE="ghcr.io/helixdb/enterprise-dev:latest"
CONTAINER_NAME="helix-raven"
PRIMARY_PORT="${RAVEN_HELIX_PORT_PRIMARY:-6969}"
FALLBACK_PORT="${RAVEN_HELIX_PORT_FALLBACK:-8080}"

# Sanity: helix CLI on PATH?
if ! command -v "$HELIX_BIN" >/dev/null 2>&1; then
    echo "helix CLI not found at $HELIX_BIN; falling back to docker"
    HELIX_BIN=""
fi

probe() {
    local port="$1"
    if curl -sS -m 2 "http://localhost:${port}/health" 2>/dev/null | grep -q '"healthy"'; then
        return 0
    fi
    return 1
}

case "${1:-up}" in
    up)
        # Already up?
        if probe "$PRIMARY_PORT" || probe "$FALLBACK_PORT"; then
            echo "HelixDB is already running"
            exit 0
        fi

        if [[ -n "$HELIX_BIN" ]]; then
            echo "Starting HelixDB via helix CLI on :$PRIMARY_PORT"
            cd "$PROJECT_ROOT"
            if ! "$HELIX_BIN" start dev --disk 2>"$PROJECT_ROOT/.helix.err" 1>"$PROJECT_ROOT/.helix.log"; then
                echo "helix CLI failed (likely Docker bridge networking). Falling back to docker --network host on :$FALLBACK_PORT"
                if ! docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1; then true; fi
                docker run -d --name "$CONTAINER_NAME" --network host "$IMAGE" >/dev/null
            fi
        else
            echo "Starting HelixDB via docker on :$FALLBACK_PORT"
            if ! docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1; then true; fi
            docker run -d --name "$CONTAINER_NAME" --network host "$IMAGE" >/dev/null
        fi

        # Wait up to 30s for health
        for i in {1..30}; do
            if probe "$PRIMARY_PORT" || probe "$FALLBACK_PORT"; then
                echo "HelixDB is healthy"
                exit 0
            fi
            sleep 1
        done
        echo "HelixDB failed to come up; check logs" >&2
        exit 1
        ;;
    down)
        if [[ -n "$HELIX_BIN" ]]; then
            cd "$PROJECT_ROOT"
            "$HELIX_BIN" stop dev 2>/dev/null || true
        fi
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        echo "HelixDB stopped"
        ;;
    status)
        if probe "$PRIMARY_PORT"; then
            echo "helix: up on :$PRIMARY_PORT (CLI mode)"
        elif probe "$FALLBACK_PORT"; then
            echo "helix: up on :$FALLBACK_PORT (docker mode)"
        else
            echo "helix: down"
            exit 1
        fi
        ;;
    logs)
        if [[ -n "$HELIX_BIN" ]]; then
            cd "$PROJECT_ROOT"
            "$HELIX_BIN" logs dev 2>/dev/null || true
        fi
        docker logs "$CONTAINER_NAME" 2>/dev/null || true
        ;;
    *)
        echo "Usage: $0 {up|down|status|logs}"
        exit 2
        ;;
esac
