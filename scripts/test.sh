#!/usr/bin/env bash
# scripts/test.sh — run the SARAS test suite with sensible defaults.
#
# Usage:
#   scripts/test.sh                # full suite
#   scripts/test.sh -x             # fail-fast
#   scripts/test.sh tests/test_x.py  # specific file
#   scripts/test.sh --helix        # start HelixDB first
#
# Environment overrides:
#   VENV          path to the venv          (default: .venv)
#   HELIX_URL     HelixDB URL                (default: http://localhost:8080)

set -euo pipefail

VENV=${VENV:-.venv}
PY=${VENV}/bin/python
PYT=${VENV}/bin/pytest
HELIX_URL=${HELIX_URL:-http://localhost:8080}

# Parse flags
START_HELIX=0
EXTRA_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --helix) START_HELIX=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *) EXTRA_ARGS+=("$arg") ;;
    esac
done

if [ ! -x "$PY" ]; then
    echo "✗ venv not found at $VENV — run 'make venv' first" >&2
    exit 1
fi

# Start HelixDB if requested
if [ "$START_HELIX" = "1" ]; then
    make helix-up
fi

# Sanity check HelixDB reachability (warn, don't fail)
if curl -fsS "$HELIX_URL/health" >/dev/null 2>&1; then
    HELIX_STATUS="✓ reachable at $HELIX_URL"
else
    HELIX_STATUS="✗ NOT reachable at $HELIX_URL (some tests will be skipped)"
fi
echo "HelixDB: $HELIX_STATUS"

export SARAS_HELIX_URL="$HELIX_URL"
export SARAS_LOG_JSON=true
export SARAS_LOG_LEVEL=INFO
export SARAS_OTEL_IN_MEMORY=true

echo "Running: $PYT ${EXTRA_ARGS[@]:-}"
exec "$PYT" "${EXTRA_ARGS[@]:-}"
