# CLI Reference

The `raven` CLI is the primary interface for managing the Raven agent,
running diagnostics, and invoking commands directly. Entry point:
`app.cli.main:main`. Registered in `pyproject.toml` as `raven =
"app.cli.main:main"`.

---

## Global Flags

| Flag | Description |
|------|-------------|
| `--version` | Show version and exit |
| `-h`, `--help` | Show help message with categorized subcommands |

---

## System Commands

### `raven run`

Start Raven in foreground or background daemon mode.

**Syntax:** `raven run [--pid] [--port PORT] [--no-voice]`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--pid` | flag | `false` | Run as background daemon (writes PID file, redirects logs) |
| `--port`, `-p` | int | `8090` | Dashboard/API server port |
| `--no-voice` | flag | `false` | Disable voice pipeline initialization |

**Exit Codes:** `0` (successful start), `1` (already running or error)

**Examples:**
```bash
raven run                              # Foreground with logs
raven run --pid                        # Background daemon
raven run --port 9090 --no-voice       # Custom port, no voice
```

**Behavior:** In daemon mode (`--pid`), forks the process. Parent writes PID to
`~/.raven/raven.pid` and exits. Child redirects stdout/stderr to
`~/.raven/raven.log`, calls `setsid()` to create a new session, then invokes
`raven daemon`. In foreground mode, writes PID and runs `raven daemon`
directly.

### `raven stop`

Gracefully stop the Raven daemon.

**Syntax:** `raven stop`

**Exit Codes:** `0` (stopped or not running), `1` (error)

**Examples:**
```bash
raven stop
```

**Behavior:** Reads PID from `~/.raven/raven.pid`, sends `SIGTERM`, waits for
process to terminate, removes PID file. Reports "not running" if no PID file.

### `raven status`

Show system health, connected edge nodes, and pending task approvals.

**Syntax:** `raven status`

**Exit Codes:** `0`

**Examples:**
```bash
raven status
```

**Output:**
```
─── RAVEN Status ───
  ● System Operational

  Pending Approvals: 2
    ● [task_abc] Review PR #42
    ● [task_def] Deploy to production

  Edge Nodes
  ● living-room-pi (online)
  ○ garage-pi (offline)
```

### `raven log`

Tail Raven daemon logs.

**Syntax:** `raven log [--lines N]`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--lines`, `-n` | int | `50` | Number of log lines to display |

**Exit Codes:** `0` (logs found), `1` (no logs)

**Examples:**
```bash
raven log              # Last 50 lines
raven log -n 200       # Last 200 lines
raven log --lines=100  # Last 100 lines
```

**Behavior:** Reads `~/.raven/raven.log`, prints last N lines between
horizontal dividers. Warns if log file does not exist.

### `raven doctor`

Run comprehensive system diagnostics.

**Syntax:** `raven doctor`

**Exit Codes:** `0` (all checks pass), `1` (warnings), `2` (critical issues)

**Examples:**
```bash
raven doctor
```

**Checks Performed (in order):**
1. **Python Environment** — Version check (3.12+ required), virtual env detection
2. **Core Dependencies** — Required (pyyaml, sentence-transformers, aiohttp, apscheduler) and optional packages verified
3. **API Keys** — Gemini (required), OpenAI, Anthropic, Groq, OpenRouter, xAI, VirusTotal, OpenWeatherMap, Wolfram Alpha
4. **Messaging Channels** — Telegram, Discord, Slack, WhatsApp (configured or not)
5. **Identity Files** — SOUL.md, MEMORY.md, AGENTS.md (required), Skills.md, Agent.md (optional)
6. **Skills System** — Bundled skills count, learned skills count
7. **System Tools** — git (required), docker, node, npm, tesseract, llama.cpp
8. **Integration API Keys** — Linear, Airtable
9. **Disk Space** — Free space check (warning <5GB, critical <1GB)
10. **Summary** — Issue/warning count with recommendations

### `raven cleanup`

Remove old checkpoints and prune stale sessions.

**Syntax:** `raven cleanup [--days N] [--dry-run]`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--days` | int | `14` | Remove items older than N days |
| `--dry-run` | flag | `false` | Show what would be removed without deleting |

**Exit Codes:** `0`

**Examples:**
```bash
raven cleanup                         # Clean items older than 14 days
raven cleanup --days 7                # Clean items older than 7 days
raven cleanup --dry-run               # Preview what would be removed
```

**Behavior:** Removes checkpoint directories under `workspace/checkpoints/`
older than cutoff. Removes session files older than cutoff. Prunes sessions
over 500KB to 100 messages. Cleans up `index.json` if empty after removal.

---

## AI & Chat Commands

### `raven chat`

Launch a terminal chat interface connected to the brain.

**Syntax:** `raven chat`

**Exit Codes:** `0`

**Examples:**
```bash
raven chat
```

**Behavior:** Creates a `BotSignal`, registers a console sender, creates a
`MessageOrchestrator`, and enters a read-eval loop. User input prefixed with
`█`. Exit with `quit`, `exit`, or `Ctrl+C`. Responses printed with timestamp
and bold `raven` prefix.

### `raven mode`

Inspect and override the operating mode.

**Syntax:** `raven mode <show|set|clear|history> [--state-file PATH]`

**Subcommands:**

| Subcommand | Description |
|------------|-------------|
| `show` | Show current effective mode, auto-detected mode, operator override |
| `set <mode>` | Force a mode override (`online`, `degraded`, `offline`) |
| `clear` | Clear any operator override |
| `history` | Show recent mode transitions |

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--state-file` | string | `workspace/mode_state.json` | Path to shared mode state file |
| `--ttl` | int (for `set`) | `300` | Override TTL in seconds |

**Examples:**
```bash
raven mode show                       # Display current mode
raven mode set offline --ttl 600      # Force offline for 10 minutes
raven mode set degraded               # Force degraded mode
raven mode clear                      # Resume auto-detection
raven mode history                    # View recent transitions
```

**Mode Detector states:** `online` (all systems nominal), `degraded` (some
down, fallback providers active), `offline` (no network, local-only inference).

### `raven providers`

Provider, model, and combo management.

**Syntax:** `raven providers <action> [args...]`

| Action | Description |
|--------|-------------|
| `list` | Show all providers with health, tier, group, latency |
| `select <id> [model]` | Activate a specific provider/model |
| `combo list` | Show all provider combos (ordered fallback chains) |
| `combo use <name>` | Activate a named combo |
| `combo create <name> <p1,p2,...>` | Create or update a combo |
| `combo delete <name>` | Delete a combo |
| `health` | Probe every provider, show status and latency |
| `stats` | Show per-model call statistics (calls, success rate, avg ms, tokens) |
| `probe <id>` | Probe a single provider |

**Examples:**
```bash
raven providers list                      # List all providers
raven providers select openai gpt-4o      # Use GPT-4o
raven providers combo list                # List combos
raven providers combo create production "openai,anthropic"
raven providers health                    # Check all provider health
raven providers stats                     # Call statistics
raven providers probe groq                # Test Groq connectivity
```

**Output format (list):**
```
=== Providers ===
ID             NAME                             TIER           GROUP        HEALTH     LATENCY
────────────────────────────────────────────────────────────────────────────────────────────────
anthropic      Anthropic (Claude)               subscription/  subscription healthy    342ms
openai         OpenAI                           subscription/  subscription healthy    285ms
```

### `raven modules`

List and manage A2A modules.

**Syntax:** `raven modules <action> [args...]`

| Action | Description |
|--------|-------------|
| `list` | List all registered A2A modules |
| `discover [tags...]` | Find modules matching skill tags |
| `call <module> <method> [json_params]` | Call a specific module method |

**Examples:**
```bash
raven modules list                      # List all modules
raven modules discover memory           # Find memory-related modules
raven modules call memory memory.recall '{"query": "hello"}'
```

---

## Knowledge Commands

### `raven memory`

Memory operations (remember, recall, stats, consolidate).

**Syntax:** `raven memory <action> [args...]`

| Action | Description |
|--------|-------------|
| `remember <text>` | Store a new memory (category: FACT) |
| `recall <query>` | Search episodic memory via FTS5 full-text search |
| `stats` | Show memory store statistics (total memories, tool guides) |
| `consolidate` | Run memory consolidation (summarize, deduplicate, prune) |

**Examples:**
```bash
raven memory remember "User prefers dark mode"   # Store a memory
raven memory recall "dark mode preferences"      # Search memories
raven memory stats                               # Show stats
raven memory consolidate                         # Consolidate
```

### `raven context`

Query user context (mood, location, activity, environment).

**Syntax:** `raven context [query]`

| Argument | Default | Description |
|----------|---------|-------------|
| `query` | `all` | Context to query: `mood`, `location`, `activity`, `environment`, `all` |

**Examples:**
```bash
raven context                          # All context dimensions
raven context mood                     # Just mood
raven context location                 # Just location
```

### `raven kg`

Knowledge graph operations.

**Syntax:** `raven kg <action> [query]`

| Action | Description |
|--------|-------------|
| `query <query>` | Query the knowledge graph |
| `stats` | Show knowledge graph statistics |
| `entities` | List knowledge graph entities |

**Examples:**
```bash
raven kg stats                         # KG statistics
raven kg entities                      # List entities
raven kg query "Python projects"       # Search knowledge graph
```

### `raven world-model`

Inspect macro understanding of people, projects, habits, events.

**Syntax:** `raven world-model <action> [args...]`

| Action | Description |
|--------|-------------|
| `people` | List known people with relationship types |
| `projects` | List known projects with status |
| `habits` | Show tracked habits with frequency |
| `events` | Show recent events |
| `context` | Build world context summary |

**Examples:**
```bash
raven world-model people               # Known people
raven world-model projects             # Current projects
raven world-model habits               # Tracked habits
raven world-model events               # Recent timeline
```

---

## Platform Commands

### `raven cowork`

Manage collaborative workspaces, propose plans, and approve/reject steps.

**Syntax:** `raven cowork <action> [args...] [--strategy STRATEGY] [--auto-approve]`

| Action | Description |
|--------|-------------|
| `list-ws` | Show all workspaces |
| `add-ws <name> <path> [ro\|rw]` | Add a workspace |
| `rm-ws <workspace_id>` | Remove a workspace |
| `list` | Show all cowork sessions |
| `active` | Show the in-flight session with plan steps |
| `start <ws_id> <goal>` | Start a new session |
| `pause <session_id>` | Pause a session |
| `resume <session_id>` | Resume a paused session |
| `stop <session_id>` | Stop a session |
| `approve-all <session_id>` | Bulk-approve all steps in plan |
| `approve <session_id> <step_id>` | Approve a specific step |
| `reject <session_id> <step_id>` | Reject a specific step |
| `events <session_id>` | Print session event log |

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--strategy` | `default\|llm\|rule` | `default` | Planner strategy |
| `--auto-approve` | flag | `false` | Auto-approve low-risk steps |

**Examples:**
```bash
raven cowork list-ws                                  # List workspaces
raven cowork add-ws myproject /path/to/project rw     # Add workspace
raven cowork start ws_abc "Refactor auth module" --auto-approve
raven cowork list                                     # Show sessions
raven cowork active                                   # Active session details
raven cowork approve ses_abc step_1                   # Approve step
```

### `raven approve`

Approve a pending Tier 3 tool execution task.

**Syntax:** `raven approve <task_id>`

**Examples:**
```bash
raven approve task_abc123
```

### `raven edge-node`

Bootstrap the current machine as a remote edge node.

**Syntax:** `raven edge-node --name NAME [--server URL] [--capabilities CAPS] [--location LOC] [--sensors SENSORS]`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--name` | string | required | Name of the edge node |
| `--server` | string | `http://localhost:8090` | URL of the Raven server |
| `--capabilities` | string | `bash,python` | Comma-separated capabilities |
| `--location` | string | `unknown` | Physical location of the node |
| `--sensors` | string | `""` | Comma-separated sensor list |

**Examples:**
```bash
raven edge-node --name living-room-pi \
  --server http://192.168.1.100:8090 \
  --capabilities bash,python,docker \
  --location "Living Room" \
  --sensors temperature,humidity,motion
```

**Behavior:** Registers with server via `POST /api/v1/edge/register`, then
enters polling loop (`GET /api/v1/edge/tasks/{name}`). Executes tasks via
`subprocess.run` with `shlex.split()` for safety. Reports completion via
`POST /api/v1/edge/tasks/{id}/complete`. Exponential backoff on connection
failure (2s → max 60s).

### `raven helix`

Manage the HelixDB sidecar (Docker-based knowledge graph database).

**Syntax:** `raven helix <action>`

| Action | Description |
|--------|-------------|
| `up` | Start HelixDB container |
| `down` | Stop HelixDB container |
| `status` | Check HelixDB status |
| `logs` | View HelixDB logs |

**Examples:**
```bash
raven helix up                         # Start HelixDB
raven helix status                     # Check status
raven helix logs                       # View logs
raven helix down                       # Stop HelixDB
```

**Behavior:** Runs `scripts/start_helix.sh <action>` with timeout of 120s
for `up`, 30s for others. Exit code from script is propagated.

---

## Setup & Development Commands

### `raven onboard`

First-time setup wizard for API keys, voice endpoints, and platform connections.

**Syntax:** `raven onboard`

**Exit Codes:** `0`

**Examples:**
```bash
raven onboard
```

**Wizard Steps:**
1. **LLM Providers** — Gemini (recommended), OpenAI, Anthropic, Groq, OpenRouter, xAI/Grok
2. **Messaging Channels** — Telegram, Discord, Slack (optional)
3. **Identity** — Default location for weather
4. **Voice Pipeline** — Enable/disable wake word + STT + TTS

Writes settings to `.env` file. Preserves existing keys.

### `raven daemon`

Start background loops and FastAPI web server (invoked internally by `raven run`).

**Syntax:** `raven daemon [--port PORT]`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port`, `-p` | int | `8090` | Dashboard/API server port |

**Examples:**
```bash
raven daemon                           # Start daemon
raven daemon --port 9090               # Start on custom port
```

**Behavior:** Imports `_main_async` from `main.py`, runs it in a daemon thread,
starts uvicorn on the FastAPI server (`app.api.server:app`).

### `raven mcp-serve`

Start Raven as an MCP (Model Context Protocol) tool server over stdio.

**Syntax:** `raven mcp-serve`

**Behavior:** Registers all runtime tools on an MCPServer instance, starts
stdio transport. External agents/IDEs can discover and invoke Raven's tools
via standard MCP JSON-RPC messages (initialize, tools/list, tools/call).

### `raven skills`

List, install, and manage skills.

**Syntax:** `raven skills <action> [args...]`

### `raven train-data`

Export conversation data as JSONL for model training.

**Syntax:** `raven train-data <action> [--session SID] [--output FILE]`

| Action | Description |
|--------|-------------|
| `export` | Export training data as JSONL |
| `stats` | Show session and training example counts |

| Flag | Type | Description |
|------|------|-------------|
| `--session`, `-s` | string | Session ID to export (all if omitted) |
| `--output`, `-o` | string | Output file path (auto-named by timestamp) |

**Examples:**
```bash
raven train-data stats                 # Count sessions and examples
raven train-data export -o data.jsonl  # Export all sessions
```

### `raven learning`

Learning system operations.

**Syntax:** `raven learning <action> [--type TYPE] [--limit N] [--min-confidence F] [--kind KIND] [--output FILE] [--input FILE]`

| Action | Description |
|--------|-------------|
| `stats` | Show learning store statistics |
| `search <query>` | Search learnings via FTS5 |
| `events` | Show recent learning events |
| `export` | Export all learnings as JSON |
| `import` | Import learnings from JSON |

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--type` | string | — | Filter by type (search/events) |
| `--limit` | int | `20` | Max results |
| `--min-confidence` | float | `0.0` | Minimum confidence threshold |
| `--kind` | string | — | Event kind filter |
| `--output`, `-o` | string | — | Output file path |
| `--input`, `-i` | string | — | Input file path |

**Examples:**
```bash
raven learning stats                   # Store statistics
raven learning search "python"         # Search learnings
raven learning events --kind learning  # Recent learning events
raven learning export -o learnings.json
raven learning import -i learnings.json
```

### `raven evolve`

Self-evolution system.

**Syntax:** `raven evolve <action>`

| Action | Description |
|--------|-------------|
| `goals` | Show active evolution goals with progress |
| `metrics` | Show tracked metrics (avg, latest, count) |
| `assess` | Generate improvement report |
| `report` | Same as assess (alias) |

**Examples:**
```bash
raven evolve goals                     # View goals
raven evolve metrics                   # Tracked metrics
raven evolve report                    # Full improvement report
```

### `raven companion`

Companion AI management (inter-agent delegation stats).

**Syntax:** `raven companion <action>`

| Action | Description |
|--------|-------------|
| `list` | List all companion AIs |
| `status` | Show collaboration summary |
| `summary` | JSON-formatted collaboration summary |

**Examples:**
```bash
raven companion list                   # List companions
raven companion status                 # Collaboration status
```

### `raven personality`

Adaptive personality inspection.

**Syntax:** `raven personality <action>`

| Action | Description |
|--------|-------------|
| `traits` | Show personality traits with bar visualization |
| `vocabulary` | Show top 20 most-used words |
| `styles` | Show response style counts |
| `prompt` | Show the personality system prompt |

**Examples:**
```bash
raven personality traits               # Trait visualization
raven personality vocabulary           # Word frequency
raven personality prompt               # System prompt
```

---

## Config File Search Paths

Raven searches for configuration in the following order:

1. `.env` file in the project root directory
2. Environment variables (override `.env`)
3. `app/settings/config.py` — `Config` class reads from `os.getenv()`
4. Default fallback values hardcoded in `Config` class

### Config Resolution

```python
# app/settings/config.py
load_dotenv()  # Reads .env from CWD

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    MEMORY_ROOT = os.getenv("MEMORY_ROOT", "workspace/memory")
    # ... all config attributes read via os.getenv with defaults
```

---

## Environment Variable Reference

### LLM Providers
| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Recommended | Google Gemini API key |
| `OPENAI_API_KEY` | Optional | OpenAI API key |
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key |
| `GROQ_API_KEY` | Optional | Groq API key |
| `OPENROUTER_API_KEY` | Optional | OpenRouter API key |
| `XAI_API_KEY` | Optional | xAI/Grok API key |
| `DEEPSEEK_API_KEY` | Optional | DeepSeek API key |
| `MISTRAL_API_KEY` | Optional | Mistral AI API key |
| `COHERE_API_KEY` | Optional | Cohere API key |
| `NVIDIA_NIM_API_KEY` | Optional | NVIDIA NIM API key |
| `HUGGINGFACE_API_KEY` | Optional | HuggingFace API key |
| `BYTEZ_API_KEY` | Optional | Bytez API key |
| `OPENCODE_ZEN_API_KEY` | Optional | OpenCode Zen key (free, no key needed) |

### Platform Tokens
| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token from BotFather |
| `DISCORD_BOT_TOKEN` | Optional | Discord bot token |
| `SLACK_BOT_TOKEN` | Optional | Slack bot token (xoxb-) |
| `SLACK_APP_TOKEN` | Optional | Slack app token (xapp-) |
| `WHATSAPP_BRIDGE_URL` | Optional | Baileys bridge URL |

### Voice Pipeline
| Variable | Required | Description |
|----------|----------|-------------|
| `ENABLE_LOCAL_VOICE` | Optional | Enable voice pipeline |
| `WHISPER_CPP_MODEL` | Optional | whisper.cpp model path |
| `PIPER_VOICE_MODEL` | Optional | Piper TTS model path |
| `PIPER_VOICE_CONFIG` | Optional | Piper TTS config path |

### Infrastructure
| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ROOT` | `workspace/memory` | Memory store directory |
| `LLM_PROVIDER` | `auto` | Default LLM provider |
| `LLM_MODEL` | `""` | Default LLM model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `MQTT_BROKER_URL` | `""` | MQTT broker URL |
| `HOME_ASSISTANT_URL` | `http://homeassistant.local:8123` | Home Assistant URL |
| `WEB_DASHBOARD_PORT` | `8090` | Web dashboard port |
| `MCP_SERVERS` | `[]` | JSON array of MCP server configs |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error / command failure |
| `2` | Parsing error (invalid args) |
| `>0` | Propagated from subprocess (helix, edge-node) |

---

## Alias Reference

| Alias | Maps to |
|-------|---------|
| `raven s` | `raven status` |
| `raven l` | `raven log` |
| `raven d` | `raven doctor` |
| `raven h` | `raven --help` |
| `raven v` | `raven --version` |
