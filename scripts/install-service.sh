#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# install-service.sh — Install Raven as a systemd service.
#
# Auto-detects:
#   - Current user
#   - Installation directory (where this script is)
#   - Python venv location
#
# Usage:
#   ./scripts/install-service.sh          # Install & enable
#   ./scripts/install-service.sh --remove # Stop & disable
#
# Works on ANY Linux device with systemd.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CURRENT_USER="$(whoami)"
SERVICE_NAME="raven"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Colors ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Remove mode ──────────────────────────────────────────────────
if [[ "${1:-}" == "--remove" || "${1:-}" == "--uninstall" ]]; then
    info "Removing Raven service..."
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "$SERVICE_FILE"
    sudo systemctl daemon-reload
    ok "Raven service removed."
    exit 0
fi

# ── Pre-flight checks ────────────────────────────────────────────
info "Installing Raven service..."
echo ""
echo "  ${CYAN}Project root:${NC}  $PROJECT_ROOT"
echo "  ${CYAN}Current user:${NC}   $CURRENT_USER"
echo "  ${CYAN}Service file:${NC}   $SERVICE_FILE"
echo ""

# Check Python venv
VENV_PYTHON=""
for candidate in \
    "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/venv/bin/python" \
; do
    if [[ -x "$candidate" ]]; then
        VENV_PYTHON="$candidate"
        break
    fi
done

if [[ -z "$VENV_PYTHON" ]]; then
    err "No Python venv found in $PROJECT_ROOT"
    echo "  Run: python -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    exit 1
fi
ok "Python venv: $VENV_PYTHON"

# Check wrapper script
WRAPPER="$PROJECT_ROOT/scripts/raven-daemon.sh"
if [[ ! -f "$WRAPPER" ]]; then
    err "Wrapper script not found: $WRAPPER"
    exit 1
fi
ok "Wrapper script: $WRAPPER"

# Check .env
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    warn "No .env file found. Using defaults."
    if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        ok "Copied .env.example to .env"
    fi
fi

# ── Generate service file ────────────────────────────────────────
info "Generating systemd service file..."

cat > /tmp/raven.service << SERVICEEOF
[Unit]
Description=Raven AI Agent — Personal JARVIS-class Intelligence
Documentation=https://github.com/swadhinbiswas/Raven
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_ROOT}
Environment=HOME=/home/${CURRENT_USER}
ExecStart=${WRAPPER} --daemon
Restart=always
RestartSec=8
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal
SyslogIdentifier=raven

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${PROJECT_ROOT} /tmp
PrivateTmp=yes

# Resource limits
MemoryMax=4G
CPUQuota=400%

[Install]
WantedBy=multi-user.target
SERVICEEOF

ok "Service file generated at /tmp/raven.service"

# ── Install service ──────────────────────────────────────────────
info "Installing systemd service..."
sudo cp /tmp/raven.service "$SERVICE_FILE"
sudo systemctl daemon-reload
ok "Service installed"

# ── Enable & start ───────────────────────────────────────────────
info "Enabling service (auto-start on boot)..."
sudo systemctl enable "$SERVICE_NAME"
ok "Service enabled"

info "Starting service..."
sudo systemctl start "$SERVICE_NAME"
sleep 2

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running!"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Raven is now running as a systemd service!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Commands:"
    echo "    systemctl status raven    — Check status"
    echo "    journalctl -u raven -f    — View logs"
    echo "    systemctl restart raven   — Restart"
    echo "    systemctl stop raven      — Stop"
    echo ""
    echo "  Dashboard:"
    echo "    raven dashboard           — Live TUI"
    echo "    http://localhost:8090      — Web UI"
    echo ""
else
    warn "Service may not have started correctly."
    echo "  Check: sudo journalctl -u raven -n 20"
fi
