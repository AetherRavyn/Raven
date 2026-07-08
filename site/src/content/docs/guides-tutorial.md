---
title: "Getting Started Tutorial"
---

# Getting Started Tutorial

> **Document level**: Hermes  
> **Last updated**: 2026-06-30  
> **Reading time**: 15 minutes

This guide walks you through installing Raven, configuring it minimally, and having your first conversation. By the end, you will have a running personal AI agent connected to your terminal.

---

## Prerequisites

### Required

| Dependency | Version | Check Command |
|------------|---------|---------------|
| Python | >=3.12, <3.14 | `python3 --version` |
| uv | >=0.4.0 | `uv --version` |
| Git | >=2.30 | `git --version` |
| Make | any | `make --version` |

### Install Python 3.12

**Ubuntu/Debian:**
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**macOS:**
```bash
brew install python@3.12
```

**Windows:** Use WSL2 with Ubuntu (see below).

### Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or via pip:
```bash
pip install uv
```

### System Dependencies

**Linux (Debian/Ubuntu):**
```bash
sudo apt update
sudo apt install -y python3-dev python3-venv build-essential \
  libssl-dev libffi-dev portaudio19-dev espeak-ng \
  tesseract-ocr tesseract-ocr-eng ffmpeg libsm6 libxext6
```

**macOS:**
```bash
brew install portaudio espeak-ng tesseract ffmpeg
```

### Docker (Optional but Recommended)

For HelixDB (knowledge graph database):
```bash
# Linux
sudo apt install docker.io docker-compose-v2

# macOS
brew install docker docker-compose
```

---

## Installation Walkthrough

### Step 1: Clone the Repository

```bash
git clone https://github.com/AetherRavyn/Raven.git
cd Raven
```

### Step 2: Create Virtual Environment

```bash
uv venv
source .venv/bin/activate
```

You should see `(.venv)` in your prompt. Add this to your shell rc file to automate activation:

```bash
# ~/.zshrc or ~/.bashrc
source /path/to/Raven/.venv/bin/activate
```

### Step 3: Install Dependencies

```bash
# Production dependencies (faster install)
uv sync --no-dev

# Or development dependencies (includes ruff, pyright, pytest)
uv sync
```

This installs ~80 direct dependencies. First install takes 2-5 minutes depending on network speed.

### Step 4: Copy Environment Template

```bash
cp .env.example .env
```

---

## Minimum Viable .env Configuration

Raven can run with a single LLM provider. The recommended minimum is **OpenCode Zen** (free, no API key needed):

```bash
# .env — minimum configuration
OPENCODE_ZEN_API_KEY=no-key-needed
OPENCODE_ZEN_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_ZEN_MODEL=big-pickle
```

If you have a Gemini API key (free tier available at aistudio.google.com):

```bash
GEMINI_API_KEY=your_gemini_key_here
```

Both providers give you a working Raven immediately. Add more providers later for capability depth and fallback resilience.

### Verify Configuration

```bash
grep -v '^#' .env | grep -v '^$'
```

Should show at least one LLM provider configured.

---

## First `raven chat` Conversation

### Start Raven

```bash
raven run
```

You will see the welcome screen:

```
██████╗  █████╗ ██████╗ ███████╗ ███╗   ██╗
██╔══██╗██╔══██╗██╔══██╗██╔════╝ ████╗  ██║
██████╔╝███████║██║  ██║█████╗   ██╔██╗ ██║
██╔══██╗██╔══██║██║  ██║██╔══╝   ██║╚██╗██║
██║  ██║██║  ██║██████╔╝███████╗ ██║ ╚████║
╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝ ╚═╝  ╚═══╝

┌── Status ─────────────────────────────────────────┐
│ RAVEN is running. All systems operational.         │
└────────────────────────────────────────────────────┘

┌── Endpoints ───────────────────────────────────────┐
│  Web Dashboard  http://localhost:8090               │
│  API            http://localhost:8090/v1/chat/completions │
└────────────────────────────────────────────────────┘
```

Leave this terminal open. Open a second terminal window.

### Launch Chat

```bash
# In the second terminal
cd /path/to/Raven
source .venv/bin/activate
raven chat
```

You will see:

```
──────────────────────────────────────────────
  RAVEN Terminal Chat
  ℹ Type your message. Type /help for commands.
  ℹ Type quit or press Ctrl+C to exit.
──────────────────────────────────────────────

  █
```

### Say Hello

Type your message and press Enter:

```
  █ Hello, Raven! What can you do?
```

Raven will process your message and respond:

```
  raven 14:23:01
  Hello! I'm Raven, your JARVIS-class AI agent. I can help you with:

  • Web searches and research
  • Code generation and debugging
  • File management and organization
  • Calendar and scheduling
  • Smart home control
  • And much more — just ask!

  Use /help to see all available commands.
```

### Chat Commands

While in `raven chat`, these commands are available:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/mode` | Show current operating mode |
| `/providers` | List available providers |
| `/memory recall <query>` | Search memories |
| `quit` or `Ctrl+C` | Exit chat |

### Exit Chat

Press `Ctrl+C` or type `quit` to return to the shell.

---

## First `raven doctor` Checkup

`raven doctor` runs comprehensive diagnostics to verify your installation.

### Run Diagnostics

```bash
raven doctor
```

### Expected Output (Healthy System)

```
Python Environment
  ✓ Python 3.12.3
  ✓ Virtual environment: /path/to/.venv

Core Dependencies
  ✓ pyyaml
  ✓ sentence-transformers
  ✓ aiohttp
  ✓ apscheduler
  ...

API Keys
  ✓ OpenCode Zen: configured
  ✓ Gemini: not set

Messaging Channels
  ○ Telegram: not configured
  ○ Discord: not configured

Identity Files
  ✓ SOUL.md (12,345 bytes)
  ✓ MEMORY.md (8,901 bytes)
  ✓ AGENTS.md (3,456 bytes)

Skills System
  ✓ Bundled skills: 12
  ✓ Learned skills: 0

System Tools
  ✓ git: found
  ○ docker: not found

Disk Space
  ✓ Disk space: 234.5 GB free

Summary
  ✓ All systems nominal!
  ℹ 2 optional checks skipped (not configured)
```

### Understanding the Output

| Symbol | Meaning |
|--------|---------|
| `✓` | Check passed or configured |
| `○` | Optional check (not configured, not required) |
| `✗` | Check failed (needs attention) |

### Common Issues and Fixes

**"Python 3.12+ required"**: Your system Python is too old. Install Python 3.12 using deadsnakes PPA or homebrew, then recreate the venv.

**"Virtual environment: not detected"**: You are not in the venv. Run `source .venv/bin/activate` first.

**"API Keys: none configured"**: You forgot to set up `.env`. Go back to the minimum viable configuration step.

---

## Using `/web search` and `/schedule` Commands

Raven supports slash commands for common actions. These work in both `raven chat` and on any connected platform (Telegram, Discord, etc.).

### Web Search

```bash
/web search latest developments in quantum computing
```

Raven will:
1. Use the Brave Search or web search tool to query the internet
2. Fetch and summarize the top results
3. Cite sources with links

```
  raven 14:25:00
  Here are the latest developments in quantum computing:

  1. **Google Willow Chip** — Google announced a new quantum chip
     that performs computation in 5 minutes that would take a
     supercomputer 10^25 years. [Source]

  2. **Error Correction Milestone** — A team at MIT demonstrated
     logical qubits with error rates below the surface code
     threshold. [Source]

  3. ...
```

### Schedule Management

```bash
/schedule remind me to review PR #42 tomorrow at 3pm
```

Raven will:
1. Parse the schedule request using NLP
2. Create a cron job in the task scheduler
3. Confirm the reminder

```
  raven 14:26:00
  ✓ Reminder set: "Review PR #42" for tomorrow at 3:00 PM.
  Use /schedule list to see all your reminders.
```

```bash
/schedule list
```

```
  raven 14:26:30
  Your scheduled items:
  • Tomorrow 3:00 PM — Review PR #42
  • Every day 8:00 AM — Morning briefing
  • Friday 5:00 PM — Weekly review
```

---

## Connecting Telegram/Discord

### Telegram (Recommended for First Connection)

1. **Create a bot** — Open Telegram, search for `@BotFather`, and send `/newbot`. Follow the prompts, choose a name (e.g., "My Raven"). Copy the token.

2. **Configure Raven**:
   ```bash
   # Edit .env and add:
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

3. **Restart Raven**:
   ```bash
   raven stop && raven run
   ```

4. **Start chatting** — Open Telegram, find your bot, and send `/start`.

```
  You: /start
  Raven: Hello! I'm Raven. How can I help you today?
```

### Discord

1. **Create a bot** — Go to https://discord.com/developers/applications, click "New Application", go to Bot → "Add Bot", and copy the token. Enable **Message Content Intent**.

2. **Configure Raven**:
   ```bash
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   DISCORD_CHANNEL_ID=123456789012345678
   ```

3. **Invite the bot** — Use the OAuth2 URL Generator with `bot` and `applications.commands` scopes. Open the URL in a browser to invite the bot to your server.

4. **Restart Raven** and send a message in the configured channel.

### All Platforms at Once

Use `raven onboard` for an interactive wizard:

```bash
raven onboard
```

It walks through the steps for each platform and writes to `.env`.

---

## Building Your First Automation Blueprint

Blueprints are reusable automation workflows defined in YAML. This example creates a daily standup reminder.

### Step 1: Create the Blueprint

Create `workspace/blueprints/standup.yaml`:

```yaml
name: daily_standup
version: "1.0"
description: Send a standup reminder to Telegram every weekday at 9:30 AM
author: you
enabled: true

steps:
  - id: send_reminder
    name: Send Standup Reminder
    description: Remind the team to post standup updates
    action:
      type: message
      platform: telegram
      target: "-1001234567890"
      text: |
        ☀️ Good morning! Time for your daily standup:

        1. What did I accomplish yesterday?
        2. What am I working on today?
        3. Any blockers?

        Reply to this message with your update.
```

### Step 2: Install the Blueprint

```bash
raven skills install workspace/blueprints/standup.yaml
```

Or via the web dashboard at `http://localhost:8090/blueprints`, click "Upload Blueprint", and paste the YAML.

### Step 3: Schedule the Blueprint

Use the cron dashboard (`http://localhost:8090/cron`) to create a cron job:

- **Job ID**: `standup_reminder`
- **Schedule**: `daily at 09:30`
- **Action**: `run_blueprint: daily_standup`

Or via API:

```bash
curl -X POST http://localhost:8090/api/cron/add \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "standup_reminder",
    "name": "Daily Standup",
    "schedule_type": "daily",
    "time_str": "09:30",
    "action_description": "run_blueprint:daily_standup"
  }'
```

### Step 4: Test It

```bash
curl -X POST http://localhost:8090/api/blueprints/run \
  -H "Content-Type: application/json" \
  -d '{"blueprint_id": "daily_standup"}'
```

### More Blueprint Ideas

| Blueprint | Description |
|-----------|-------------|
| `morning_briefing` | Weather + calendar + news digest |
| `weekly_report` | Aggregate weekly stats and learnings |
| `website_monitor` | Check a URL every 5 minutes, alert on changes |
| `git_backup` | Auto-commit and push workspace changes |
| `smart_home_goodnight` | Turn off lights, lock doors, set thermostat |

See the [Features — Automation](/features-automation/) doc for complete blueprint reference.

---

## Next Steps / Where to Go From Here

### Immediate Next Steps

1. **Set up voice** — Enable local STT (Whisper) + TTS (Piper) for hands-free interaction. See `installation.md:Voice Pipeline`.
2. **Connect more platforms** — Add WhatsApp (via Baileys bridge), Slack, or Signal.
3. **Create your first skill** — Raven can auto-crystallize multi-step workflows into reusable skills. Ask it to "remember how to do this."
4. **Explore the web dashboard** — Open `http://localhost:8090` in your browser for the full management interface.

### Recommended Reading

| Document | What It Covers |
|----------|----------------|
| `docs/overview.md` | Complete feature overview and architecture |
| `docs/reference-cli.md` | All CLI commands with examples |
| `docs/reference-api.md` | Full API reference |
| `docs/developer-architecture.md` | Deep dive into the 8-layer stack |
| `docs/guides-agents.md` | 15 agents and the swarm system |
| `docs/features-skills.md` | Skill crystallization and the learning system |
| `docs/features-automation.md` | Ambient loop, scheduling, workflows |
| `docs/02-platform-connectors.md` | Complete platform setup guides |
| `docs/08-deployment-scaling.md` | Docker, cloud, and edge deployment |

### Join the Community

- **GitHub Issues**: Report bugs or request features
- **Discussions**: Ask questions and share blueprints
- **Discord/Telegram**: Get real-time help (configured channels in your Raven instance)

### Production Deployment Checklist

- [ ] Set up at least 2 LLM providers for fallback
- [ ] Configure `ADMIN_USER_IDS` for privileged access
- [ ] Enable dashboard authentication (`API_BEARER_TOKEN`)
- [ ] Set up Docker for HelixDB and sandboxed execution
- [ ] Configure monitoring alerts for system health
- [ ] Review and customize `SOUL.md` and `MEMORY.md`
- [ ] Run `raven cleanup --dry-run` to preview data pruning
- [ ] Test backup and restore workflow
