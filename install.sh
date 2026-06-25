#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Raven Agent — Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/SwadhinBiswas/Raven/main/install.sh | bash
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

RAVEN_HOME="${HERMES_HOME:-$HOME/.raven}"
RAVEN_REPO="https://github.com/SwadhinBiswas/Raven.git"
RAVEN_BRANCH="main"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

banner() {
    echo -e "${BLUE}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║   ██████╗  █████╗ ██████╗ ████████╗      ║"
    echo "  ║   ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝      ║"
    echo "  ║   ██████╔╝███████║██║  ██║   ██║          ║"
    echo "  ║   ██╔══██╗██╔══██║██║  ██║   ██║          ║"
    echo "  ║   ██║  ██║██║  ██║██████╔╝   ██║          ║"
    echo "  ║   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝    ╚═╝          ║"
    echo "  ║   Raven Agent — JARVIS-class AI            ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
}

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; }
info()  { echo -e "${BLUE}[·]${NC} $*"; }

# ─── Check prerequisites ─────────────────────────────────────────────
check_prereqs() {
    if ! command -v git &>/dev/null; then
        error "git is required. Install it first."
        exit 1
    fi
    if ! command -v curl &>/dev/null; then
        error "curl is required. Install it first."
        exit 1
    fi
}

# ─── Install uv (fast Python package manager) ────────────────────────
install_uv() {
    if command -v uv &>/dev/null; then
        log "uv already installed"
    else
        info "Installing uv (fast Python package manager)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        log "uv installed"
    fi
}

# ─── Install Python 3.12+ via uv ────────────────────────────────────
install_python() {
    if uv python list 2>/dev/null | grep -q "3.12\|3.13"; then
        log "Python 3.12+ already available via uv"
    else
        info "Installing Python 3.12 via uv..."
        uv python install 3.12
        log "Python 3.12 installed"
    fi
}

# ─── Clone or update Raven ────────────────────────────────────────────
setup_repo() {
    if [ -d "$RAVEN_HOME" ]; then
        log "Raven directory exists at $RAVEN_HOME"
        info "Pulling latest changes..."
        cd "$RAVEN_HOME" && git pull origin "$RAVEN_BRANCH" 2>/dev/null || true
    else
        info "Cloning Raven to $RAVEN_HOME..."
        git clone --depth 1 -b "$RAVEN_BRANCH" "$RAVEN_REPO" "$RAVEN_HOME"
        log "Raven cloned"
    fi
    cd "$RAVEN_HOME"
}

# ─── Create virtual environment and install ───────────────────────────
setup_venv() {
    cd "$RAVEN_HOME"
    if [ ! -d ".venv" ]; then
        info "Creating virtual environment..."
        uv venv --python 3.12 .venv
    fi

    info "Installing Raven and dependencies..."
    uv pip install -e "." --quiet 2>/dev/null || uv pip install -e "."
    log "Raven installed"
}

# ─── Create global 'raven' command ────────────────────────────────────
setup_command() {
    local BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/raven" << 'LAUNCHER'
#!/usr/bin/env bash
RAVEN_HOME="${HERMES_HOME:-$HOME/.raven}"
exec "$RAVEN_HOME/.venv/bin/raven" "$@"
LAUNCHER
    chmod +x "$BIN_DIR/raven"

    # Add to PATH if not already there
    if ! echo "$PATH" | grep -q "$BIN_DIR"; then
        echo '' >> "$HOME/.bashrc"
        echo '# Raven Agent' >> "$HOME/.bashrc"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        info "Added $BIN_DIR to PATH in ~/.bashrc"
        info "Run: source ~/.bashrc"
    fi

    log "Global 'raven' command available"
}

# ─── Setup .env from example ──────────────────────────────────────────
setup_env() {
    cd "$RAVEN_HOME"
    if [ ! -f ".env" ]; then
        cp .env.example .env
        log "Created .env from .env.example"
        info "Edit $RAVEN_HOME/.env to add your API keys"
    else
        log ".env already exists"
    fi
}

# ─── Create systemd service (optional) ────────────────────────────────
setup_service() {
    if [ -d "/etc/systemd/system" ]; then
        cat > /tmp/raven.service << EOF
[Unit]
Description=Raven AI Agent
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$RAVEN_HOME
ExecStart=$RAVEN_HOME/.venv/bin/raven run --no-voice
Restart=on-failure
RestartSec=5
Environment=PATH=$RAVEN_HOME/.venv/bin:/usr/local/bin:/usr/bin

[Install]
WantedBy=multi-user.target
EOF
        info "Systemd service file created at /tmp/raven.service"
        info "To install: sudo cp /tmp/raven.service /etc/systemd/system/"
        info "To enable:  sudo systemctl enable raven && sudo systemctl start raven"
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────
main() {
    banner
    check_prereqs
    install_uv
    install_python
    setup_repo
    setup_venv
    setup_command
    setup_env
    setup_service

    echo ""
    log "Raven is installed! 🐦‍⬛"
    echo ""
    echo -e "  ${GREEN}Quick start:${NC}"
    echo "    source ~/.bashrc      # Reload shell"
    echo "    raven run              # Start Raven (with logs)"
    echo "    raven chat             # Terminal chat"
    echo "    raven status           # Check health"
    echo ""
    echo -e "  ${YELLOW}Edit your API keys:${NC}"
    echo "    nano $RAVEN_HOME/.env"
    echo ""
    echo -e "  ${BLUE}Open dashboard:${NC}"
    echo "    http://localhost:8090/ui"
    echo ""
}

main "$@"
