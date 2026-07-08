---
title: "01 - System Architecture"
---

# 01 - System Architecture

## Design Principle: One Brain, Many Mouths

RAVEN has a single intelligent core (the "brain") that receives messages from many
platforms and responds through the same platform the user spoke from. The architecture
is a **hub-and-spoke model**:

```
                    Telegram ──────┐
                    Discord ───────┤
                    WhatsApp ──────┤
                    Microphone ────┼──▶  Unified Message Bus  ──▶  RAVEN Brain  ──▶  Reply
                    Web UI ────────┤                                   │
                    HTTP API ──────┤                                   │
                    Sensor alert ──┘                                   │
                                                                      │
                                                              ┌───────┴────────┐
                                                              │                │
                                                          Tool Calls       Memory
                                                         (search, code,   (who you are,
                                                          smart home,      past convos,
                                                          calendar...)     preferences)
```

There is no concept of "video calling" or "WebRTC". Messages come in from bots and
devices, the brain thinks, and responses go back out through the same channel.

---

## Full Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              RAVEN BOT SERVER                                    │
│                         (single machine or VPS)                                  │
│                                                                                  │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│  LAYER 1: PLATFORM CONNECTORS (async, always-on)                                │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│                                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │ Telegram   │ │ Discord    │ │ WhatsApp   │ │ Voice I/O  │ │ Web / API    │  │
│  │ Connector  │ │ Connector  │ │ Connector  │ │ Connector  │ │ Connector    │  │
│  │            │ │            │ │            │ │            │ │              │  │
│  │ - Text msg │ │ - Text msg │ │ - Text msg │ │ - Mic in   │ │ - REST API   │  │
│  │ - Voice    │ │ - Voice    │ │ - Voice    │ │ - Speaker  │ │ - WebSocket  │  │
│  │   notes    │ │   channels │ │   notes    │ │   out      │ │ - Dashboard  │  │
│  │ - Photos   │ │ - Files    │ │ - Images   │ │ - Wake     │ │              │  │
│  │ - Files    │ │ - Reactions│ │            │ │   word     │ │              │  │
│  │ - Commands │ │ - Slash    │ │            │ │ - VAD      │ │              │  │
│  │            │ │   commands │ │            │ │            │ │              │  │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └──────┬───────┘  │
│        │              │              │              │               │           │
│  ══════╪══════════════╪══════════════╪══════════════╪═══════════════╪═════════  │
│  LAYER 2: UNIFIED MESSAGE BUS                                                   │
│  ══════╪══════════════╪══════════════╪══════════════╪═══════════════╪═════════  │
│        │              │              │              │               │           │
│        ▼              ▼              ▼              ▼               ▼           │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                        MESSAGE ROUTER                                    │   │
│  │                                                                          │   │
│  │  Normalizes every incoming message into:                                │   │
│  │  {                                                                       │   │
│  │    "id": "msg-uuid",                                                    │   │
│  │    "source": "telegram" | "discord" | "whatsapp" | "voice" | "web",    │   │
│  │    "user_id": "user-uuid",                                              │   │
│  │    "input_type": "text" | "voice" | "image" | "file" | "command",      │   │
│  │    "content": { "text": "...", "audio_path": "...", "image_path": ""},  │   │
│  │    "context": { "chat_id": "...", "reply_to": "...", "guild_id": ""},   │   │
│  │    "timestamp": "2026-02-12T10:30:00Z"                                  │   │
│  │  }                                                                       │   │
│  │                                                                          │   │
│  │  Routes: voice → STT first, then brain                                  │   │
│  │          image → VLM description first, then brain                      │   │
│  │          text → directly to brain                                        │   │
│  │          command → directly to tool executor                             │   │
│  └──────────────────────────────┬───────────────────────────────────────────┘   │
│                                 │                                               │
│  ═══════════════════════════════╪═══════════════════════════════════════════════ │
│  LAYER 3: THE BRAIN                                                             │
│  ═══════════════════════════════╪═══════════════════════════════════════════════ │
│                                 │                                               │
│                                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                          BRAIN CORE                                      │   │
│  │                                                                          │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │   │
│  │  │    MEMORY         │  │   PERSONALITY     │  │   CONTEXT BUILDER    │   │   │
│  │  │                   │  │                   │  │                      │   │   │
│  │  │ - Conversation    │  │ - System prompt   │  │ - Current message    │   │   │
│  │  │   history (last   │  │   (who RAVEN is)  │  │ - Relevant memories  │   │   │
│  │  │   100 messages)   │  │ - Tone, humor,    │  │ - Sensor state       │   │   │
│  │  │ - Long-term facts │  │   speaking style  │  │ - Time of day        │   │   │
│  │  │   about user      │  │ - User-specific   │  │ - User's recent      │   │   │
│  │  │   (pgvector       │  │   adaptations     │  │   activity           │   │   │
│  │  │    semantic search)│  │ - Mood awareness  │  │ - Available tools    │   │   │
│  │  │ - User preferences│  │                   │  │ - Device states      │   │   │
│  │  │ - Past tool usage │  │                   │  │                      │   │   │
│  │  └────────┬─────────┘  └────────┬──────────┘  └──────────┬───────────┘   │   │
│  │           │                     │                         │               │   │
│  │           └─────────────────────┼─────────────────────────┘               │   │
│  │                                 │                                         │   │
│  │                                 ▼                                         │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐     │   │
│  │  │                     LLM ENGINE                                   │     │   │
│  │  │                                                                  │     │   │
│  │  │  Model: Mistral 7B Instruct (AWQ 4-bit) via vLLM               │     │   │
│  │  │  + LoRA adapter for RAVEN personality                           │     │   │
│  │  │  + Tool-calling format (function calling)                       │     │   │
│  │  │  + Streaming token output                                       │     │   │
│  │  │                                                                  │     │   │
│  │  │  Input:  system_prompt + memories + context + user_message      │     │   │
│  │  │  Output: text response AND/OR tool_call(s)                      │     │   │
│  │  └──────────────────────────┬───────────────────────────────────────┘     │   │
│  │                             │                                             │   │
│  │                     ┌───────┴───────┐                                     │   │
│  │                     │               │                                     │   │
│  │                text response    tool_call                                 │   │
│  │                     │               │                                     │   │
│  │                     │               ▼                                     │   │
│  │                     │    ┌──────────────────────┐                         │   │
│  │                     │    │   TOOL EXECUTOR       │                         │   │
│  │                     │    │                       │                         │   │
│  │                     │    │  - web_search         │                         │   │
│  │                     │    │  - run_code           │                         │   │
│  │                     │    │  - read_url           │                         │   │
│  │                     │    │  - smart_home         │                         │   │
│  │                     │    │  - get_weather        │                         │   │
│  │                     │    │  - set_reminder       │                         │   │
│  │                     │    │  - read_sensor        │                         │   │
│  │                     │    │  - take_photo         │                         │   │
│  │                     │    │  - play_music         │                         │   │
│  │                     │    │  - calculate          │                         │   │
│  │                     │    │  - ... (plugins)      │                         │   │
│  │                     │    └──────────┬────────────┘                         │   │
│  │                     │               │ result                               │   │
│  │                     │               ▼                                     │   │
│  │                     │    Tool result fed back to LLM                      │   │
│  │                     │    for final response generation                    │   │
│  │                     │               │                                     │   │
│  │                     ▼               ▼                                     │   │
│  │              ┌────────────────────────────────────┐                       │   │
│  │              │        RESPONSE FORMATTER           │                       │   │
│  │              │                                     │                       │   │
│  │              │  Adapts response for platform:      │                       │   │
│  │              │  - Telegram: Markdown, inline btns  │                       │   │
│  │              │  - Discord: Embeds, reactions       │                       │   │
│  │              │  - WhatsApp: Plain text             │                       │   │
│  │              │  - Voice: Send to TTS               │                       │   │
│  │              │  - Web: Rich HTML                   │                       │   │
│  │              └──────────────┬──────────────────────┘                       │   │
│  │                             │                                             │   │
│  └─────────────────────────────┼─────────────────────────────────────────────┘   │
│                                │                                                │
│  ══════════════════════════════╪════════════════════════════════════════════════ │
│  LAYER 4: VOICE ENGINE                                                          │
│  ══════════════════════════════╪════════════════════════════════════════════════ │
│                                │                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                                                                          │   │
│  │  ┌─────────────┐       ┌──────────────┐       ┌─────────────────────┐   │   │
│  │  │  STT Engine  │       │  TTS Engine   │       │  Audio I/O Manager  │   │   │
│  │  │              │       │               │       │                     │   │   │
│  │  │ faster-      │       │ Piper (fast)  │       │ - PyAudio / sound-  │   │   │
│  │  │ whisper      │       │ or            │       │   device for local  │   │   │
│  │  │ (medium,     │       │ XTTS v2       │       │   mic/speaker       │   │   │
│  │  │  INT8)       │       │ (cloned voice)│       │ - Discord voice     │   │   │
│  │  │              │       │               │       │   client (opus)     │   │   │
│  │  │ Handles:     │       │ Handles:      │       │ - Telegram voice    │   │   │
│  │  │ - Voice notes│       │ - Generate    │       │   note download/    │   │   │
│  │  │   (all plat) │       │   speech from │       │   upload (ogg)      │   │   │
│  │  │ - Live mic   │       │   text        │       │ - WhatsApp voice    │   │   │
│  │  │ - Discord    │       │ - Stream to   │       │   message (ogg)     │   │   │
│  │  │   voice ch   │       │   speaker or  │       │                     │   │   │
│  │  │              │       │   encode to   │       │                     │   │   │
│  │  │              │       │   ogg/opus    │       │                     │   │   │
│  │  └──────────────┘       └──────────────┘       └─────────────────────┘   │   │
│  │                                                                          │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│  LAYER 5: SENSOR NETWORK & SMART HOME                                           │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                                                                          │   │
│  │  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────────┐  │   │
│  │  │ MQTT Listener │  │  Sensor Manager   │  │  Smart Home Bridge       │  │   │
│  │  │               │  │                   │  │                          │  │   │
│  │  │ Subscribes to │  │ - Track all       │  │ - Home Assistant API     │  │   │
│  │  │ sensor topics │  │   sensor values   │  │ - Direct MQTT control    │  │   │
│  │  │               │  │ - Detect anomaly  │  │ - Device registry        │  │   │
│  │  │ ESP32, RPi,   │  │   (temp spike,    │  │ - Action confirmation    │  │   │
│  │  │ Zigbee, etc   │  │    motion at      │  │                          │  │   │
│  │  │               │  │    odd hour)      │  │                          │  │   │
│  │  │               │  │ - Push alerts     │  │                          │  │   │
│  │  │               │  │   to brain        │  │                          │  │   │
│  │  └──────────────┘  └──────────────────┘  └───────────────────────────┘  │   │
│  │                                                                          │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│  LAYER 6: DATA STORES                                                           │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│                                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐     │
│  │ PostgreSQL   │  │ Redis        │  │ SQLite       │  │ File System     │     │
│  │ + pgvector   │  │              │  │ (optional    │  │                 │     │
│  │              │  │ - Active     │  │  lightweight │  │ - Voice note    │     │
│  │ - Users      │  │   sessions  │  │  alternative)│  │   cache         │     │
│  │ - Memories   │  │ - Rate      │  │              │  │ - Generated     │     │
│  │ - Convos     │  │   limits    │  │              │  │   TTS audio     │     │
│  │ - Devices    │  │ - Sensor    │  │              │  │ - User uploads  │     │
│  │ - Embeddings │  │   latest    │  │              │  │ - Model cache   │     │
│  │ - Preferences│  │   values    │  │              │  │                 │     │
│  │ - Audit log  │  │ - Pub/Sub   │  │              │  │                 │     │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────────┘     │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Process Lifecycle

The RAVEN bot server runs as a **single Python process** with async coroutines
for each connector. This is simpler and more reliable than microservices for a
1-2 person team.

```python
# main.py -- conceptual entry point
import asyncio
from raven.brain import RavenBrain
from raven.connectors.telegram import TelegramConnector
from raven.connectors.discord import DiscordConnector
from raven.connectors.whatsapp import WhatsAppConnector
from raven.connectors.voice_io import VoiceIOConnector
from raven.connectors.web_api import WebAPIConnector
from raven.sensors.mqtt_listener import MQTTSensorListener
from raven.scheduler import RavenScheduler

async def main():
    # Initialize the brain (loads LLM, memory, tools)
    brain = RavenBrain()
    await brain.initialize()

    # Start all connectors concurrently
    connectors = [
        TelegramConnector(brain, token=config.TELEGRAM_TOKEN),
        DiscordConnector(brain, token=config.DISCORD_TOKEN),
        WhatsAppConnector(brain, bridge_url=config.WA_BRIDGE_URL),
        VoiceIOConnector(brain, mic_device=config.MIC_DEVICE,
                         speaker_device=config.SPEAKER_DEVICE),
        WebAPIConnector(brain, port=config.WEB_PORT),
    ]

    # Start sensor network
    sensors = MQTTSensorListener(brain, broker=config.MQTT_BROKER)

    # Start scheduler (reminders, alarms, routines)
    scheduler = RavenScheduler(brain)

    # Run everything
    await asyncio.gather(
        *[c.start() for c in connectors],
        sensors.start(),
        scheduler.start(),
        brain.run_background_tasks(),
    )

if __name__ == "__main__":
    asyncio.run(main())
```

### Why Single Process, Not Microservices

| Factor | Single Process | Microservices |
|---|---|---|
| Complexity | Low | High (networking, service mesh) |
| Team size needed | 1 person | 3+ people |
| Latency | Zero network hops | Multiple hops |
| Memory sharing | Direct (shared brain) | Serialization overhead |
| Deployment | `python main.py` | Docker Compose / K8s |
| Debugging | Normal Python debugger | Distributed tracing |
| Failure modes | Process crash = restart | Partial failures everywhere |

For a personal bot, a single process is the right choice. If you later need to scale
to thousands of users, you can split the brain into a service -- but that's a future
problem.

**Exception:** The WhatsApp connector runs in a separate Node.js process (Baileys)
because WhatsApp libraries are JavaScript-only. It communicates with the main Python
process via a local HTTP bridge.

---

## Unified Message Format

Every platform connector normalizes incoming messages into a single format:

```python
@dataclass
class IncomingMessage:
    """Platform-agnostic message from any source."""

    id: str                          # Unique message ID
    source: str                      # "telegram", "discord", "whatsapp", "voice", "web"
    user_id: str                     # Internal user ID (mapped from platform ID)
    platform_user_id: str            # Platform-specific ID (Telegram chat_id, etc.)

    input_type: str                  # "text", "voice", "image", "file", "command"
    text: str | None                 # Text content (or transcribed voice)
    audio_path: str | None           # Path to voice note file (pre-STT)
    image_path: str | None           # Path to image file
    file_path: str | None            # Path to uploaded file

    # Platform-specific context (for routing replies)
    reply_context: ReplyContext

    timestamp: datetime
    is_voice: bool = False           # True if this came from speech (voice note or mic)

@dataclass
class ReplyContext:
    """Everything needed to send a reply back on the same platform."""
    platform: str
    chat_id: str                     # Telegram chat ID, Discord channel ID, etc.
    guild_id: str | None             # Discord server ID
    reply_to_message_id: str | None  # For threaded replies
    voice_channel_id: str | None     # For Discord voice
    supports_markdown: bool
    supports_voice_reply: bool
    supports_images: bool
    supports_buttons: bool

@dataclass
class OutgoingMessage:
    """Platform-agnostic response."""

    text: str
    voice_audio_path: str | None = None  # TTS-generated audio file
    image_path: str | None = None
    buttons: list[dict] | None = None    # Inline buttons (Telegram/Discord)
    embed: dict | None = None            # Rich embed (Discord)
    reply_to: ReplyContext | None = None  # Where to send this
```

---

## Database Schema

```sql
-- Users (mapped from platform identities)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(255),
    telegram_id BIGINT UNIQUE,
    discord_id BIGINT UNIQUE,
    whatsapp_id VARCHAR(50) UNIQUE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Conversation history (all platforms, unified)
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    source VARCHAR(20) NOT NULL,          -- telegram, discord, etc.
    role VARCHAR(20) NOT NULL,            -- user, assistant, system, tool
    content TEXT NOT NULL,
    tool_calls JSONB,                     -- tool calls made in this turn
    tool_results JSONB,                   -- results from tool execution
    was_voice BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_conv_user_time ON conversations(user_id, timestamp DESC);

-- Long-term memory (semantic search via pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    content TEXT NOT NULL,                -- "User prefers dark mode"
    category VARCHAR(50),                 -- "preference", "fact", "event", "emotion"
    embedding vector(384) NOT NULL,       -- Sentence embedding for semantic search
    importance FLOAT DEFAULT 0.5,         -- 0-1, how important this memory is
    last_accessed TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_memories_embedding ON memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Sensor readings
CREATE TABLE sensor_readings (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(255) NOT NULL REFERENCES devices(device_id),
    sensor_type VARCHAR(100) NOT NULL,     -- "temperature", "motion", "humidity"
    value DOUBLE PRECISION,
    unit VARCHAR(20),
    location VARCHAR(100),                 -- Denormalized for query speed
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sensor_time ON sensor_readings(device_id, timestamp DESC);
CREATE INDEX idx_readings_type ON sensor_readings(sensor_type, timestamp DESC);

-- Smart home / sensor devices
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(255) UNIQUE NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    device_type VARCHAR(100) NOT NULL,     -- "esp32", "rpi", "zigbee"
    location VARCHAR(100),
    connection_type VARCHAR(50),           -- "mqtt", "homeassistant", "http"
    capabilities JSONB NOT NULL DEFAULT '{}',
    sensors TEXT[],                         -- {"temperature", "humidity"}
    config JSONB DEFAULT '{}',
    firmware_version VARCHAR(50),
    is_online BOOLEAN DEFAULT FALSE,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sensor alerts (anomaly detection, threshold breaches)
CREATE TABLE sensor_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    sensor_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    current_value TEXT,
    threshold_value TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notes (user-created via create_note tool)
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled tasks (reminders, alarms, routines)
CREATE TABLE scheduled_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    task_type VARCHAR(50) NOT NULL,       -- "reminder", "alarm", "routine"
    description TEXT NOT NULL,
    trigger_time TIMESTAMPTZ,             -- When to fire
    cron_expression VARCHAR(100),         -- For recurring tasks
    target_platform VARCHAR(20),          -- Where to deliver the notification
    target_context JSONB,                 -- ReplyContext serialized
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log (safety + IoT actions)
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action_type VARCHAR(50) NOT NULL,
    details JSONB NOT NULL,
    safety_score FLOAT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Configuration

```yaml
# config.yaml

# Bot identity
bot:
  name: "RAVEN"
  wake_word: "raven"            # For microphone wake-word detection
  personality: "friendly"        # Loads personality prompt from prompts/friendly.txt
  language: "en"
  timezone: "Asia/Kolkata"

# Platform connectors
telegram:
  enabled: true
  token: "${TELEGRAM_BOT_TOKEN}"
  allowed_users: []              # Empty = allow all, or list of telegram IDs

discord:
  enabled: true
  token: "${DISCORD_BOT_TOKEN}"
  command_prefix: "!"
  voice_enabled: true

whatsapp:
  enabled: true
  bridge_url: "http://localhost:3001"  # Baileys bridge
  phone_number: "+91XXXXXXXXXX"

voice_io:
  enabled: true
  mic_device: "default"
  speaker_device: "default"
  wake_word_enabled: true
  vad_threshold: 0.5
  silence_timeout_ms: 800

web:
  enabled: true
  port: 8080
  require_auth: true

# Brain
llm:
  model: "mistralai/Mistral-7B-Instruct-v0.3"
  quantization: "awq"
  max_context_tokens: 8192
  temperature: 0.7
  gpu_memory_fraction: 0.7
  lora_adapter: "models/raven-personality-lora"

voice:
  stt_model: "medium"                    # Whisper model size
  stt_compute_type: "int8_float16"
  tts_engine: "piper"                    # "piper" or "xtts"
  tts_voice: "en_US-lessac-medium"
  tts_sample_rate: 22050

memory:
  max_conversation_history: 50           # Messages kept in context
  semantic_search_top_k: 5              # Memories retrieved per query
  embedding_model: "all-MiniLM-L6-v2"  # Sentence transformer for embeddings

# Sensors
mqtt:
  enabled: true
  broker: "localhost"
  port: 1883
  topic_prefix: "raven/sensors"

smart_home:
  enabled: true
  backend: "homeassistant"              # "homeassistant" or "mqtt_direct"
  ha_url: "http://homeassistant.local:8123"
  ha_token: "${HA_LONG_LIVED_TOKEN}"

# Tools
tools:
  web_search:
    enabled: true
    engine: "searxng"
    url: "http://localhost:8888"
  code_execution:
    enabled: true
    timeout_seconds: 30
    sandbox: true
  weather:
    enabled: true
    api: "openmeteo"                     # Free, no API key needed
  news:
    enabled: true
    sources: ["hackernews", "rss"]

# Safety
safety:
  enabled: true
  fail_closed: true
  iot_confirmation_required:
    - "unlock"
    - "disarm"
    - "open"
  max_messages_per_minute: 30
  blocked_tool_actions: ["delete_all", "format_disk"]

# Database
database:
  url: "postgresql://raven:pass@localhost:5432/raven"
  redis_url: "redis://localhost:6379/0"
```

---

## Error Handling & Resilience

```python
class RavenBrain:
    async def handle_message(self, message: IncomingMessage) -> OutgoingMessage:
        try:
            # Normal flow
            response = await self._think_and_respond(message)
            return response

        except LLMTimeoutError:
            return OutgoingMessage(
                text="Sorry, I'm thinking a bit slowly right now. Try again in a sec?"
            )

        except ToolExecutionError as e:
            return OutgoingMessage(
                text=f"I tried to {e.tool_name} but it didn't work: {e.message}. "
                     f"Want me to try something else?"
            )

        except SafetyBlockedError:
            return OutgoingMessage(
                text="I can't help with that. Let's talk about something else."
            )

        except Exception as e:
            logger.exception(f"Unexpected error handling message: {e}")
            return OutgoingMessage(
                text="Something went wrong on my end. I've logged the error. "
                     "Can you try again?"
            )
```

**Connector resilience:** Each platform connector runs in its own async task with
automatic reconnection. If Telegram's API goes down, Discord and WhatsApp keep working.

```python
class TelegramConnector:
    async def start(self):
        while True:
            try:
                await self.bot.polling(drop_pending_updates=True)
            except Exception as e:
                logger.error(f"Telegram connector crashed: {e}")
                await asyncio.sleep(5)  # Wait 5s before reconnecting
                logger.info("Reconnecting to Telegram...")
```
