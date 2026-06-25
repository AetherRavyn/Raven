# AetherRavyn: JARVIS-Class AI Agent — Master Execution Plan

> **Codename**: AetherRavyn (Ravyn)
> **Goal**: Surpass Hermes Agent & OpenClaw — the most complete self-evolving personal AI ever built.
> **Scope**: 6 phases, 24 weeks. Phases 1-2 are DONE. Phases 3-6 remain.

---

## Current Codebase Architecture

```
RAVEN/
├── main.py                          # Entry point — runs Telegram/Discord/Slack/WhatsApp + background loops
├── SOUL.md                          # ✅ Persona definition (YAML frontmatter)
├── MEMORY.md                        # ✅ Persistent user knowledge
├── AGENTS.md                        # ✅ Workspace instructions
├── Skills.md                        # ✅ Skills system documentation
├── Agent.md                         # ✅ Agent architecture documentation
├── app/
│   ├── core/
│   │   ├── orchestrator.py          # Central message processor (1151 lines)
│   │   ├── runtime.py               # AgentRuntime — tool registration + LLM calls (45k bytes)
│   │   ├── agency.py                # SwarmManager — multi-agent coordination
│   │   ├── bootstrapper.py          # System prompt builder (now uses SoulEngine)
│   │   ├── soul_engine.py           # ✅ SOUL.md/MEMORY.md/AGENTS.md parser
│   │   ├── skill_learner.py         # ✅ Auto-creates skills from experience
│   │   ├── skill_registry.py        # Skill discovery (module.yaml/SKILL.md)
│   │   ├── trajectory_compressor.py # ✅ Context window compression
│   │   ├── persona.py               # PersonaEngine — emotional states, tone
│   │   ├── security.py              # SecurityGuard — jailbreak detection, RBAC
│   │   ├── session.py               # SessionManager — JSONL-based history
│   │   ├── autonomy_engine.py       # State machine for autonomous execution
│   │   ├── ambient_loop.py          # Always-on background processing
│   │   ├── sentinel_bridge.py       # Sensor fusion (MQTT, Calendar, Health)
│   │   ├── self_improvement.py      # Feedback + model/tool stats
│   │   ├── model_router.py          # AutoModelRouter — provider selection
│   │   ├── memory.py                # ChromaDB vector store
│   │   ├── memory_manager.py        # High-level memory operations
│   │   └── ... (55 files total)
│   ├── agents/
│   │   ├── base.py                  # BaseAgent ABC (342 lines) — soul, personality, goals, heartbeat
│   │   ├── developer.py, researcher.py, security.py, sysadmin.py, finance.py
│   │   ├── productivity.py, news.py, assistant.py, reviewer.py, scientist.py
│   │   ├── communications.py, dataengineer.py, homeguardian.py, moral.py
│   │   └── (14 agents total)
│   ├── tools/
│   │   ├── base.py                  # BaseTool ABC — get_name(), get_schema(), execute()
│   │   └── (55+ tools: browser, mobile, desktop, git, docker, finance, network, etc.)
│   ├── mcp/
│   │   ├── server.py                # ✅ MCP server (tools/list, tools/call over stdio)
│   │   └── manager.py               # MCP client (connects to external MCP servers)
│   ├── cli/
│   │   ├── main.py                  # ✅ CLI: daemon, chat, status, onboard, doctor, skills, mcp-serve
│   │   ├── onboard.py               # ✅ Interactive setup wizard
│   │   ├── doctor.py                # ✅ System diagnostics
│   │   └── edge_node.py             # Edge device client
│   ├── telegram/, discord/, slack/, whatsapp/  # Channel integrations
│   ├── voice/                       # Wake word → STT → LLM → TTS pipeline
│   ├── api/                         # FastAPI web server
│   └── settings/config.py           # All env vars (173 lines)
├── skills/
│   ├── bundled/                     # ✅ 8 skills (code_reviewer, morning_briefing, etc.)
│   └── learned/                     # ✅ Auto-created by SkillLearner
└── tests/
    ├── test_soul_engine.py          # ✅ 24 tests
    ├── test_skill_learner.py        # ✅ 18 tests
    ├── test_trajectory_compressor.py # ✅ 13 tests
    └── test_mcp_server.py           # ✅ 12 tests
```

---

## Key Patterns & Conventions

### Code Style Rules
- **Python 3.12+**, type hints everywhere, `async/await` for all I/O
- **Formatter**: `ruff format` | **Linter**: `ruff check` | **Types**: `pyright`
- **Max line length**: 100 chars
- **Logging**: `logging.getLogger(__name__)`, never `print()`
- **Tests**: Every module needs `test_*.py`, run with `.venv/bin/python -m pytest`
- **Package manager**: `uv` with `.venv/`

### How to Create a New Tool
```python
# app/tools/my_tool.py
from app.tools.base import BaseTool, ToolParameter, ToolSchema, ToolCapability

class MyTool(BaseTool):
    group = "my_group"

    def get_name(self) -> str:
        return "my_tool"

    def get_description(self) -> str:
        return "What this tool does"

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name="my_tool",
            description="...",
            parameters=[
                ToolParameter(name="action", type="string", description="...", required=True),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(risk_level="medium", readonly=False)

    async def execute(self, **kwargs) -> dict:
        return {"success": True, "result": "..."}
```
Then register in `app/core/orchestrator.py` → `MessageOrchestrator.__init__()`.

### How to Create a New Agent
```python
# app/agents/my_agent.py
from app.agents.base import BaseAgent

class MyAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "MyAgent"

    @property
    def role_prompt(self) -> str:
        return "You are a specialist in..."

    @property
    def soul(self) -> str:
        return "Core purpose statement"

    @property
    def tools(self) -> list:
        return [SomeTool(), AnotherTool()]
```
Then register in `orchestrator.py` → `self._swarm.register_agent(MyAgent())`.

### How to Create a Bundled Skill
Each skill lives in `skills/bundled/<skill_name>/` with two files:
- `module.yaml` — Machine-readable manifest (schema_version, module_id, triggers, dependencies)
- `SKILL.md` — Human-readable procedure with YAML frontmatter

---

## ✅ COMPLETED — Phase 1: Foundation (Weeks 1-2)

| File | Status |
|------|--------|
| `SOUL.md`, `MEMORY.md`, `AGENTS.md`, `Skills.md`, `Agent.md` | ✅ Created |
| `app/core/soul_engine.py` | ✅ Loads SOUL/MEMORY/AGENTS, builds dynamic prompts |
| `app/core/skill_learner.py` | ✅ Auto-creates skills from successful interactions |
| `app/core/trajectory_compressor.py` | ✅ Context compression with fact extraction |
| `app/core/bootstrapper.py` | ✅ Integrated with SoulEngine |
| `app/core/skill_registry.py` | ✅ Added bundled/learned/workspace/community roots |
| `skills/bundled/` (8 skills) | ✅ code_reviewer, morning_briefing, security_audit, research_synthesis, deploy_pipeline, incident_response, meeting_prep, weekly_review |

## ✅ COMPLETED — Phase 2: MCP, CLI & Onboarding (Weeks 3-5)

| File | Status |
|------|--------|
| `app/mcp/server.py` | ✅ Full MCP server (initialize, tools/list, tools/call) |
| `app/cli/main.py` | ✅ 9 commands: daemon, chat, status, onboard, doctor, skills, mcp-serve, approve, edge-node |
| `app/cli/onboard.py` | ✅ Interactive setup wizard |
| `app/cli/doctor.py` | ✅ Full diagnostics |

---

## 🔧 TODO — Phase 3: Security, Sandboxing & Access Control (Weeks 6-8)

### 3.1 — [NEW] `app/core/sandbox_manager.py`

**Purpose**: Execute untrusted code/commands in isolated Docker containers or subprocess sandboxes.

**What to build**:
```python
class SandboxManager:
    """Manages isolated execution environments."""

    async def execute_sandboxed(self, command: str, timeout: int = 30,
                                 image: str = "python:3.12-slim") -> SandboxResult:
        """Run a command inside a Docker container with resource limits."""
        # 1. Create temp container with --network=none, --memory=512m, --cpus=1
        # 2. Copy any input files into container
        # 3. Execute command with timeout
        # 4. Capture stdout/stderr
        # 5. Clean up container
        # 6. Return SandboxResult(stdout, stderr, exit_code, timed_out)

    async def execute_subprocess(self, command: str, timeout: int = 30) -> SandboxResult:
        """Fallback: subprocess with resource limits (no Docker)."""
        # Use asyncio.create_subprocess_exec with timeout
        # Set ulimits if on Linux
```

**Integration point**: Modify `app/tools/exectool.py` and `app/tools/docker_exec_tool.py` to route through SandboxManager when `Config.ALLOW_HOST_SHELL_EXECUTION` is False.

**Existing code to study**: `app/tools/sandbox.py` (6237 bytes) already has some sandbox logic — extend it, don't replace.

**Test file**: `tests/test_sandbox_manager.py` — test container creation, timeout handling, cleanup, fallback to subprocess.

---

### 3.2 — [NEW] `app/core/dm_pairing.py`

**Purpose**: When an unknown user DMs the bot, require a pairing code approved by the admin before allowing interaction.

**What to build**:
```python
@dataclass
class PairingRequest:
    user_id: str
    platform: str
    code: str           # 6-digit alphanumeric
    created_at: datetime
    approved: bool = False
    expires_at: datetime  # 10 minutes

class DMPairingManager:
    """Manages DM pairing codes for unknown senders."""

    def __init__(self, store_path: Path):
        # JSONL-backed store at workspace/memory/pairing/

    def generate_pairing_code(self, user_id: str, platform: str) -> str:
        """Generate a 6-char code, store it, return to user."""

    def approve_code(self, code: str) -> bool:
        """Admin approves a pairing code via CLI or chat."""

    def is_paired(self, user_id: str, platform: str) -> bool:
        """Check if user has been paired."""

    def cleanup_expired(self) -> int:
        """Remove expired pairing requests."""
```

**Integration point**: In `app/core/orchestrator.py` → `handle()` method, check `is_paired()` before processing. If not paired and not admin, send pairing code and return early.

**Config addition** in `app/settings/config.py`:
```python
DM_PAIRING_ENABLED: bool = os.getenv("DM_PAIRING_ENABLED", "true").lower() in {"1", "true", "yes"}
```

**Test file**: `tests/test_dm_pairing.py` — test code generation, approval, expiry, paired check.

---

### 3.3 — [MODIFY] `app/core/security.py`

**Purpose**: Add per-session tool allowlists and per-channel permission scoping.

**What to add to existing `SecurityGuard` class**:
```python
# Add these methods to the existing SecurityGuard class:

def get_channel_permissions(self, platform: str, channel_id: str) -> set[str]:
    """Return allowed tool names for a specific channel."""
    # Load from workspace/config/channel_permissions.json
    # Default: all tools allowed for admin channels

def set_channel_permissions(self, platform: str, channel_id: str,
                             allowed_tools: list[str]) -> None:
    """Set tool allowlist for a channel."""

def is_tool_allowed(self, tool_name: str, platform: str,
                     channel_id: str, user_id: str) -> tuple[bool, str]:
    """Check if a tool is allowed in this context."""
    # 1. Check if user is admin → always allowed
    # 2. Check channel permissions
    # 3. Check tool risk level
    # 4. Return (allowed, reason)
```

**Integration point**: In `app/core/runtime.py` → before tool execution, call `is_tool_allowed()`.

**Test file**: Add tests to existing test files or create `tests/test_security_enhanced.py`.

---

### 3.4 — [NEW] `app/core/secret_vault.py`

**Purpose**: Encrypted storage for API keys instead of plaintext `.env`.

**What to build**:
```python
class SecretVault:
    """Encrypted secrets management using Fernet symmetric encryption."""

    def __init__(self, vault_path: Path, master_key: str | None = None):
        # vault_path: workspace/secrets/vault.enc
        # master_key: from RAVYN_MASTER_KEY env var or keyring

    def store(self, key: str, value: str) -> None:
        """Encrypt and store a secret."""

    def retrieve(self, key: str) -> str | None:
        """Decrypt and return a secret."""

    def list_keys(self) -> list[str]:
        """List all stored key names (not values)."""

    def delete(self, key: str) -> bool:
        """Remove a secret."""

    def export_to_env(self) -> dict[str, str]:
        """Decrypt all secrets for runtime use."""
```

**Dependencies**: `cryptography` package (Fernet).

**Integration point**: Optional — `Config` class can try vault first, fall back to env vars.

**Test file**: `tests/test_secret_vault.py` — test encrypt/decrypt, key listing, deletion.

---

## 🔧 TODO — Phase 4: Multi-Channel Gateway (Weeks 9-12)

### 4.1 — [NEW] `app/gateway/daemon.py`

**Purpose**: Persistent gateway daemon that manages all channel connections, replaces `main.py`'s monolithic startup.

**What to build**:
```python
class GatewayDaemon:
    """Persistent daemon that manages channel lifecycle."""

    def __init__(self):
        self._channels: dict[str, ChannelAdapter] = {}
        self._orchestrator: MessageOrchestrator
        self._session_router: SessionRouter

    async def start(self) -> None:
        """Start all configured channels + background loops."""
        # 1. Initialize orchestrator
        # 2. Start configured channels (Telegram, Discord, etc.)
        # 3. Start background loops (ambient, scheduler, heartbeat)
        # 4. Write PID file for systemd/launchd

    async def stop(self) -> None:
        """Graceful shutdown with timeout."""

    async def restart_channel(self, name: str) -> None:
        """Hot-restart a single channel without stopping others."""

    def get_status(self) -> dict:
        """Return status of all channels and services."""
```

**Existing code to study**: `main.py` lines 1-473 — this is the current monolithic startup. The daemon should replicate its functionality but modularly.

**systemd unit file** — create `deploy/aetherravyn.service`:
```ini
[Unit]
Description=AetherRavyn Gateway Daemon
After=network.target

[Service]
Type=simple
ExecStart=/path/to/.venv/bin/python -m app.cli.main daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

### 4.2 — [NEW] `app/gateway/protocol.py`

**Purpose**: Documented RPC protocol for gateway ↔ agent communication.

**What to build**:
```python
@dataclass
class GatewayMessage:
    """Standardized message format for all channels."""
    id: str
    platform: str
    channel_id: str
    user_id: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class GatewayProtocol:
    """Handles message routing between channels and orchestrator."""

    async def route_inbound(self, msg: GatewayMessage) -> None:
        """Route incoming message to appropriate agent session."""

    async def route_outbound(self, msg: GatewayMessage) -> None:
        """Route response back to originating channel."""
```

---

### 4.3 — [NEW] `app/gateway/session_router.py`

**Purpose**: Route channels/accounts to isolated agent sessions. Different Telegram groups can talk to different agent personas.

**What to build**:
```python
class SessionRouter:
    """Routes channels to isolated agent sessions."""

    def __init__(self, config_path: Path):
        # Load routing config: channel_id → agent_name mapping

    def get_session(self, platform: str, channel_id: str, user_id: str) -> str:
        """Return session_id for this context."""

    def get_agent(self, platform: str, channel_id: str) -> str:
        """Return which agent handles this channel."""

    def set_routing(self, platform: str, channel_id: str, agent_name: str) -> None:
        """Configure routing for a channel."""
```

**Integration point**: `app/core/orchestrator.py` → use SessionRouter to determine which agent and session to use.

---

### 4.4 — [NEW] Channel Integrations

Create new channel bots following the existing patterns in `app/telegram/`, `app/discord/`, `app/slack/`:

| File | Channel | Priority |
|------|---------|----------|
| `app/channels/signal_bot.py` | Signal (via signal-cli-rest-api) | P1 |
| `app/channels/matrix_bot.py` | Matrix/Element (via matrix-nio) | P1 |
| `app/channels/irc_bot.py` | IRC (via irc3 or pydle) | P2 |
| `app/channels/teams_bot.py` | Microsoft Teams (via botframework) | P2 |

Each channel adapter must:
1. Implement `async def start(stop_event: asyncio.Event)` 
2. Convert platform messages to `IncomingRequest` (from `app/core/models.py`)
3. Register a sender callback with `BotSignal`
4. Handle graceful shutdown

---

## 🔧 TODO — Phase 5: Cognitive Architecture Upgrades (Weeks 13-18)

These features make AetherRavyn categorically superior to both Hermes and OpenClaw.

### 5.1 — [NEW] `app/core/goal_manager.py`

**Purpose**: Autonomous multi-day goal pursuit with task decomposition.

```python
@dataclass
class Goal:
    id: str
    title: str
    description: str
    priority: int        # 1 (highest) to 5
    status: str          # active, paused, completed, failed
    subtasks: list[SubTask]
    deadline: datetime | None
    progress: float      # 0.0 to 1.0
    created_at: datetime

class GoalManager:
    """Manages autonomous goal pursuit."""

    async def create_goal(self, title: str, description: str) -> Goal:
        """Decompose a goal into subtasks using LLM."""

    async def advance_goals(self) -> list[str]:
        """Called by ambient_loop — pick next subtask and execute."""
        # 1. Find highest-priority active goal
        # 2. Find next incomplete subtask
        # 3. Execute via orchestrator
        # 4. Update progress

    async def report_progress(self) -> str:
        """Generate a progress report for all goals."""
```

**Integration point**: Hook into `app/core/ambient_loop.py` to call `advance_goals()` periodically.

**Test file**: `tests/test_goal_manager.py`

---

### 5.2 — [NEW] `app/core/metacognition.py`

**Purpose**: Monitor reasoning quality and adapt strategy.

```python
class MetaCognitiveMonitor:
    """Tracks reasoning performance and adapts strategies."""

    def evaluate_response(self, query: str, response: str,
                           tools_used: list[str], success: bool) -> float:
        """Score reasoning quality (0.0 to 1.0)."""

    def select_strategy(self, query: str) -> str:
        """Choose reasoning strategy: 'analytical', 'creative', 'systematic', 'rapid'."""
        # Based on past performance on similar queries

    def get_confidence(self) -> float:
        """Current confidence level based on recent performance."""
```

---

### 5.3 — [NEW] `app/core/attention.py`

**Purpose**: Working memory with human-like 7±2 item attention buffer.

```python
class WorkingMemory:
    """7±2 item attention buffer for focused reasoning."""

    def __init__(self, capacity: int = 7):
        self._items: list[MemoryItem] = []
        self._capacity = capacity

    def focus(self, item: MemoryItem) -> None:
        """Add item to working memory, evicting least relevant if full."""

    def get_context(self) -> list[MemoryItem]:
        """Return current focus items for prompt injection."""

    def relevance_decay(self) -> None:
        """Reduce relevance scores over time."""
```

---

### 5.4 — [NEW] `app/core/analogy.py`

**Purpose**: Case-based reasoning — find past solutions to similar problems.

```python
class AnalogyEngine:
    """Finds analogous past solutions for current problems."""

    async def find_analogies(self, problem: str, top_k: int = 3) -> list[Analogy]:
        """Search memory for similar past problems and their solutions."""
        # Use vector similarity on past interaction embeddings

    async def transfer_solution(self, analogy: Analogy, current_problem: str) -> str:
        """Adapt a past solution to the current problem."""
```

**Integration point**: Called by `app/core/runtime.py` before tool selection to check if a similar problem was solved before.

---

### 5.5 — [NEW] `app/core/counterfactual.py`

**Purpose**: Simulate "what if" scenarios before high-risk actions.

```python
class CounterfactualEngine:
    """Simulates outcomes before committing to high-risk actions."""

    async def simulate(self, action: str, context: dict) -> SimulationResult:
        """Run a mental simulation of the action's consequences."""
        # 1. Identify risks
        # 2. Generate possible outcomes (best/worst/likely)
        # 3. Score confidence
        # 4. Return recommendation (proceed/abort/modify)
```

**Integration point**: Called by `SecurityGuard.requires_approval()` for high-risk tools.

---

### 5.6 — [NEW] `app/agents/negotiation.py`

**Purpose**: Structured debate protocol when agents disagree.

```python
class NegotiationProtocol:
    """Manages structured agent debates."""

    async def debate(self, topic: str, agents: list[BaseAgent],
                      rounds: int = 3) -> DebateResult:
        """Run a structured debate between agents."""
        # Round 1: Each agent presents position
        # Round 2: Agents critique each other
        # Round 3: Consensus or escalation to operator
```

**Integration point**: Called by `SwarmManager` in `app/core/agency.py` when multiple agents are candidates for a task.

---

## 🔧 TODO — Phase 6: Visual Workspace & Companion Apps (Weeks 19-24)

### 6.1 — [NEW] `app/canvas/live_canvas.py`

**Purpose**: Agent-driven visual workspace (A2UI-inspired). The agent generates and controls UI components in real-time.

```python
class LiveCanvas:
    """Agent-driven visual workspace."""

    def __init__(self):
        self._components: list[CanvasComponent] = []

    def add_component(self, component: CanvasComponent) -> str:
        """Add a UI component (chart, table, form, etc.)."""

    def update_component(self, component_id: str, data: Any) -> None:
        """Update a component's data in real-time."""

    def render_html(self) -> str:
        """Render the canvas as HTML for web dashboard."""

    async def handle_interaction(self, component_id: str, event: dict) -> None:
        """Handle user interaction with a canvas component."""
```

**Integration point**: Exposed via `app/api/server.py` WebSocket endpoint.

---

### 6.2 — [NEW] `app/canvas/renderer.py`

**Purpose**: HTML/JS renderer for canvas components.

**Components to support**: charts (Chart.js), tables, forms, markdown, code editors, image viewers, terminal output.

---

### 6.3 — Companion Apps (Can be deferred)

| App | Tech | Description |
|-----|------|-------------|
| `mobile/android/` | Kotlin | WebSocket node, voice, camera, screen capture |
| `desktop/macos/` | Swift | Menu bar app, voice wake, push-to-talk |

These connect to the gateway daemon via WebSocket and act as edge nodes.

---

## Testing Requirements

Every new module MUST have a corresponding test file:

| Phase | Test File | What to Test |
|-------|-----------|-------------|
| 3 | `tests/test_sandbox_manager.py` | Container creation, timeout, cleanup, subprocess fallback |
| 3 | `tests/test_dm_pairing.py` | Code generation, approval, expiry, paired check |
| 3 | `tests/test_security_enhanced.py` | Channel permissions, tool allowlists |
| 3 | `tests/test_secret_vault.py` | Encrypt/decrypt, key listing, deletion |
| 4 | `tests/test_gateway_daemon.py` | Daemon lifecycle, channel management, status |
| 4 | `tests/test_session_router.py` | Routing rules, session isolation |
| 5 | `tests/test_goal_manager.py` | Goal decomposition, progress tracking, advancement |
| 5 | `tests/test_metacognition.py` | Strategy selection, confidence scoring |
| 5 | `tests/test_attention.py` | Working memory capacity, eviction, decay |
| 5 | `tests/test_analogy.py` | Similarity search, solution transfer |
| 5 | `tests/test_counterfactual.py` | Risk simulation, outcome scoring |
| 6 | `tests/test_live_canvas.py` | Component CRUD, rendering, interactions |

**Run all tests**: `.venv/bin/python -m pytest tests/ -v --tb=short`

---

## Execution Order (for any AI agent)

```
Phase 3 (do in this order):
  1. sandbox_manager.py + test
  2. dm_pairing.py + test
  3. security.py modifications + test
  4. secret_vault.py + test

Phase 4 (do in this order):
  1. gateway/protocol.py
  2. gateway/session_router.py + test
  3. gateway/daemon.py + test + systemd unit
  4. Channel adapters (signal, matrix, irc, teams)

Phase 5 (can be parallelized):
  1. goal_manager.py + test
  2. metacognition.py + test
  3. attention.py + test
  4. analogy.py + test
  5. counterfactual.py + test
  6. negotiation.py

Phase 6:
  1. canvas/live_canvas.py + test
  2. canvas/renderer.py
  3. Companion apps (defer if needed)
```

---

## Config Keys to Add (in `app/settings/config.py`)

```python
# Phase 3
DM_PAIRING_ENABLED: bool          # Enable DM pairing security
SANDBOX_BACKEND: str              # "docker" | "subprocess" | "none"
SANDBOX_TIMEOUT: int              # Default sandbox timeout seconds
RAVYN_MASTER_KEY: str             # Master key for secret vault

# Phase 4
GATEWAY_PID_FILE: str             # PID file path for daemon
SIGNAL_CLI_URL: str               # signal-cli-rest-api URL
MATRIX_HOMESERVER: str            # Matrix homeserver URL
MATRIX_ACCESS_TOKEN: str          # Matrix bot token

# Phase 5
GOAL_MANAGER_ENABLED: bool        # Enable autonomous goal pursuit
METACOGNITION_ENABLED: bool       # Enable meta-cognitive monitoring
WORKING_MEMORY_CAPACITY: int      # Attention buffer size (default 7)
```

---

## Verification Checklist

After each phase, verify:
- [ ] All new tests pass: `.venv/bin/python -m pytest tests/ -v`
- [ ] `ruff check app/` passes with no errors
- [ ] `ravyn doctor` shows no new issues
- [ ] Existing functionality (Telegram, Discord, CLI chat) still works
- [ ] New modules follow the patterns above (async, logging, type hints, dataclasses)
