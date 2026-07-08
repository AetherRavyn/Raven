#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8090/health}"

# 1. Check if the process is running
if ! pgrep -f "raven daemon" >/dev/null 2>&1 && ! pgrep -f "uvicorn" >/dev/null 2>&1; then
    echo "UNHEALTHY: no raven process found"
    exit 1
fi

# 2. Check if the /health endpoint responds
if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    echo "UNHEALTHY: $HEALTH_URL not responding"
    exit 1
fi

echo "HEALTHY"
exit 0
