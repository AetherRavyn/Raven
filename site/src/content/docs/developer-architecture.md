---
title: "RAVEN System Architecture Reference"
---

# RAVEN System Architecture Reference

> **Document level**: Hermes / OpenClaw  
> **Last updated**: 2026-06-29  
> **Codebase**: `/home/swadhin/SARAS`  
> **Python**: 3.12+ — async-first, type-hinted throughout

--

## Table of Contents

1. [Architecture Overview — The 8-Layer Stack](#1-architecture-overview-the-8-layer-stack)
2. [Layer 1 — Platform Connectors (12 Channels)](#2-layer-1-platform-connectors-12-channels)
3. [Layer 2 — BotSignal Message Bus](#3-layer-2-botsignal-message-bus)
4. [Layer 3 — Cognitive Core](#4-layer-3-cognitive-core)
5. [Layer 4 — Tool Execution (98 Tools)](#5-layer-4-tool-execution-98-tools)
6. [Layer 5 — Voice Pipeline](#6-layer-5-voice-pipeline)
7. [Layer 6 — Memory & Knowledge](#7-layer-6-memory-knowledge)
8. [Layer 7 — Autonomy & Scheduling](#8-layer-7-autonomy-scheduling)
9. [Layer 8 — Skills & Self-Improvement](#9-layer-8-skills-self-improvement)
10. [Event System](#10-event-system)
11. [Security Architecture](#11-security-architecture)
12. [Configuration System](#12-configuration-system)
13. [Cross-Layer Interaction Patterns](#13-cross-layer-interaction-patterns)
14. [Performance Characteristics & Failure Modes](#14-performance-characteristics-failure-modes)

--

## 1. Architecture Overview — The 8-Layer Stack

RAVEN abandons the traditional "chatbot per platform" model in favor of a **Unified Hub-and-Spoke** architecture. A single cognitive core processes all inbound telemetry, messages, and voice streams, while Platform Connectors act strictly as I/O endpoints.

```
                         ┌─────────────────────────────────────┐
                         │         Layer 8: Skills             │
                         │  SkillCrystallizer | SelfImprove    │
                         │  RLHF | CorrectionVerifier          │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │         Layer 7: Autonomy            │
                         │  AmbientLoop (27 intervals)          │
                         │  APScheduler | WorkflowEngine       │
                         │  AutonomousActionEngine              │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │      Layer 6: Memory & Knowledge     │
                         │  SQLite FTS5 | HelixDB | ChromaDB   │
                         │  LearningDB | RLHF | Agent Memory   │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │       Layer 5: Voice Pipeline        │
                         │  WakeWord → VAD → STT → LLM → TTS   │
                         │  openwakeword | pywhispercpp | Piper │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │       Layer 4: Tool Execution        │
                         │  98 Tools | BaseTool ABC            │
                         │  Resilience | CircuitBreaker        │
                         │  ToolRouter | Sandbox               │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │       Layer 3: Cognitive Core        │
                         │  MessageOrchestrator (8 phases)      │
                         │  System 1 (MiniEngine) < 2s         │
                         │  System 2 (AgentRuntime) 5-30s      │
                         │  15-Agent Supervisor | SwarmManager  │
                         └────────────────┬────────────────────┘
                         ┌────────────────┴────────────────────┐
                         │     Layer 2: BotSignal Message Bus   │
                         │  BotSignal | Sender Registry        │
                         │  Nonce-based Idempotency            │
                         │  Output Priority Router             │
                         └────────────────┬────────────────────┘
    ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
    │Tele  │Disc  │Slack │WA    │Signal│Matrix│ IRC  │ LINE │iMsg  │WeChat│Voice │ Web  │
    │gram  │ ord  │      │      │      │      │      │      │      │      │      │      │
    └──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘
                         Layer 1: Platform Connectors
```

### Cognitive Ladder — Three Systems

```
Inbound BotSignal
    │
    ▼
MessageOrchestrator.handle()
    │
    ├── Security Guard (prompt injection check)
    ├── Rate Limiter (sliding window)
    ├── DM Pairing enforcement
    ├── ContextReferenceResolver (@mentions, @file, @url)
    │
    ├── System 1: MiniEngine (fast reflex, <2s)
    │   └── Escalates to System 2 if needed
    │
    └── System 2: AgentRuntime (ReAct loop, 5-30s)
        ├── Supervisor selects agent
        └── SwarmManager for multi-agent tasks
```

--

## 2. Layer 1 — Platform Connectors (12 Channels)

Every connector follows the same lifecycle: `start()` -> listen for messages -> normalize to `BotSignal` -> publish -> receive `OutgoingSignal` -> format -> send.

### Connector Matrix

| Platform | Package | Library | Transport | Auth | Voice | Chunking | 
|-----|-----|-----|------|---|----|-----|
| Telegram | `app/telegram/` | python-telegram-bot PTB Application | Polling/Webhook | Bot token | Voice messages | 4096 char |
| Discord | `app/discord/` | discord.py Client | Gateway WS | Bot token | /join VC | 2000 char |
| Slack | `app/slack/` | slack_bolt AsyncApp | Socket Mode | xoxb + xapp tokens | No | mrkdwn |
| WhatsApp | `app/whatsapp/` | Baileys bridge (Node.js) | HTTP POST | Bridge URL | Voice notes | None |
| Signal | `app/signal/` | httpx -> signal-cli | JSON-RPC | signal-cli socket | No | None |
| Matrix | `app/matrix/` | matrix-nio | Homeserver WS | Access token | No | None |
| IRC | `app/irc/` | asyncio IRC client | TCP/TLS | NickServ | No | None |
| LINE | `app/line/` | line-bot-sdk | Webhook | Channel secret | No | None |
| iMessage | `app/imessage/` | osascript | macOS only | macOS FS | No | None |
| WeChat | `app/wechat/` | itchat | Web protocol | QR code | No | None |
| Voice | `app/voice/` | sounddevice | Local mic/speaker | None | Full duplex | N/A |
| Web | `app/web/` + `app/api/server.py` | FastAPI | WS port 8090 | Session | Browser WS | N/A |

### Connector Pattern — Code Example

Every connector follows this pattern:

```python
# app/telegram/bot.py — Telegram connector (abbreviated pattern)
from telegram.ext import Application, CommandHandler, MessageHandler
from app.core.botsignal import get_botsignal, IncomingRequest, ReplyTarget

class TelegramBot:
    def __init__(self, token: str):
        self._app = Application.builder().token(token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(MessageHandler(filters.TEXT, self._on_message))

    async def _on_message(self, update, context):
        # Normalize platform-specific message → IncomingRequest
        request = IncomingRequest(
            platform="telegram",
            user_id=str(update.effective_user.id),
            text=update.message.text,
            reply_target=ReplyTarget(
                platform="telegram",
                chat_id=str(update.effective_chat.id),
                reply_to_id=str(update.message.message_id),
            ),
        )
        # Publish to core
        await get_orchestrator().handle(request)
```

### Config for Connectors

```bash
# .env — Platform Connector Configuration
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_API_ID=0
TELEGRAM_API_HASH=your_api_hash

DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_CHANNEL_ID=your-discord-channel-id

SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_APP_TOKEN=xapp-1-your-app-token

WHATSAPP_BRIDGE_URL=http://localhost:3000
WHATSAPP_WHAPI_TOKEN=your-whapi-token

SIGNAL_CLI_SOCKET=/tmp/signal-cli.socket

MATRIX_HOMESERVER=https://matrix.example.com
MATRIX_ACCESS_TOKEN=syt_your_matrix_access_token

WEB_DASHBOARD_ENABLED=true
WEB_DASHBOARD_PORT=8090
WEB_DASHBOARD_HOST=127.0.0.1
```

### Edge Cases — Platform Connectors

- **Telegram**: 4096-char hard limit per message. Messages exceeding this are split on sentence boundaries using `_split_and_send()` in `app/telegram/bot.py`.
- **Slack**: Socket Mode requires no public HTTP endpoint. The `AsyncSocketModeHandler` maintains a persistent WebSocket connection to Slack's Events API.
- **WhatsApp**: Baileys bridge runs as a separate Node.js process. The Python side sends HTTP POST to `WHATSAPP_BRIDGE_URL/incoming`. Heartbeat pings every 30s detect bridge death.
- **iMessage**: macOS-only. Polls `~/Library/Messages/chat.db` SQLite database every 5 seconds. Sends via `osascript -e 'tell application "Messages" to send ...'`. No push delivery.
- **Voice**: The `VoicePipeline` registers a `"voice"` sender on `BotSignal`. When the orchestrator replies, the `_voice_sender` callback calls `_speak_streaming()` which synthesizes via Piper-TTS and fans out through `SinkRegistry`.
- **Discord Voice**: The `/join` command joins the user's current voice channel using `discord.py`'s `VoiceClient`. Audio is received via `pcm_audio` event and forwarded to the voice pipeline's STT.

--

## 3. Layer 2 — BotSignal Message Bus

The `BotSignal` class (`app/core/botsignal.py:97`) is the unified output API used by all platform connectors. It implements a **sender registry** pattern where each platform registers a `Sender` callback (type alias: `Callable[[ReplyTarget, SignalPayload], Awaitable[None]]`).

### BotSignal Architecture

```
                 ┌──────────────┐
                 │  BotSignal   │
                 │  (Singleton) │
                 └──────┬───────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
    Sender[telegram]  Sender[discord]  Sender[slack]  ...
          │             │             │
          ▼             ▼             ▼
    Outbox.enqueue() → Outbox.drain_once() → Sender(target, payload)
                        │
                   ┌────┴────┐
                   ▼         ▼
               success    failure
                         (entry stays, retried)
```

### Idempotency — Nonce-based dedup

```python
# app/core/botsignal.py:28-34
_send_nonce = itertools.count()
_nonce_lock = threading.Lock()

def _new_nonce() -> int:
    with _nonce_lock:
        return next(_send_nonce) | (int(time.time_ns()) << 16)
```

Every call to `BotSignal.send()` generates a unique nonce. The outbox entry's `idempotency_key` combines:
- Source prefix (`"botsignal"`)
- Channel name
- Chat ID
- SHA-256 hash of payload content
- Monotonic nonce

This means two separate `send` calls with identical text to the same chat produce **different** outbox entries (distinct user intents). Retries within a single send path go through `Outbox.drain_once()` which does not generate a new nonce.

### Outbox Integration

```python
# app/core/botsignal.py:128-191
async def send(self, target: ReplyTarget, payload: SignalPayload) -> None:
    sender = self._senders.get(target.platform.lower())
    if not sender:
        raise ValueError(f"No sender registered for platform '{target.platform}'")

    from app.runtime.outbox import get_outbox, make_idempotency_key
    payload_dict = _payload_to_dict(payload)
    key = make_idempotency_key(
        "botsignal", channel, target.chat_id,
        _payload_hash(payload_dict), _new_nonce(),
    )
    outbox = get_outbox()
    outbox.register_sender(channel, _make_outbox_sender(sender))
    entry = await outbox.enqueue(idempotency_key=key, channel=channel, ...)
    await outbox.drain_once()
    if entry.state != "sent":
        raise RuntimeError(f"outbox drain failed: {entry.last_error}")
```

### Output Priority Router

The priority system allows critical system messages to bypass normal queue ordering:

| Priority | Typical Use | Behavior |
|-----|-------|-----|
| CRITICAL | Security alerts, system failures | Immediate dispatch, bypass rate limits |
| HIGH | Correction acknowledgments, time-sensitive | Next available slot |
| NORMAL | Standard user replies | Default FIFO |
| LOW | Proactive suggestions, learning summaries | Batched, may be deferred |
| SILENT | Internal telemetry, logging only | Not delivered to user |

### BotSignalWrapper

The `BotSignalWrapper` (in `app/core/learning_messenger.py`) wraps `BotSignal` to add learning signal recording — every message sent through the wrapper is logged to the `LearningDB` as a learning event:

```python
# Conceptual: BotSignalWrapper records every outbound message
class BotSignalWrapper:
    def __init__(self, inner: BotSignal):
        self._inner = inner

    async def send_text(self, target, text, ...):
        await self._inner.send_text(target, text, ...)
        # Record to learning store
        get_learning_store().add(
            type_="outbound_message",
            content=text[:200],
            topic=target.platform,
        )
```

--

## 4. Layer 3 — Cognitive Core

### 4.1 MessageOrchestrator (`app/core/orchestrator.py`)

The `MessageOrchestrator` is the central entry point for all inbound `BotSignal` payloads. It implements an **8-phase processing pipeline** inside its single `handle()` method.

#### 8-Phase Pipeline

```
handle(request: IncomingRequest)
  │
  ├── Phase 0: Identity Resolution
  │     resolve platform user_id → canonical RAVEN user
  │
  ├── Phase 0.5: DM Pairing Enforcement
  │     check_dm_pairing(user_id, platform)
  │
  ├── Phase 1: Context Reference Expansion
  │     resolver.resolve_references(text)
  │     └── @file, @folder, @url, @git references
  │
  ├── Phase 2: Direct Tool Dispatch (System 0.5)
  │     _handle_direct_tool_prompt — /git, file, web search, /webfetch, virus, /image
  │     _handle_internet_intel_direct — /internet status/search/read
  │     _handle_learning_query — /learned, /progress
  │
  ├── Phase 3: System 1 — MiniEngine (Fast Reflex)
  │     route_message(user_id, text)
  │     └── Returns (response, escalate_flag)
  │
  ├── Phase 4: System 2 — AgentRuntime (Deep Reasoning)
  │     execute_turn(request) — full ReAct loop
  │
  ├── Phase 5: Post-Processing
  │     5a: SkillLearner observe (learn from tool traces)
  │     5b: ScheduleLearner (learn wake/sleep patterns)
  │     5c: Self-review cycle (Hermes pattern)
  │     5d: Uncertainty estimation & clarification
  │     5e: Response quality scoring
  │
  ├── Phase 6: Self-Correction & Learning
  │     6a: Prompt improvement orchestration
  │     6b: Self-correction acknowledgment
  │     6c: RLHF feedback recording
  │     6d: Fact-check gate (cross-reference KG)
  │
  ├── Phase 7: Retrospective Analysis (every 50 S2 turns)
  │     analyzer.analyze() → PromptImprover adjustments
  │
  ├── Phase 8: Patterns & Reflection
  │     8a: Success pattern learning
  │     8b: Learned reflector (LLM-based correction detection)
  │     8c: Correction storage → LearningDB + SelfImprovement
  │     8d: Knowledge graph fact extraction
  │
  └── Phase 9: Health Monitoring
        record_turn() → alerts on anomaly
```

#### Code Structure — Orchestrator Initialization

```python
# app/core/orchestrator.py:143-156
class MessageOrchestrator:
    def __init__(self, botsignal, output_directory="workspace"):
        self._botsignal = BotSignalWrapper(botsignal)
        self._engine = System1Router()              # MiniEngine
        self._agent_runtime = AgentRuntime(...)      # System 2
        self._swarm_manager = SwarmManager(...)      # Multi-agent
        self._init_scheduler()                       # TaskScheduler

        # Registers ~140+ tools dynamically
        tools = [AdvancedFileOperationTool(), GitOperationTool(), ...]
        for tool in tools:
            self._agent_runtime.register_tool(tool)
```

### 4.2 AgentRuntime (`app/core/runtime.py`)

The System 2 execution engine (~3064 lines). Implements a full **ReAct loop** (Reasoning + Acting):

```
Thought → Action (tool call) → Observation → Thought → ...

Max 15 turns per ReAct loop
Tool timeout: 30s per tool (configurable)
```

#### ReAct Loop Flow

```python
# Conceptual ReAct loop (app/core/runtime.py)
async def execute_turn(self, request):
    messages = [system_prompt, user_message]
    for turn in range(15):
        # 1. Call LLM with messages + tool definitions
        response = await self.provider.chat_completion(
            model=self.model_name,
            messages=messages,
            tools=self._build_openai_tools(),
        )
        # 2. Extract content and tool calls
        content, tool_calls = self._extract_provider_message(response)

        if not tool_calls:
            return {"response": content, "success": True}  # Done

        # 3. Execute each tool call
        for tc in tool_calls:
            result = await self.tools[tc.name].execute(**tc.args)
            messages.append({"role": "tool", "content": result})

    return {"response": "Max turns reached", "success": True}
```

#### AutoModelRouter Integration

When the primary provider fails, `AgentRuntime` falls back across all configured providers:

```python
# From orchestrator.py:819-832
fallbacks = AutoModelRouter.get_available_models("agent")
for f_prov_name, f_model_name in fallbacks:
    f_prov = create_provider(f_prov_name)
    f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
    if f_res.get("success"):
        result = f_res
        break
```

### 4.3 Supervisor (`app/core/supervisor.py`)

The `Supervisor` routes incoming requests to the best agent based on **keyword-matched capabilities**.

#### AgentRegistry — 15 Agents

```python
# app/core/supervisor.py:57-189
class AgentRegistry:
    def register_all(self):
        self.register(AgentCapability("assistant", "PersonalAssistant",
            ["general", "chat", "casual"], ["help", "hello", "general"]))
        self.register(AgentCapability("herald", "HeraldAgent",
            ["communications", "messaging", "scheduling"],
            ["message", "email", "schedule", "remind", "meeting", "send"]))
        self.register(AgentCapability("researcher", "ResearcherAgent",
            ["research", "factcheck", "analysis"],
            ["research", "find", "search", "investigate", "analyze", "lookup"]))
        self.register(AgentCapability("developer", "DeveloperAgent",
            ["coding", "development", "debugging"],
            ["code", "write", "program", "debug", "fix", "implement"]))
        self.register(AgentCapability("finance", "FinanceAgent",
            ["finance", "budget", "investing"],
            ["finance", "money", "budget", "invest", "stock", "cost"]))
        self.register(AgentCapability("homeguardian", "HomeGuardianAgent",
            ["home", "iot", "automation"],
            ["home", "iot", "device", "sensor", "light", "thermostat"]))
        self.register(AgentCapability("security", "SecurityAgent",
            ["security", "threat", "compliance"],
            ["security", "threat", "vulnerability", "attack", "protect"]))
        self.register(AgentCapability("archivist", "ArchivistAgent",
            ["data", "organization", "storage"],
            ["organize", "file", "data", "archive", "store", "backup"]))
        self.register(AgentCapability("reviewer", "ReviewerAgent",
            ["qa", "testing", "validation"],
            ["review", "test", "validate", "verify", "approve", "qa"]))
        self.register(AgentCapability("news", "NewsAgent",
            ["news", "current events"],
            ["news", "latest", "headline", "current", "update on"]))
        self.register(AgentCapability("polymath", "PolymathAgent",
            ["science", "math", "crossdomain"],
            ["science", "math", "physics", "biology", "chemistry", "theory"]))
        self.register(AgentCapability("negotiation", "NegotiationAgent",
            ["negotiation", "persuasion"],
            ["negotiate", "deal", "offer", "bargain", "persuade"]))
        self.register(AgentCapability("sysadmin", "SysadminAgent",
            ["devops", "system", "infrastructure"],
            ["server", "deploy", "infra", "docker", "kubernetes", "config"]))
```

#### Keyword Scoring Algorithm

```python
# app/core/supervisor.py:207-239
def select_agent(self, text, context=None):
    text_lower = text.lower()
    skip_agents = list(context.get("learning_hints", []) if context else [])

    best_match, best_score = None, 0
    for cap in self._registry._capabilities.values():
        if cap.agent_id in skip_agents:
            continue
        match_count = sum(
            1 for kw in cap.keywords
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower)
        )
        score = match_count * 10 + cap.priority
        if match_count > 0 and score > best_score:
            best_match = cap.agent_id
            best_score = score

    return best_match or "assistant"
```

### 4.4 SwarmManager (`app/core/agency.py`)

The `SwarmManager` creates `WorkerAgent` instances from `BaseAgent` subclasses and executes them in parallel via `asyncio.gather`.

#### WorkerAgent Architecture

```python
# app/core/agency.py:15-193
class WorkerAgent:
    def __init__(self, name, role_prompt, tools, workspace_dir=None, ...):
        self.runtime = AgentRuntime(...)
        self.runtime.bootstrapper.build_system_prompt = lambda: _prompt
        for tool in tools:
            self.runtime.register_tool(tool)
        self.scratchpad: Dict[str, Any] = {}

    async def execute_task(self, task_description, request):
        """Full ReAct loop, max 10 turns, with provider fallback."""
        messages = [system_prompt, {"role": "user", "content": f"TASK: {task_description}"}]
        for turn in range(10):
            response = await self.provider.chat_completion_resilient(
                messages, tools=openai_tools, ...
            )
            content, tool_calls = self.runtime._extract_provider_message(response)
            if not tool_calls:
                return content
            for tc in tool_calls:
                result = await self.runtime.tools[tc.name].execute(**tc.args)
                messages.append({"role": "tool", "content": result})
        return final_answer
```

#### SwarmManager — Cross-Agent Context Sharing

```python
# app/core/agency.py:196-561
class SwarmManager:
    def __init__(self, workspace_dir=None):
        self.shared_context: Dict[str, Any] = {}
        self._message_bus: Dict[str, list[Dict[str, Any]]] = {}

    def send_message(self, from_agent, to_agent, message):
        """Agent-to-agent messaging via inbox queue."""
        if to_agent not in self._message_bus:
            self._message_bus[to_agent] = []
        self._message_bus[to_agent].append({"from": from_agent, "message": message, ...})

    def broadcast(self, from_agent, message):
        """Broadcast to all registered agents."""
        for name in self.available_agents:
            if name != from_agent:
                self.send_message(from_agent, name, message)

    async def execute_case_study(self, request, tasks):
        """Execute multiple agents in parallel, then cross-check outputs."""
        workers = [...]
        coroutines = [w.execute_task(task, request) for w in workers]
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        # Cross-check: reviewer i reviews worker i+1
        # Compile Evidence Board → send to ReviewerQA → final report
```

### 4.5 Context Reference Resolver

The `ContextReferenceResolver` (in `app/core/context_references.py`) resolves inline references before the message reaches System 1 or System 2:

- `@file path/to/file.txt` — reads file contents inline
- `@folder path/to/folder` — lists directory contents
- `@url https://...` — fetches URL content
- `@git` — gets git status/log

```python
# app/core/orchestrator.py:2044-2057
resolver = get_context_resolver()
expanded_text, resolved_refs = resolver.resolve_references(request.text)
if resolved_refs:
    request.text = expanded_text
    source_kind = "context_expanded"
```

### 4.6 Metacognition Monitor

Every System 2 escalation is recorded by the metacognitive monitor (`app/core/metacognition.py`):

```python
# app/core/orchestrator.py:2101-2114
metacog = get_metacognitive_monitor()
metacog.record(
    query=request.text,
    category="system1_escalated",
    strategy="rapid",
    tools_used=[],
    success=True,
    confidence=0.5,
    duration_ms=0.0,
)
```

--

## 5. Layer 4 — Tool Execution (98 Tools)

### Architecture

```
                    ┌───────────────┐
                    │  ToolRouter   │
                    │  parse JSON → │
                    │  validate →   │
                    │  dispatch →   │
                    │  format       │
                    └───────┬───────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  Resilience   │   │    Policy     │   │   Sandbox     │
│  Layer        │   │   Engine      │   │   Manager     │
│               │   │               │   │               │
│ @with_retry   │   │ permission    │   │ restricted    │
│ @with_timeout │   │ check         │   │ subprocess    │
│ @with_fallback│   │ tier gates    │   │ execution     │
│ CircuitBreaker│   │ approval req  │   │ Docker wrap   │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        └───────────────────┼───────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  ToolOutput     │
                   │  Normalizer     │
                   └─────────────────┘
```

### BaseTool ABC

```python
# app/tools/base.py
@dataclass
class ToolParameter:
    name: str; type: str; description: str; required: bool = False; enum: List[str] = ...

@dataclass
class ToolSchema:
    name: str; description: str; parameters: List[ToolParameter] = ...

@dataclass
class ToolCapability:
    required_permissions: List[str] = ...
    risk_level: str = "low"       # low | medium | high | critical
    cost_tier: str = "low"        # low | medium | high
    confirmation_policy: str = "none"  # none | confirm | always_confirm
    readonly: bool = True

class BaseTool(ABC):
    group: str = "ungrouped"

    @abstractmethod
    def get_name(self) -> str: ...
    @abstractmethod
    def get_description(self) -> str: ...
    @abstractmethod
    def get_schema(self) -> ToolSchema: ...
    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]: ...
```

### Tool Categories

| Domain | Example Tools | Count |
|----|--------|----|
| File Operations | `AdvancedFileOperationTool`, `DeliverFileTool` | 4 |
| Git | `GitOperationTool` | 1 |
| Web | `WebOperationTool`, `WebFetchOperationTool`, `InternetIntelTool` | 3 |
| Knowledge | `KnowledgeGraphTool`, `MemoryTool`, `SessionSearchTool` | 4 |
| Security | `VirusTotalTool`, `TOTPGeneratorTool`, `HaveIBeenPwnedTool` | 4 |
| Finance | `FinanceOperationTool`, `StockQuoteTool`, `CryptoPriceTool`, `CryptoAlertTool` | 5 |
| Smart Home | `SmartHomeTool`, `SensorReadTool`, `CameraSnapshotTool` | 3 |
| Calendar | `GoogleCalendarTool`, `OutlookCalendarTool`, `CalendarTool` | 3 |
| Email | `MailTool`, `GmailTool`, `EmailDrafterTool` | 3 |
| Messaging | `PlatformMessagingTool` | 1 |
| Social | `TwitterTool`, `RedditTool`, `YouTubeTool` | 3 |
| Data | `DatabaseConnector`, `RESTAPIConnector`, `DatabaseQueryTool` | 4 |
| Document | `PDFReaderTool`, `DocxReaderTool`, `ExcelReaderTool`, `PDFGeneratorTool`, ... | 10 |
| Visualization | `ChartGeneratorTool`, `TableVisualizerTool` | 2 |
| System | `SystemStatsTool`, `DockerTool`, `DockerExecTool`, `ShellTool` | 5 |
| Sandbox | `SandboxExecTool`, `ExecTool` | 2 |
| AI/ML | `LocalMLTool`, `ImageGenerationTool`, `XAIImageUnderstandTool` | 3 |
| Voice | `Voicetool` | 1 |
| Productivity | `PomodoroTool`, `TodoListTool`, `MeetingNotesTool` | 5 |
| Academic | `ArxivSearchTool`, `SemanticScholarTool`, `WolframAlphaTool` | 3 |
| Health | `HealthTrackerTool`, `CommuteTool`, `AirQualityTool` | 3 |
| Other | `TranslationTool`, `MapsGeocodingTool`, `ShoppingTool`, `TripPlannerTool`, ... | 30+ |

### Resilience Layer (`app/tools/resilience.py`)

```python
# Decorator usage in any tool:
class MyTool(BaseTool):
    @with_retry(max_attempts=3, backoff_base=1.5)
    @with_timeout(seconds=30)
    async def execute(self, **kwargs):
        ...
```

#### Retry Strategy

```python
def with_retry(max_attempts=3, backoff_base=1.5, retry_on=(Exception,),
               skip_on=(KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
    """Exponential backoff: 1s, 1.5s, 2.25s for default config."""

    async def wrapper(*args, **kwargs):
        for attempt in range(1, max_attempts + 1):
            try:
                return await fn(*args, **kwargs)
            except skip_on:
                raise
            except retry_on as exc:
                if attempt < max_attempts:
                    delay = backoff_base ** (attempt - 1)
                    await asyncio.sleep(delay)
        raise last_exc
```

#### Circuit Breaker

```python
class ToolCircuitBreaker:
    """States: CLOSED → OPEN (5 failures) → HALF_OPEN (60s cooldown) → CLOSED"""
    def __init__(self, failure_threshold=5, cooldown_seconds=60.0):
        self._failure_count = 0
        self._state = "CLOSED"

    def allow_request(self) -> bool:
        return self.state in ("CLOSED", "HALF_OPEN")

    def record_failure(self):
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._state = "OPEN"
```

#### Self-Corrector Strategies

```python
_default_corrector = SelfCorrector()
_default_corrector.add_strategy("relax_params", _relax_parameters)
_default_corrector.add_strategy("simplify_query", _simplify_query)
_default_corrector.add_strategy("add_timeout", _add_timeout)
_default_corrector.add_strategy("switch_provider", _switch_provider)
```

### Tool Registration in Orchestrator

The `MessageOrchestrator.__init__` registers approximately 140+ tools. Each tool is conditionally registered based on available API keys:

```python
# Conditional tool registration pattern
if Config.NOTION_API_KEY:
    tools.append(NotionTool(api_key=Config.NOTION_API_KEY))

try:
    tools.append(GitHubTool())
except Exception:
    logger.warning("GitHubTool skipped")

# Skill plugin tools
sr = SkillRegistry()
plugin_tools = sr.load_plugin_tools()
if plugin_tools:
    tools.extend(plugin_tools)
```

### Sandboxed Execution

The `SandboxExecTool` runs shell commands inside a Docker container by default. Host execution requires `Config.ALLOW_HOST_SHELL_EXECUTION=True` **and** the caller passes `force_host=True`:

```python
# app/core/orchestrator.py:243
SandboxExecTool(workspace_dir=output_directory)
# — refuses host execution unless Config.ALLOW_HOST_SHELL_EXECUTION is True
```

--

## 6. Layer 5 — Voice Pipeline

### Full Pipeline

```
Mic → WakeWord → VAD → STT → LLM → TTS → SinkRegistry → Speaker(s)
        │          │      │            │         │
    openwakeword  RMS   pywhispercpp  Piper    local+WS
    ONNX model   numpy  ggml-tiny    ONNX     fan-out
    (no PyTorch) 300    75MB CPU     en_US    16kHz 16-bit
                 thrshld             lessac   80ms frames
```

### Audio Constants

```python
# app/voice/pipeline.py:36-43
_SAMPLE_RATE = 16_000              # 16 kHz
_CHANNELS = 1                       # Mono
_DTYPE = "int16"                    # 16-bit PCM
_BLOCKSIZE = 1280                   # 80ms frames at 16 kHz
_RMS_SPEECH_THRESHOLD = 300         # Energy VAD threshold
_SILENCE_FRAMES_TO_END = 15         # 15 × 80ms = 1.2s silence → end utterance
_SPECULATIVE_STT_ENABLED = True     # Start transcribing before utterance ends
_MAX_UTTERANCE_FRAMES = 300         # 300 × 80ms = 24s hard cap
```

### Pipeline State Machine

```
          ┌──────────┐
          │ WAITING  │ ← initial state, listening for wake word
          └────┬─────┘
               │ Wake word detected (score >= threshold)
               ▼
          ┌──────────┐
          │RECORDING │ ← collecting PCM frames
          └────┬─────┘
               │ Silence >= 1.2s OR frames >= 24s
               ▼
          ┌──────────┐
          │ PROCESS  │ → STT → orchestrator.handle()
          └──────────┘
               │
               ▼
          ┌──────────┐
          │ WAITING  │ ← back to listening
          └──────────┘
```

### Wake Word Detection

```python
# app/voice/pipeline.py:139-147
oww = OWWModel(
    wakeword_models=["hey_jarvis"],
    inference_framework="onnx",
)
threshold = Config.VOICE_WAKE_WORD_THRESHOLD  # default 0.5

# During recording loop:
pcm_f32 = pcm.astype(np.float32) / 32768.0
prediction = oww.predict(pcm_f32)
score = max(prediction.values()) if prediction else 0.0
if score >= threshold:
    # Wake word detected → start recording
    state = "recording"
```

### Speculative STT

```python
# app/voice/pipeline.py:234-242
if _SPECULATIVE_STT_ENABLED and len(utterance_frames) >= 6:  # ~480ms
    partial_audio = b"".join(utterance_frames)
    self._speculative_task = asyncio.ensure_future(
        self._speculative_transcribe(partial_audio)
    )
```

When utterance ends, if speculative result is ready and audio is < 30KB, use it directly (saves ~500ms latency).

### TTS — Streaming with Barge-In

```python
# app/voice/pipeline.py:479-545
async def _speak_streaming(self, text):
    emotion_params = detect_emotion(text)           # Sentiment → speed/pitch
    sentences = self._split_sentences(text)          # Sentence boundary split

    self._is_playing = True
    for sentence in sentences:
        if not self._is_playing:
            break  # Barge-in interrupted

        audio_path = await synthesize(sentence, voice=voice)
        await self._sink_registry.play(self._user_id, audio_path)

        if self._barge_in_event and self._barge_in_event.is_set():
            break  # User started speaking → stop playback
    self._is_playing = False
```

### Sink Registry — Fan-Out Pattern

```python
# app/voice/sink_registry.py:40-168
class SinkRegistry:
    def __init__(self):
        self._sinks: dict[str, list[VoiceSink]] = defaultdict(list)

    def register(self, user_id, sink):
        self._sinks[user_id].append(sink)

    async def play(self, user_id, audio_path):
        # Read audio bytes ONCE → fan-out to all sinks via gather
        sinks = self.sinks_for(user_id)
        await asyncio.gather(*(_safe_play(s) for s in sinks))
```

### Voice Config

```bash
# .env — Voice Pipeline
ENABLE_LOCAL_VOICE=true
VOICE_STT_MODEL=tiny
VOICE_WAKE_WORD_THRESHOLD=0.5
VOICE_MIC_DEVICE=0
VOICE_REPLY_WITH_AUDIO=false
VOICE_TTS_VOICES=user123:amy,user456:brian

WHISPER_CPP_MODEL=workspace/models/whisper/ggml-tiny.bin
WHISPER_CPP_LANGUAGE=en
WHISPER_CPP_THREADS=2

PIPER_VOICE_MODEL=app/voice/en_US-lessac-medium.onnx
PIPER_VOICE_NAME=autherRaven
```

### Voice Edge Cases

- **Barge-in**: If user speaks while TTS is playing, VAD detects RMS > 300 and sets `_is_playing = False`. The sentence loop breaks, and the new utterance is recorded.
- **Enrollment**: "register my voice as <name>" triggers speaker identification enrollment.
- **Speculative STT failure**: Falls through to full `_dispatch()` which transcribes the complete utterance.
- **Chime playback**: Confirmation chime (880Hz, 150ms) plays on wake word detection; error chime (440Hz) on transcription failure.
- **No sinks**: `SinkRegistry.play()` returns 0 silently.

--

## 7. Layer 6 — Memory & Knowledge

### Memory Tier Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MEMORY ARCHITECTURE                          │
├────────────┬──────────────────┬──────────────────┬───────────────┤
│    Tier    │    Backend       │     Content       │  Persistence │
├────────────┼──────────────────┼──────────────────┼───────────────┤
│ Working    │ Attention        │ Current context   │ Session       │
│            │ (in-memory)      │ conversation      │ (volatile)    │
├────────────┼──────────────────┼──────────────────┼───────────────┤
│ Episodic   │ SQLite FTS5      │ Conversations,    │ Days          │
│            │ (learning.db)    │ corrections       │               │
├────────────┼──────────────────┼──────────────────┼───────────────┤
│ Semantic   │ HelixDB +        │ Facts, preferences│ Weeks/Months  │
│            │ ChromaDB         │ knowledge graph   │               │
├────────────┼──────────────────┼──────────────────┼───────────────┤
│ Procedural │ Skill files +    │ Crystallized     │ Permanent     │
│            │ LearningDB       │ skills, workflows │               │
├────────────┼──────────────────┼──────────────────┼───────────────┤
│ Identity   │ SOUL.md +        │ Self-definition,  │ Permanent     │
│            │ MEMORY.md +      │ user knowledge    │               │
│            │ AGENTS.md        │                   │               │
└────────────┴──────────────────┴──────────────────┴───────────────┘
```

### SQLite — LearningDB (`app/core/learning_db.py`)

Unified SQLite store with FTS5 full-text search. Stores corrections, facts, patterns, feedback, and learning signals.

```
┌──────────────────────┐
│    LearningDB        │
│  workspace/memory/   │
│   learning.db        │
├──────────────────────┤
│ Items table:         │
│  - id (INTEGER PK)   │
│  - type (TEXT)       │
│  - content (TEXT)    │
│  - topic (TEXT)      │
│  - confidence (REAL) │
│  - metadata (TEXT)   │
│  - source (TEXT)     │
│  - created_at (ISO)  │
│  - updated_at (ISO)  │
│  - use_count (INT)   │
├──────────────────────┤
│ FTS5 virtual table   │
│ on content column    │
└──────────────────────┘
```

```python
# Learning store usage
store = get_learning_store()
correction_id = store.add(
    type_="correction",
    content="The capital of France is Paris, not London.",
    topic="geography",
    confidence=0.95,
    metadata={"wrong_segment": "London is the capital of France"},
    source="phase8",
)
# Search with FTS5
results = store.search("capital of France", limit=5, min_confidence=0.4)
```

### SQLite — RLHF (`app/core/rlhf.py`)

Preference store per provider/style:

```
┌──────────────────────┐
│    RLHF DB           │
│  workspace/memory/   │
│   rlhf.db            │
├──────────────────────┤
│ Preferences table:   │
│  - id (INTEGER PK)   │
│  - task_type (TEXT)  │
│  - provider_id (TEXT)│
│  - preferred (BOOL)  │
│  - response_style    │
│  - created_at (ISO)  │
└──────────────────────┘
```

```python
# RLHF usage
from app.core.rlhf import record_feedback
record_feedback(
    task_type="coding",
    provider_id="gpt-4o",
    preferred=False,  # User corrected the output
    response_style="concise",
)
```

### HelixDB — Knowledge Graph

HTTP-based knowledge graph service on `localhost:6969`:

- RDF triples (subject → predicate → object)
- Semantic memory
- Entity extraction

```python
# KnowledgeManager usage
from app.core.knowledge_manager import get_knowledge_manager
mgr = get_knowledge_manager()
mgr.record_fact("Swadhin", "works_at", "OpenClaw", source="conversation")

# Query facts about an entity
facts = mgr.query("Swadhin")
# Returns: [Fact(subject="Swadhin", predicate="works_at", object="OpenClaw"), ...]

# Find path between entities
path = mgr.find_path("Swadhin", "Python")
# Returns: ["Swadhin", "programs_in", "Python"]
```

### ChromaDB — Vector Embeddings

- Model: `all-MiniLM-L6-v2` (384-dimensional embeddings)
- Used for semantic search across memory
- Path: `workspace/memory/vector/`

### Agent Memory — File-backed

Each agent stores memory in `workspace/agents/{name}/`:

| File | Purpose | Cap |
|---|-----|---|
| `soul.md` | Immutable core purpose | N/A |
| `goals.md` | Current objectives | 50KB |
| `memory.md` | Episodic memory entries | 50KB |
| `journal.md` | Timestamped reflections | 40KB |
| `skill.md` | Learned capabilities | 30KB |

```python
# BaseAgent memory management
class BaseAgent(ABC):
    def save_to_memory(self, category, content):
        """Appends to memory.md, capped at 50KB."""
        self._ensure_memory_files()
        # ... append to file ...
        if p.stat().st_size > 50_000:
            text = p.read_text(encoding="utf-8")
            p.write_text(text[-40_000:], encoding="utf-8")
        # Dual-write to HelixDB
        self._helix_memory_save(category, content)
```

### Memory Manager (`app/core/memory_manager.py`)

Extracts facts, preferences, and tasks from conversations:

```python
# Conceptual usage
from app.core.memory_manager import MemoryManager
mm = MemoryManager()
mm.extract_from_conversation("I love Italian food", user_id="swadhin")
# → records fact: user="swadhin" prefers "Italian" cuisine
# confidence scoring + TTL governance
```

### Memory Config

```bash
# .env — Memory & Knowledge
MEMORY_ROOT=workspace/memory
VECTOR_DB_PATH=${MEMORY_ROOT}/vector
GRAPH_DB_PATH=${MEMORY_ROOT}/graph/raven.sqlite
STATE_DB_PATH=${MEMORY_ROOT}/state/ledger.sqlite
MEMORY_BACKEND=helix
KG_BACKEND=helix
MEMORY_EMBEDDING_MODEL=all-MiniLM-L6-v2
```

--

## 8. Layer 7 — Autonomy & Scheduling

### AmbientLoop (`app/core/ambient_loop.py`)

The `AmbientLoop` is RAVEN's always-on background heartbeat. It runs 27 interval-based subsystems on a 60-second tick cycle, transforming RAVEN from a request-response chatbot into an ambient intelligence system.

#### Interval Schedule

| Interval | Subsystem | Description |
|-----|------|-------|
| 30s | Heartbeat | Dashboard + inproc bus broadcast |
| 60s | CronEngine tick | Dynamic cron job evaluation |
| 2min | Proactive intelligence | Context-aware insight generation |
| 5min | Health check | Dependency service monitoring |
| 5min | Knowledge sync | LifeContext → HelixDB sync |
| 5min | RL replay | Experience buffer replay training |
| 5min | Sentinel digest flush | Buffered event dispatch |
| 5min | Working memory decay | Relevance decay application |
| 5min | Perception scan | Environmental perception |
| 5min | Degradation monitoring | Capability degradation checks |
| 5min | Environmental sensors | Sensor data polling |
| 5min | Notification retry | Pending notification delivery |
| 5min | A2A server health | Agent-to-Agent server checks |
| 10min | Memory auto-update | MEMORY.md from LifeContext |
| 10min | Agent heartbeats | Background agent work |
| 10min | Resilience check | Circuit breaker health |
| 10min | Companion discovery | A2A companion registration |
| 10min | Multimodal processing | Image/audio batch processing |
| 10min | Event digest | Event stream aggregation |
| 30min | Presence refresh | Scene/location snapshot |
| 30min | Goal advancement | Long-horizon goal progress |
| 30min | Regression detection | Behavioral regression checks |
| 30min | Curiosity exploration | Curiosity-driven queries |
| 1h | Self-improvement | Correction verification + recommendations |
| 1h | Predictive scheduling | Schedule suggestion generation |
| 1h | Nudge engine | Proactive reminder evaluation |
| 1h | Learning summary | Learning tracker heartbeat |
| 1h | Self-evolution | Capability self-assessment |
| 1h | Evaluation harness | Benchmark suite execution |
| 2h | Forecast update | Predictive model refresh |
| 2h | Retrospective analysis | Deep interaction pattern analysis |
| 6h | Training data export | Session → training data |
| 24h | Persona daily reset | Energy/confidence restoration |

#### Ambient Loop Tick Architecture

```python
# app/core/ambient_loop.py:119-134
async def run(self):
    self._running = True
    while self._running:
        await self._tick()
        self._tick_count += 1
        await asyncio.sleep(60)  # 1 minute between ticks

async def _tick(self):
    now = time.time()
    # Check each subsystem against its interval:
    if now - self._last_digest_flush >= _DIGEST_INTERVAL: ...
    if now - self._last_self_improvement >= _SELF_IMPROVEMENT_INTERVAL: ...
    if now - self._last_health_check >= _HEALTH_CHECK_INTERVAL: ...
    # ... 27 total checks ...
    await self._broadcast_heartbeat()
```

#### Workflow Engine Tick

```python
# app/core/ambient_loop.py:390-456
async def _tick_workflows(self):
    engine = WorkflowEngine()
    runs = engine.list_runs()
    for run in runs:
        if run.get("status") == "running":
            wf = engine.load_workflow(run["workflow_id"])
            # Find next pending step, check dependencies
            for step in wf.steps:
                if step.status == "pending":
                    deps_met = all(
                        dep in [s.step_id for s in wf.steps if s.status == "done"]
                        for dep in step.depends_on
                    )
                    if deps_met and step.condition:
                        if engine.evaluate_condition(step.condition, run["context"]):
                            engine.advance_step(run_id, step.step_id, "in_progress")
                            break
            # Chain to next workflow if all steps done
            if all_steps_done:
                next_wf = engine.check_chain(run)
                if next_wf:
                    engine.start_run(next_wf, context=run["context"])
```

### APScheduler (`app/core/scheduler.py`)

SQLite-backed persistent job store for reminders, alarms, and recurring routines:

```python
from app.core.task_scheduler import get_scheduler

sched = get_scheduler()
sched.register("prune_stores", interval_turns=100, callback=prune_func)
sched.register("crystallize_skills", interval_turns=200, callback=crystallize_func)
sched.register("consolidate_knowledge", interval_turns=300, callback=consolidate_func)
```

### AutonomousActionEngine

Three risk levels for autonomous actions:

| Risk Level | Examples | Approval Required |
|------|-----|----------|
| Low | Notify, remind | Never |
| Medium | Execute workflow, adjust settings | User configurable |
| High | Financial transactions, destructive operations | Always |

```python
# Conceptual
from app.core.autonomous_engine import AutonomousActionEngine, Event
engine = AutonomousActionEngine(botsignal)
event = Event(event_type="sensor_temperature", source="mqtt",
              data={"temp": 38.5}, urgency=0.7)
await engine.process_event(event)
# → Evaluates rules → may trigger "turn on AC" action
```

--

## 9. Layer 8 — Skills & Self-Improvement

### Skill Architecture

```
Skill Discovery (SKILL.md + module.yaml manifests)
    │
    ▼
SkillRegistry.discover()
    │
    ▼
Health Check (parse, identity, capabilities, version)
    │
    ▼
SkillCrystallizer (trace → generalize → crystallize → register)
    │
    ▼
SkillInvoker (match query → select → invoke → observe)
    │
    ▼
LearningDB (corrections, facts, patterns, feedback)
```

### SkillRegistry (`app/core/skill_registry.py`)

Discovers skill/plugin/integration manifests from the repository tree:

```python
_DEFAULT_ROOTS = ("skills", "plugins", "agent_reach/skill")

# Manifest discovery priority:
# 1. module.yaml (highest)
# 2. module.yml
# 3. manifest.json
# 4. SKILL.md frontmatter (lowest)
```

Each record includes a full health report:

```python
{
    "module_id": "skill.file_organizer",
    "display_name": "File Organizer",
    "version": "1.0.0",
    "health_state": "healthy",  # healthy | degraded | unhealthy
    "capabilities": ["file_management", "organization"],
    "trust_level": "workspace",  # workspace | community | external
    "enabled_by_default": True,
    "entrypoint": "plugin.py:get_tools",
    "source_path": "skills/file_organizer",
}
```

### Skill Matching — Token Overlap

```python
# app/core/skill_registry.py:645-696
def match_skills(self, query, min_confidence=0.0):
    query_tokens = query.lower().split()
    for record in self.discover():
        if record["health_state"] != "healthy":
            continue
        haystack = " ".join([record["display_name"], record["description"],
                             record.get("body", "")]).lower()
        matched = sum(1 for tok in query_tokens if tok in haystack)
        confidence = matched / len(query_tokens)
        if confidence >= min_confidence:
            record["match_confidence"] = confidence
            results.append(record)
    return sorted(results, key=lambda r: -r["match_confidence"])
```

### SkillCrystallizer

```python
# Conceptual
from app.core.skill_crystallizer import SkillCrystallizer
crystal = SkillCrystallizer()
names = crystal.crystallize_all(min_confidence=0.6)
# → trace analysis → generalization → crystallization → registration
```

### SelfImprovementLoop

```python
from app.core.self_improvement import get_self_improvement_loop

loop = get_self_improvement_loop()
# Every 20 System 2 turns:
results = await loop.run_batch(limit=10)  # Verify corrections applied correctly
passed = sum(1 for r in results if r.passed)
```

### CorrectionVerifier

```python
# app/core/orchestrator.py:2554-2568
loop = get_self_improvement_loop()
if self._verify_counter % 20 == 0:
    results = await loop.run_batch(limit=10)
    passed = sum(1 for r in results if r.passed)
    logger.info("Batch verification: %d/%d passed", passed, len(results))
```

### RLHF — Preference Learning

```python
from app.core.rlhf import (
    PreferenceStore,    # SQLite-backed preference storage
    RlhfRouter,         # Routes feedback to correct crystallizer
    RlhfCrystallizer,   # Converts preferences into prompt adjustments
)
```

--

## 10. Event System

### EventEnvelope (`app/core/events.py`)

All internal communication uses the `EventEnvelope` class — a signed, schema-versioned, content-addressed message format.

```python
@dataclass(slots=True)
class Header:
    schema: str = "1.0"
    kind: str                     # CHAT | TOOL_CALL | TOOL_RESULT | ALERT | METRIC | ...
    timestamp: str                # ISO-8601 UTC with millisecond precision
    correlation_id: str           # Stable per user-visible request chain
    source: str                   # Sidecar that produced the event
    causation_id: str             # Reply-to for command/response correlation
    idempotency_key: str          # For dedup on retry

@dataclass(slots=True)
class Envelope:
    header: Header
    body: dict[str, Any]          # ≤ 8KB; larger → content-addressed ref
    signature: str                # ed25519 hex signature
    signer_pubkey: str            # Signer's public key, hex-encoded
```

### Signing & Verification

```python
env = make_envelope(
    kind=EventKind.HEALTH,
    source="ambient_loop",
    body={"tick": 42, "uptime_seconds": 3600},
)
env.sign(signing_key)       # ed25519 — cryptographic package loaded lazily

# Receiver
if env.verify(strict=True):  # False if unsigned or invalid
    process(env)
```

### TrustStore

```python
class TrustStore:
    def add(self, signer: TrustedSigner): ...
    def is_trusted(self, env: Envelope) -> bool: ...
```

### InProc Bus (`app/core/inproc_bus.py`)

Publisher-subscriber pattern for internal event dispatch:

```python
from app.core.inproc_bus import get_inproc_bus
from app.core.events import make_envelope, EventKind

env = make_envelope(kind=EventKind.HEALTH, source="system", body={...})
await get_inproc_bus().publish("ambient.heartbeat", env)
```

--

## 11. Security Architecture

### Security Layers

```
User Input → SecurityGuard → DM Pairing → Rate Limiter → Policy Engine → Tool Execution
    │             │              │             │              │              │
    │        Jailbreak      Pairing        Sliding       Permission     Sandbox
    │        detection     enforcement      window        checks         Docker
    │        (regex)      (code-based)    (in-memory)   (tier 1/2/3)    exec
    ▼
Block or Allow
```

### SecurityGuard (`app/core/security.py`)

#### Prompt Injection Detection

```python
class SecurityGuard:
    JAILBREAK_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        r"(?i)you\s+are\s+now\s+(?:a|an|the)",
        r"(?i)forget\s+(all\s+)?(?:your|the)\s+(?:rules|instructions|guidelines)",
        r"(?i)system\s*prompt\s*(?:override|injection|override)",
        r"(?i)bypass\s+(?:all\s+)?(?:restrictions|safety|rules|guidelines)",
        r"(?i)DAN\s+mode",
        r"(?i)developer\s+mode\s+(?:enabled|activated)",
        # 13 total patterns
    ]

    DANGEROUS_COMMANDS = [
        r"\brm\s+-rf\s+/\b",
        r"\brm\s+-rf\s+\*\b",
        r"\bmkfs\b",
        r"\bdd\s+if=.*of=/dev/sda\b",
        r">\s*/dev/sda\b",
        r"\b:\(\)\{\s*:\s*\|\s*:&\s*\};\s*:\b",  # Fork bomb
    ]

    def analyze_prompt(self, text) -> Tuple[bool, str]:
        for pattern in self._compiled_jailbreaks:
            if pattern.search(text):
                return False, "Prompt injection detected"
        return True, "Safe"
```

#### Tool Approval — Three Tiers

```python
def requires_approval(self, tool_name, args) -> Tuple[bool, str, str]:
    # Autonomous mode: no approval except destructive commands
    # Balanced mode (default): high-risk tools need approval
    # Strict mode: all tools need approval

    high_risk_tools = {"system_execute", "git_ops", "file_operations",
                       "agency_delegation", "virustotal_scanner",
                       "sql_query", "bash_execute"}

    if approval_level.startswith("Strict"):
        return True, "High", "Strict policy requires manual auth"

    if tool_name in high_risk_tools:
        # Exempt safe reads
        if tool_name == "file_operations" and args.get("operation") in ("read", "info", "list"):
            return False, "Low", "Safe read operation"
        return True, "High", f"{tool_name} is high risk"
```

### Secret Vault

```python
# Fernet AES-128-CBC encrypted secrets, RAven_MASTER_KEY env var
from app.core.secret_vault import SecretVault
vault = SecretVault()
api_key = vault.get("openai")
# Falls back to os.environ["OPENAI_API_KEY"] if vault not configured
```

### Credential Rotation

```python
from app.core.security import resolve_credential, rotate_credential, is_credential_stale

key = resolve_credential("openai", env_var="OPENAI_API_KEY")
# ... later, when key is rotated externally ...
rotate_credential("openai", env_var="OPENAI_API_KEY")
is_credential_stale("openai")  # → True until next resolve_credential call
```

### Rate Limiter

Sliding window per-user:
```python
# app/core/orchestrator.py:1994-1996
rate_limiter = get_rate_limiter()
allowed, reason = rate_limiter.is_allowed(f"{platform}:{user_id}")
```

--

## 12. Configuration System

### Config Class (`app/settings/config.py`)

299-line `Config` class with environment variable mappings. Key groups:

```python
class Config:
    # LLM Providers
    LLM_PROVIDER: str = "auto"
    LLM_MODEL: str = ""
    OPENAI_API_KEY: str | None = ...
    ANTHROPIC_API_KEY: str | None = ...
    GEMINI_API_KEY: str | None = ...
    # ... 15+ provider API keys

    # Platform Connectors
    TELEGRAM_BOT_TOKEN: str | None = ...
    DISCORD_BOT_TOKEN: str | None = ...
    SLACK_BOT_TOKEN: str | None = ...
    # ... 12+ platform configs

    # Voice Pipeline (see §6)
    ENABLE_LOCAL_VOICE: bool = False
    WHISPER_CPP_MODEL: str = "workspace/models/whisper/ggml-tiny.bin"
    PIPER_VOICE_MODEL: str = "app/voice/en_US-lessac-medium.onnx"

    # Memory (see §7)
    MEMORY_ROOT: str = "workspace/memory"
    MEMORY_BACKEND: str = "helix"
    KG_BACKEND: str = "helix"

    # Routing
    LOCAL_LIGHT_MODEL: str = "gemma:7b"    # System 1
    CLOUD_HEAVY_MODEL: str = "gpt-4o"       # System 2

    # Scheduling
    MODULES_ROOT: str = ""
    PRIVACY_V2_ENABLED: bool = False
    CITATIONS_IN_RESULTS: bool = False
    AUTO_ROLLBACK: bool = True

    # Safety
    ALLOW_HOST_SHELL_EXECUTION: bool = False
    ADMIN_USER_IDS: list[str] = []
```

### .env.example

```bash
# LLM Providers
LLM_PROVIDER=auto
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
OPENROUTER_API_KEY=sk-or-...
XAI_API_KEY=...

# Platform Connectors
TELEGRAM_BOT_TOKEN=...
DISCORD_BOT_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Local Models
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
LOCAL_LIGHT_MODEL=gemma:7b
CLOUD_HEAVY_MODEL=gpt-4o

# Voice
ENABLE_LOCAL_VOICE=true
WHISPER_CPP_MODEL=workspace/models/whisper/ggml-tiny.bin
PIPER_VOICE_MODEL=app/voice/en_US-lessac-medium.onnx

# Memory
MEMORY_ROOT=workspace/memory
MEMORY_BACKEND=helix

# Security
ADMIN_USER_IDS=user_id_1,user_id_2
ALLOW_HOST_SHELL_EXECUTION=false
```

--

## 13. Cross-Layer Interaction Patterns

### Pattern 1: User Message → Response (Full Path)

```
Platform Connector (e.g., Telegram)
  │  receives /research latest AI breakthroughs
  │
  ▼
IncomingRequest(platform="telegram", user_id="123", text="...")
  │
  ▼
MessageOrchestrator.handle()
  │  Phase 0: identity resolution
  │  Phase 0.5: DM pairing check → allowed
  │  Phase 1: context references → none found
  │  Phase 2: direct tools → no match
  │  Phase 3: System 1 → MiniEngine escalates (needs research)
  │
  ▼
AgentRuntime.execute_turn()
  │  ReAct Turn 1: LLM → tool call web_search("AI breakthroughs 2026")
  │  Resilience: @with_retry(3) on web search
  │  Result: [list of articles]
  │  ReAct Turn 2: LLM → tool call web_fetch("https://...")
  │  Result: [article content]
  │  ReAct Turn 3: LLM synthesizes → final response
  │
  ▼
BotSignal.send(target=telegram:chat_456, payload="Here are the latest...")
  │  Outbox.enqueue → Outbox.drain_once
  │
  ▼
Telegram Sender (registered in BotSignal)
  │  PTB Application.send_message(chat_id=456, text=...)
  │
  ▼
User sees response
```

### Pattern 2: Ambient Loop → Proactive Alert

```
AmbientLoop tick (every 60s)
  │  _tick_proactive_intelligence() (every 2min)
  │
  ▼
ProactiveIntelligence.analyze(context)
  │  Evaluates user's context, calendar, overdue tasks
  │  Returns insights with urgency scores
  │
  ▼
Decision: emit=True (urgency=0.7, confidence=0.8)
  │
  ▼
BotSignal.send(channel="proactive", body="Reminder: ...")
  │  Outbox routes to registered platform connector
  │
  ▼
User receives proactive reminder
```

### Pattern 3: Voice → Full Pipeline

```
VoicePipeline._loop_blocking()
  │  Mic → openwakeword → "Hey Jarvis" detected (score=0.85)
  │  Play confirm chime → Record 3.2s utterance
  │  Silence 1.2s → End utterance
  │
  ▼
VoicePipeline._dispatch(audio_bytes)
  │  Speaker ID → "swadhin" (confidence=0.92)
  │  Write WAV → transcribe_audio() → pywhispercpp → "what's the weather"
  │
  ▼
IncomingRequest(platform="voice", user_id="swadhin", text="what's the weather")
  │
  ▼
MessageOrchestrator.handle()
  │  → AgentRuntime → tool call WeatherTool.execute()
  │  → Response: "It's 22°C and sunny in London."
  │
  ▼
BotSignal.send(platform="voice", ...)
  │
  ▼
VoicePipeline._voice_sender()
  │  _speak_streaming("It's 22°C and sunny in London.")
  │  → detect_emotion → neutral
  │  → synthesize() → Piper-TTS ONNX → WAV
  │  → SinkRegistry.play() → local speaker + browser WS
  │
  ▼
User hears response
```

### Pattern 4: Swarm Parallel Execution

```
MessageOrchestrator receives complex analysis request
  │
  ▼
Supervisor.select_agent("Analyze TSLA stock and write a report")
  │  → matches keywords for FinanceAgent + DeveloperAgent
  │
  ▼
SwarmManager.execute_case_study(tasks=[
    {"agent_name": "FinanceAnalyst", "task": "Pull TSLA market data"},
    {"agent_name": "Researcher", "task": "Find recent TSLA news"},
])
  │
  ├── WorkerAgent("FinanceAnalyst").execute_task()
  │     → ReAct loop with FinanceOperationTool
  │     → Returns market analysis
  │
  ├── WorkerAgent("Researcher").execute_task()
  │     → ReAct loop with WebSearchTool
  │     → Returns news summary
  │
  ▼
asyncio.gather(*coroutines) — BOTH RUN IN PARALLEL
  │
  ▼
Cross-check: ReviewerQA agent synthesizes both outputs
  │
  ▼
BotSignal.send(platform="telegram", payload="TSLA Analysis: ...")
```

### Pattern 5: Self-Correction Cycle

```
User: "The capital of France is London"
  │
  ▼
System 2: AgentRuntime responds with (incorrect) answer
  │
  ▼
Phase 6d: Fact-check gate
  │  engine.check_response(response, query)
  │  → Finds contradiction in KG: France.capital != London
  │
  ▼
Correction sent: "Hold on — I need to correct myself..."
  │
  ▼
Phase 8b: Learned reflector
  │  reflector.reflect(user_message, response)
  │  → ReflectionResult(is_correction=True, topic="geography",
  │     corrected_claim="The capital of France is Paris")
  │
  ▼
LearningDB: store.add(type_="correction", ...)
  │  → FTS5 searchable for future fact-checking
  │
  ▼
SelfImprovement: loop.on_correction_stored(correction_id)
  │  → CorrectionVerifier will later confirm it was applied
  │
  ▼
RLHF: record_feedback(preferred=False, task_type="geography")
  │  → Preference store updated for provider selection
```

--

## 14. Performance Characteristics & Failure Modes

### Timing Budgets

| Component | Target | Hard Limit | Degradation |
|------|----|------|-------|
| System 1 (MiniEngine) | < 500ms | < 2s | Escalate to System 2 |
| System 2 (AgentRuntime) | < 10s | 15 turns × 30s = 450s | Tool timeout per call |
| Voice STT | < 1s real-time | 24s utterance cap | Vosk fallback |
| Voice TTS | < 500ms/sentence | Streaming starts immediately | WAV cache miss |
| Ambient Loop tick | < 5s | 60s interval | Skips to next tick |
| Tool execution | < 5s | 30s (configurable) | Circuit breaker OPEN |
| API call (LLM) | < 3s | 30s | Provider fallback chain |

### Failure Modes & Mitigations

| Failure | Symptom | Mitigation |
|-----|-----|------|
| LLM provider down | `chat_completion` fails | `AutoModelRouter` fallback chain across all providers |
| Tool timeout | Tool hangs > 30s | `@with_timeout` raises `TimeoutError`; retry with reduced params |
| Network partition | Web requests fail | `@with_retry(3, exponential)`; circuit breaker after 5 failures |
| API key invalid | 401 errors | `CredentialsResolver` rotation detection; admin alert |
| Voice mic fails | No audio input | `sounddevice` error → log + continue; no crash |
| STT model missing | `pywhispercpp` import error | Vosk fallback (if installed); else log error |
| Memory DB corrupt | SQLite `OperationalError` | Auto-VACUUM on learning store; backup recovery |
| HelixDB down | KG queries fail | JSONL fallback; knowledge sync retries on next tick |
| OS resource exhausted | `OSError: [Errno 24] Too many open files` | Each connector manages its own FD pool; `ResourceWarning` logging |
| Process restart | In-flight messages lost | Outbox persists to SQLite; idempotency keys prevent duplicates |
| Long ReAct loop | > 15 turns → truncated | Returns partial response; user can continue the conversation |
| Rate limit hit | 429 from provider | Backoff + fallback to different provider/model |
| Ambient tick crash | One subsystem fails | Each tick is wrapped in `try/except`; next tick continues |

### Resource Usage

| Resource | Baseline | Peak |
|-----|-----|---|
| RAM (idle) | ~150 MB | ~500 MB (voice + LLM) |
| RAM (voice STT) | +75 MB (ggml-tiny) | +300 MB (ggml-small) |
| RAM (ChromaDB) | +100 MB (384-dim vectors) | +500 MB |
| CPU (idle) | < 1% | 10-20% (STT inference) |
| CPU (voice) | 2 threads (whisper.cpp) | 4 threads |
| Disk (SQLite) | 10-50 MB | 500 MB (long-running) |
| Disk (models) | 75 MB (whisper) + 50 MB (Piper) | 200 MB |
| Network | Minimal | Depends on LLM usage |
| Open FDs | ~50 | ~200 (all connectors + DB) |

### Concurrency Model

```
┌──────────────────────────────────────────────────┐
│                  asyncio Event Loop               │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Telegram │  │ Discord  │  │  Voice   │  ...   │
│  │ Connector│  │ Connector│  │ Pipeline │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │             │              │
│       └──────────────┼─────────────┘              │
│                      ▼                            │
│           ┌──────────────────┐                    │
│           │  Orchestrator    │                    │
│           │  (single-thread) │                    │
│           └──────────────────┘                    │
│                      │                            │
│         ┌────────────┴────────────┐               │
│         ▼                        ▼                │
│   ┌──────────┐           ┌──────────┐             │
│   │ System 1 │           │ System 2 │             │
│   │ (instant)│           │ (ReAct)  │             │
│   └──────────┘           └──────────┘             │
│                                                   │
│  ┌──────────────────────────────────────────┐      │
│  │  ThreadPoolExecutor (for blocking calls)  │      │
│  │  - VoicePipeline._loop_blocking()         │      │
│  │  - sounddevice audio callback (Numpy)    │      │
│  │  - osascript (iMessage)                   │      │
│  │  - signal-cli subprocess                  │      │
│  └──────────────────────────────────────────┘      │
└──────────────────────────────────────────────────┘
```

### Thread Safety Notes

- `BotSignal._send_nonce` uses `threading.Lock()` because it can be called from both async context and thread executor (voice pipeline).
- `SinkRegistry` uses per-user `asyncio.Lock()` for registry mutations; reads use existing list reference.
- `AgentRuntime` is **not thread-safe** — runs entirely on the event loop.
- `LearningDB` uses SQLite with WAL mode (concurrent reads, serialized writes).
- `AmbientLoop` runs on the event loop but calls `asyncio.run_coroutine_threadsafe()` for dashboard broadcasts.

--

## Appendix A: Key Files Reference

| File | Purpose | Lines |
|---|-----|----|
| `main.py` | Application entry point | ~200 |
| `app/core/orchestrator.py` | MessageOrchestrator — 8-phase pipeline | 2606 |
| `app/core/runtime.py` | AgentRuntime — System 2 ReAct loop | ~3064 |
| `app/core/botsignal.py` | BotSignal — unified output API | 272 |
| `app/core/supervisor.py` | Supervisor — 15-agent keyword router | 291 |
| `app/core/agency.py` | SwarmManager — multi-agent orchestrator | 561 |
| `app/core/ambient_loop.py` | AmbientLoop — 27-interval heartbeat | ~1200 |
| `app/core/events.py` | EventEnvelope — signed, versioned event format | 285 |
| `app/core/security.py` | SecurityGuard — injection detection + RBAC | 528 |
| `app/settings/config.py` | Config — 299 env var mappings | 299 |
| `app/voice/pipeline.py` | VoicePipeline — full voice pipeline | 617 |
| `app/voice/sink_registry.py` | SinkRegistry — TTS fan-out dispatcher | 212 |
| `app/tools/base.py` | BaseTool ABC — tool contract | 53 |
| `app/tools/resilience.py` | ResilienceLayer — retry/timeout/circuit breaker | 325 |
| `app/agents/base.py` | BaseAgent ABC — agent identity + memory | 345 |
| `app/core/skill_registry.py` | SkillRegistry — SKILL.md + module.yaml discovery | 719 |
| `.env.example` | Template for all environment variables | — |
