# Changelog

All notable changes to Raven are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-06-30

### Added

#### 15 Specialist Agents
- **Assistant** — General-purpose conversational interface with context management
- **Communications** — Multi-platform message routing and response orchestration
- **Data Engineer** — ETL pipelines, data transformation, and storage management
- **Developer** — Code generation, review, debugging, and git operations
- **Finance** — Expense tracking, budgeting, financial analysis, and crypto monitoring
- **Home Guardian** — Smart home monitoring, anomaly detection, and alert dispatch
- **Moral** — Ethical boundary checking and value-aligned decision making
- **Negotiation** — Persuasive communication and multi-party coordination
- **News** — News aggregation, summarization, and trend analysis
- **Productivity** — Task management, scheduling, and workflow optimization
- **Researcher** — Deep web research, academic paper analysis, and evidence gathering
- **Reviewer** — Code review, document QA, and quality assurance
- **Scientist** — Experimental design, data analysis, and hypothesis testing
- **Security** — Vulnerability scanning, threat assessment, and security auditing
- **Sysadmin** — System monitoring, maintenance, and infrastructure management

#### 98+ Tools
- **Web & Search**: Brave Search, Firecrawl, web fetch, YouTube transcript, Reddit, RSS feeds
- **Code & Shell**: Shell execution, Docker management, Python REPL, git operations, file system
- **Calendar & Email**: Google Calendar, Outlook/CalDAV, Gmail, SMTP email
- **Finance**: YFinance stock quotes, crypto price tracking, expense tracking
- **Smart Home**: Home Assistant, MQTT broker, camera bridge, sensor read
- **AI & Media**: Image generation, OCR (tesseract), document parsing (PDF/DOCX/XLSX), document generation, video stream analysis
- **Memory & Knowledge**: Knowledge graph, memory store, FTS5 search, learning DB
- **Productivity**: Todoist, Notion, Obsidian vault, Spotify music control
- **Security**: VirusTotal scanning, breach checking, secret vault
- **Infrastructure**: MCP server management, edge node orchestration, HelixDB

#### 12 Messaging Platforms
- Telegram (full text + voice + commands)
- Discord (channels, threads, voice)
- WhatsApp (Baileys WebSocket bridge)
- Signal (signal-cli daemon)
- Slack (Socket Mode)
- iMessage (macOS AppleScript bridge)
- WeChat (itchat)
- LINE (Messaging API webhook)
- Matrix (matrix-nio)
- IRC (irc library)
- Web Dashboard (FastAPI + Hermes UI)
- Webhooks (inbound/outbound)
- CLI (terminal chat)

#### Ambient Intelligence Loop
- 27 background intervals ranging from 30-second heartbeat to 24-hour system self-review
- Proactive insight generation from sensor data, calendar, and email
- Automatic memory consolidation and skill crystallization
- Learning health monitoring and reporting
- Database maintenance (VACUUM, index optimization)

#### Cognitive Architecture
- **System 0/1/2**: Reactive (0), Deliberative (1), Metacognitive (2) reasoning tiers
- **ModelRouter**: Request classification into local/cheap/deep tiers
- **AutoModelRouter**: Cascading provider fallback chain with health probing
- **RLHF**: Localized Q-learning with 4 state dimensions, rewards from +1.0 to -1.0
- **Fact-Checking**: Claim extraction + cross-referencing + confidence scoring
- **Self-Improvement**: Correction verification loop with automated retraining

#### Skills & Learning System
- **SkillCrystallizer**: Auto-translates multi-step traces into reusable YAML/Python skills
- **SkillRegistry**: Manifest-based skill discovery (SKILL.md + module.yaml)
- **LearningStore**: Unified SQLite + FTS5 store for corrections, facts, patterns, feedback
- **SkillMarketplace**: Version management, dependency tracking, community sharing

#### Voice Pipeline
- Wake word detection (openwakeword)
- STT via whisper.cpp (pywhispercpp binding) with Vosk fallback
- TTS via Piper (local on-device, <100ms latency)
- Full-duplex conversational barge-in
- Cross-channel voice bridge (web ↔ Telegram ↔ Discord)
- Speaker verification for sensitive commands

#### Security & Privacy
- 4-layer tool execution pipeline: policy engine → approval manager → command sanitizer → audit logger
- Risk-tiered approval system (Tier 0-3)
- SecretVault with Fernet AES-128-CBC encryption
- Immutable JSONL audit log
- Privacy zones with consent-gated data classification
- Bandit SAST scanning in CI

#### Web Dashboard (Hermes UI)
- 25+ management pages: chat, sessions, models, providers, cron, channels, pairing, MCP, webhooks, plugins, profiles, skills, kanban, blueprints, automation, learning, audit, search, onboarding, config editor
- Real-time WebSocket status updates
- OpenAI-compatible API bridge
- Config editor with live save
- Jinja2 + Tailwind CSS rendering

#### Automation System
- **Kanban Board**: Full CRUD with status columns, priority, agent assignment
- **Blueprints**: YAML-defined multi-step automation workflows with installer and runner
- **Event Hooks**: pub/sub event system with delivery tracking
- **Rate Limit Middleware**: Token bucket per-endpoint rate limiting
- **Cron Engine**: Persistent JSON-based scheduler with add/remove/toggle

#### Infrastructure
- Async-first architecture throughout (asyncio, aiohttp, httpx)
- SQLite with WAL mode + FTS5 full-text search
- ChromaDB for vector embeddings
- HelixDB sidecar for knowledge graph storage
- Docker deployment with NVIDIA CUDA support
- OpenTelemetry metrics + Prometheus exposition
- Pre-commit hooks (ruff, pyright, detect-secrets)
- GitHub Actions CI (lint, typecheck, test)

### Changed
- Transitioned from edge-tts to Piper TTS for local on-device voice (`app/voice/`)
- Replaced faster-whisper with whisper.cpp (pywhispercpp) for STT
- Unified Hermes dashboard routes under single `raven run` port
- Migrated to `uv` as the sole package manager
- Upgraded all provider SDKs to latest versions

### Fixed
- Circular import between outbox and botsignal resolved
- WebSocket disconnect handling for chat and UI streams
- Edge node task claiming race condition with capability filtering
- Cron job persistence on unclean shutdown
- Memory leak in long-lived WebSocket connections

---

## [0.5.0] — 2025-12-15

### Added — FRIDAY-Level Transformation
- **BotSignal** unified message bus replacing ad-hoc per-platform dispatch
- **MessageOrchestrator** 8-phase processing pipeline
- **15 Specialist Agents** with SwarmManager coordination
- **Agent Supervisor** (keyword-based routing, 14 agents)
- **TaskLedger** persistent task tracking with approval workflow
- **ModelRouter** and **AutoModelRouter** cascading provider fallback
- **RLHF PreferenceStore** localized Q-learning
- **SkillCrystallizer** automatic skill generation from execution traces
- **SkillRegistry** manifest-based discovery (SKILL.md + module.yaml)
- **LearningDB** SQLite + FTS5 unified learning store
- **Self-Improvement Loop** correction verification
- **Hermes Web Dashboard** initial release with 8 pages
- **Dual-mode chat**: synchronous REST + streaming WebSocket
- **Edge Node Protocol** for distributed computation
- **MCP Server** hot-plug support
- **12 Platform Connectors** (initial implementations)
- **Voice Pipeline** with openwakeword + whisper.cpp + Piper

### Changed
- Complete rewrite of task scheduling (APScheduler → custom CronEngine)
- Migration from single-agent to multi-agent architecture
- API versioning introduced at `/api/v1/`

### Fixed
- Discord message content intent detection
- Telegram webhook vs polling mode conflict resolution
- Signal CLI process lifecycle management

---

## [0.1.0] — 2025-06-01

### Added — Initial RAVEN Release
- **Core CLI** (`raven` command with run, stop, status, log, doctor)
- **Terminal Chat** (`raven chat`) with basic LLM integration
- **Module system** based on `raven_protocol`
- **Basic memory store** (JSON file-based)
- **Agent identity** from SOUL.md and MEMORY.md
- **Telegram and Discord** platform connectors
- **Docker deployment** support
- **Project structure** with `app/` package layout
- **pyproject.toml** with uv dependency management
- **Pre-commit** hooks configuration
- **Environment configuration** via `.env`

---

## Format

```
### Added    — for new features
### Changed  — for changes in existing functionality
### Deprecated — for soon-to-be removed features
### Removed  — for now removed features
### Fixed    — for bug fixes
### Security — for vulnerability fixes
```

[1.0.0]: https://github.com/AetherRavyn/Raven/releases/tag/v1.0.0
[0.5.0]: https://github.com/AetherRavyn/Raven/releases/tag/v0.5.0
[0.1.0]: https://github.com/AetherRavyn/Raven/releases/tag/v0.1.0
