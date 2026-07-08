---
title: "Agent Architecture & Custom Agent Guide"
---

# Agent Architecture & Custom Agent Guide

RAVEN operates using a swarm architecture governed by a Supervisor and SwarmManager. Rather than relying on a single mega-prompt, RAVEN delegates complex tasks to a specialized swarm of isolated sub-agents. Most agents extend `BaseAgent(ABC)` from `app/agents/base.py` and have file-backed memory, personality, soul, goals, and provider routing.

## 1. Complete Agent Reference Table

| Agent Name | Class Name | File | Soul | Tools (count) | Capabilities | Perfectness |
|---|---|---|---|---|---|---|
| PersonalAssistant | `PersonalAssistantAgent` | `app/agents/assistant.py` | General-purpose conversationalist | 90+ (all registered) | general, chat, casual | 0.5 |
| HeraldAgent | `HeraldAgent` | `app/agents/communications.py` | Communications specialist | email, messaging, calendar | communications, messaging, scheduling | 0.7 |
| ArchivistAgent | `ArchivistAgent` | `app/agents/dataengineer.py` | Data management | data, database, organization | data, organization, storage | 0.8 |
| DeveloperAgent | `DeveloperAgent` | `app/agents/developer.py` | Code specialist | code, git, shell, docker | coding, development, debugging | 0.9 |
| FinanceAgent | `FinanceAgent` | `app/agents/finance.py` | Financial analyst | stocks, crypto, budgeting | finance, budget, investing | 0.8 |
| HomeGuardianAgent | `HomeGuardianAgent` | `app/agents/homeguardian.py` | Home protector | smart_home, sensors, cameras | home, iot, automation | 0.7 |
| ConscienceAgent | `ConscienceAgent` | `app/agents/moral.py` | Ethics advisor | none (pure LLM) | ethics, philosophy, alignment | 0.3 |
| NegotiationAgent | `NegotiationAgent` | `app/agents/negotiation.py` | Dealmaker | web_search, email | negotiation, persuasion | 0.6 |
| NewsAgent | `NewsAgent` | `app/agents/news.py` | News curator | rss, web_search | news, current events | 0.7 |
| ConductorAgent | `ConductorAgent` | `app/agents/productivity.py` | Productivity manager | calendar, todo, reminders | productivity, scheduling | 0.8 |
| ResearcherAgent | `ResearcherAgent` | `app/agents/researcher.py` | Deep researcher | web_search, academic, fetch | research, factcheck, analysis | 0.9 |
| ReviewerAgent | `ReviewerAgent` | `app/agents/reviewer.py` | Quality assurance | code_review, file_read | qa, testing, validation | 0.95 |
| PolymathAgent | `PolymathAgent` | `app/agents/scientist.py` | Science & math | wolfram, calculator | science, math, crossdomain | 0.8 |
| SecurityAgent | `SecurityAgent` | `app/agents/security.py` | Security monitor | virus_total, network_scan | security, threat, compliance | 0.95 |
| SysadminAgent | `SysadminAgent` | `app/agents/sysadmin.py` | System administrator | shell, docker, system_stats | devops, system, infrastructure | 0.9 |

### Agent Registration in Orchestrator

All 15 agents are registered into the `SwarmManager` in `MessageOrchestrator.__init__()` (`app/core/orchestrator.py:436-577`):

```python
self._swarm_manager.register_agent(FinanceAgent())
self._swarm_manager.register_agent(ResearcherAgent())
self._swarm_manager.register_agent(SecurityAgent())
self._swarm_manager.register_agent(ReviewerAgent())
self._swarm_manager.register_agent(SysadminAgent())
self._swarm_manager.register_agent(DeveloperAgent())
self._swarm_manager.register_agent(PersonalAssistantAgent())
self._swarm_manager.register_agent(NewsAgent())
self._swarm_manager.register_agent(HomeGuardianAgent())
self._swarm_manager.register_agent(HeraldAgent())
self._swarm_manager.register_agent(PolymathAgent())
self._swarm_manager.register_agent(ConductorAgent())
self._swarm_manager.register_agent(ArchivistAgent())
self._swarm_manager.register_agent(ConscienceAgent())
self._swarm_manager.register_agent(NegotiationAgent())
```

Each registration is also logged to the audit trail as an `AuditEvent(kind="agent", action="register", ...)`.

## 2. BaseAgent ABC (`app/agents/base.py`)

The `BaseAgent` class (345 lines) provides the abstract base and concrete defaults for all agents.

### Abstract Properties (must be overridden)

| Property | Type | Description |
|---|---|---|
| `name` | `str` | Unique agent identifier (e.g., "FinanceAgent") |
| `role_prompt` | `str` | Legacy system prompt defining the agent's persona |
| `tools` | `List[BaseTool]` | Instantiated tools this agent may use |

### Concrete Properties (override as desired)

| Property | Type | Default | Description |
|---|---|---|---|
| `provider_name` | `str` | `"auto"` | LLM provider override. "auto" lets AutoModelRouter pick |
| `model_name` | `str` | `""` | Model override. Empty = AutoModelRouter picks for provider |
| `soul` | `str` | `""` | Immutable core purpose (override per agent) |
| `personality` | `str` | `""` | Communication style (override per agent) |
| `goals` | `List[str]` | `[]` | Current high-level objectives |
| `perfectness` | `float` | `0.5` | 0.0 = creative/loose, 1.0 = strict/precise |
| `heartbeat_interval` | `int` | `0` | Seconds between heartbeat calls. 0 disables |

### Concrete Methods

| Method | Returns | Description |
|---|---|---|
| `memory_dir` | `Path` | Per-agent workspace: `workspace/agents/{name_lower}/` |
| `load_memory()` | `str` | Reads memory.md (returns empty string on first use) |
| `load_skills()` | `str` | Reads skill.md |
| `save_to_memory(category, content)` | `None` | Appends to memory.md; caps at 50KB; saves to HelixDB |
| `save_to_skills(name, description)` | `None` | Appends to skill.md; caps at 30KB; saves to HelixDB |
| `save_to_journal(entry)` | `None` | Appends to journal.md; caps at 40KB |
| `get_enhanced_prompt()` | `str` | Builds rich system prompt with soul, personality, goals, skills, memory |
| `heartbeat()` | `Optional[str]` | Override for periodic background work |

## 3. Agent Memory System

### File-Backed Persistence

Each agent has a dedicated directory at `workspace/agents/{name_lower}/` with markdown files:

| File | Purpose | Auto-Cap | Created If Missing |
|---|---|---|---|
| `soul.md` | Immutable core purpose | N/A | Yes (seeded from `soul` property) |
| `goals.md` | Strategic objectives | N/A | Yes (seeded from `goals` property) |
| `memory.md` | Episodic memory | 50KB (trims oldest) | Yes (empty header) |
| `journal.md` | Interaction journal | 40KB (trims oldest) | Yes (empty header) |
| `skill.md` | Crystallized skills | 30KB (trims oldest) | Yes (empty header) |

### Auto-Capping Mechanism

When a memory file exceeds its cap, the oldest content is trimmed:
```python
# From base.py save_to_memory
if p.stat().st_size > 50_000:
    text = p.read_text(encoding="utf-8")
    p.write_text(text[-40_000:], encoding="utf-8")
```

This preserves the most recent 40KB of content (from the 50KB file), keeping the most relevant context.

### HelixDB Integration

All memory operations are dual-written to HelixDB for fast semantic retrieval:
```python
def _helix_memory_save(self, category: str, content: str) -> None:
    store = get_memory_store()
    tagged = f"[agent:{self.name}] {content}"
    store.save(category="FACT", content=tagged, user_id=f"agent_{self.name}")
```

The `get_enhanced_prompt()` method prioritizes HelixDB semantic search results over file-tail fallback:
```python
# Prefer HelixDB semantic search
helix_memories = self._helix_memory_retrieve(query="...", top_k=8)
if helix_memories:
    # Use semantic results
else:
    # Fallback: last 2000 chars of memory.md
```

## 4. Agent Personality System

### Soul

The `soul` property defines an agent's immutable core purpose. It is written to `soul.md` and included in the enhanced prompt:

```python
# From base.py get_enhanced_prompt
if self.soul:
    parts.append(f"\n## Soul (Immutable Core Purpose)\n{self.soul}")
```

### Personality

The `personality` property defines communication style. Not all agents override this:

```python
# From base.py get_enhanced_prompt
if self.personality:
    parts.append(f"\n## Personality\n{self.personality}")
```

### Goals

The `goals` property defines current strategic objectives. Updated at runtime via dashboard:

```python
# From base.py get_enhanced_prompt
if self.goals:
    goal_lines = "\n".join(f"- {g}" for g in self.goals)
    parts.append(f"\n## Current Goals\n{goal_lines}")
```

### Perfectness

The `perfectness` property (0.0 to 1.0) controls operating mode:
- `>= 0.8`: High-precision mode — "Verify every claim, double-check calculations, cite sources"
- `<= 0.2`: Creative mode — "Think laterally, brainstorm freely, propose unconventional solutions"
- `0.3 - 0.7`: Balanced mode — no additional instruction

### Journal

The `save_to_journal()` method appends timestamped entries:
```python
def save_to_journal(self, entry: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(self.memory_dir / "journal.md", "a") as f:
        f.write(f"\n### {ts}\n\n{entry}\n")
```

## 5. Provider Routing per Agent

Each agent can specify its own provider and model, or defer to AutoModelRouter:

### Agent-Level Override

```python
class DeveloperAgent(BaseAgent):
    @property
    def provider_name(self) -> str:
        return "anthropic"  # Always use Claude for coding tasks

    @property
    def model_name(self) -> str:
        return "claude-3-5-sonnet-20241022"
```

### AutoModelRouter Resolution

When `provider_name` is `"auto"` (or `""` or `"opencode_zen"`), the `SwarmManager.execute_case_study()` method resolves the best provider:

1. **Dashboard slot**: Check `ProviderManager.resolve_model_slot("agent:{agent_name}")`
2. **Agent override**: Check `ProviderManager.get_agent_model(agent_name)`
3. **Global dashboard**: Check `ProviderManager.select_model()` for non-default selection
4. **AutoModelRouter**: Call `AutoModelRouter.get_best_model(agent_name)` for cascading fallback

```python
# From agency.py — provider resolution in execute_case_study
if (worker_provider or "").lower() in {"", "auto", "opencode_zen"}:
    pm = ProviderManager(self.workspace_dir)
    slot_pid, slot_mid = pm.resolve_model_slot(f"agent:{agent_name}")
    if slot_pid and slot_mid:
        worker_provider, worker_model = slot_pid, slot_mid
    else:
        agent_override = pm.get_agent_model(agent_name)
        if agent_override:
            worker_provider, worker_model = agent_override
        else:
            pm_provider, pm_model = pm.select_model()
            if pm_provider != "opencode_zen" or pm_model != "big-pickle":
                worker_provider, worker_model = pm_provider, pm_model
            else:
                worker_provider, worker_model = AutoModelRouter.get_best_model(agent_name)
```

## 6. WorkerAgent (`app/core/agency.py`)

The `WorkerAgent` wraps any `BaseAgent` into an executable sub-agent with its own `AgentRuntime`, tool set, and ReAct loop. It is the execution unit of the swarm.

### Constructor

```python
worker = WorkerAgent(
    name="ResearcherAgent",
    role_prompt="You are a deep research specialist...",
    tools=[WebSearchTool(), AcademicSearchTool()],
    workspace_dir="workspace",
    provider_name="openai",
    model_name="gpt-4o",
    system_prompt="Optional: full system prompt (overrides role_prompt)",
    shared_context={"key": "value"},
)
```

### Dynamic Agent Spawning

The `SwarmManager.spawn_agent()` method creates WorkerAgents on-the-fly for ad-hoc tasks:
```python
worker = swarm.spawn_agent(
    name="PythonExpert",
    role_description="Expert Python developer specializing in async patterns",
    tools=[SandboxExecTool(), GitOperationTool()],
)
result = await worker.execute_task("Refactor this async function to use asyncio.gather", request)
```

### Execution Loop

The `execute_task()` method runs a simplified ReAct loop (max 10 turns) with:
1. System prompt construction (from `Bootstrapper` or `get_enhanced_prompt`)
2. Provider call with resilient fallback
3. Tool execution loop (max 10 turns)
4. Provider fallback on failure (cascades through available models)
5. Returns final answer or error message

```python
async def execute_task(self, task_description: str, request: IncomingRequest) -> str:
    # Build messages
    # Run ReAct loop (max 10 turns)
    # Return final answer or error
```

## 7. Cross-Agent Collaboration

### Supervisor Keyword Matching

The `Supervisor` (`app/core/supervisor.py:192`) routes incoming requests to the best agent based on keyword matching:

```python
def select_agent(self, text: str, context: dict | None = None) -> str:
    text_lower = text.lower()
    # Score each agent's keywords against the input text
    for cap in self._registry._capabilities.values():
        match_count = sum(
            1 for kw in cap.keywords 
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower)
        )
        score = match_count * 10 + cap.priority
        if match_count > 0 and score > best_score:
            best_match = cap.agent_id
    return best_match or "assistant"
```

Each agent declares its keywords in the `AgentRegistry`:

| Agent | Keywords | Priority |
|---|---|---|
| assistant | help, hello, general | 0 |
| herald | message, email, schedule, remind, meeting, send | 0 |
| researcher | research, find, search, investigate, analyze, lookup, what is, explain | 0 |
| developer | code, write, program, debug, fix, implement, function, class, app | 0 |
| finance | finance, money, budget, invest, stock, cost, price, buy | 0 |
| homeguardian | home, iot, device, sensor, light, thermostat | 0 |
| security | security, threat, vulnerability, attack, protect, encrypt | 0 |
| archivist | organize, file, data, archive, store, backup | 0 |
| reviewer | review, test, validate, verify, approve, qa | 0 |
| news | news, latest, headline, current, update on | 0 |
| polymath | science, math, physics, biology, chemistry, theory | 0 |
| negotiation | negotiate, deal, offer, bargain, persuade | 0 |
| sysadmin | server, deploy, infra, docker, kubernetes, config | 0 |

### SwarmManager Parallel Execution

The `SwarmManager.execute_case_study()` method executes multiple agents in parallel:

```python
# Execute all agents in parallel
results = await asyncio.gather(*coroutines, return_exceptions=True)
```

Each agent runs independently with its own runtime, tools, and provider. Results are compiled into an Evidence Board and optionally passed to the ReviewerAgent for synthesis.

### Inter-Agent Communication

The `SwarmManager` provides a message bus for agent-to-agent communication:

```python
# Send message from one agent to another
swarm.send_message("DeveloperAgent", "ReviewerAgent", "Please review my code changes")

# Broadcast to all agents
swarm.broadcast("Orchestrator", "System maintenance in 5 minutes")

# Read inbox
messages = swarm.check_inbox("ReviewerAgent")
```

### Cross-Agent Learning

The `WorkerAgent._build_learning_context()` method gathers relevant learnings from the shared learning store for domain-relevant context. This allows one agent's discoveries to inform another agent's decisions.

### Agent Feedback Loop

After swarm execution, the FeedbackCollector performs cross-check validation:
- Each worker's output is reviewed by the next worker (circular)
- Outputs shorter than 50 chars are flagged as incomplete
- Outputs containing "error" or "failed" trigger a critical warning
- Feedback is logged for quality monitoring

## 8. Adding a New Agent: Complete Example (Illustrative)

> **Note:** The `MarketingAgent` shown below is an illustrative example. The file `app/agents/marketing.py` is **not shipped** with RAVEN — it exists only to demonstrate the pattern.

### Step 1: Create the Agent Class

```python
# app/agents/marketing.py  (illustrative example — this file is not shipped)
from typing import List
from app.agents.base import BaseAgent
from app.tools.base import BaseTool
from app.tools.websearch import WebOperationTool
from app.tools.webfetch import WebFetchOperationTool

class MarketingAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "MarketingAgent"

    @property
    def role_prompt(self) -> str:
        return (
            "You specialize in SEO content strategy, social media scheduling, "
            "and marketing analytics. You provide data-driven recommendations "
            "for content marketing campaigns."
        )

    @property
    def tools(self) -> List[BaseTool]:
        return [
            WebOperationTool(),
            WebFetchOperationTool(),
        ]

    @property
    def soul(self) -> str:
        return "I help users grow their audience through strategic content marketing."

    @property
    def personality(self) -> str:
        return "Analytical and creative. I combine data with storytelling."

    @property
    def goals(self) -> List[str]:
        return [
            "Optimize content for search engines",
            "Analyze social media engagement metrics",
            "Suggest data-driven content strategies",
        ]

    @property
    def perfectness(self) -> float:
        return 0.7
```

### Step 2: Register in Supervisor Registry

```python
# app/core/supervisor.py — in AgentRegistry.register_all()
self.register(
    AgentCapability(
        agent_id="marketing",
        agent_name="MarketingAgent",
        specialties=["marketing", "seo", "social media"],
        keywords=[
            "marketing", "seo", "social media", "content strategy",
            "audience", "campaign", "engagement", "analytics",
        ],
    )
)
```

### Step 3: Register in Orchestrator

```python
# app/core/orchestrator.py — in MessageOrchestrator.__init__()
from app.agents.marketing import MarketingAgent
self._swarm_manager.register_agent(MarketingAgent())
```

### Step 4: Register Agent Capability Keywords

Add to the `AgentRegistry.register_all()` method in `supervisor.py` with appropriate keywords so the Supervisor can route tasks to the new agent.

### Step 5: Configure Provider (Optional)

```python
class MarketingAgent(BaseAgent):
    @property
    def provider_name(self) -> str:
        return "openai"  # Or "auto" for automatic selection
```

## 9. WorkerAgent Execution Details

### Provider Fallback Chain

When a worker's primary provider fails, it tries all available models from `AutoModelRouter.get_available_models()`:
1. Skips the current (failed) provider
2. Tries Anthropic (if key configured)
3. Tries OpenAI (if key configured)
4. Tries Google/Gemini (if key configured)
5. Tries OpenRouter (if key configured)
6. Tries OpenCode Zen (free, always available)

### WorkerAgent vs BaseAgent

| Feature | BaseAgent | WorkerAgent |
|---|---|---|
| Type | ABC (inheritance) | Wrapper (composition) |
| Has AgentRuntime | No | Yes (own runtime instance) |
| Tool Registration | Returns tool list | Tools injected into runtime |
| Execution Method | N/A (agent definition only) | `execute_task(task, request)` |
| Max Turns | N/A | 10 (fixed) |
| Provider Resolution | Properties | AutoModelRouter cascade |
| Memory | File-backed via BaseAgent | No file memory (ephemeral) |
| Cross-Agent Learning | No | Shared context + learning store |
| Use Case | Agent definition for Swarm | One-shot task execution |

## 10. Configuration

```ini
# Per-agent provider overrides (dashboard)
AGENT_DEVELOPER_PROVIDER=anthropic
AGENT_DEVELOPER_MODEL=claude-3-5-sonnet-20241022
AGENT_RESEARCHER_PROVIDER=openai
AGENT_RESEARCHER_MODEL=gpt-4o

# Agent memory limits
AGENT_MEMORY_MAX_SIZE_KB=50
AGENT_SKILLS_MAX_SIZE_KB=30
AGENT_JOURNAL_MAX_SIZE_KB=40

# Swarm execution
SWARM_MAX_WORKERS=15
SWARM_WORKER_TIMEOUT_SECONDS=120
SWARM_FALLBACK_MAX_ATTEMPTS=3

# Supervisor
SUPERVISOR_DEFAULT_AGENT=assistant
SUPERVISOR_MIN_MATCH_SCORE=1
```
