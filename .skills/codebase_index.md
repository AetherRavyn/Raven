# SARAS Intelligence OS — Codebase Index

> Auto-generated system map for AI comprehension. Updated after Phase 1–7 transformation + device automation.

---

## Entry Points

| File | Purpose |
|------|---------|
| `main.py` | Main entry — starts all platform bots, scheduler, proactive routines, and ambient loop |
| `app/core/orchestrator.py` | Central message handler — routes to System1/System2, manages tools, agents, sessions |
| `app/core/runtime.py` | ReAct agent runtime — tool calling loop (max 15 turns), streaming support |

---

## Core Intelligence (`app/core/`)

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| `orchestrator.py` | Central brain — all messages flow through `MessageOrchestrator.handle()` | `MessageOrchestrator` |
| `runtime.py` | ReAct loop with 50+ tools, streaming, multi-modal | `AgentRuntime`, `ToolTrace` |
| `ambient_loop.py` | **Always-on background heartbeat** — sentinel, self-improvement, workflows, health | `AmbientLoop`, `get_ambient_loop()` |
| `autonomy_engine.py` | Long-horizon goal execution with state machine + retry | `AutonomyEngine`, `GoalState` |
| `workflow_engine.py` | Durable multi-step workflow definitions and runs | `WorkflowEngine`, `WorkflowStep` |
| `self_improvement.py` | Feedback tracking, routing recommendations, skill discovery | `InteractionFeedback`, `get_feedback_tracker()` |
| `persona.py` | Dynamic personality — mood/trust/humor affect response style | `PersonaEngine`, `get_persona_engine()` |
| `output_router.py` | Smart output routing by priority (CRITICAL→voice, LOW→inbox) | `OutputRouter`, `Priority` |
| `health.py` | Dependency health monitor (Redis, Ollama, HA, SMTP, GCal) | `HealthMonitor`, `get_health_monitor()` |
| `sentinel_bridge.py` | HomeSentinel camera/sensor → SARAS event bridge via Redis | `SentinelBridge`, `SentinelEvent` |
| `user_identity.py` | Cross-platform user identity resolution (SQLite) | `UserIdentityStore` |
| `session.py` | JSONL-backed conversation session persistence | `SessionManager` |
| `memory.py` | ChromaDB/pgvector semantic memory | `MemoryStore` |
| `memory_manager.py` | High-level memory operations (store, recall, search) | `MemoryManager` |
| `model_router.py` | System1/System2 routing (local vs cloud LLM) | `ModelRouter` |
| `agency.py` | Multi-agent swarm orchestration | `SwarmManager` |
| `bootstrapper.py` | Agent persona + system prompt construction | `AgentBootstrapper` |
| `scheduler.py` | APScheduler + SQLite persistent job scheduling | `PersistentScheduler` |
| `proactive_bootstrap.py` | Registers calendar watcher + sentinel bridge at startup | `register_proactive_routines()` |
| `proactive.py` | Follow-up scheduling | `schedule_follow_up()` |
| `policy.py` | Security policy engine + RBAC | `PolicyEngine` |
| `security.py` | Human-in-the-loop approval, audit logging | `SecurityGate` |
| `user_profile.py` | User preference storage | `UserProfileStore` |
| `forecast.py` | Hybrid statistical + LLM prediction engine (trend, anomaly, regression) | `ForecastEngine`, `SimpleTimeSeries`, `MetricsCollector` |
| `skill_registry.py` | YAML/JSON/MD skill manifest discovery + loading | `SkillRegistry` |

---

## Tools (`app/tools/`)

| Module | Tool Name | Group |
|--------|-----------|-------|
| `workflowtool.py` | `workflow_ops` (WorkflowTool) | automation |
| `mail.py` | `send_email` / `read_inbox` / `search_email` | communication |
| `resilience.py` | (decorators: `@with_retry`, `@with_timeout`, `@with_fallback`) | infrastructure |
| `weathertool.py` | `get_weather` | information |
| `websearch.py` | `web_search` | information |
| `webfetch.py` | `web_fetch` | information |
| `githubtool.py` | `github_ops` | developer |
| `codetool.py` | `code_exec` | developer |
| `dockertool.py` | `docker_ops` | developer |
| `filetool.py` | `file_ops` | system |
| `systemstatstool.py` | `system_stats` | system |
| `smarthometool.py` | `smart_home` | iot |
| `googlecalender.py` | `google_calendar` | productivity |
| `todolisttool.py` | `todo_list` | productivity |
| `pomodorotool.py` | `pomodoro` | productivity |
| `cryptopricetool.py` | `crypto_price` | finance |
| `financetools.py` | `stock_quote` / `crypto_alert` | finance |
| `rssreadertool.py` | `rss_reader` | information |
| `virustool.py` | `virustotal` | security |
| `wolframtool.py` | `wolfram_alpha` | information |
| `xaiimagetool.py` | `xai_image` | multimodal |
| `browsertool.py` | `browser_ops` (22 operations) | automation |
| `mobiletool.py` | `mobile_device` (24 operations) | automation |
| `desktoptool.py` | `desktop_control` (16 operations) | automation |
| `screenreadertool.py` | `screen_reader` (8 operations) | automation |
| `computeruse.py` | `computeruse` (5 operations) | automation |

---

## Voice (`app/voice/`)

| Module | Purpose |
|--------|---------|
| `pipeline.py` | Always-on voice loop: wake word → STT → LLM → streaming TTS, speaker ID, chimes |
| `speaker_id.py` | Voice biometrics — enroll/identify speakers via embeddings |
| `tts.py` | Edge-TTS synthesis wrapper |
| `stt.py` | Whisper-based speech-to-text |

---

## Web (`app/web/`)

| Module | Purpose |
|--------|---------|
| `server.py` | FastAPI dashboard server — 9 REST endpoints + WebSocket events |
| `web/index.html` | OpenClaw-grade Command Center: 7-panel dashboard (Chat, Dashboard, Agents, Goals, Inspection, Health, Settings) |

### API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/system/status` | GET | CPU, memory, disk, uptime, tools, agents |
| `/api/health` | GET | Dependency health (Redis, Ollama, HA, SMTP, GCal) |
| `/api/goals` | GET/POST | Autonomy engine goals CRUD |
| `/api/memory/search` | GET | Semantic memory search |
| `/api/sessions/list` | GET | List conversation sessions |
| `/api/agents` | GET | Registered agents metadata |
| `/api/sentinel/events` | GET | Security event history |
| `/ws/events` | WebSocket | Real-time event broadcast stream |
| `/chat/{user_id}` | WebSocket | Interactive chat |

---

## Platforms (`app/telegram/`, `app/discord/`, `app/slack/`, `app/whatsapp/`)

All platforms use the same flow: `Platform → Orchestrator.handle() → BotSignal.send()`

---

## Background Routines (`app/routines/`)

| Module | Purpose | Interval |
|--------|---------|----------|
| `calendar_watcher.py` | Proactive meeting alerts + daily summary | 5 min |

---

## Configuration

| File | Key Settings |
|------|-------------|
| `app/settings/config.py` | All env vars — API keys, model selection, voice config, feature flags |
| `.env` | Secret values (not in repo) |

### Key Environment Variables

```
OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY
LLM_PROVIDER, LLM_MODEL
TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN, SLACK_BOT_TOKEN
REDIS_URL, OLLAMA_BASE_URL
ENABLE_LOCAL_VOICE, VOICE_TTS_VOICES
HOME_ASSISTANT_URL, HOME_ASSISTANT_TOKEN
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
GOOGLE_CALENDAR_CREDENTIALS_PATH, GOOGLE_CALENDAR_TOKEN_PATH
```

---

## Architecture Flow

```
User Message (any platform)
  → UserIdentityStore.resolve()     # canonical user ID
  → PersonaEngine.generate_prompt() # inject personality
  → ModelRouter.classify()          # System1 or System2?
  → AgentRuntime.run()              # ReAct loop (max 15 turns)
    → Tool calls (with retry/timeout/circuit breaker)
    → Self-improvement feedback recording
  → OutputRouter.route()            # CRITICAL/HIGH/NORMAL/LOW/DIGEST
  → BotSignal.send()                # deliver on appropriate channels

Background (AmbientLoop — always running):
  Every 1 min:  workflow tick, heartbeat broadcast
  Every 5 min:  sentinel digest flush, health checks
  Every 1 hour: self-improvement analysis + routing recommendations
  Daily:        persona reset (mood/energy/confidence)
```
