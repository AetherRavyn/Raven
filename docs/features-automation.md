# Automation, Agents & Orchestration

> **Document level**: Hermes
> **Last updated**: 2026-06-30
> **Codebase**: `/home/swadhin/SARAS`
> **Python**: 3.12+ — async-first, type-hinted throughout

--

## Table of Contents

1. [Automation Overview — How Everything Connects](#1-automation-overview-how-everything-connects)
2. [Kanban Multi-Agent Board](#2-kanban-multi-agent-board)
3. [Automation Blueprints Catalog](#3-automation-blueprints-catalog)
4. [Subagent Delegation System](#4-subagent-delegation-system)
5. [Codex App-Server Runtime](#5-codex-app-server-runtime)
6. [Lean Persistent Goals](#6-lean-persistent-goals)
7. [Code Execution & Sandbox](#7-code-execution-sandbox)
8. [Event Hooks (Outbound Webhooks)](#8-event-hooks-outbound-webhooks)
9. [Rate-Limit Middleware](#9-rate-limit-middleware)
10. [Batch Processing](#10-batch-processing)
11. [Cross-System Integration Matrix](#11-cross-system-integration-matrix)
12. [Tutorial — Multi-Step Automation End-to-End](#12-tutorial-multi-step-automation-end-to-end)

--

## 1. Automation Overview — How Everything Connects

Raven's automation stack forms a layered, interconnected system:

```
                        ┌──────────────────────────────────────┐
                        │         User / Platform Layer         │
                        │  CLI, Telegram, Discord, Voice, Web  │
                        └──────────────┬───────────────────────┘
                                       │
                        ┌──────────────┴───────────────────────┐
                        │        Supervisor (Routing)           │
                        │  14 agents — keyword-matched dispatch │
                        └──────────────┬───────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
   ┌──────────┴──────────┐  ┌─────────┴─────────┐  ┌──────────┴──────────┐
   │   Orchestrator       │  │  TaskScheduler    │  │   Ambient Loop      │
   │  Tool registry       │  │  Turn-based jobs  │  │  60s tick, 27 subs  │
   │  Slash commands      │  │  curator, petdex  │  │  goals, routines    │
   │  Hook integration    │  │  memory_sync      │  │  health, sensors    │
   └──────────┬──────────┘  └─────────┬─────────┘  └──────────┬──────────┘
              │                      │                        │
   ┌──────────┴──────────────────────┴────────────────────────┴──────────┐
   │                    Core Automation Services                          │
   │                                                                      │
   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────┐  │
   │  │  Kanban    │  │ Blueprints │  │   Goals    │  │  Delegation  │  │
   │  │  Board     │  │  Catalog   │  │  Manager   │  │  Manager     │  │
   │  │  (P0)      │  │  (P0)      │  │  (existing)│  │  (existing)  │  │
   │  └─────┬──────┘  └─────┬──────┘  └──────┬─────┘  └──────┬───────┘  │
   │        │               │                │               │          │
   │  ┌─────┴──────┐  ┌─────┴──────┐  ┌──────┴─────┐  ┌──────┴───────┐  │
   │  │  Kanban    │  │ Blueprint │  │  Codex     │  │  Batch       │  │
   │  │  Tool      │  │  Tool     │  │  AppServer │  │  Processor   │  │
   │  │  /kanban   │  │  /blueprint│  │  (P2)      │  │  (existing)  │  │
   │  └────────────┘  └───────────┘  └────────────┘  └──────────────┘  │
   │                                                                      │
   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────┐  │
   │  │  Hooks     │  │  Curator   │  │  Sandbox   │  │  Deliverable │  │
   │  │  (P1)      │  │  (P1)      │  │  (existing)│  │  (P3)        │  │
   │  └────────────┘  └────────────┘  └────────────┘  └──────────────┘  │
   └─────────────────────────────────────────────────────────────────────┘
                                       │
                        ┌──────────────┴───────────────────────┐
                        │         Persistence Layer             │
                        │  SQLite (per-service DBs)            │
                        │  HelixDB | ChromaDB | LearningDB    │
                        │  workspace/memory/*.db               │
                        └──────────────────────────────────────┘
```

### Key Integration Points

| Connection | Mechanism | Location |
|--|--|--|
| Supervisor -> Agents | Keyword routing + delegate() | `app/core/supervisor.py:241` |
| Orchestrator -> Tools | Tool registry (98 tools) | `app/core/orchestrator.py:300-330` |
| Orchestrator -> Scheduler | _init_scheduler() registers 6+ tasks | `app/core/orchestrator.py:730-775` |
| Orchestrator -> Kanban | KanbanTool + /kanban slash command | `app/tools/kanbantool.py`, `orchestrator.py:1751` |
| Orchestrator -> Blueprints | BlueprintTool + /blueprint slash command | `app/tools/blueprinttool.py`, `orchestrator.py:1814` |
| Orchestrator -> LSP | LSPTool registered in runtime | `app/tools/lsp_tool.py` |
| HookEmitter -> Hooks | Mixin for any core module | `app/core/hook_emitter.py` |
| Scheduler -> Curator | curator_pipeline every 100 turns | `orchestrator.py:747` |
| Scheduler -> Petdex | petdex_tick every 10 turns | `orchestrator.py:758` |
| Scheduler -> MemorySync | memory_sync every 200 turns | `orchestrator.py:770` |
| Goals -> Kanban | Goals can create/list kanban cards | Via Orchestrator |
| Blueprints -> Tools | BlueprintRunner._execute_step() calls orchestrator tools | `app/core/blueprint_runner.py:205` |

--

## 2. Kanban Multi-Agent Board

**Files**: `app/core/kanban.py` (363 lines), `app/tools/kanbantool.py` (223 lines)
**Priority**: P0
**Database**: `workspace/memory/kanban.db`

The Kanban system provides a multi-agent task board with full CRUD, status tracking, per-agent queues, and board analytics. It is accessible both programmatically (KanbanBoard API) and via the agent tool interface (KanbanTool).

### Data Model

```
TaskStatus (Enum):
  BACKLOG → READY → IN_PROGRESS → REVIEW → DONE
                      ↓
                   BLOCKED

KanbanCard:
  id, title, description, agent_id, status,
  priority (0-5), tags[], blocked_reason,
  created_at, updated_at
```

### SQLite Schema

```sql
CREATE TABLE kanban_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'backlog',
    priority INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    blocked_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_kanban_status ON kanban_cards(status);
CREATE INDEX idx_kanban_agent ON kanban_cards(agent_id);
```

### API — KanbanBoard

| Method | Signature | Description |
|--|--|--|
| `create_card` | `(title, description, agent_id, priority, tags) -> KanbanCard` | Create a new card in BACKLOG |
| `get_card` | `(card_id) -> KanbanCard | None` | Retrieve card by ID |
| `update_card` | `(card_id, **fields) -> bool` | Update arbitrary fields |
| `move_card` | `(card_id, new_status) -> bool` | Transition card status |
| `block_card` | `(card_id, reason) -> bool` | Block with reason |
| `unblock_card` | `(card_id) -> bool` | Unblock -> IN_PROGRESS |
| `delete_card` | `(card_id) -> bool` | Remove card from board |
| `list_cards` | `(status, agent_id) -> list[KanbanCard]` | List with optional filters |
| `get_board_summary` | `() -> dict` | Stats: total, by_status, agents, blocked_count, avg_age |
| `get_agent_queue` | `(agent_id) -> list[KanbanCard]` | Non-terminal cards for agent, sorted by priority |

### Tool Interface — KanbanTool

Registered as `kanban` in the orchestrator's tool registry. Actions:

| Action | Parameters | Description |
|--|--|--|
| `add_card` | `title`, `description`, `agent_id`, `priority`, `tags` | Create a card |
| `move_card` | `card_id`, `status` | Move card to new status |
| `list_cards` | `status`, `agent_id` | List cards with filters |
| `get_card` | `card_id` | Get card details |
| `delete_card` | `card_id` | Delete card |
| `agent_queue` | `agent_id` | Get agent's pending queue |
| `summary` | (none) | Board statistics |

### Slash Command — `/kanban`

Available via any chat platform (Telegram, Discord, CLI):

```
/kanban list                    — all cards
/kanban list in_progress        — filter by status
/kanban add "Fix auth bug"      — create card
/kanban move 42 done            — move card to done
/kanban delete 42               — delete card
```

### Kanban Worker Pattern

The Kanban system supports a **worker pattern** where agents pull from the board. The typical flow:

1. Orchestrator or user creates a card with `agent_id` assigned
2. The assigned agent's next tick checks `get_agent_queue(agent_id)`
3. Agent picks highest-priority card, moves it to `IN_PROGRESS`
4. On completion, moves to `DONE` or `REVIEW`
5. On failure, moves to `BLOCKED` with reason

--

## 3. Automation Blueprints Catalog

**Files**: `app/core/blueprint_models.py` (161 lines), `app/core/blueprint_manager.py` (215 lines), `app/core/blueprint_runner.py` (258 lines), `app/tools/blueprinttool.py` (215 lines)
**Priority**: P0
**Database**: `workspace/memory/blueprints.db`

Blueprints provide a reusable, YAML-defined automation catalog. Each blueprint declares triggers, steps (with DAG dependencies), conditions, and requirements.

### Data Model

```
Blueprint:
  name, version, description, author, tags[]
  triggers[]:  {type: "cron"|"interval"|"event", expression, description}
  steps[]:     {id, tool, params{}, output, depends_on[], condition}
  conditions[]:{if_expr, then_action, else_action}
  requirements:{env_vars[], tools[]}

BlueprintMetadata (stored in DB):
  name, version, description, author, tags[], enabled,
  installed_at, last_run_at, run_count, last_status

BlueprintRun (execution history):
  id, blueprint_name, started_at, finished_at,
  status, steps_total, steps_completed, error
```

### YAML Blueprint Format

```yaml
name: "daily-server-health"
version: "1.0.0"
description: "Check server health every morning"
author: "sysadmin"
tags: ["monitoring", "health"]
triggers:
  - type: cron
    expression: "0 9 * * *"
    description: "Every morning at 9 AM"
steps:
  - id: check_cpu
    tool: system_stats
    params:
      type: cpu
  - id: check_memory
    tool: system_stats
    params:
      type: memory
  - id: report
    tool: send_message
    params:
      message: "{{check_cpu}} / {{check_memory}}"
    depends_on:
      - check_cpu
      - check_memory
```

### DAG Execution

The `BlueprintRunner` builds a Directed Acyclic Graph from step dependencies and executes in topological order:

1. `_build_dag(steps)` — maps each step to its dependencies
2. `_topological_sort(dag)` — Kahn's algorithm for execution order
3. Step-by-step execution with condition checks
4. Template resolution: `{{ step_id }}` and `$ENV_VAR` substitution
5. Post-step condition evaluation (if/then/else)

### Tool Interface — BlueprintTool

| Action | Parameters | Description |
|--|--|--|
| `list` | (none) | List installed blueprints |
| `install` | `name`, `content` (YAML) | Install new blueprint |
| `uninstall` | `blueprint_id` | Remove blueprint |
| `enable` | `blueprint_id` | Enable a blueprint |
| `disable` | `blueprint_id` | Disable a blueprint |
| `get` | `blueprint_id` | Get blueprint details |
| `run` | `blueprint_id` | Execute blueprint now |
| `history` | `blueprint_id` | View run history |

### Slash Command — `/blueprint`

```
/blueprint list                   — list all blueprints
/blueprint run daily-server-health — execute a blueprint
/blueprint enable my-blueprint    — enable
/blueprint disable my-blueprint   — disable
/blueprint history my-blueprint   — view run history
```

--

## 4. Subagent Delegation System

**Files**: `app/core/delegation_manager.py` (181 lines), `app/core/supervisor.py` (291 lines), `app/core/agency.py`
**Priority**: Core (pre-existing)

The delegation system enables agents to recursively delegate subtasks to other agents, creating a hierarchy of collaboration.

### Architecture

```
Agent A (Manager)
  ├── creates TaskDelegation
  ├── DelegationManager.create_delegation()
  │     delegation: from_agent="A", to_agent="B",
  │                  task_description="...", context={...}
  ├── Agent B receives delegation
  ├── Agent B may delegate further to Agent C
  └── Results flow back up
      DelegationManager tracks the full chain
```

### Data Model

```python
@dataclass(slots=True)
class TaskDelegation:
    delegation_id: str       # "del_1", "del_2", ...
    from_agent: str          # "developer"
    to_agent: str            # "researcher"
    task_description: str    # "Find API docs"
    context: dict            # Shared working memory
    status: str              # pending|running|completed|failed
    result: str              # Output from the agent
    created_at: str
    completed_at: str | None

@dataclass(slots=True)
class SharedWorkingMemory:
    session_id: str
    entries: dict            # Shared state between agents
    participants: list[str]  # All agents in this collaboration
```

### DelegationManager API

| Method | Description |
|--|--|
| `create_delegation(from_agent, to_agent, task, context)` | Create a new delegation |
| `execute_delegation(delegation_id)` | Mark as running |
| `complete_delegation(delegation_id, result)` | Mark as completed |
| `fail_delegation(delegation_id, error)` | Mark as failed |
| `get_pending_for_agent(agent_name)` | Get pending delegations |
| `get_delegation_chain(delegation_id)` | Full chain of delegations |

### Integration with Supervisor

The `Supervisor` (`app/core/supervisor.py`) routes incoming requests to the best-fit agent using keyword matching:

```python
registry = AgentRegistry()
registry.register_all()  # 14 agents with specialties

# The Supervisor.delegate() method:
async def delegate(self, request) -> Response:
    best_agent = self._select_agent(request.text)
    if best_agent:
        delegation = delegation_manager.create_delegation(
            from_agent="supervisor",
            to_agent=best_agent.agent_id,
            task_description=request.text,
        )
        # ... execute and return result
```

### Recursive Delegation Flow

1. User asks "Research quantum computing and write a summary"
2. Supervisor delegates to `developer`
3. `developer` decomposes the task:
   - Sub-task 1: Research (delegates to `researcher`)
   - Sub-task 2: Write summary (self-executes)
4. `researcher` may delegate to `archivist` for data lookup
5. Results bubble up: archivist -> researcher -> developer -> user

--

## 5. Codex App-Server Runtime

**File**: `app/core/app_server.py` (533 lines)
**Priority**: P2
**Database**: `workspace/memory/app_server.db`
**Port Range**: 9000-9999

The Codex App-Server Runtime manages isolated code execution as long-running web services. Each app runs as an asyncio subprocess with its own port, log ring buffer, health checks, and auto-restart.

### Data Model

```python
@dataclass(slots=True)
class AppSpec:
    name: str
    code: str
    requirements: list[str]    # pip packages
    port_request: int | None   # None = auto-assign
    env_vars: dict[str, str]
    network_access: bool
    auto_restart: bool

@dataclass(slots=True)
class AppInstance:
    id, name, status, port, pid, created_at,
    started_at, last_health_at, restart_count,
    health_status, code, requirements[],
    env_vars{}, network_access, auto_restart

@dataclass(slots=True)
class AppLog:
    line: str
    timestamp: str
    stream: str          # "stdout" | "stderr"
```

### AppServerManager API

| Method | Description |
|--|--|
| `create_app(spec)` | Create app, install deps, start process |
| `start_app(app_id)` | Start a stopped app |
| `stop_app(app_id)` | Stop app with SIGTERM, then SIGKILL after 5s |
| `restart_app(app_id)` | Stop + start |
| `delete_app(app_id)` | Stop, remove from DB and port pool |
| `get_app(app_id)` | Get AppInstance by ID |
| `list_apps(status)` | List all apps, optionally filtered by status |
| `get_logs(app_id, tail=100)` | Get recent log lines from ring buffer |
| `health_check(app_id)` | HTTP GET /health on app's port |

### Process Lifecycle

```
create_app()
  └─ allocate port (9000-9999)
  └─ write main.py + requirements.txt + .env
  └─ pip install -r requirements.txt
  └─ _start_process()
       └─ subprocess_exec("python", "-u", "main.py")
       └─ pipe readers (stdout, stderr -> ring buffer)
       └─ health check loop (every 30s)
       └─ process watcher (auto-restart on crash)

auto_restart = True:
  crash -> restart_count++ -> backoff(2^restart_count s) -> restart
  max 3 attempts -> status = "crashed"

stop:
  SIGTERM -> wait 5s -> SIGKILL -> health loop cancelled
```

### Health Check Flow

```
_health_loop() every 30s:
  httpx.get(f"http://localhost:{port}/health", timeout=5)
  200 OK → health_status = "healthy"
  error  → health_status = "unhealthy"
```

### Integration

- App server can be launched from Blueprints via `app_server.create_app` tool
- Logs can be inspected through the `/kanban` or dashboard
- Webhook hooks can be set to alert on app crash/health change

--

## 6. Lean Persistent Goals

**Files**: `app/core/goal_manager.py` (352 lines), `app/core/planning/goal_tracker.py` (203 lines), `app/core/autonomy_engine.py` (406 lines)
**Priority**: Core (pre-existing)

Raven supports two goal systems that complement each other:

### GoalManager (Simple Persistent Goals)

**File**: `app/core/goal_manager.py`

A lightweight, self-contained goal system with task decomposition:

```python
@dataclass
class Goal:
    id: str
    title: str
    description: str
    status: GoalStatus  # ACTIVE | PAUSED | COMPLETED | FAILED | CANCELLED
    subtasks: list[SubTask]
    created_at, updated_at, completed_at
    progress: float      # 0.0 - 1.0

@dataclass
class SubTask:
    id, title, description, status  # PENDING | IN_PROGRESS | COMPLETED | FAILED | BLOCKED
```

| Method | Description |
|--|--|
| `create_goal(title, description, subtasks)` | Create a new active goal |
| `get_goal(goal_id)` | Get goal by ID |
| `list_goals(status)` | List goals with optional filter |
| `advance_goals()` | Check all active goals, advance next pending subtask |
| `complete_subtask(goal_id, subtask_id)` | Mark subtask done, update progress |
| `pause_goal(goal_id)` / `resume_goal(goal_id)` | Pause/resume |
| `cancel_goal(goal_id)` | Cancel a goal |
| `get_daily_digest()` | Summary of active goals for the user |

Goals persist to `workspace/memory/goals.jsonl` and are advanced during ambient loop cycles.

### GoalTracker (Planning Subsystem)

**File**: `app/core/planning/goal_tracker.py`

A more structured long-horizon goal tracker with:

- Deadline-based goal tracking
- Auto-decomposition to daily/weekly sub-plans
- HelixDB persistence (via PlanStore)
- Progress tracking (0.0-1.0)
- Composable decomposer (rule-based default, LLM pluggable)

```python
@dataclass(slots=True)
class Goal:
    id, title, description, user_id,
    status: GoalStatus, deadline: datetime | None,
    sub_plans: list[str],  # plan IDs
    progress: float,        # 0..1
    created_at, updated_at, completed_at
```

### AutonomyEngine (Execution Engine)

**File**: `app/core/autonomy_engine.py`

The `AutonomyEngine` bridges goals to execution:

1. Reads goals from `goals.jsonl`
2. Generates plans via `TaskPlanner`
3. Delegates plan steps to the agent swarm
4. Verifies results via `ResultVerifier`
5. Updates progress and reports to the inbox

Step state machine:
```
Pending → In Progress → Completed
                      → Retry (max 3, exponential backoff) → Blocked
```

A blocked step does NOT block the entire goal — independent steps continue to execute.

### Goal -> Kanban Integration

Goals can drive Kanban boards:

```python
# Pseudocode for integration
goal = goal_manager.create_goal("Deploy v2.0", "Ship the new release")
for subtask in goal.subtasks:
    board.create_card(
        title=subtask.title,
        description=subtask.description,
        agent_id="developer",
        priority=1,
    )
# As cards move to DONE, goal progress advances
```

--

## 7. Code Execution & Sandbox

**Files**: `app/core/sandbox_manager.py`, `app/core/app_server.py`, `app/tools/exectool.py`

### SandboxManager

**File**: `app/core/sandbox_manager.py`

Centralized isolated execution for untrusted code with multiple backends:

| Backend | Description | Trust Level |
|--|--|--|
| `DOCKER` | Full container isolation | community modules |
| `SUBPROCESS` | Subprocess with resource limits | workspace modules |
| `NONE` | Direct host execution | system modules |

```python
@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    success: bool
    timed_out: bool
    duration: float

@dataclass
class SandboxConstraints:
    max_cpu: float          # CPU cores
    max_memory_mb: int      # Memory limit
    max_duration_sec: float # Timeout
    max_network: bool       # Network access
    allowed_paths: list[str]
    forbidden_commands: list[str]
```

| Method | Description |
|--|--|
| `execute(command, constraints, input_files)` | Run command in sandbox |
| `cleanup()` | Kill all active sandboxes |
| `get_status()` | Backend health and active count |

### Code Execution Flow

```
User request → Orchestrator → Tool Router → SandboxExecTool
                                              └── SandboxManager.execute()
                                                    └── Docker container
                                                    └── OR subprocess
                                                    └── OR host (trusted)
```

### Codex App Server vs Sandbox

| Feature | SandboxManager | AppServerManager |
|--|--|--|
| **Purpose** | Ephemeral command execution | Long-running web services |
| **Lifetime** | Seconds to minutes | Hours to days |
| **Isolation** | Docker / subprocess | asyncio subprocess |
| **Port** | None (stdio) | Assigned from pool (9000-9999) |
| **Logging** | stdout/stderr capture | Ring buffer (1000 lines) |
| **Health** | Exit code based | HTTP /health endpoint |
| **Restart** | None | Auto-restart (up to 3 attempts) |
| **Use Case** | "Run this python script" | "Host a Flask API" |

--

## 8. Event Hooks (Outbound Webhooks)

**Files**: `app/core/hooks.py` (419 lines), `app/core/hook_emitter.py` (29 lines)
**Priority**: P1
**Database**: `workspace/memory/hooks.db`

The event hooks system provides outbound webhook delivery and an internal sync/async dispatch mechanism.

### Architecture

```
HookEventType (9 events):
  TASK_COMPLETED, MEMORY_CONSOLIDATED, PROVIDER_HEALTH_CHANGED,
  AGENT_TASK_STARTED, AGENT_TASK_COMPLETED, ERROR_CRITICAL,
  MEMORY_EXTRACTED, SKILL_CRYSTALLIZED, SCHEDULER_TRIGGERED

Internal Dispatch (HookDispatcher):
  register(event_name, handler) -> on_event, handler fires
  dispatch(event_name, payload) -> fire all registered handlers

Outbound Delivery (EventHookManager):
  register(name, url, events, secret, retry_policy) -> EventHook
  trigger(event_type, payload) -> find matching hooks, deliver

HookEmitter (mixin):
  class MyModule(HookEmitter):
      await self.emit_hook("task_completed", {"task_id": "123"})
```

### Retry Policy

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0    # Exponential: 1, 2, 4, 8...
    max_delay: float = 60.0    # Cap at 60 seconds
```

### Delivery Headers

```
Content-Type: application/json
X-Raven-Event: task_completed
X-Raven-Delivery-Id: <uuid>
X-Raven-Signature: <hmac-sha256>  # If secret configured
```

### EventHookManager API

| Method | Description |
|--|--|
| `register(name, url, events, secret, retry_policy)` | Create a webhook |
| `unregister(hook_id)` | Remove a webhook |
| `update(hook_id, **fields)` | Update hook fields |
| `list_hooks()` | List all registered hooks |
| `get_hook(hook_id)` | Get hook details |
| `trigger(event_type, payload)` | Fire event to matching hooks |
| `get_delivery_history(hook_id, limit)` | View delivery log |
| `get_stats()` | Total hooks, deliveries, success rate |

### SQLite Schema

```sql
CREATE TABLE event_hooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, url TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]',
    secret TEXT NOT NULL DEFAULT '',
    max_retries INTEGER NOT NULL DEFAULT 3,
    base_delay REAL NOT NULL DEFAULT 1.0,
    max_delay REAL NOT NULL DEFAULT 60.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    last_error TEXT, response_code INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (hook_id) REFERENCES event_hooks(id)
);
```

### Integration With Core Systems

```
Kanban Card Moved           → HookEvent.emit("task_completed", card_data)
Blueprint Run Complete      → HookEvent.emit("task_completed", run_data)
Goal Subtask Advanced       → HookEvent.emit("task_completed", goal_data)
App Server Health Change    → HookEvent.emit("provider_health_changed", app_data)

Memory Extracted            → HookEvent.emit("memory_extracted", stats)
  MemoryManager.store_extraction()  — per-turn memory extraction
  MemoryFacade.remember()           — direct memory storage

Memory Consolidated         → HookEvent.emit("memory_consolidated", stats)
  ConsolidationEngine.consolidate_all()  — 4-pass LearningStore maintenance
  LearningStore.prune()                  — low-confidence / excess removal

Error Critical              → HookEvent.emit("error_critical", error_data)
```

| Hook Event | Emitter | File:Line | Payload |
|--|--|--|--|
| `memory_extracted` | `MemoryManager.store_extraction()` | `app/core/memory_manager.py:165` | `{user_id, facts_count, preferences_count, tasks_count, total}` |
| `memory_extracted` | `MemoryFacade.remember()` | `app/core/memory_facade.py:109` | `{memory_id, category, user_id, content_preview}` |
| `memory_consolidated` | `ConsolidationEngine.consolidate_all()` | `app/core/consolidation.py:97` | `{merges, deletions, contradictions, promotions, errors}` |
| `memory_consolidated` | `LearningStore.prune()` | `app/core/learning_db.py:384` | `{action, low_confidence_removed, excess_removed, total_removed}` |

--

## 9. Rate-Limit Middleware

**Files**: `app/core/rate_limit_middleware.py` (120 lines), `app/core/subscription_proxy.py` (558 lines)
**Priority**: P3 (wired into runtime)
**Toggle**: `RAVEN_RATE_LIMIT=true` (default: enabled)

The rate-limit middleware combines two enforcement layers into a single pre-LLM-call check that is injected into every LLM call site in `AgentRuntime.execute_turn()`.

### Architecture

```
execute_turn() before every LLM call:
  └── _check_llm_budget(user_id, input_tokens, output_tokens)
       ├── RateLimiter.check_rate_limit(user_id)
       │     └── Sliding 60-second window per user
       │     └── max_requests_per_minute (60) + burst_capacity (10)
       │     └── max_tokens_per_hour (100K)
       └── SubscriptionManager.has_tokens(user_id, total_needed)
             └── Monthly token budget per tier:
                   BASIC=100K, PRO=500K, ENTERPRISE=5M, BETA=50K

  If blocked: sends user-friendly message via BotSignal, skips LLM call
  If allowed: proceeds, then tracks consumption via _track_llm_usage()
```

### RateLimitMiddleware API

| Method | Description |
|--|--|
| `check(user_id, input_tokens, output_tokens)` | Returns `{"allowed": True}` or `{"allowed": False, "reason": ..., "retry_after": ...}` |
| `record(user_id, tokens_consumed, action, metadata)` | Records consumed tokens in subscription ledger + rate-limiter sliding window |
| `set_enabled(bool)` | Toggle at runtime without restart |

### LLM Call Sites Protected

| Location | Lines | Description |
|--|--|--|
| Primary ReAct loop | 2302-2312 | Main `chat_completion_resilient` call |
| Streaming path | 2278-2298 | Final-turn streaming output |
| Max-turns-exhausted | 2998-3008 | Force-final-answer call |
| Cognition Ladder | 692-706 | `_try_cheap_model` cheap model probe |
| Planner | (closure) | TaskPlanner LLM calls |

### Integration Points

| Connection | Mechanism | Location |
|--|--|--|
| Runtime -> RateLimitMiddleware | Initialized in `__init__` | `app/core/runtime.py:316` |
| Before each LLM call | `_check_llm_budget()` | `app/core/runtime.py:2270` |
| After each LLM call | `_track_llm_usage()` | `app/core/runtime.py:2330` |
| SubscriptionManager | Monthly token budget | `app/core/subscription_proxy.py:259` |
| RateLimiter | Per-minute sliding window | `app/core/subscription_proxy.py:425` |

## 10. Batch Processing

**File**: `app/core/batch_processor.py` (140 lines)
**Priority**: Core (pre-existing)

The batch processor runs the agent across many prompts in parallel for training data generation and evaluation.

### Data Model

```python
@dataclass(slots=True)
class BatchJob:
    job_id: str
    prompt: str
    status: str           # pending | running | completed | failed
    result: str
    trajectory: list[dict]  # Full tool call trace
    started_at: float
    completed_at: float
    error: str
```

### BatchProcessor API

| Method | Description |
|--|--|
| `process_batch(prompts, orchestrator, max_concurrent, output_format)` | Run batch |
| `get_status()` | Current batch status |
| `get_results()` | Processed results |
| `cancel()` | Cancel running batch |

### Output Formats

| Format | Description |
|--|--|
| `sharegpt` | ShareGPT conversation format |
| `jsonl` | JSONL with trajectories |
| `alpaca` | Alpaca instruction format |

### Concurrency

Default `max_concurrent = 3`. Each prompt is processed independently with full isolation. Results are written to `workspace/batch_output/`.

### Integration

- Batch processing can be triggered from Blueprints
- Results feed into the Curator pipeline for training dataset generation
- Hook events fire on batch completion

--

## 11. Cross-System Integration Matrix

The following table shows how every system connects to every other system:

| | Kanban | Blueprints | Goals | AppServer | Hooks | Batch | Sandbox | Curator | Deliverable | Petdex |
|--|--|--|--|--|--|--|--|--|--|--|
| **Kanban** | — | Run BP from card | Goal -> cards | Deploy from card | Card events | — | — | — | — | — |
| **Blueprints** | KanbanTool action | — | BP advances goals | BP deploys apps | BP fires hooks | BP triggers batch | BP runs sandbox | BP runs curation | BP delivers output | — |
| **Goals** | Cards track tasks | BP auto-runs for goal | — | — | Goal completion | — | — | — | — | — |
| **AppServer** | App status cards | BP manages lifecycle | — | — | Health change events | — | App server IS code exec | — | App output → deliverable | — |
| **Hooks** | Hook on card move | Hook on BP run | Hook on goal done | Hook on app crash | — | Hook on batch done | — | Hook on curation | — | — |
| **Batch** | — | BP triggers batch | — | — | Batch completion hook | — | Batch uses sandbox | Batch -> curation data | — | — |
| **Sandbox** | — | BP uses sandbox tools | — | Sandbox is single-exec | — | Batch runs sandboxed | — | Curator runs sandboxed | — | — |
| **Curator** | — | BP schedules curation | — | — | Curation done hook | Batch feeds curator | — | — | Curated export | — |
| **Deliverable**| — | BP delivers output | — | App output → deliverables | — | — | — | Curator exports | — | — |
| **Petdex** | — | — | — | — | — | — | — | — | — | — |

### How Scheduler Links Everything

The `TaskScheduler` in the orchestrator (`app/core/orchestrator.py:730-775`) runs registered tasks on turn-based intervals:

```python
# Registered tasks (turn intervals):
curator_pipeline  (100 turns) — runs Curator pipeline -> delivers stats
petdex_tick       (10 turns)  — advances pet stats -> hooks fire
memory_sync       (200 turns) — syncs memory stores -> consolidation
```

### How Ambient Loop Links Everything

The Ambient Loop (`app/core/ambient_loop.py`, 60s tick) runs 27 subsystems including:

- Goal advancement (30 min) — `GoalManager.advance_goals()`
- Autonomy worker (30 min) — `AutonomyEngine` execution
- Memory consolidation (5 min)
- Curiosity exploration (30 min)
- Self-improvement loop (60 min)
- Predictive scheduling (60 min)

--

## 12. Tutorial — Multi-Step Automation End-to-End

This tutorial demonstrates how all systems connect by creating a "Deploy v2.0" automation.

### Step 1: Create a Goal

```python
from app.core.goal_manager import GoalManager

gm = GoalManager()
goal = gm.create_goal(
    title="Deploy v2.0",
    description="Ship the production release with monitoring",
    subtasks=[
        {"title": "Run tests", "description": "Full test suite"},
        {"title": "Build Docker image", "description": "Docker build"},
        {"title": "Deploy to staging", "description": "kubectl apply"},
        {"title": "Run health checks", "description": "Verify endpoints"},
        {"title": "Promote to production", "description": "kubectl promote"},
    ]
)
```

### Step 2: Create Kanban Cards from Goal Subtasks

```python
from app.core.kanban import KanbanBoard

board = KanbanBoard()
for st in goal.subtasks:
    board.create_card(
        title=st.title,
        description=st.description,
        agent_id="developer",
        priority=5 if "production" in st.title else 3,
    )
```

### Step 3: Register a Webhook for Status Updates

```python
from app.core.hooks import EventHookManager, HookEventType

hooks = EventHookManager()
hooks.register(
    name="deploy-alerts",
    url="https://hooks.slack.com/services/xxx",
    events=[HookEventType.TASK_COMPLETED, HookEventType.ERROR_CRITICAL],
    secret="whsec_xxx",
)
```

### Step 4: Create a Blueprint for the Deploy Pipeline

```yaml
# blueprints/deploy-v2.yaml
name: "deploy-v2"
version: "1.0.0"
description: "Automated deploy pipeline for v2.0"
tags: ["deploy", "ci-cd"]
steps:
  - id: run_tests
    tool: sandbox_exec
    params:
      command: "pytest tests/ -v"
  - id: build_docker
    tool: sandbox_exec
    params:
      command: "docker build -t app:v2.0 ."
    depends_on: ["run_tests"]
  - id: deploy_staging
    tool: sandbox_exec
    params:
      command: "kubectl apply -f k8s/staging.yaml"
    depends_on: ["build_docker"]
  - id: health_check
    tool: lsp
    params:
      action: diagnostics
      text: "Check http://staging.app.com/health"
    depends_on: ["deploy_staging"]
  - id: promote
    tool: sandbox_exec
    params:
      command: "kubectl set image deployment/app app=app:v2.0"
    depends_on: ["health_check"]
```

Install and run:

```python
from app.core.blueprint_manager import BlueprintManager
from app.core.blueprint_runner import BlueprintRunner

mgr = BlueprintManager()
mgr.install("deploy-v2", yaml_content)  # From file or dict

runner = BlueprintRunner(manager=mgr)
result = runner.run("deploy-v2")
# result.status, result.steps_results, result.duration
```

### Step 5: Watch in the Dashboard

```bash
RAVEN_THEME=midnight raven dashboard
```

The dashboard shows:
- System health (CPU, memory, disk)
- Agent status grid (14 agents)
- Gap services panel (kanban, blueprints, etc.)
- Recent audit events

### Step 6: Track with Kanban

```bash
/kanban list in_progress       # See what's being worked on
/kanban move 1 done           # Mark done
/kanban summary               # Board stats
```

### Step 7: What Fires on Each Event

```
Card moved to IN_PROGRESS:
  → KanbanBoard.move_card()
  → HookEmitter.emit("agent_task_started", card_data)
  → EventHookManager.trigger()
  → Webhook POST to Slack with X-Raven-Signature

Blueprint step completes:
  → BlueprintRunner._execute_step()
  → HookEmitter.emit("task_completed", step_data)
  → Webhook to Slack

App server health change:
  → AppServerManager.health_check()
  → HookEmitter.emit("provider_health_changed", app_data)
  → Webhook to Slack

Goal advances:
  → GoalManager.complete_subtask()
  → Goal progress updated
  → Ambient loop picks up next subtask
```

--

## Related Documentation

| Document | Topics |
|--|--|
| `docs/developer-architecture.md` | Full 8-layer architecture, event system, security |
| `docs/roadmap-gaps.md` | Gap prioritization and implementation plans |
| `docs/reference-cli.md` | CLI command reference (kanban, blueprint, dashboard) |
| `docs/features-core.md` | Core cognitive engine, memory, learning |
| `docs/features-skills.md` | Skill system and crystallization |
| `docs/guides-agents.md` | Agent architecture and creation guide |
| `docs/overview.md` | High-level project overview |
