# Frequently Asked Questions

> **Last updated**: 2026-06-30

---

## General Questions

### What is Raven?

Raven is a JARVIS-class personal AI agent — a self-improving, multi-platform, autonomous assistant that runs on your own hardware. It handles conversations, automates tasks, manages your schedule, controls smart home devices, and proactively monitors your digital environment.

### How is Raven different from ChatGPT?

| Aspect | Raven | ChatGPT |
|--------|-------|---------|
| **Architecture** | Self-hosted, runs on your hardware | Cloud-only |
| **Privacy** | Data stays on your machine | Data processed on OpenAI servers |
| **Autonomy** | Proactive ambient loop (27 subsystems) | Reactive (waits for prompts) |
| **Multi-platform** | 12 platforms + voice + web | Web + mobile app |
| **Tools** | 98+ tools (shell, git, docker, calendar, email, smart home, ...) | Browse + DALL-E + code interpreter |
| **Customization** | Full source access, SOUL.md, custom skills, custom agents | Limited to system prompt |
| **Offline** | Fully offline capable with local models | Requires internet |
| **Cost** | Free (self-hosted, local models) or API costs only | Subscription ($20/month+) |
| **Voice** | Local STT/TTS, wake word, barge-in | Cloud-based, limited |

### Is Raven really free?

Yes — Raven is MIT-licensed open source. You can run it with completely free local models (Ollama with Llama 3.2, Mistral, etc.) and OpenCode Zen (free tier, no API key). The only costs are your own hardware and electricity.

### What hardware do I need?

**Minimum** (terminal-only, no voice):
- 2 CPU cores, 4 GB RAM
- 10 GB disk space
- Any Linux, macOS, or Windows (WSL2) system

**Recommended** (full features, voice, web dashboard):
- 4+ CPU cores, 8+ GB RAM
- 20+ GB disk space (SSD preferred)
- GPU optional but recommended for local LLMs

**Raspberry Pi 4/5**: Runs the core agent and terminal chat, but voice and local LLMs are not practical.

### What does "JARVIS-class" mean?

Raven is designed to be the kind of AI assistant portrayed by JARVIS in the Iron Man movies — always on, proactive, capable of executing complex multi-step tasks across platforms, and deeply integrated with your digital environment.

### Does Raven use my data for training?

No. All data stays on your machine unless you explicitly configure a cloud LLM provider. Even then, only the prompts and responses are sent to the provider — no training or data mining.

---

## Installation Questions

### How do I install Raven?

```bash
git clone https://github.com/AetherRavyn/Raven.git
cd Raven
uv venv
source .venv/bin/activate
uv sync
cp .env.example .env
# Edit .env with at least one LLM provider
```

Detailed instructions in `docs/installation.md`.

### Python 3.12 is not available on my system

**Ubuntu/Debian:**
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**macOS:**
```bash
brew install python@3.12
```

### uv command not found

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or install via pip: `pip install uv`

### uv sync fails with build errors

Install system build dependencies:

```bash
# Ubuntu/Debian
sudo apt install build-essential python3-dev

# macOS
xcode-select --install
```

### Can I run Raven in Docker?

Yes. See `docs/installation.md` (Method 3: Docker Installation).

```bash
docker compose up -d
```

### Can I run Raven on Windows?

Windows native support is experimental. Use WSL2 (Ubuntu) for the best experience. See `docs/installation.md` (Method 4).

### How do I update Raven?

```bash
git pull
uv sync
raven stop && raven run
```

Check the CHANGELOG for breaking changes before updating.

---

## Configuration Questions

### What is the minimum .env configuration?

```bash
OPENCODE_ZEN_API_KEY=no-key-needed
OPENCODE_ZEN_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_ZEN_MODEL=big-pickle
```

This gives you a fully working Raven with a free LLM provider (no API key needed).

### What LLM providers are supported?

13+ providers: OpenAI, Anthropic, Google/Gemini, xAI/Grok, Groq, DeepSeek, OpenRouter, Ollama, vLLM, NVIDIA NIM, HuggingFace, Mistral, Cohere, OpenCode Zen, LocalAI/LM Studio. See `docs/features-core.md` for the full table.

### Do I need a GPU?

No. Raven runs on CPU alone using local models (Ollama) or cloud providers. A GPU accelerates local inference but is not required.

### How do I change the default LLM provider?

```bash
# Set in .env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o

# Or use the CLI
raven providers select openai gpt-4o
```

### Can I use multiple providers?

Yes. Raven automatically falls back through providers on failure. Configure combos:

```bash
raven providers combo create production "openai,anthropic,groq"
raven providers combo use production
```

### How do I enable voice?

Set in `.env`:

```bash
ENABLE_LOCAL_VOICE=true
```

Raven uses Whisper (STT) and Piper (TTS) — both run locally. See `docs/installation.md#voice-pipeline` for setup.

### What is OpenCode Zen?

OpenCode Zen is a free LLM gateway provided by the OpenCode project. It offers 5 free models (big-pickle, deepseek-v4-flash-free, mimo-v2.5-free, qwen3.6-plus-free, nemotron-3-super-free) with no API key required. It serves as Raven's always-available fallback provider.

---

## Usage Questions

### How do I start Raven?

```bash
raven run
```

This starts the daemon, FastAPI server, and all background loops.

### How do I chat with Raven?

```bash
raven chat          # Terminal chat interface
# Or open http://localhost:8090 in your browser
# Or message your bot on Telegram/Discord/etc.
```

### What commands can I use in chat?

| Command | Description |
|---------|-------------|
| `/web search <query>` | Search the web |
| `/schedule <reminder>` | Set a reminder |
| `/memory recall <query>` | Search memories |
| `/memory remember <text>` | Store a memory |
| `/clear` | Clear conversation |
| `/help` | Show available commands |
| `quit` | Exit chat |

### Can Raven browse the internet?

Yes. Raven has multiple web search tools (Brave Search, Firecrawl, web fetch, YouTube, Reddit, RSS). Configure at least one search provider in `.env`.

### Can Raven control my smart home?

Yes, if you have Home Assistant or MQTT. Configure:

```bash
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=your_token
# or
MQTT_BROKER_URL=mqtt://localhost:1883
```

### Can Raven write and execute code?

Yes. Raven has shell execution, Python REPL, Docker management, and git tools. All code execution goes through the 4-layer security pipeline — high-risk actions require human approval.

### Can Raven send emails?

Yes. Configure SMTP in `.env`:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
```

### Can Raven access my calendar?

Yes. Raven supports Google Calendar (OAuth) and Outlook/CalDAV. See `app/tools/calendar.py` and the integration guide.

### What is the ambient loop?

The ambient loop is a set of 27 background subsystems that run continuously — monitoring sensors, checking email, consolidating memories, generating insights, and performing maintenance. It makes Raven proactive rather than purely reactive.

### How do I see what Raven is doing?

- `raven dashboard` — Terminal system HUD
- `raven status` — Quick health check
- `raven log` — Recent log lines
- `http://localhost:8090` — Web dashboard

### Can I create custom skills?

Yes. Raven's SkillCrystallizer automatically creates skills from your interactions. You can also write skills manually as YAML/Python files with `SKILL.md` + `module.yaml` manifests.

### What are blueprints?

Blueprints are YAML-defined multi-step automation workflows. They can be scheduled via cron or triggered by events. See `docs/guides-tutorial.md` for a walkthrough.

---

## Troubleshooting Questions

### Raven won't start

Run diagnostics:
```bash
raven doctor
```

Common fixes:
- Ensure `.env` has at least one valid LLM provider
- Check Python version: `python3 --version` (must be 3.12+)
- Check virtual environment is activated
- Check port 8090 is not in use: `lsof -i :8090`

### Raven is not responding

- Check if Raven is running: `raven status`
- View recent logs: `raven log`
- Try restarting: `raven stop && raven run`
- Check the WebSocket connection in the browser dashboard

### "ModuleNotFoundError: No module named 'raven_protocol'"

The `raven_protocol` package is bundled in the repo. Ensure submodules are initialized:

```bash
git submodule update --init --recursive
```

### Chat is very slow

- Check which provider is active: `raven providers list`
- Switch to a faster provider: `raven providers select groq llama3-70b`
- Check network latency: `raven providers health`
- Use local models for simple queries: Ollama can respond in <1s

### Voice isn't working

- Verify `ENABLE_LOCAL_VOICE=true` in `.env`
- Check `sounddevice` sees your microphone: `python -c "import sounddevice; print(sounddevice.query_devices())"`
- Ensure whisper.cpp model is downloaded: `ls -la workspace/models/whisper/ggml-tiny.bin`
- Check system deps: portaudio, espeak-ng, ffmpeg

### Discord bot not responding

- Verify Message Content Intent is enabled in Discord Developer Portal
- Re-invite the bot with updated permissions
- Check `DISCORD_CHANNEL_ID` matches an actual channel
- Run `raven log` to see if Discord messages are being received

### Telegram bot not receiving group messages

- Open BotFather → `/mybots` → Select bot → Bot Settings → Group Privacy → Disable
- Add bot to group as administrator for full message access

### Port 8090 already in use

```bash
raven run --port 9090
# Or
raven stop  # then try again
```

### How do I reset everything?

```bash
# Stop Raven
raven stop

# Remove workspace data (careful — deletes all sessions, memories, learnings)
rm -rf workspace

# Remove config
rm .env

# Clean start
cp .env.example .env
raven onboard
```

### How do I get help?

- `raven doctor` — System diagnostics
- `raven --help` — CLI command list
- `raven log` — View recent logs
- `docs/` — Full documentation
- GitHub Issues — Bug reports and feature requests
