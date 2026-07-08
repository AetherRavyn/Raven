# Raven

**JARVIS-class personal AI agent** — self-improving, multi-platform, autonomous.

Raven is an intelligent personal AI companion you can talk to from anywhere: Telegram, Discord, WhatsApp, iMessage, WeChat, LINE, Signal, IRC, Matrix, voice, or web dashboard. It learns from every interaction, remembers your preferences, and gets better over time through RLHF and self-improvement loops.

---

## Documentation

Full documentation site: [https://aetherravyn.github.io/Raven](https://aetherravyn.github.io/Raven)

---

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | >=3.12, <3.14 | CPython only. 3.12 or 3.13 recommended. |
| uv | >=0.4.0 | Fast Python package manager by Astral. |
| Git | >=2.30 | For cloning and version management. |

**System dependencies (Linux Debian/Ubuntu):**

```bash
sudo apt update && sudo apt install -y \
  ffmpeg portaudio19-dev libsndfile1 build-essential \
  python3-dev python3-venv
```

---

## Quick Start

```bash
git clone https://github.com/AetherRavyn/Raven.git
cd Raven
uv venv && source .venv/bin/activate
uv sync
cp .env.example .env
# Edit .env: set at least ANTHROPIC_API_KEY or OPENAI_API_KEY
python main.py
```

---

## Minimum Viable `.env`

Only one of these is required to start chatting:

```env
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
# or
GEMINI_API_KEY=...
```

---

## Docker Setup

```bash
# Build and run with HelixDB
docker compose up -d
docker compose logs -f
```

For GPU acceleration (NVIDIA):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

---

## Testing

```bash
pytest              # 3800+ tests
ruff check app/     # linting
ruff format --check # formatting
pyright             # type checking
```

---

## Channel Support

| Platform | Status | Directory |
|----------|--------|-----------|
| Telegram | ✅ | `app/telegram/` |
| Discord | ✅ | `app/discord/` |
| IRC | ✅ | `app/irc/` |
| Matrix | ✅ | `app/matrix/` |
| Signal | ✅ | `app/signal/` |
| WhatsApp | ✅ | `app/whatsapp/` (requires Node.js bridge) |
| iMessage | ✅ | `app/imessage/` (macOS only) |
| WeChat | ✅ | `app/wechat/` |
| LINE | ✅ | `app/line/` |
| Slack | ✅ | `app/slack/` |
| Voice | ✅ | `app/voice/` |
| Web Dashboard | ✅ | `app/web/` |

---

## Troubleshooting

### `uv: command not found`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### `uv sync` fails with build errors

```bash
sudo apt install build-essential python3-dev
```

### Python 3.12+ not available

Ubuntu 22.04: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv`

macOS: `brew install python@3.12`

### Discord bot does not respond

Enable **Message Content Intent** in Discord Developer Portal under Bot settings, then re-invite the bot.

### Voice: no audio output

```bash
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Ensure `ENABLE_LOCAL_VOICE=true` and the Piper model exists at `app/voice/en_US-lessac-medium.onnx`.

---

## License

MIT
