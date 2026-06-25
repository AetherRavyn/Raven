# RAVEN - Your Personal AI Companion

## What RAVEN Actually Is

RAVEN is an **intelligent personal AI companion** -- a bot that acts as your friend,
assistant, and brainstorming partner. It is NOT a video calling platform. It is a
single AI entity that you can talk to from **anywhere**:

- Send it a Telegram message
- Talk to it in a Discord voice channel
- Message it on WhatsApp
- Speak to it through a microphone on any device connected to the bot server
- Interact through a web dashboard

It speaks like a **normal person** -- not robotic, not overly formal. It has personality,
remembers your conversations, knows your preferences, and gets better at helping you
over time.

---

## Core Identity

```
RAVEN is:
  ✓ A friend you can text or talk to anytime
  ✓ A brainstorming partner that thinks with you
  ✓ A tool-wielding assistant (web search, code, APIs, math, files)
  ✓ An environment-aware companion (sensors, cameras, alerts)
  ✓ A voice that sounds human, not robotic
  ✓ Present on every platform you already use
  ✓ Self-hostable on your own server

RAVEN is NOT:
  ✗ A video calling app
  ✗ A web-only chatbot
  ✗ A smart home dashboard
  ✗ A cloud-dependent SaaS product
```

---

## How You Interact With RAVEN

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                     YOU (the human)                                         ║
║                                                                             ║
║   "Hey RAVEN, help me brainstorm startup ideas"     (Telegram text)         ║
║   "RAVEN, what's the temperature in my room?"       (Discord voice)         ║
║   "Remind me to buy groceries at 5pm"               (WhatsApp message)      ║
║   "RAVEN, someone's at the door"                    (Motion sensor alert)   ║
║   "Search for the best Python async frameworks"     (Telegram command)      ║
║   "Read me the latest Hacker News headlines"        (Microphone on Pi)      ║
║                                                                             ║
╚═══════════════════════════════════════╦══════════════════════════════════════╝
                                        ║
                      All roads lead to one brain
                                        ║
                                        ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                             ║
║                          RAVEN BOT SERVER                                   ║
║                     (runs on your machine / VPS)                            ║
║                                                                             ║
║   ┌──────────────────────────────────────────────────────────────────────┐  ║
║   │                     PLATFORM CONNECTORS                              │  ║
║   │                                                                      │  ║
║   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │  ║
║   │  │ Telegram │ │ Discord  │ │ WhatsApp │ │  Mic /   │ │   Web    │ │  ║
║   │  │   Bot    │ │   Bot    │ │   Bot    │ │ Speaker  │ │Dashboard │ │  ║
║   │  │          │ │ (text +  │ │ (text +  │ │ (direct  │ │ (admin + │ │  ║
║   │  │  text +  │ │  voice   │ │  voice   │ │  voice   │ │  chat)   │ │  ║
║   │  │  voice   │ │  channel)│ │  notes)  │ │  on any  │ │          │ │  ║
║   │  │  notes)  │ │          │ │          │ │  device) │ │          │ │  ║
║   │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │  ║
║   │       │             │            │             │            │       │  ║
║   └───────┼─────────────┼────────────┼─────────────┼────────────┼───────┘  ║
║           │             │            │             │            │          ║
║           ▼             ▼            ▼             ▼            ▼          ║
║   ┌──────────────────────────────────────────────────────────────────────┐  ║
║   │                    UNIFIED MESSAGE BUS                               │  ║
║   │          (every message becomes the same format)                     │  ║
║   │                                                                      │  ║
║   │  { source: "telegram", user: "swadhin", type: "text",              │  ║
║   │    content: "help me brainstorm startup ideas",                     │  ║
║   │    context: { chat_id, timestamp, reply_to, ... } }                 │  ║
║   └──────────────────────────────┬───────────────────────────────────────┘  ║
║                                  │                                         ║
║                                  ▼                                         ║
║   ┌──────────────────────────────────────────────────────────────────────┐  ║
║   │                       RAVEN BRAIN                                    │  ║
║   │                                                                      │  ║
║   │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐                │  ║
║   │  │  Memory      │  │  Personality │  │  Tool Router  │                │  ║
║   │  │  (who you    │  │  (how RAVEN  │  │  (what RAVEN  │                │  ║
║   │  │   are, past  │  │   talks,     │  │   can do)     │                │  ║
║   │  │   convos,    │  │   jokes,     │  │               │                │  ║
║   │  │   prefs)     │  │   style)     │  │  web_search   │                │  ║
║   │  │              │  │              │  │  run_code     │                │  ║
║   │  └──────┬───────┘  └──────┬───────┘  │  read_url   │                │  ║
║   │         │                 │           │  smart_home   │                │  ║
║   │         ▼                 ▼           │  calendar     │                │  ║
║   │  ┌──────────────────────────────┐    │  reminder     │                │  ║
║   │  │         LLM ENGINE           │    │  math         │                │  ║
║   │  │  (Mistral / LLaMA / custom)  │◄───│  wikipedia    │                │  ║
║   │  │  + LoRA for personality      │    │  weather      │                │  ║
║   │  │  + Tool calling              │    │  news         │                │  ║
║   │  │  + Streaming                 │    │  ...plugins   │                │  ║
║   │  └──────────────┬───────────────┘    └──────────────┘                │  ║
║   │                 │                                                     │  ║
║   └─────────────────┼─────────────────────────────────────────────────────┘  ║
║                     │                                                       ║
║                     ▼                                                       ║
║   ┌──────────────────────────────────────────────────────────────────────┐  ║
║   │                    VOICE ENGINE                                       │  ║
║   │  STT (hear) ◄──► Brain ◄──► TTS (speak)                             │  ║
║   │  Whisper          │         Piper / XTTS                             │  ║
║   │                   │                                                   │  ║
║   │  Speaks back on whichever platform the user talked from              │  ║
║   └──────────────────────────────────────────────────────────────────────┘  ║
║                                                                             ║
║   ┌──────────────────────────────────────────────────────────────────────┐  ║
║   │                    SENSOR NETWORK                                     │  ║
║   │                                                                      │  ║
║   │  Temperature ──┐                                                     │  ║
║   │  Motion ───────┤                                                     │  ║
║   │  Door sensor ──┼──▶ RAVEN decides what's important ──▶ Alerts you   │  ║
║   │  Camera ───────┤       on Telegram/Discord/Speaker                   │  ║
║   │  Smoke ────────┤                                                     │  ║
║   │  Humidity ─────┘                                                     │  ║
║   │                                                                      │  ║
║   └──────────────────────────────────────────────────────────────────────┘  ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Example Day With RAVEN

```
07:00  [RAVEN → Telegram]
       "Good morning! It's 22°C outside, partly cloudy.
        You have 2 meetings today: standup at 10am, design review at 3pm.
        Want me to read you the news while you get ready?"

07:05  [You → Microphone (kitchen speaker)]
       "Yeah, what's on Hacker News?"

07:05  [RAVEN → Kitchen speaker]
       "Top stories: First one -- 'Rust in the Linux kernel reaches 1.0'...
        Second -- 'Show HN: I built a self-hosted Notion alternative'...
        Want me to save any of these for later?"

09:30  [You → Telegram]
       "RAVEN, help me brainstorm features for the new dashboard"

09:30  [RAVEN → Telegram]
       "Sure! Let's think about this. Who's the primary user?
        Are we talking internal team or customers?
        And what's the one thing the current dashboard is missing?"

       ... (back-and-forth brainstorming) ...

09:45  [RAVEN → Telegram]
       "Here's what we've landed on:
        1. Real-time activity feed (top request from users)
        2. Customizable widget grid
        3. Export to PDF/CSV
        4. Dark mode (finally 😄)
        Want me to draft a PRD from this?"

14:00  [RAVEN → Telegram alert]
       "🚨 Motion detected at front door. No one's home.
        Camera snapshot: looks like a delivery person.
        Want me to keep watching?"

17:00  [You → Discord voice channel]
       "RAVEN, I'm stuck on this Python async bug.
        The task keeps getting cancelled."

17:00  [RAVEN → Discord voice]
       "Okay, can you paste the error or describe what's happening?
        Common causes are: the task isn't being awaited, or the event
        loop is closing before it finishes. Are you using asyncio.gather
        or TaskGroup?"

22:00  [You → WhatsApp]
       "set an alarm for 6:30 tomorrow"

22:00  [RAVEN → WhatsApp]
       "Done. Alarm set for 6:30 AM. Good night! 🌙"
```

---

## Technology Stack Summary

| Component | Technology | Why |
|---|---|---|
| **Bot framework** | Custom Python (asyncio) | Unified control over all platforms |
| **Telegram** | python-telegram-bot / Telethon | Voice notes, text, files, inline |
| **Discord** | discord.py + voice support | Voice channels, text, servers |
| **WhatsApp** | Baileys (Node.js bridge) | Free, no Business API needed |
| **Voice input** | Whisper (faster-whisper) | Best open-source STT |
| **Voice output** | Piper TTS / XTTS v2 | Natural voice, fast, self-hosted |
| **LLM brain** | Mistral 7B / LLaMA 3 8B (vLLM) | Open-weight, tool calling, fast |
| **Memory** | PostgreSQL + pgvector | Long-term memory with semantic search |
| **Tools** | Plugin system (Python) | Extensible, sandboxed |
| **Sensors** | MQTT + ESP32 / Raspberry Pi | Cheap, reliable, wireless |
| **Smart home** | Home Assistant API / MQTT | Control any device |
| **Search** | SearXNG (self-hosted) | Private web search |
| **Scheduler** | APScheduler | Reminders, alarms, routines |
| **Cache** | Redis | Session state, rate limits |
| **Monitoring** | Prometheus + Grafana | Bot health, latency, usage |

---

## Document Index

| # | Document | What It Covers |
|---|---|---|
| 00 | [This file](./00-overview.md) | What RAVEN is, interaction examples, stack overview |
| 01 | [System Architecture](./01-system-architecture.md) | Bot server design, message bus, brain architecture |
| 02 | [Platform Connectors](./02-platform-connectors.md) | Telegram, Discord, WhatsApp, mic/speaker, web |
| 03 | [Voice & Personality](./03-voice-personality.md) | Natural speech, personality system, memory |
| 04 | [Tools Ecosystem](./04-tools-ecosystem.md) | All tools RAVEN can use, plugin system |
| 05 | [Sensor Awareness](./05-sensor-awareness.md) | IoT sensors, environment scanning, alerts |
| 06 | [Safety & Moderation](./06-safety-moderation.md) | Content safety, IoT safety, abuse prevention |
| 07 | [ML Depth](./07-ml-depth.md) | Models trained, datasets, experiments |
| 08 | [Deployment](./08-deployment-scaling.md) | Self-hosting, cloud, costs |
| 09 | [Repo & Resume](./09-repository-structure.md) | GitHub structure, resume bullet points |

---

## Milestone Roadmap (1-2 Engineers)

| Phase | Weeks | Deliverable |
|---|---|---|
| **M1: Brain + Telegram** | 1-3 | LLM brain with memory, Telegram text bot working |
| **M2: Voice** | 4-6 | STT + TTS, voice notes on Telegram, mic/speaker on server |
| **M3: Tools** | 7-9 | Web search, code execution, file reading, reminders |
| **M4: Discord + WhatsApp** | 10-12 | Multi-platform, Discord voice channels |
| **M5: Sensors + Smart Home** | 13-16 | MQTT sensors, alerts, Home Assistant integration |
| **M6: ML + Personality** | 17-20 | Fine-tune models, personality training, evaluation |
| **M7: Polish + Deploy** | 21-24 | Monitoring, safety hardening, documentation |
