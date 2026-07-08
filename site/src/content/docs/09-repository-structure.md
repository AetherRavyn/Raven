---
title: "09 - Repository Structure, Setup & Deliverables"
---

# 09 - Repository Structure, Setup & Deliverables

This document maps every file in the RAVEN repository, explains how modules
connect, provides setup instructions, and lists resume-ready accomplishments
and a deliverables checklist aligned with the milestone roadmap.

---

## Full Repository Tree

```
RAVEN/
│
├── main.py                                # Entry point: asyncio.run(main()), starts brain + all connectors
├── pyproject.toml                         # Project metadata, dependencies (managed with uv)
├── .python-version                        # Python 3.12
├── config.yaml                            # Runtime configuration (platforms, LLM, voice, sensors, tools)
├── .env.example                           # Template for secrets (API tokens, DB passwords)
├── .gitignore                             # Ignores .env, models/, data/, __pycache__, *.pyc
├── LICENSE                                # MIT license
├── README.md                              # Project overview, demo GIF, quickstart
├── Makefile                               # Common commands: dev, test, lint, download-models
├── Dockerfile                             # Python app container (CUDA base for GPU inference)
├── docker-compose.yml                     # Full stack: raven app, PostgreSQL, Redis, Mosquitto, SearXNG
│
├── raven/                                 # Main Python package -- the entire bot
│   ├── __init__.py                        # Package init, version string
│   ├── config.py                          # Loads config.yaml + .env, exposes typed Config dataclass
│   ├── models.py                          # Pydantic/dataclass models: IncomingMessage, OutgoingMessage, ReplyContext
│   ├── scheduler.py                       # RavenScheduler: APScheduler wrapper for reminders, alarms, routines
│   ├── exceptions.py                      # Custom exceptions: LLMTimeoutError, SafetyBlockedError, ToolExecutionError
│   │
│   ├── brain/                             # Core intelligence subsystem
│   │   ├── __init__.py
│   │   ├── brain.py                       # RavenBrain: main orchestrator, handle_message(), tool loop
│   │   ├── llm_engine.py                  # LLM client: vLLM OpenAI-compatible API, streaming, LoRA loading
│   │   ├── memory.py                      # MemoryManager: pgvector semantic search, conversation history
│   │   ├── personality.py                 # PersonalityManager: loads prompt files, user-specific tone adaptation
│   │   ├── context_builder.py             # Assembles LLM prompt: system prompt + memories + sensor state + message
│   │   ├── tool_router.py                 # Parses LLM tool_call JSON, dispatches to correct tool, returns result
│   │   └── embeddings.py                  # SentenceTransformer wrapper (all-MiniLM-L6-v2) for memory embeddings
│   │
│   ├── connectors/                        # Platform connectors (each runs as async task)
│   │   ├── __init__.py
│   │   ├── base.py                        # BaseConnector ABC: start(), stop(), send_reply(), reconnect logic
│   │   ├── telegram.py                    # TelegramConnector: python-telegram-bot, text + voice notes + photos
│   │   ├── discord.py                     # DiscordConnector: discord.py, text + voice channels + slash commands
│   │   ├── whatsapp.py                    # WhatsAppConnector: HTTP client to Node.js Baileys bridge
│   │   ├── voice_io.py                    # VoiceIOConnector: local mic/speaker via PyAudio, wake word, VAD
│   │   └── web_api.py                     # WebAPIConnector: FastAPI server, REST + WebSocket, admin dashboard
│   │
│   ├── voice/                             # Voice processing engine
│   │   ├── __init__.py
│   │   ├── stt.py                         # STTEngine: faster-whisper, transcribe audio files and streams
│   │   ├── tts.py                         # TTSEngine: Piper TTS synthesis, audio format conversion
│   │   ├── audio_utils.py                 # Format conversion (ogg/opus/wav/mp3), resampling, normalization
│   │   ├── vad.py                         # Voice Activity Detection: Silero VAD wrapper, silence detection
│   │   └── wake_word.py                   # Wake word detector: openWakeWord or custom model, "Hey RAVEN"
│   │
│   ├── sensors/                           # IoT sensor network
│   │   ├── __init__.py
│   │   ├── mqtt_listener.py               # MQTTSensorListener: subscribes to MQTT topics, parses readings
│   │   ├── device_registry.py             # DeviceRegistry: CRUD for smart home devices in PostgreSQL
│   │   ├── anomaly_detection.py           # AnomalyDetector: Isolation Forest on sensor streams, alert triggers
│   │   └── home_assistant.py              # HomeAssistantBridge: REST API client for HA device control
│   │
│   ├── tools/                             # Tool implementations (called by LLM via tool_router)
│   │   ├── __init__.py
│   │   ├── base.py                        # BaseTool ABC: name, description, parameters schema, execute()
│   │   ├── web_search.py                  # WebSearchTool: SearXNG query, result parsing, snippet extraction
│   │   ├── run_code.py                    # RunCodeTool: sandboxed Python exec (subprocess + timeout)
│   │   ├── read_url.py                    # ReadURLTool: fetch URL, extract text with trafilatura/readability
│   │   ├── weather.py                     # WeatherTool: Open-Meteo API, current + forecast
│   │   ├── calculator.py                  # CalculatorTool: safe math expression eval (sympy)
│   │   ├── set_reminder.py                # SetReminderTool: creates scheduled task via RavenScheduler
│   │   ├── smart_home.py                  # SmartHomeTool: control devices via DeviceRegistry + HA bridge
│   │   ├── read_sensor.py                 # ReadSensorTool: query latest sensor values from DB/Redis
│   │   ├── wikipedia.py                   # WikipediaTool: Wikipedia API search + summary extraction
│   │   ├── news.py                        # NewsTool: Hacker News API + RSS feed parser
│   │   ├── take_photo.py                  # TakePhotoTool: capture from connected camera, return image
│   │   ├── play_music.py                  # PlayMusicTool: control media playback (mpv/VLC subprocess)
│   │   ├── file_reader.py                 # FileReaderTool: read uploaded files (PDF, TXT, DOCX)
│   │   ├── datetime_tool.py               # DateTimeTool: current time, timezone conversion, date math
│   │   └── plugin_loader.py               # Discovers and loads tools from plugins/ directory
│   │
│   ├── safety/                            # Safety and moderation subsystem
│   │   ├── __init__.py
│   │   ├── safety_gate.py                 # SafetyGate: orchestrates all checks, fail-closed design
│   │   ├── content_classifier.py          # ContentClassifier: DistilBERT multi-label (ONNX), 8 safety categories
│   │   ├── prompt_injection.py            # PromptInjectionDetector: heuristic + ML detection of injection attempts
│   │   ├── iot_safety.py                  # IoTSafetyGate: confirmation for destructive actions, device allow-lists
│   │   ├── rate_limiter.py                # RateLimiter: Redis-backed per-user rate limiting
│   │   └── audit.py                       # AuditLogger: logs all safety events + IoT actions to PostgreSQL
│   │
│   ├── utils/                             # Shared utilities
│   │   ├── __init__.py
│   │   ├── logging.py                     # Structured logging setup (structlog), log levels per module
│   │   ├── database.py                    # AsyncPG connection pool, migration runner
│   │   ├── redis_client.py                # Redis async client wrapper (aioredis)
│   │   ├── http_client.py                 # Shared aiohttp session with retry logic and timeouts
│   │   └── metrics.py                     # Prometheus metrics: latency histograms, counters, gauges
│   │
│   └── db/                                # Database management
│       ├── __init__.py
│       ├── schema.sql                     # Full PostgreSQL schema: users, conversations, memories, devices, audit
│       ├── migrations/                    # Incremental SQL migrations
│       │   ├── 001_initial_schema.sql     # Users, conversations, memories tables + pgvector extension
│       │   ├── 002_sensor_devices.sql     # Sensor readings, smart home devices tables
│       │   ├── 003_scheduled_tasks.sql    # Scheduled tasks (reminders, alarms, routines)
│       │   └── 004_audit_log.sql          # Audit log table for safety + IoT events
│       └── seed.py                        # Seed script: default user, sample devices, test memories
│
├── whatsapp-bridge/                       # Node.js WhatsApp bridge (separate process)
│   ├── package.json                       # Dependencies: @whiskeysockets/baileys, express, qrcode-terminal
│   ├── package-lock.json
│   ├── Dockerfile                         # Node.js 20 container for the bridge
│   ├── .env.example                       # RAVEN_CALLBACK_URL, PORT
│   ├── index.js                           # Express server: /send, /status endpoints + Baileys client
│   ├── baileys_client.js                  # Baileys wrapper: QR auth, message listener, reconnection
│   ├── message_handler.js                 # Incoming message parsing, forwards to Python callback URL
│   └── auth_store/                        # Baileys session persistence (gitignored, created at runtime)
│       └── .gitkeep
│
├── models/                                # ML model files (gitignored, downloaded via script)
│   ├── .gitkeep
│   ├── piper/                             # Piper TTS voice models
│   │   ├── en_US-lessac-medium.onnx       # Default English voice model
│   │   └── en_US-lessac-medium.onnx.json  # Voice model config
│   ├── whisper/                           # faster-whisper model cache
│   │   └── medium/                        # Whisper medium INT8 model files
│   ├── safety/                            # Safety classifier
│   │   └── content_classifier.onnx        # DistilBERT safety model (ONNX export)
│   ├── embeddings/                        # Sentence embedding model
│   │   └── all-MiniLM-L6-v2/             # SentenceTransformer model files
│   ├── wake_word/                         # Wake word detection model
│   │   └── hey_raven.onnx                 # Custom openWakeWord model
│   └── lora/                              # LoRA adapter weights
│       └── raven-personality/             # Personality fine-tuned LoRA adapter
│           ├── adapter_config.json
│           └── adapter_model.safetensors
│
├── prompts/                               # Personality and system prompt templates
│   ├── system_prompt.txt                  # Base system prompt: who RAVEN is, capabilities, constraints
│   ├── friendly.txt                       # Friendly personality overlay: casual tone, humor, warmth
│   ├── professional.txt                   # Professional personality overlay: concise, formal
│   ├── tool_instructions.txt              # Instructions for tool-calling format and behavior
│   ├── safety_preamble.txt                # Safety rules injected into every prompt
│   └── sensor_context.txt                 # Template for injecting current sensor state into context
│
├── plugins/                               # User-added custom tools (discovered at startup)
│   ├── README.md                          # Plugin development guide: interface, manifest, examples
│   ├── example_plugin/                    # Example plugin for reference
│   │   ├── manifest.json                  # Plugin metadata: name, description, version, parameters
│   │   └── tool.py                        # Plugin implementation: subclass of BaseTool
│   └── .gitkeep
│
├── tests/                                 # Test suite (mirrors raven/ package structure)
│   ├── __init__.py
│   ├── conftest.py                        # Shared fixtures: mock brain, mock LLM, test DB, test Redis
│   │
│   ├── brain/                             # Brain unit tests
│   │   ├── __init__.py
│   │   ├── test_brain.py                  # RavenBrain message handling, tool loop, error recovery
│   │   ├── test_llm_engine.py             # LLM client mocking, streaming, token counting
│   │   ├── test_memory.py                 # Memory storage, semantic search, conversation history
│   │   ├── test_personality.py            # Prompt loading, user-specific adaptation
│   │   ├── test_context_builder.py        # Context assembly, token budget management
│   │   └── test_tool_router.py            # Tool call parsing, dispatch, error handling
│   │
│   ├── connectors/                        # Connector unit tests
│   │   ├── __init__.py
│   │   ├── test_telegram.py               # Message parsing, voice note handling, reply formatting
│   │   ├── test_discord.py                # Text + voice channel handling, slash commands
│   │   ├── test_whatsapp.py               # Bridge HTTP communication, message forwarding
│   │   ├── test_voice_io.py               # Mic input, speaker output, wake word triggering
│   │   └── test_web_api.py                # REST endpoints, WebSocket, auth
│   │
│   ├── voice/                             # Voice engine tests
│   │   ├── __init__.py
│   │   ├── test_stt.py                    # Transcription accuracy, format handling
│   │   ├── test_tts.py                    # Synthesis, audio format output, latency
│   │   ├── test_audio_utils.py            # Format conversion, resampling correctness
│   │   └── test_vad.py                    # VAD threshold, silence detection
│   │
│   ├── sensors/                           # Sensor subsystem tests
│   │   ├── __init__.py
│   │   ├── test_mqtt_listener.py          # MQTT message parsing, topic routing
│   │   ├── test_device_registry.py        # Device CRUD, state tracking
│   │   ├── test_anomaly_detection.py      # Anomaly thresholds, alert generation
│   │   └── test_home_assistant.py         # HA API client, device control commands
│   │
│   ├── tools/                             # Tool unit tests
│   │   ├── __init__.py
│   │   ├── test_web_search.py             # Search query, result parsing
│   │   ├── test_run_code.py               # Sandbox execution, timeout, output capture
│   │   ├── test_read_url.py               # URL fetch, text extraction
│   │   ├── test_weather.py                # API response parsing, forecast formatting
│   │   ├── test_smart_home.py             # Device command dispatch, confirmation flow
│   │   ├── test_set_reminder.py           # Reminder creation, trigger time parsing
│   │   └── test_plugin_loader.py          # Plugin discovery, validation, loading
│   │
│   ├── safety/                            # Safety subsystem tests
│   │   ├── __init__.py
│   │   ├── test_safety_gate.py            # Full safety pipeline, fail-closed behavior
│   │   ├── test_content_classifier.py     # Classification accuracy, threshold tuning
│   │   ├── test_prompt_injection.py       # Injection detection, evasion resistance
│   │   ├── test_iot_safety.py             # IoT confirmation flow, blocked actions
│   │   ├── test_rate_limiter.py           # Rate limit enforcement, window expiry
│   │   └── test_audit.py                  # Audit log creation, query
│   │
│   └── integration/                       # Integration tests (require running services)
│       ├── __init__.py
│       ├── test_full_message_flow.py      # End-to-end: message in -> brain -> reply out
│       ├── test_voice_pipeline.py         # Audio in -> STT -> brain -> TTS -> audio out
│       ├── test_tool_execution.py         # LLM tool call -> tool exec -> result -> final reply
│       ├── test_memory_persistence.py     # Store memory -> restart -> retrieve memory
│       └── test_sensor_alert.py           # Sensor reading -> anomaly -> alert via connector
│
├── scripts/                               # Utility and operations scripts
│   ├── setup_dev.sh                       # Full dev environment setup: venv, deps, DB, Redis, models
│   ├── download_models.sh                 # Download Whisper, Piper, embedding, wake word models
│   ├── backup_db.sh                       # PostgreSQL pg_dump backup to timestamped file
│   ├── restore_db.sh                      # Restore PostgreSQL from backup file
│   ├── run_migrations.py                  # Apply SQL migrations in order
│   ├── benchmark_latency.py              # Measure end-to-end latency: text and voice pipelines
│   ├── export_safety_model.py            # Export trained safety classifier to ONNX
│   └── generate_test_data.py             # Generate synthetic test conversations and sensor data
│
├── data/                                  # Training datasets (gitignored, downloaded or generated)
│   ├── .gitkeep
│   ├── wake_word/                         # Wake word training audio samples
│   │   ├── positive/                      # "Hey RAVEN" recordings
│   │   └── negative/                      # Background noise, other speech
│   ├── lora/                              # LoRA fine-tuning datasets
│   │   ├── conversations.jsonl            # Multi-turn conversation examples with RAVEN personality
│   │   ├── tool_calls.jsonl               # Tool-calling examples (function format)
│   │   └── safety_refusals.jsonl          # Examples of appropriate refusal responses
│   ├── safety/                            # Safety classifier training data
│   │   ├── toxic_samples.jsonl            # Labeled toxic/safe text samples
│   │   └── injection_samples.jsonl        # Prompt injection examples
│   └── stt/                               # STT fine-tuning data
│       ├── iot_commands/                   # Recorded IoT voice commands with transcripts
│       └── noise_profiles/                # Background noise samples for augmentation
│
├── docs/                                  # Design documentation (this series)
│   ├── 00-overview.md                     # What RAVEN is, interaction examples, stack overview
│   ├── 01-system-architecture.md          # Single-process architecture, message bus, brain design
│   ├── 02-platform-connectors.md          # Telegram, Discord, WhatsApp, Voice I/O, Web API
│   ├── 03-voice-personality.md            # Voice pipeline (STT + TTS), personality system, memory
│   ├── 04-multimodal-intelligence.md      # Tool ecosystem, image understanding, file handling
│   ├── 05-safety-moderation.md            # Content safety, prompt injection, IoT safety, audit
│   ├── 06-iot-integration.md              # MQTT sensors, device registry, anomaly detection, Home Assistant
│   ├── 07-ml-depth.md                     # Models trained, datasets, fine-tuning, evaluation
│   ├── 08-deployment-scaling.md           # Docker, self-hosting, cloud deployment, monitoring
│   └── 09-repository-structure.md         # This file: repo map, setup, resume bullets, deliverables
│
└── .github/
    └── workflows/
        ├── ci.yml                         # CI: lint (ruff), type check (mypy), unit tests, coverage
        ├── integration_tests.yml          # Integration tests: spins up PostgreSQL + Redis in CI
        └── model_eval.yml                 # Scheduled model evaluation: safety classifier, STT WER
```

---

## Key File Descriptions

### Root Files

| File | Purpose |
|---|---|
| `main.py` | Entry point. Calls `asyncio.run(main())` which initializes `RavenBrain`, starts all connectors, MQTT listener, and scheduler as concurrent async tasks via `asyncio.gather()`. |
| `pyproject.toml` | Project metadata, Python dependencies (faster-whisper, piper-tts, vllm, discord.py, python-telegram-bot, asyncpg, aioredis, sentence-transformers, apscheduler, fastapi, paho-mqtt, onnxruntime). Build system config for uv. |
| `config.yaml` | All runtime configuration: which platforms are enabled, LLM model path, voice settings, MQTT broker address, tool toggles, safety thresholds. Secrets reference `.env` variables. |
| `docker-compose.yml` | Orchestrates the full stack: RAVEN Python app (GPU-enabled), PostgreSQL 16 with pgvector, Redis 7, Mosquitto MQTT broker, SearXNG (self-hosted search), and the WhatsApp bridge. |

### Brain Module (`raven/brain/`)

| File | Purpose |
|---|---|
| `brain.py` | `RavenBrain` class. Receives `IncomingMessage` from any connector, orchestrates memory retrieval, context assembly, LLM inference, tool execution loop, and returns `OutgoingMessage`. Central hub of the entire system. |
| `llm_engine.py` | Wraps the vLLM OpenAI-compatible API. Handles streaming token generation, LoRA adapter loading, token counting, and retry logic. |
| `memory.py` | `MemoryManager` with two tiers: recent conversation history (last N messages from PostgreSQL) and long-term semantic memory (pgvector similarity search). Handles memory extraction, storage, and retrieval. |
| `personality.py` | Loads personality prompt files from `prompts/`, merges base system prompt with personality overlay, adapts tone based on user preferences stored in the DB. |
| `context_builder.py` | Assembles the final LLM prompt within a token budget: system prompt + personality + retrieved memories + sensor context + recent conversation + current message. |
| `tool_router.py` | Parses tool call JSON from LLM output, validates parameters against tool schemas, dispatches to the correct tool's `execute()` method, and formats results for the LLM. |
| `embeddings.py` | Thin wrapper around SentenceTransformer (`all-MiniLM-L6-v2`). Generates 384-dim embeddings for memory storage and query. |

### Connector Module (`raven/connectors/`)

| File | Purpose |
|---|---|
| `base.py` | `BaseConnector` abstract class. Defines the interface: `start()`, `stop()`, `send_reply()`. Includes reconnection loop with exponential backoff. |
| `telegram.py` | Telegram bot using `python-telegram-bot`. Handles text messages, voice notes (downloads OGG, sends to STT), photos, file uploads, inline buttons, and Markdown formatting. |
| `discord.py` | Discord bot using `discord.py`. Handles text channels, voice channel join/leave (PCM audio stream to STT, TTS output to voice sink), slash commands, embeds. |
| `whatsapp.py` | HTTP client that communicates with the Node.js Baileys bridge. Sends messages via POST `/send`, receives incoming messages via webhook callback. |
| `voice_io.py` | Local microphone/speaker connector using PyAudio. Listens for wake word, uses VAD to detect speech boundaries, sends audio to STT, plays TTS responses through speaker. |
| `web_api.py` | FastAPI server with REST endpoints (`/chat`, `/status`, `/devices`) and WebSocket for real-time chat. Serves as admin dashboard and programmatic API. |

### Voice Module (`raven/voice/`)

| File | Purpose |
|---|---|
| `stt.py` | `STTEngine` wrapping faster-whisper. Transcribes audio files (voice notes) and audio streams (live mic). Supports INT8 quantization for speed. |
| `tts.py` | `TTSEngine` wrapping Piper TTS. Converts text to speech audio, outputs WAV/OGG/OPUS. Handles sentence-level streaming for low-latency voice responses. |
| `audio_utils.py` | Audio format conversion (OGG Opus to WAV, resampling to 16kHz for Whisper), volume normalization, silence trimming. |
| `vad.py` | Silero VAD wrapper. Detects speech start/end in audio streams. Used by VoiceIOConnector and Discord voice to know when the user has finished speaking. |
| `wake_word.py` | Wake word detector using openWakeWord. Continuously listens on mic for "Hey RAVEN" trigger phrase before activating the main STT pipeline. |

### Safety Module (`raven/safety/`)

| File | Purpose |
|---|---|
| `safety_gate.py` | `SafetyGate` orchestrator. Runs all safety checks (content classification, injection detection, rate limiting) on both input and output. Fail-closed: blocks on any error. |
| `content_classifier.py` | ONNX-optimized DistilBERT model. Multi-label classification across 8 safety categories. Sub-5ms inference. |
| `prompt_injection.py` | Detects prompt injection attempts using heuristic rules (known patterns, instruction override phrases) plus ML-based detection. |
| `iot_safety.py` | IoT-specific safety gate. Requires confirmation for destructive actions (unlock, disarm, open). Enforces device allow-lists and action rate limits. |
| `rate_limiter.py` | Redis-backed sliding window rate limiter. Per-user message limits to prevent abuse. |
| `audit.py` | Logs all safety decisions, IoT commands, and blocked actions to the `audit_log` PostgreSQL table. |

---

## Module Dependency Diagram

```
                          ┌──────────────┐
                          │   main.py    │
                          └──────┬───────┘
                                 │ creates + starts
                 ┌───────────────┼───────────────────────────────┐
                 │               │                               │
                 ▼               ▼                               ▼
        ┌────────────┐  ┌──────────────┐                ┌──────────────┐
        │ Connectors │  │  RavenBrain  │                │  Scheduler   │
        │            │  │              │                │              │
        │ telegram   │  │              │                │ (APScheduler)│
        │ discord    │  │              │                └──────┬───────┘
        │ whatsapp   │──▶  depends on  │◀──────────────────────┘
        │ voice_io   │  │              │
        │ web_api    │  └──┬───┬───┬───┘
        └────────────┘     │   │   │
                           │   │   │
              ┌────────────┘   │   └────────────┐
              ▼                ▼                 ▼
     ┌──────────────┐  ┌────────────┐   ┌──────────────┐
     │    Memory     │  │ Personality │   │ Tool Router  │
     │              │  │            │   │              │
     │ memory.py    │  │ loads from │   │ dispatches   │
     │ embeddings.py│  │ prompts/   │   │ to tools/    │
     └──────┬───────┘  └────────────┘   └──────┬───────┘
            │                                   │
            │                          ┌────────┴────────┐
            ▼                          ▼                  ▼
     ┌──────────────┐         ┌──────────────┐   ┌──────────────┐
     │  PostgreSQL   │         │    Tools      │   │   Plugins    │
     │  + pgvector   │         │              │   │  plugins/    │
     └──────────────┘         │ web_search   │   └──────────────┘
                              │ run_code     │
                              │ read_url     │
                              │ smart_home ──┼──▶ sensors/device_registry
                              │ read_sensor ─┼──▶ sensors/mqtt_listener
                              │ set_reminder─┼──▶ scheduler
                              │ weather      │
                              │ calculator   │
                              │ ... (15+)    │
                              └──────────────┘

     ┌──────────────┐         ┌──────────────┐
     │ MQTT Listener │────────▶│  RavenBrain  │  (pushes alerts when anomaly detected)
     │ sensors/      │         └──────────────┘
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │   Anomaly     │
     │  Detection    │
     └──────────────┘

     ┌──────────────┐
     │  Voice Engine │◀──── used by connectors (telegram, discord, voice_io)
     │              │
     │ stt.py       │      Connectors call STT to transcribe voice input,
     │ tts.py       │      then call TTS to synthesize voice replies
     │ vad.py       │
     │ wake_word.py │
     └──────────────┘

     ┌──────────────┐
     │  Safety Gate  │◀──── called by RavenBrain on every input and output
     │              │
     │ classifier   │
     │ injection    │
     │ iot_safety   │
     │ rate_limiter │
     │ audit        │
     └──────────────┘

     ┌──────────────┐
     │    Utils      │◀──── used by everything
     │              │
     │ database.py  │      AsyncPG pool, Redis client, HTTP client,
     │ redis.py     │      structured logging, Prometheus metrics
     │ logging.py   │
     │ metrics.py   │
     └──────────────┘
```

**Import direction summary:**
- `connectors` import `brain`, `voice`
- `brain` imports `memory`, `personality`, `tool_router`, `safety`, `utils`
- `tool_router` imports individual `tools`
- `tools` import `sensors`, `scheduler`, `utils` (as needed per tool)
- `sensors` import `brain` (to push alerts), `utils`
- `safety` imports `utils`
- `utils` imports nothing from `raven` (leaf dependency)

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- Redis 7+
- NVIDIA GPU with CUDA 12+ (for LLM and Whisper inference)
- Node.js 20+ (only if using WhatsApp connector)
- uv (Python package manager)

### Step-by-Step Setup

**1. Clone the repository**

```bash
git clone https://github.com/your-username/RAVEN.git
cd RAVEN
```

**2. Install uv and create virtual environment**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12
source .venv/bin/activate
```

**3. Install Python dependencies**

```bash
uv sync
```

This installs all dependencies declared in `pyproject.toml`: faster-whisper,
piper-tts, vllm, discord.py, python-telegram-bot, asyncpg, sentence-transformers,
apscheduler, fastapi, paho-mqtt, onnxruntime, and others.

**4. Set up PostgreSQL with pgvector**

```bash
# Install pgvector extension (Ubuntu/Debian)
sudo apt install postgresql-16-pgvector

# Create database and user
sudo -u postgres psql -c "CREATE USER raven WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE raven OWNER raven;"
sudo -u postgres psql -d raven -c "CREATE EXTENSION vector;"

# Run schema migrations
python scripts/run_migrations.py
```

Or use Docker Compose (handles everything automatically):

```bash
docker compose up -d postgres
```

**5. Set up Redis**

```bash
# Install Redis
sudo apt install redis-server
sudo systemctl start redis

# Or via Docker Compose
docker compose up -d redis
```

**6. Configure config.yaml and .env**

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your secrets:
#   TELEGRAM_BOT_TOKEN=your_telegram_token
#   DISCORD_BOT_TOKEN=your_discord_token
#   DATABASE_URL=postgresql://raven:your_password@localhost:5432/raven
#   REDIS_URL=redis://localhost:6379/0
#   HA_LONG_LIVED_TOKEN=your_home_assistant_token  (optional)

# Edit config.yaml to enable/disable platforms and configure settings
```

**7. Download models**

```bash
./scripts/download_models.sh
```

This downloads:
- faster-whisper medium model (~1.5 GB)
- Piper TTS voice model (~60 MB)
- all-MiniLM-L6-v2 sentence embeddings (~90 MB)
- openWakeWord base model (~5 MB)

The vLLM model (Mistral 7B AWQ) is downloaded automatically on first run
by vLLM from Hugging Face (~4 GB).

**8. Run RAVEN**

```bash
python main.py
```

RAVEN will start all enabled connectors and print status to the console.
You should see log lines confirming each connector is online.

**9. Set up WhatsApp bridge (optional)**

```bash
cd whatsapp-bridge
npm install
cp .env.example .env
# Edit .env: set RAVEN_CALLBACK_URL=http://localhost:8080/webhook/whatsapp

node index.js
# Scan the QR code with your WhatsApp mobile app
# The bridge will persist the session in auth_store/
```

### Quick Start with Docker Compose

To run everything in containers (recommended for first-time setup):

```bash
cp .env.example .env
# Edit .env with your API tokens

docker compose up -d
```

This starts: RAVEN app, PostgreSQL + pgvector, Redis, Mosquitto, SearXNG,
and the WhatsApp bridge. The app container has CUDA support for GPU inference.

---

## Resume Bullet Points

These are polished, quantified bullet points suitable for an ML Engineer's
resume or portfolio. Adjust numbers based on your actual implementation.

- Architected and built a **multi-platform AI companion bot** that runs as a single
  Python async process, serving **5 communication platforms** (Telegram, Discord,
  WhatsApp, local microphone/speaker, web API) through a unified message bus and
  shared brain

- Implemented a **tool-calling LLM pipeline with 15+ integrated tools** including
  web search, sandboxed code execution, URL reading, weather, IoT device control,
  and calendar reminders -- with automatic tool chaining and result re-injection
  for multi-step reasoning

- Built an **end-to-end voice pipeline** with sub-2-second latency using
  faster-whisper (INT8) for STT and Piper TTS for synthesis, supporting voice
  notes across Telegram/Discord/WhatsApp and live mic/speaker interaction with
  wake word detection

- Designed a **long-term semantic memory system** using PostgreSQL pgvector,
  storing user facts, preferences, and conversation summaries as 384-dimensional
  embeddings with cosine similarity retrieval, enabling personalized responses
  across sessions

- **Trained a custom wake word model** using openWakeWord with 500+ positive
  samples and noise augmentation across 7 acoustic environments, achieving
  95%+ recall at <1% false activation rate

- **Fine-tuned Mistral 7B with LoRA** (rank 16, ~17M trainable parameters) on
  curated conversation and tool-calling datasets, achieving 96% tool call format
  accuracy and measurably improved conversational naturalness versus the base model

- Built an **IoT sensor network** with MQTT-connected ESP32/Raspberry Pi devices,
  real-time anomaly detection using Isolation Forest, and proactive alerting
  through any connected platform when sensor readings breach learned thresholds

- Implemented a **5-layer safety system** with ONNX-optimized DistilBERT content
  classifier (<5ms inference, 8 categories), prompt injection detection, IoT
  action confirmation gates, Redis-backed rate limiting, and comprehensive
  audit logging

- Designed the system as **fully self-hosted and privacy-first**: all inference
  runs locally on a single GPU server, no data leaves the machine, with
  configurable safety thresholds and a fail-closed security architecture

---

## Deliverables Checklist

Organized by milestone from the project roadmap. Each item is a concrete,
buildable deliverable.

### M1: Brain + Telegram (Weeks 1-3)

- [ ] `raven/brain/brain.py` -- RavenBrain class with handle_message() method
- [ ] `raven/brain/llm_engine.py` -- vLLM client with streaming token generation
- [ ] `raven/brain/memory.py` -- MemoryManager with conversation history (PostgreSQL)
- [ ] `raven/brain/memory.py` -- Semantic memory search with pgvector embeddings
- [ ] `raven/brain/embeddings.py` -- SentenceTransformer embedding wrapper
- [ ] `raven/brain/personality.py` -- System prompt loading from prompts/ files
- [ ] `raven/brain/context_builder.py` -- Prompt assembly with token budget
- [ ] `raven/models.py` -- IncomingMessage, OutgoingMessage, ReplyContext dataclasses
- [ ] `raven/config.py` -- Config loader (config.yaml + .env)
- [ ] `raven/db/schema.sql` -- PostgreSQL schema: users, conversations, memories
- [ ] `raven/db/migrations/001_initial_schema.sql` -- Initial migration
- [ ] `raven/utils/database.py` -- AsyncPG connection pool
- [ ] `raven/utils/redis_client.py` -- Redis async client wrapper
- [ ] `raven/utils/logging.py` -- Structured logging setup
- [ ] `raven/connectors/base.py` -- BaseConnector ABC with reconnection logic
- [ ] `raven/connectors/telegram.py` -- TelegramConnector: text messages, commands
- [ ] `main.py` -- Entry point with asyncio.gather()
- [ ] `config.yaml` -- Initial configuration file
- [ ] `docker-compose.yml` -- PostgreSQL + Redis containers
- [ ] `tests/brain/test_brain.py` -- Brain unit tests
- [ ] `tests/brain/test_memory.py` -- Memory unit tests
- [ ] `tests/connectors/test_telegram.py` -- Telegram connector tests

### M2: Voice (Weeks 4-6)

- [ ] `raven/voice/stt.py` -- faster-whisper STT engine integration
- [ ] `raven/voice/tts.py` -- Piper TTS synthesis engine
- [ ] `raven/voice/audio_utils.py` -- Audio format conversion (OGG/WAV/OPUS)
- [ ] `raven/voice/vad.py` -- Silero VAD wrapper for speech boundary detection
- [ ] `raven/voice/wake_word.py` -- openWakeWord detector for "Hey RAVEN"
- [ ] `raven/connectors/telegram.py` -- Voice note handling (download, transcribe, reply with audio)
- [ ] `raven/connectors/voice_io.py` -- VoiceIOConnector with PyAudio mic/speaker
- [ ] `scripts/download_models.sh` -- Model download script (Whisper, Piper, embeddings)
- [ ] `models/` directory structure with .gitkeep files
- [ ] `tests/voice/test_stt.py` -- STT transcription tests
- [ ] `tests/voice/test_tts.py` -- TTS synthesis tests
- [ ] `tests/voice/test_vad.py` -- VAD detection tests
- [ ] `tests/connectors/test_voice_io.py` -- Voice I/O connector tests
- [ ] End-to-end voice latency benchmark (target: sub-2 seconds)

### M3: Tools (Weeks 7-9)

- [ ] `raven/tools/base.py` -- BaseTool ABC with name, description, parameters, execute()
- [ ] `raven/brain/tool_router.py` -- Tool call parsing and dispatch from LLM output
- [ ] `raven/tools/web_search.py` -- SearXNG web search tool
- [ ] `raven/tools/run_code.py` -- Sandboxed Python code execution
- [ ] `raven/tools/read_url.py` -- URL content extraction (trafilatura)
- [ ] `raven/tools/weather.py` -- Open-Meteo weather API
- [ ] `raven/tools/calculator.py` -- Safe math expression evaluation
- [ ] `raven/tools/set_reminder.py` -- Reminder creation via scheduler
- [ ] `raven/tools/wikipedia.py` -- Wikipedia search and summary
- [ ] `raven/tools/news.py` -- Hacker News + RSS feed reader
- [ ] `raven/tools/take_photo.py` -- Camera capture tool
- [ ] `raven/tools/play_music.py` -- Media playback control
- [ ] `raven/tools/file_reader.py` -- PDF/TXT/DOCX file reading
- [ ] `raven/tools/datetime_tool.py` -- Time, timezone, date math
- [ ] `raven/tools/plugin_loader.py` -- Dynamic plugin discovery from plugins/
- [ ] `raven/scheduler.py` -- RavenScheduler with APScheduler
- [ ] `prompts/tool_instructions.txt` -- Tool-calling format instructions for LLM
- [ ] `plugins/README.md` -- Plugin development guide
- [ ] `plugins/example_plugin/` -- Reference plugin implementation
- [ ] `tests/tools/` -- Unit tests for each tool
- [ ] `tests/brain/test_tool_router.py` -- Tool routing tests

### M4: Discord + WhatsApp (Weeks 10-12)

- [ ] `raven/connectors/discord.py` -- DiscordConnector: text channels, slash commands
- [ ] `raven/connectors/discord.py` -- Discord voice channel support (join, listen, speak)
- [ ] `raven/connectors/whatsapp.py` -- WhatsAppConnector: HTTP bridge client
- [ ] `whatsapp-bridge/index.js` -- Express server with /send and /status endpoints
- [ ] `whatsapp-bridge/baileys_client.js` -- Baileys wrapper: QR auth, reconnection
- [ ] `whatsapp-bridge/message_handler.js` -- Message parsing and forwarding
- [ ] `whatsapp-bridge/package.json` -- Node.js dependencies
- [ ] `whatsapp-bridge/Dockerfile` -- Container for the bridge
- [ ] `raven/connectors/web_api.py` -- WebAPIConnector: REST + WebSocket + dashboard
- [ ] `tests/connectors/test_discord.py` -- Discord connector tests
- [ ] `tests/connectors/test_whatsapp.py` -- WhatsApp connector tests
- [ ] `tests/connectors/test_web_api.py` -- Web API tests
- [ ] Cross-platform message parity verification (same user, different platforms)

### M5: Sensors + Smart Home (Weeks 13-16)

- [ ] `raven/sensors/mqtt_listener.py` -- MQTTSensorListener: MQTT subscribe + parse
- [ ] `raven/sensors/device_registry.py` -- DeviceRegistry: CRUD for devices in PostgreSQL
- [ ] `raven/sensors/anomaly_detection.py` -- Isolation Forest anomaly detector
- [ ] `raven/sensors/home_assistant.py` -- Home Assistant REST API client
- [ ] `raven/tools/smart_home.py` -- SmartHomeTool: LLM-callable device control
- [ ] `raven/tools/read_sensor.py` -- ReadSensorTool: query latest sensor values
- [ ] `raven/db/migrations/002_sensor_devices.sql` -- Sensor + device tables
- [ ] `prompts/sensor_context.txt` -- Template for sensor state injection into context
- [ ] Mosquitto MQTT broker in docker-compose.yml
- [ ] `tests/sensors/test_mqtt_listener.py` -- MQTT listener tests
- [ ] `tests/sensors/test_device_registry.py` -- Device registry tests
- [ ] `tests/sensors/test_anomaly_detection.py` -- Anomaly detection tests
- [ ] `tests/sensors/test_home_assistant.py` -- HA bridge tests
- [ ] Proactive alert flow: sensor anomaly -> brain -> user notification on active platform

### M6: ML + Personality (Weeks 17-20)

- [ ] `data/wake_word/` -- Collect 500+ wake word audio samples
- [ ] Custom wake word model training with openWakeWord trainer
- [ ] `data/lora/conversations.jsonl` -- Curate multi-turn conversation dataset
- [ ] `data/lora/tool_calls.jsonl` -- Curate tool-calling examples dataset
- [ ] `data/lora/safety_refusals.jsonl` -- Curate safety refusal examples
- [ ] LoRA fine-tune Mistral 7B for RAVEN personality and tool calling
- [ ] `models/lora/raven-personality/` -- Trained LoRA adapter weights
- [ ] `data/safety/` -- Compile safety classifier training data
- [ ] Train DistilBERT safety classifier (8 categories)
- [ ] `scripts/export_safety_model.py` -- Export to ONNX
- [ ] `models/safety/content_classifier.onnx` -- Exported safety model
- [ ] `data/stt/iot_commands/` -- Record IoT-domain voice commands
- [ ] Fine-tune Whisper on IoT command domain (target: <5% WER on IoT vocab)
- [ ] Evaluation suite: safety F1, STT WER, tool call accuracy, personality naturalness
- [ ] `prompts/friendly.txt` -- Refined personality prompt based on LoRA evaluation
- [ ] Model cards documenting each trained model's data, metrics, and limitations

### M7: Polish + Deploy (Weeks 21-24)

- [ ] `raven/safety/safety_gate.py` -- Full safety pipeline integration
- [ ] `raven/safety/content_classifier.py` -- ONNX classifier integration
- [ ] `raven/safety/prompt_injection.py` -- Prompt injection detector
- [ ] `raven/safety/iot_safety.py` -- IoT confirmation and allow-list gates
- [ ] `raven/safety/rate_limiter.py` -- Redis rate limiter
- [ ] `raven/safety/audit.py` -- Audit logger
- [ ] `raven/db/migrations/004_audit_log.sql` -- Audit log table
- [ ] `raven/utils/metrics.py` -- Prometheus metrics export
- [ ] `Dockerfile` -- Production container with CUDA support
- [ ] `docker-compose.yml` -- Complete stack with all services
- [ ] `.github/workflows/ci.yml` -- CI pipeline: lint, type check, test, coverage
- [ ] `.github/workflows/integration_tests.yml` -- Integration test pipeline
- [ ] `.github/workflows/model_eval.yml` -- Scheduled model evaluation
- [ ] `scripts/backup_db.sh` -- Database backup script
- [ ] `scripts/restore_db.sh` -- Database restore script
- [ ] `scripts/benchmark_latency.py` -- End-to-end latency benchmark
- [ ] `tests/integration/test_full_message_flow.py` -- Full message flow test
- [ ] `tests/integration/test_voice_pipeline.py` -- Voice pipeline integration test
- [ ] `tests/integration/test_tool_execution.py` -- Tool execution integration test
- [ ] `tests/integration/test_memory_persistence.py` -- Memory persistence test
- [ ] `tests/integration/test_sensor_alert.py` -- Sensor alert flow test
- [ ] `tests/safety/` -- Full safety test suite
- [ ] Security review: input sanitization, SQL injection prevention, sandbox escape audit
- [ ] Documentation finalization: all 10 design docs complete and consistent
- [ ] README.md with demo GIF, quickstart, architecture diagram

---

## License and Contribution

RAVEN is released under the **MIT License**. You are free to use, modify, and
distribute it for personal or commercial purposes.

### Contributing

This is a personal project built as a portfolio piece and daily-use companion.
If you fork it and build something cool, contributions back are welcome:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`make test`)
5. Ensure code passes lint (`make lint`)
6. Submit a pull request with a clear description of what and why

**Code style:** Ruff for formatting and linting, mypy for type checking.
All public functions must have type annotations and docstrings.
