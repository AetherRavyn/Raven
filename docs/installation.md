# Installation & Setup

Complete guide to installing Raven on Linux, macOS, Windows (WSL2),
and containerized environments.

---

## Prerequisites

### Required

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | >=3.12, <3.14 | 3.12 or 3.13 recommended. CPython only. |
| uv | >=0.4.0 | Fast Python package manager by Astral. |
| Git | >=2.30 | For cloning and version management. |

### Platform-Specific System Dependencies

**Linux (Debian/Ubuntu):**
```bash
sudo apt update
sudo apt install -y python3-dev python3-venv build-essential \
  libssl-dev libffi-dev portaudio19-dev espeak-ng \
  tesseract-ocr tesseract-ocr-eng ffmpeg libsm6 libxext6
```

**Linux (Fedora/RHEL):**
```bash
sudo dnf install -y python3-devel gcc-c++ portaudio-devel \
  espeak-ng tesseract tesseract-langpack-eng ffmpeg
```

**Linux (Arch):**
```bash
sudo pacman -S python python-pip base-devel portaudio espeak-ng \
  tesseract tesseract-data-eng ffmpeg
```

**macOS (Homebrew):**
```bash
brew install python@3.12 uv portaudio espeak-ng tesseract ffmpeg
```

**Windows (WSL2 with Ubuntu):**
```bash
# Install WSL2 first: wsl --install -d Ubuntu-24.04
# Then follow Linux instructions above.
```

---

## Minimum Viable Configuration

Only **three environment variables** are essential to get Raven running:

```env
# Pick ONE LLM provider:
ANTHROPIC_API_KEY=sk-ant-...   # Claude — recommended
# or
OPENAI_API_KEY=sk-...          # GPT-4o / o-series
# or
GEMINI_API_KEY=...             # Gemini 2.5 Pro — free tier available
```

Raven works with any single provider. The full `.env.example` has 200+ variables, all optional.

---

### Optional but Recommended

| Tool | Purpose | Install |
|------|---------|---------|
| Docker | HelixDB sidecar, container management | `docker.io` or `docker-ce` |
| Node.js + npm | WhatsApp bridge, MCP servers | `nodejs` >=18 |
| CUDA Toolkit | GPU acceleration for local LLMs | `nvidia-cuda-toolkit` |
| Ollama | Local LLM inference | `curl -fsSL https://ollama.ai/install.sh \| sh` |
| Playwright Browsers | Browser automation | `playwright install chromium` |
| Piper TTS Voice | Local text-to-speech | Downloaded on first voice use |

---

## Installation Methods

### Method 1: Standard Installation (Linux/macOS)

```bash
# 1. Clone the repository
git clone https://github.com/AetherRavyn/Raven.git
cd Raven

# 2. Create virtual environment with uv
uv venv
source .venv/bin/activate

# 3. Install dependencies
uv sync

# 4. Copy environment template
cp .env.example .env

# 5. Run first-time setup
raven onboard
```

### Method 2: Development Installation

```bash
git clone https://github.com/AetherRavyn/Raven.git
cd Raven
uv venv
source .venv/bin/activate

# Install with dev dependencies (ruff, pyright, pytest)
uv sync

# Install Playwright browsers for web tool
playwright install chromium

# Install additional dev tools
uv pip install pre-commit
pre-commit install
```

Development installation includes:
- `ruff` — linter and formatter
- `pyright` — static type checker
- `pytest`, `pytest-asyncio`, `pytest-cov` — test runner and coverage
- `cairosvg` — SVG rendering in tests

---

## Auto-Start on Boot (systemd)

Raven can run as a systemd service that starts automatically on boot.

### Quick Install

```bash
# One command — detects paths, installs, enables
./scripts/install-service.sh
```

This will:
1. Auto-detect your installation directory
2. Find the Python venv
3. Generate a systemd service file
4. Install, enable, and start the service

### Manual Install

```bash
# The wrapper script auto-detects venv and .env
chmod +x scripts/raven-daemon.sh

# Copy the service template
sudo cp deploy/raven.service /etc/systemd/system/raven.service

# Edit paths if needed (default: /home/$USER/SARAS)
sudo nano /etc/systemd/system/raven.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable raven
sudo systemctl start raven
```

### Managing the Service

```bash
systemctl status raven        # Check status
systemctl restart raven       # Restart
systemctl stop raven          # Stop
journalctl -u raven -f        # View live logs
```

### Uninstall

```bash
./scripts/install-service.sh --remove
```

### Method 3: Docker Installation

**Using Docker Compose (recommended):**

Ensure Docker and Docker Compose v2 are installed:
```bash
docker --version         # Docker 24+
docker compose version   # Docker Compose v2
```

Edit `docker-compose.yml` to set your API keys or mount a `.env` file:
```yaml
services:
  raven:
    build: .
    ports:
      - "8090:8090"
    env_file:
      - .env
    volumes:
      - ./workspace:/app/workspace
      - ./models:/app/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

```bash
docker compose up -d
docker compose logs -f
```

**Building the Docker image manually:**
```bash
docker build -t raven:latest .
docker run -d --name raven \
  -p 8090:8090 \
  --env-file .env \
  -v $(pwd)/workspace:/app/workspace \
  raven:latest
```

The Dockerfile uses:
- Base: `nvidia/cuda:12.4.0-runtime-ubuntu22.04` for CUDA-accelerated ONNX
- Python 3.12 installed via deadsnakes PPA
- System deps: ffmpeg, portaudio, tesseract, espeak-ng, git
- uv installer via curl
- `uv sync` without dev dependencies (production profile)

### Method 4: Windows Installation (Native, Experimental)

Windows native support is limited. WSL2 (Method 1) is strongly recommended.

```powershell
# Using PowerShell 7+
git clone https://github.com/AetherRavyn/Raven.git
cd Raven

# Requires Python 3.12 from python.org
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install uv
pip install uv

# Install dependencies
uv sync

# Copy env template
copy .env.example .env

# Run setup
python -m app.cli.main onboard
```

**Known Windows limitations:**
- Voice pipeline (sounddevice) does not work natively
- iMessage connector is macOS-only
- WeChat connector has stability issues on Windows
- Edge node service (`os.fork()` not supported) — use Docker instead

---

## First-Time Setup: `raven onboard`

The `raven onboard` command runs an interactive wizard that configures
essential settings. The wizard walks through 4 steps:

### Step 1: LLM Providers

```
━━━ Step 1: LLM Providers ━━━

  ✓ Gemini: configured
  → Configure OpenAI? [y/N]: y
  → OpenAI key (https://platform.openai.com/api-keys): ************
  ✓ OpenAI: set
  → Configure Anthropic? [y/N]: n
  ↷ Anthropic: skipped
  ...
```

Prompts for these providers in order:
1. **Gemini** (recommended) — Sign up at https://aistudio.google.com/apikey
2. **OpenAI** — https://platform.openai.com/api-keys
3. **Anthropic** — https://console.anthropic.com
4. **Groq** — https://console.groq.com
5. **OpenRouter** — https://openrouter.ai/keys
6. **xAI/Grok** — https://console.x.ai

### Step 2: Messaging Channels

```
━━━ Step 2: Messaging Channels ━━━

  ✓ Telegram Bot: configured
  → Configure Discord Bot? [y/N]: y
  → Discord Bot token: ************
  ✓ Discord: set
  ↷ Slack: skipped
```

Prompts for Telegram, Discord, and Slack bot tokens.

### Step 3: Identity

```
━━━ Step 3: Identity ━━━

  → Your city (for weather) [London]: San Francisco
```

Sets `DEFAULT_LOCATION` for weather queries.

### Step 4: Voice Pipeline

```
━━━ Step 4: Voice Pipeline ━━━

  → Enable voice (wake word + STT + TTS)? [y/N]: y
  ✓ Voice: enabled
```

Sets `ENABLE_LOCAL_VOICE=true`.

### Completion

```
━━━ Saving Configuration ━━━

  ✓ Wrote 4 settings to /path/to/Raven/.env

━━━ Setup Complete ───

  Run raven doctor to verify everything works
  Run raven chat to start chatting
```

---

## Platform-Specific Setup Guides

### Telegram

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow prompts to create a bot
3. Copy the bot token (format: `123456:ABC-DEF1234ghIkl`)
4. Set `TELEGRAM_BOT_TOKEN` in `.env`
5. (Optional) Disable Group Privacy in Bot Settings → Group Privacy → Off
6. (Optional) For webhook mode, set `TELEGRAM_WEBHOOK_URL` to your public HTTPS URL

### Discord

1. Go to https://discord.com/developers/applications
2. Click "New Application", give it a name
3. Go to Bot → "Add Bot" → Copy token
4. Enable **Message Content Intent** (REQUIRED) and **Voice State Intent**
5. Set `DISCORD_BOT_TOKEN` in `.env`
6. Use OAuth2 URL Generator with `bot` and `applications.commands` scopes
7. Select required permissions: Send Messages, Read Message History, Attach Files, Embed Links
8. Open the generated URL in browser to invite bot to your server
9. Find your server's channel ID (right-click channel → Copy ID with Developer Mode enabled)
10. Set `DISCORD_CHANNEL_ID` in `.env`

### Slack

1. Go to https://api.slack.com/apps → "Create New App" → "From scratch"
2. Set Bot Token Scopes: `channels:history`, `groups:history`, `im:history`, `mpim:history`, `channels:read`, `chat:write`, `files:write`, `app_mentions:read`
3. Enable Socket Mode (Settings → Socket Mode → Enable)
4. Subscribe to events: `message.channels`, `message.groups`, `message.im`, `message.mpim`, `app_mention`
5. Install to Workspace → Copy Bot Token (`xoxb-...`)
6. Go to Settings → Basic Information → App-Level Tokens → Generate Token with `connections:write` scope → Copy App Token (`xapp-...`)
7. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`

### WhatsApp

1. Navigate to the Baileys bridge directory (separate Node.js project):
   ```bash
   cd bridge/waha
   npm install
   ```
2. Run the bridge:
   ```bash
   npm run start
   ```
3. Scan the QR code displayed in terminal with WhatsApp mobile app (Settings → Linked Devices → Link a Device)
4. Set `WHATSAPP_BRIDGE_URL=http://localhost:3001` in `.env`
5. Restart Raven. The bridge session persists in `bridge/auth_info/`.

### Signal

1. Download and install signal-cli:
   ```bash
   # Linux
   curl -LO https://github.com/AsamK/signal-cli/releases/latest/download/signal-cli-.tar.gz
   tar -xzf signal-cli-*.tar.gz
   sudo ln -s $(pwd)/signal-cli-/bin/signal-cli /usr/local/bin/
   ```
2. Register your phone number:
   ```bash
   signal-cli -u +15551234567 register
   # Check SMS for captcha if required:
   signal-cli -u +15551234567 register --captcha
   ```
3. Verify with the code received via SMS:
   ```bash
   signal-cli -u +15551234567 verify 123456
   ```
4. Start signal-cli in daemon mode:
   ```bash
   signal-cli -u +15551234567 daemon --http
   ```
5. Set env vars in `.env`:
   ```
   SIGNAL_PHONE_NUMBER=+15551234567
   SIGNAL_HTTP_URL=http://localhost:8080
   ```

### Matrix

1. Create a Matrix account on a homeserver (e.g., matrix.org)
2. Log in with Element (app.element.io)
3. Get access token: Settings → Help & About → Advanced → Access Token
4. Set env vars:
   ```
   MATRIX_HOMESERVER=https://matrix.org
   MATRIX_USER_ID=@raven:matrix.org
   MATRIX_ACCESS_TOKEN=syt_your_matrix_token_here
   MATRIX_DEVICE_ID=raven-bot
   ```
5. Invite the bot user to target rooms

### IRC

1. Register the bot nickname on the IRC network (if required):
   ```
   /msg NickServ REGISTER password youremail@example.com
   ```
2. Set env vars:
   ```
   IRC_SERVER=irc.libera.chat
   IRC_PORT=6697
   IRC_NICK=RavynBot
   IRC_CHANNELS=#raven,#bots
   IRC_PASSWORD=server_password
   ```

### LINE

1. Create a Messaging API channel at https://developers.line.biz/console/
2. Set webhook URL: `https://your-public-host/webhook/line`
3. Enable webhook in LINE Developers Console
4. Set env vars:
   ```
   LINE_CHANNEL_ACCESS_TOKEN=your_access_token
   LINE_CHANNEL_SECRET=your_channel_secret
   ```
5. NOTE: LINE requires a public HTTPS URL. Use a reverse proxy (nginx/caddy) or ngrok for testing:
   ```bash
   ngrok http 8090
   ```

### iMessage (macOS Only)

1. Ensure macOS has an active iMessage account signed in
2. Grant Full Disk Access to your terminal emulator:
   - System Settings → Privacy & Security → Full Disk Access
   - Add your terminal app (Terminal, iTerm2, Warp)
3. No env vars required. Automatically detected on macOS.

### WeChat

1. Install itchat: `uv pip install itchat`
2. No env vars required. Run Raven and scan the QR code in terminal.
3. NOTE: WeChat Web protocol is deprecated. Stability is not guaranteed.

### Voice Pipeline

1. Ensure system deps are installed (portaudio, espeak-ng, ffmpeg)
2. Set env vars:
   ```
   ENABLE_LOCAL_VOICE=true
   VOICE_STT_MODEL=tiny
   WHISPER_CPP_MODEL=workspace/models/whisper/ggml-tiny.bin
   ```
3. Download whisper.cpp model:
   ```bash
   mkdir -p workspace/models/whisper
   curl -L -o workspace/models/whisper/ggml-tiny.bin \
     https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin
   ```
4. Piper TTS voice model is shipped with the repo at `app/voice/en_US-lessac-medium.onnx`.

### Web Dashboard

1. Set env vars (all optional with sensible defaults):
   ```
   WEB_DASHBOARD_ENABLED=true
   WEB_DASHBOARD_PORT=8090
   WEB_DASHBOARD_HOST=127.0.0.1
   ```
2. Access dashboard at `http://localhost:8090/ui`

---

## Verifying System Dependencies

Check that all system-level dependencies are available:

```bash
# Python version
python3 --version                 # Must be >= 3.12

# Package manager
uv --version                      # Must be >= 0.4.0

# Media/audio deps
ffmpeg -version                   # Should print version info
pkg-config --libs portaudio-2.0   # Should print -lportaudio
ldconfig -p | grep libsndfile     # Should show libsndfile

# Container runtime (optional)
docker --version                  # Docker 24+ for sidecar services
```

All commands should exit with status 0 and print version/library information.

---

## Verifying Installation

### Run Diagnostics

```bash
raven doctor
```

Expected output (healthy system):
```
Python Environment
  ✓ Python 3.12.3
  ✓ Virtual environment: /path/to/.venv

Core Dependencies
  ✓ pyyaml
  ✓ sentence-transformers
  ✓ google-generativeai
  ...

API Keys
  ✓ Gemini: ABCD...wxyz
  ✓ OpenAI: not set
  ...

Messaging Channels
  ✓ Telegram: configured
  ...

Identity Files
  ✓ SOUL.md (12,345 bytes)
  ✓ MEMORY.md (8,901 bytes)
  ✓ AGENTS.md (3,456 bytes)

Skills System
  ✓ Bundled skills: 12
  ✓ Learned skills: 0

System Tools
  ✓ docker: found
  ✓ git: found
  ...

Disk Space
  ✓ Disk space: 234.5 GB free

Summary
  All systems nominal!
```

### Test Chat

```bash
raven chat
```

```
──────────────────────────────────────────────
  RAVEN Terminal Chat
  ℹ Type your message. Type /help for commands.
  ℹ Type quit or press Ctrl+C to exit.
──────────────────────────────────────────────

  █ Hello, Raven!
  raven 14:23:01
  Hello! I'm Raven, your JARVIS-class AI agent. How can I help you today?
```

---

## Troubleshooting

### uv: command not found

Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or with pip:
pip install uv
```

### Python 3.12 not available on system

**Ubuntu 22.04 (deadSnakes PPA):**
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**macOS (Homebrew):**
```bash
brew install python@3.12
```

**Windows:**
Download from https://www.python.org/downloads/

### uv sync fails with build errors

Install system build dependencies:
```bash
# Ubuntu/Debian
sudo apt install build-essential python3-dev
# macOS
xcode-select --install
```

### Playwright browser not found

```bash
playwright install chromium
# Or force reinstall:
playwright install --force chromium
```

### Discord: Bot does not respond

1. Verify Message Content Intent is enabled in Discord Developer Portal
2. Re-invite the bot with updated permissions
3. Check `DISCORD_CHANNEL_ID` matches an actual channel in your server

### Telegram: Bot does not receive group messages

1. Open BotFather → `/mybots` → Select bot → Bot Settings → Group Privacy → Disable
2. Add bot to group as administrator for full message access

### Voice: No audio output

1. Check `sounddevice` sees your devices:
   ```bash
   python -c "import sounddevice; print(sounddevice.query_devices())"
   ```
2. Set `VOICE_MIC_DEVICE` to the correct device index
3. Verify Piper model exists at `PIPER_VOICE_MODEL` path
4. Check `ENABLE_LOCAL_VOICE=true` is set

### Port conflicts (port 8090 already in use)

```bash
raven run --port 9090
# Or kill the existing process:
raven stop
lsof -i :8090  # Find PID
kill -9 <PID>
```

### ModuleNotFoundError: No module named 'raven_protocol'

The `raven_protocol` package is not yet published to PyPI. Install from source:
```bash
# It should be bundled in the repo. If not:
git submodule update --init --recursive
```

### Docker: NVIDIA GPU not accessible

Install NVIDIA Container Toolkit:
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

## Next Steps

Now that Raven is installed, continue with:

| Guide | Description |
|-------|-------------|
| [CLI Reference](reference-cli.md) | All `raven` subcommands and flags |
| [Agent Architecture](guides-agents.md) | Understanding the 15-agent swarm |
| [Soul Definition](guides-soul.md) | Customizing Raven's personality |
| [Voice Pipeline](features-voice.md) | Wake-word, STT, TTS setup |
| [Messaging Platforms](messaging-platforms.md) | Per-platform setup guides |
| [Dashboard Overview](index.md) | Full documentation index |

---

## Uninstallation

```bash
# Stop Raven
raven stop

# Remove virtual environment
rm -rf .venv

# Remove workspace data (logs, checkpoints, sessions)
rm -rf workspace

# Remove config
rm .env

# Remove PID files
rm -f ~/.raven/raven.pid ~/.raven/raven.log

# Remove Docker images (if used)
docker compose down --rmi all
```
