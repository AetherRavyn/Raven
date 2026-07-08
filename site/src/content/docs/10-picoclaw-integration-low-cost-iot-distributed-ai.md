---
title: "10 - PicoClaw Integration- Low-Cost IoT & Distributed AI Strategy"
---

# 10 - PicoClaw Integration: Low-Cost IoT & Distributed AI Strategy

## Executive Summary

This document analyzes [PicoClaw](https://github.com/sipeed/picoclaw) -- an ultra-lightweight
AI assistant written in Go that runs on $10 hardware with <10MB RAM -- and proposes how RAVEN
can adopt its strategies to dramatically reduce IoT management costs. It also explores using
phone processing power as distributed AI compute nodes, enabling RAVEN to run AI workloads
across multiple devices without expensive centralized servers.

**Key takeaways:**

- PicoClaw proves AI agents can run on $10 SBCs (LicheeRV-Nano, NanoKVM) by being a thin
  Go binary that offloads inference to cloud LLM APIs
- RAVEN can adopt a hybrid architecture: lightweight Go/Rust edge agents on cheap boards +
  Python brain on a central server + phone-based compute for local AI inference
- A phone's GPU (Snapdragon 8 Gen 3 = 45 TOPS NPU) rivals entry-level cloud GPU instances
  for inference workloads
- Total IoT node cost can drop from ~$50/node (RPi + sensors) to ~$12/node (ESP32-S3 +
  PicoClaw-style agent on LicheeRV-Nano)

---

## Part 1: PicoClaw Architecture Analysis

### 1.1 What PicoClaw Actually Is

PicoClaw is **not** a microcontroller firmware project. It is a **pure software AI agent
written in Go** that compiles to a single static binary. The "cheapness" comes from the
binary being so lightweight (<10MB RAM, 1-second boot on 0.6GHz) that it runs on ultra-cheap
Linux SBCs.

```
PicoClaw Architecture:
                                                                           
  ┌──────────────────────────────────────────────────────────────────────┐
  │                   $10 Linux SBC (LicheeRV-Nano)                      │
  │                                                                      │
  │   ┌──────────────────────────────────────────────────────────────┐   │
  │   │               PicoClaw Binary (~15MB on disk)                │   │
  │   │                                                              │   │
  │   │  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌────────────┐ │   │
  │   │  │  Agent   │  │  Tool    │  │  Channel   │  │  Session   │ │   │
  │   │  │  Loop    │  │ Registry │  │  Manager   │  │  Manager   │ │   │
  │   │  │          │  │          │  │            │  │            │ │   │
  │   │  │  LLM     │  │ read_file│  │ Telegram   │  │  JSON      │ │   │
  │   │  │  iterate │  │ exec     │  │ Discord    │  │  files     │ │   │
  │   │  │  tools   │  │ web      │  │ MaixCam    │  │            │ │   │
  │   │  │  respond │  │ cron     │  │ WhatsApp   │  │            │ │   │
  │   │  └─────────┘  └──────────┘  └────────────┘  └────────────┘ │   │
  │   │                      │                                       │   │
  │   │              ┌───────▼───────┐                               │   │
  │   │              │  Message Bus  │                               │   │
  │   │              │  (in-process) │                               │   │
  │   │              └───────────────┘                               │   │
  │   └──────────────────────────────────────────────────────────────┘   │
  └──────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTPS API calls
                                     ▼
                          ┌──────────────────────┐
                          │  Cloud LLM Providers  │
                          │  OpenRouter / Zhipu   │
                          │  Groq / Anthropic     │
                          │  (AI runs HERE)       │
                          └──────────────────────┘
```

### 1.2 How PicoClaw Achieves Low Cost

| Strategy | Implementation | Cost Impact |
|---|---|---|
| **Language choice: Go** | Single static binary, no runtime dependencies, no Python/Node.js interpreter | Eliminates 100-500MB runtime overhead |
| **No on-device AI** | All inference offloaded to cloud APIs (OpenRouter, Zhipu free tiers) | No GPU needed on device |
| **Minimal dependencies** | Only 14 direct Go dependencies (vs hundreds in Python/Node projects) | Tiny binary size |
| **JSON file storage** | Sessions/memory stored as flat JSON files, no PostgreSQL/Redis | No database overhead |
| **In-process message bus** | Go channels instead of external message broker | No MQTT/Redis for internal routing |
| **Single binary deployment** | `go build` produces one executable, copy to device and run | No Docker, no package manager |
| **Cross-compilation** | Build for RISC-V/ARM64/x86 from any machine with `GOOS=linux GOARCH=riscv64` | One Makefile for all platforms |
| **Free LLM tiers** | Zhipu (200K tokens/month free), OpenRouter (200K tokens/month free), Groq (free tier) | $0/month for light usage |

**Comparison: PicoClaw vs RAVEN current plan**

| Resource | PicoClaw | RAVEN (Planned) | Difference |
|---|---|---|---|
| RAM | <10MB | >4GB (vLLM + Python + PostgreSQL + Redis) | 400x less |
| Storage | ~50MB | >20GB (models + databases) | 400x less |
| CPU | 0.6GHz single core | 4+ cores recommended | 6x less |
| Boot time | <1s | >30s | 30x faster |
| Hardware cost | $10 (LicheeRV-Nano) | $599+ (Mac Mini) or $30+/month VPS | 60x cheaper |
| Monthly cloud cost | $0 (free tiers) | $0 (self-hosted models) | Equal |

### 1.3 Key Source Code Patterns Worth Adopting

**Agent Loop Pattern** (from `pkg/agent/loop.go:230-290`):

PicoClaw's agent loop is remarkably simple -- 60 lines of core logic:

```
1. Update tool contexts (channel, chatID)
2. Build messages (history + summary + user message)
3. Save user message to session
4. Run LLM iteration loop (max 20 iterations)
   - Call LLM with tools
   - If no tool calls → done
   - Execute tool calls → append results → loop
5. Handle empty response
6. Save assistant message
7. Maybe summarize (if >20 messages or >75% context window)
8. Optionally send response via bus
```

**MaixCam IoT Channel** (from `pkg/channels/maixcam.go`):

PicoClaw has a TCP server that accepts JSON from MaixCam devices. This is the closest
thing to IoT integration -- the device does person detection on-board and sends structured
events to PicoClaw:

```go
type MaixCamMessage struct {
    Type      string                 `json:"type"`      // "person_detected", "heartbeat", "status"
    Tips      string                 `json:"tips"`
    Timestamp float64                `json:"timestamp"`
    Data      map[string]interface{} `json:"data"`      // class_name, score, x, y, w, h
}
```

This shows the pattern: **smart edge device does heavy processing (vision AI) locally,
sends lightweight structured events to the central agent.**

**Context Window Summarization** (from `pkg/agent/loop.go:446-632`):

PicoClaw automatically summarizes conversation history when it exceeds thresholds,
using multi-part summarization for long histories. This keeps memory usage bounded
even on tiny devices.

---

## Part 2: Integration Strategy for RAVEN

### 2.1 Proposed Hybrid Architecture

Instead of choosing between PicoClaw's thin-client model and RAVEN's full-stack model,
we propose a **three-tier hybrid architecture**:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         TIER 1: EDGE NODES ($10-15/node)                   │
│                                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ LicheeRV-Nano│  │ ESP32-S3     │  │ ESP32-C3     │  │ MaixCAM      │  │
│  │ + sensors    │  │ + DHT22      │  │ + PIR        │  │ (camera +    │  │
│  │              │  │ + MQ-135     │  │ + reed sw    │  │  person det) │  │
│  │ Runs:        │  │              │  │              │  │              │  │
│  │ raven-edge   │  │ Runs:        │  │ Runs:        │  │ Runs:        │  │
│  │ (Go binary)  │  │ MicroPython  │  │ Arduino FW   │  │ MaixPy       │  │
│  │              │  │ MQTT publish  │  │ MQTT publish  │  │ TCP→PicoClaw │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │                  │          │
│         │  WiFi/Ethernet  │  WiFi            │  WiFi            │  WiFi   │
│         └────────┬────────┴──────────┬───────┴──────────┬───────┘          │
│                  │                   │                   │                  │
└──────────────────┼───────────────────┼───────────────────┼──────────────────┘
                   │                   │                   │
                   ▼                   ▼                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    TIER 2: RAVEN BRAIN (Central Server / VPS)               │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    RAVEN Core (Python asyncio)                      │    │
│  │                                                                    │    │
│  │  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │ Brain   │ │ Sensor   │ │ Platform  │ │ Voice    │ │ Safety │ │    │
│  │  │ (LLM)   │ │ Manager  │ │ Connectors│ │ Engine   │ │ Layer  │ │    │
│  │  └─────────┘ └──────────┘ └───────────┘ └──────────┘ └────────┘ │    │
│  │                                                                    │    │
│  │  ┌─────────┐ ┌──────────┐ ┌───────────┐                          │    │
│  │  │ MQTT    │ │PostgreSQL│ │ Redis     │                          │    │
│  │  │ Broker  │ │+ pgvector│ │ Cache     │                          │    │
│  │  └─────────┘ └──────────┘ └───────────┘                          │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │           raven-edge-gateway (Go binary, PicoClaw-inspired)        │    │
│  │  Lightweight Go service that bridges edge nodes to RAVEN core      │    │
│  │  - Accepts TCP connections from LicheeRV-Nano / MaixCAM nodes     │    │
│  │  - Translates edge events → MQTT messages for RAVEN sensor layer  │    │
│  │  - Provides OTA firmware updates to edge nodes                    │    │
│  │  - Manages device registry and health monitoring                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────┘
                   │
                   │ Distribute inference tasks
                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                 TIER 3: DISTRIBUTED COMPUTE (Phones + PCs)                 │
│                                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Android Phone│  │ iPhone       │  │ Old Laptop   │  │ Gaming PC    │  │
│  │ Snapdragon   │  │ A17 Pro      │  │ with GPU     │  │ RTX 3060     │  │
│  │ 8 Gen 3      │  │ 35 TOPS      │  │              │  │              │  │
│  │ 45 TOPS NPU  │  │ Neural Engine│  │ Runs:        │  │ Runs:        │  │
│  │              │  │              │  │ raven-worker  │  │ raven-worker │  │
│  │ Runs:        │  │ Runs:        │  │ (vLLM/       │  │ (vLLM/       │  │
│  │ raven-worker │  │ raven-worker │  │  llama.cpp)  │  │  llama.cpp)  │  │
│  │ (MLC-LLM /  │  │ (MLX /       │  │              │  │              │  │
│  │  llama.cpp)  │  │  Core ML)    │  │              │  │              │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                                            │
│  Each device registers with RAVEN brain and advertises its capabilities:   │
│  - Available TOPS/TFLOPS                                                   │
│  - Available RAM for model loading                                         │
│  - Battery level (phones) / power state                                    │
│  - Network latency to RAVEN brain                                          │
│  - Currently loaded models                                                 │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Cost Comparison: Before vs After

| Component | Current RAVEN Plan | After PicoClaw Integration | Savings |
|---|---|---|---|
| IoT sensor node (temp/humidity) | $35 (RPi Zero W + DHT22 + case) | $7 (ESP32-C3 + DHT22) | 80% |
| IoT gateway / coordinator | $50+ (RPi 4 or VPS) | $10 (LicheeRV-Nano running raven-edge) | 80% |
| Motion detection camera | $100+ (IP camera + NVR) | $50 (MaixCAM with on-device AI) | 50% |
| AI inference server | $599 (Mac Mini) or $30/month VPS with GPU | $0 (use phones + free cloud tiers) | 100% |
| Total 5-node IoT setup | ~$375 | ~$95 | **75% reduction** |

### 2.3 What to Build: raven-edge (Go Binary)

Inspired by PicoClaw, we build a lightweight Go binary called `raven-edge` that runs on
$10 Linux SBCs. This replaces the need for a full RAVEN installation on every IoT node.

**Responsibilities:**

1. **Sensor data collection** -- read from local GPIO/I2C/SPI sensors
2. **Local anomaly detection** -- threshold checks without calling the brain
3. **MQTT bridge** -- publish sensor readings to RAVEN brain's MQTT broker
4. **Edge AI inference** -- run tiny models (wake word, simple classification) on-device
5. **OTA updates** -- accept firmware updates from RAVEN brain
6. **Heartbeat** -- report health status to RAVEN brain

**Proposed module structure:**

```
raven-edge/
├── cmd/
│   └── raven-edge/
│       └── main.go              # Entry point, CLI
├── pkg/
│   ├── sensors/
│   │   ├── dht.go               # DHT22/BME280 temperature/humidity
│   │   ├── pir.go               # PIR motion sensor
│   │   ├── gas.go               # MQ-2/MQ-135 gas sensor
│   │   ├── gpio.go              # Generic GPIO reader
│   │   └── registry.go          # Sensor auto-discovery
│   ├── mqtt/
│   │   ├── client.go            # MQTT publish/subscribe
│   │   └── topics.go            # Topic naming conventions
│   ├── anomaly/
│   │   ├── threshold.go         # Simple threshold checks
│   │   └── rate.go              # Rate-of-change detection
│   ├── config/
│   │   └── config.go            # JSON config (PicoClaw-style)
│   ├── heartbeat/
│   │   └── service.go           # Health reporting
│   └── ota/
│       └── updater.go           # Self-update mechanism
├── Makefile                      # Cross-compile for RISC-V, ARM64, x86
└── go.mod
```

**Target hardware for raven-edge:**

| Board | Price | CPU | RAM | WiFi | Best For |
|---|---|---|---|---|---|
| LicheeRV-Nano | $9.90 | RISC-V 1GHz | 64MB DDR3 | Optional (WiFi6) | Sensor gateway |
| ESP32-S3 (with Linux) | $4 | Xtensa 240MHz | 512KB SRAM | Yes | Direct sensor node |
| NanoKVM | $30 | RISC-V 1GHz | 256MB | Yes | Server monitoring |
| MaixCAM | $50 | RISC-V 1GHz + 1 TOPS NPU | 256MB | Yes | Vision AI + sensors |

---

## Part 3: Using Phone Processing Power for Distributed AI

### 3.1 Why Phones Are Viable AI Compute Nodes

Modern smartphones have more AI compute power than most people realize:

| Device | NPU/Neural Engine | GPU | RAM | Equivalent Cloud Cost |
|---|---|---|---|---|
| Snapdragon 8 Gen 3 | 45 TOPS | Adreno 750 (4.6 TFLOPS) | 8-16GB | ~$0.50/hr GPU instance |
| Apple A17 Pro | 35 TOPS | 6-core GPU | 8GB | ~$0.40/hr GPU instance |
| Google Tensor G3 | 25+ TOPS | Mali-G715 | 12GB | ~$0.30/hr GPU instance |
| Samsung Exynos 2400 | 34.7 TOPS | Xclipse 940 | 8-12GB | ~$0.35/hr GPU instance |
| Snapdragon 7 Gen 2 (mid-range) | 13 TOPS | Adreno 725 | 6-8GB | ~$0.15/hr GPU instance |
| MediaTek Dimensity 9300 | 41.6 TOPS | Immortalis-G720 | 12-16GB | ~$0.45/hr GPU instance |

**What a phone can run right now (2026):**

- Llama 3.2 1B/3B (int4): 30-60 tokens/second on flagship phones
- Phi-3 mini (3.8B, int4): 15-25 tokens/second
- Whisper tiny/base: real-time STT
- Piper TTS: real-time speech synthesis
- MobileNet/YOLO: 30+ FPS object detection
- all-MiniLM-L6-v2: <10ms per embedding

### 3.2 Distributed AI Architecture: "RAVEN Compute Mesh"

We propose a distributed compute system called **RAVEN Compute Mesh** where any device
(phone, laptop, desktop, SBC) can contribute processing power to RAVEN.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                      RAVEN COMPUTE MESH ARCHITECTURE                       │
│                                                                            │
│                    ┌──────────────────────────┐                            │
│                    │    RAVEN Brain (Server)    │                            │
│                    │                            │                            │
│                    │  ┌────────────────────┐   │                            │
│                    │  │  Task Scheduler     │   │                            │
│                    │  │  - Queue inference  │   │                            │
│                    │  │  - Route to best    │   │                            │
│                    │  │    available worker  │   │                            │
│                    │  │  - Fallback chain   │   │                            │
│                    │  └─────────┬──────────┘   │                            │
│                    │            │               │                            │
│                    │  ┌─────────▼──────────┐   │                            │
│                    │  │  Worker Registry    │   │                            │
│                    │  │  - Device caps      │   │                            │
│                    │  │  - Loaded models    │   │                            │
│                    │  │  - Battery/power    │   │                            │
│                    │  │  - Latency          │   │                            │
│                    │  │  - Availability     │   │                            │
│                    │  └────────────────────┘   │                            │
│                    └───────────┬────────────────┘                            │
│                                │                                             │
│              ┌─────────────────┼─────────────────┐                          │
│              │                 │                   │                          │
│              ▼                 ▼                   ▼                          │
│  ┌───────────────────┐ ┌──────────────┐ ┌─────────────────┐                │
│  │  Phone Worker      │ │ Laptop Worker│ │ Cloud Fallback   │                │
│  │  (raven-worker)    │ │ (raven-worker│ │ (OpenRouter /    │                │
│  │                    │ │  + llama.cpp)│ │  Groq free tier) │                │
│  │  Capabilities:     │ │              │ │                   │                │
│  │  - whisper-tiny    │ │ Capabilities:│ │  Capabilities:    │                │
│  │  - phi-3-mini-int4 │ │ - llama-3-8B │ │  - Any model      │                │
│  │  - piper-tts       │ │ - whisper-med│ │  - Unlimited       │                │
│  │  - embeddings      │ │ - vllm       │ │  - Costs $$        │                │
│  │                    │ │              │ │                   │                │
│  │  Status:           │ │ Status:      │ │  Status:          │                │
│  │  - Battery: 85%    │ │ - Plugged in │ │  - Always on      │                │
│  │  - WiFi: 50ms      │ │ - WiFi: 5ms  │ │  - Latency: 200ms │                │
│  │  - RAM free: 4GB   │ │ - RAM: 16GB  │ │                   │                │
│  └───────────────────┘ └──────────────┘ └─────────────────┘                │
│                                                                            │
│  ROUTING PRIORITY:                                                         │
│  1. Local device (if capable) → 0ms network latency                        │
│  2. Nearby phone/laptop on same WiFi → 5-50ms latency                      │
│  3. Home server / desktop GPU → 5ms latency, most capable                  │
│  4. Cloud API fallback → 100-500ms latency, costs money                    │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Worker Registration Protocol

Each device running `raven-worker` registers with the RAVEN brain via a simple REST API:

```json
POST /api/v1/workers/register
{
  "worker_id": "phone-pixel8-swadhin",
  "device_type": "phone",
  "platform": "android",
  "capabilities": {
    "npu_tops": 25,
    "gpu_tflops": 2.1,
    "ram_total_gb": 12,
    "ram_available_gb": 6,
    "storage_available_gb": 32
  },
  "loaded_models": [
    {"name": "phi-3-mini-int4", "type": "llm", "ctx_len": 4096},
    {"name": "whisper-tiny", "type": "stt"},
    {"name": "all-MiniLM-L6-v2", "type": "embeddings"}
  ],
  "power": {
    "battery_percent": 85,
    "charging": false,
    "power_source": "battery"
  },
  "network": {
    "type": "wifi",
    "latency_ms": 12,
    "bandwidth_mbps": 150
  },
  "availability": {
    "schedule": "always",
    "min_battery": 20,
    "allow_background": true
  }
}
```

### 3.4 Task Routing Logic

The RAVEN brain routes inference tasks to the best available worker:

```python
# Proposed routing logic for raven/compute/scheduler.py

class TaskScheduler:
    """Routes AI inference tasks to the best available worker."""
    
    def select_worker(self, task: InferenceTask) -> Worker:
        """
        Priority chain:
        1. Local (same device that originated the request)
        2. LAN workers sorted by: capability match → latency → power state
        3. Cloud API fallback
        """
        candidates = self.registry.get_available_workers()
        
        # Filter by capability
        capable = [w for w in candidates if w.can_handle(task)]
        
        if not capable:
            return self.cloud_fallback
        
        # Score each worker
        scored = []
        for worker in capable:
            score = 0
            # Prefer local
            if worker.is_local(task.origin_device):
                score += 1000
            # Prefer plugged-in devices
            if worker.power.charging or worker.power.source == "ac":
                score += 100
            # Prefer low latency
            score += max(0, 100 - worker.network.latency_ms)
            # Prefer high battery
            if worker.device_type == "phone":
                score += worker.power.battery_percent
            # Prefer already-loaded model
            if task.model in worker.loaded_models:
                score += 500
            scored.append((score, worker))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
```

### 3.5 Phone Worker Implementation Options

| Framework | Platform | Models Supported | Performance | Effort |
|---|---|---|---|---|
| **MLC-LLM** | Android, iOS, Linux | Llama, Phi, Gemma, Qwen | Best on Android (Vulkan/OpenCL) | Medium |
| **llama.cpp** | All | Llama, Phi, Gemma, Mistral | Good everywhere (CPU + GPU) | Low |
| **MLX** | macOS/iOS only | All GGUF models | Best on Apple Silicon | Low (Apple only) |
| **MediaPipe LLM** | Android, iOS | Gemma, Falcon, Phi | Google-optimized | Low |
| **ExecuTorch** | Android, iOS | Any PyTorch model | Meta-optimized, new | High |
| **ONNX Runtime Mobile** | Android, iOS | Any ONNX model | Good for non-LLM AI | Medium |

**Recommended approach for RAVEN:**

Use **llama.cpp** as the universal backend (works on everything) with **MLC-LLM** for
optimized Android inference. The `raven-worker` app wraps these in a simple HTTP API that
the RAVEN brain can call.

### 3.6 What Can Run Where

| Task | Phone (Flagship) | Phone (Mid-range) | $10 SBC | Laptop | Server |
|---|---|---|---|---|---|
| Wake word detection | Yes (real-time) | Yes (real-time) | Yes | Yes | Yes |
| STT (Whisper tiny) | Yes (real-time) | Yes (real-time) | Slow | Yes | Yes |
| STT (Whisper medium) | Yes (2x real-time) | Slow | No | Yes | Yes |
| Embeddings (MiniLM) | Yes (<10ms) | Yes (<20ms) | Yes (<50ms) | Yes | Yes |
| LLM (1-3B, int4) | Yes (30-60 tok/s) | Yes (10-20 tok/s) | No | Yes | Yes |
| LLM (7-8B, int4) | Slow (5-10 tok/s) | No | No | Yes (15-30 tok/s) | Yes |
| TTS (Piper) | Yes (real-time) | Yes (real-time) | Yes | Yes | Yes |
| Object detection (YOLO) | Yes (30+ FPS) | Yes (15 FPS) | MaixCAM only | Yes | Yes |
| Anomaly detection | Yes | Yes | Yes | Yes | Yes |
| Sensor data collection | No (no GPIO) | No (no GPIO) | Yes | No | No |

---

## Part 4: Implementation Roadmap

### Phase 1: PicoClaw-Inspired Edge Gateway (Weeks 1-3)

**Goal:** Build `raven-edge` Go binary for LicheeRV-Nano / NanoKVM

- [ ] Fork PicoClaw's build system (Makefile with cross-compilation)
- [ ] Implement MQTT client for publishing sensor data
- [ ] Implement basic sensor drivers (DHT22 via GPIO, PIR via interrupt)
- [ ] Implement heartbeat service (report health to RAVEN brain)
- [ ] Implement threshold-based anomaly detection (no LLM needed)
- [ ] Test on LicheeRV-Nano ($9.90) with WiFi

**Deliverable:** A Go binary that reads sensors and publishes to RAVEN MQTT broker

### Phase 2: Phone Worker App (Weeks 4-8)

**Goal:** Build `raven-worker` Android app that contributes AI compute to RAVEN

- [ ] Build Android app with llama.cpp / MLC-LLM backend
- [ ] Implement worker registration API (POST to RAVEN brain)
- [ ] Implement inference API server (HTTP on local network)
- [ ] Support models: whisper-tiny (STT), phi-3-mini-int4 (LLM), piper (TTS)
- [ ] Battery-aware scheduling (reduce work when battery <20%)
- [ ] Background service with foreground notification
- [ ] Build iOS version using MLX / Core ML

**Deliverable:** Android app that serves as an AI inference node on local network

### Phase 3: Task Scheduler in RAVEN Brain (Weeks 6-10)

**Goal:** Add distributed task routing to RAVEN core

- [ ] Build worker registry (track all connected devices)
- [ ] Build task scheduler with priority-based routing
- [ ] Implement fallback chain: local → LAN worker → cloud API
- [ ] Add OpenRouter/Groq as cloud fallback providers
- [ ] Build monitoring dashboard for compute mesh status
- [ ] Implement model distribution (push models to workers)

**Deliverable:** RAVEN brain that automatically routes inference to best available device

### Phase 4: MaixCAM Vision Integration (Weeks 8-12)

**Goal:** Integrate MaixCAM for vision-based IoT (person detection, security)

- [ ] Adopt PicoClaw's MaixCam channel protocol (TCP + JSON)
- [ ] Build RAVEN connector for MaixCAM events
- [ ] Implement camera snapshot pipeline (motion → capture → analyze)
- [ ] Add person detection events to RAVEN sensor layer
- [ ] Build alerting pipeline (MaixCAM → RAVEN → Telegram notification)

**Deliverable:** MaixCAM ($50) as a smart security camera integrated with RAVEN

---

## Part 5: Cost Analysis for Complete Setup

### Minimal Setup (1 Room, Basic IoT)

| Item | Qty | Unit Cost | Total |
|---|---|---|---|
| LicheeRV-Nano W (WiFi) | 1 | $9.90 | $9.90 |
| ESP32-C3 + DHT22 sensor | 1 | $5.00 | $5.00 |
| ESP32-C3 + PIR sensor | 1 | $5.50 | $5.50 |
| USB power supply (5V/2A) | 2 | $3.00 | $6.00 |
| Old Android phone (AI worker) | 1 | $0 (existing) | $0 |
| Cloud LLM (Zhipu/Groq free tier) | - | $0/month | $0 |
| **Total** | | | **$26.40** |

### Full Home Setup (3 Rooms, Security Camera, Voice)

| Item | Qty | Unit Cost | Total |
|---|---|---|---|
| LicheeRV-Nano W (WiFi) | 1 | $9.90 | $9.90 |
| ESP32-S3 + DHT22 + MQ-135 | 3 | $8.00 | $24.00 |
| ESP32-C3 + PIR | 3 | $5.50 | $16.50 |
| ESP32-C3 + reed switch (doors) | 2 | $4.50 | $9.00 |
| MaixCAM (person detection) | 1 | $50.00 | $50.00 |
| USB microphone + speaker | 1 | $15.00 | $15.00 |
| Old Android phone (AI worker) | 2 | $0 (existing) | $0 |
| Cloud LLM (OpenRouter paid tier) | - | $5/month | $5/month |
| **Total hardware** | | | **$124.40** |
| **Monthly cost** | | | **$5.00** |

### Comparison with Commercial Solutions

| Solution | Hardware Cost | Monthly Cost | AI Capable | Self-Hosted | Privacy |
|---|---|---|---|---|---|
| **RAVEN + PicoClaw strategy** | $26-125 | $0-5 | Yes | Yes | Full |
| Amazon Alexa + Ring + sensors | $300-500 | $10-25 | Limited | No | Low |
| Google Home + Nest | $250-400 | $6-12 | Limited | No | Low |
| Apple HomeKit + HomePod | $400-800 | $0-3 | Limited | Partial | Medium |
| Home Assistant + RPi setup | $150-300 | $0 | No (DIY) | Yes | Full |

---

## Part 6: Key Lessons from PicoClaw for RAVEN

### What to Adopt

1. **Go binary for edge nodes** -- PicoClaw proves Go is perfect for lightweight,
   cross-platform edge computing. RAVEN should use Go for `raven-edge` and
   `raven-worker` binaries while keeping Python for the brain.

2. **Single binary deployment** -- No Docker, no package manager, no dependencies.
   Just `scp binary device:~/raven-edge && ssh device './raven-edge'`.

3. **Cloud LLM as default, local as optimization** -- PicoClaw uses cloud APIs by
   default and runs perfectly. RAVEN should not require a GPU server; cloud APIs
   should be the starting experience, with local inference as an upgrade path.

4. **JSON file storage for edge** -- Edge nodes do not need PostgreSQL. A simple
   JSON file for config, sessions, and sensor cache is sufficient. Reserve heavy
   databases for the central brain.

5. **Multi-channel message bus** -- PicoClaw's in-process Go channel-based message
   bus is elegant for edge nodes. RAVEN can use this pattern for `raven-edge`
   while keeping MQTT for inter-device communication.

6. **MaixCAM TCP protocol** -- PicoClaw's approach to camera integration (device
   does AI locally, sends structured events) is exactly right. RAVEN should adopt
   this same protocol for vision-based IoT.

7. **Context window summarization** -- PicoClaw's automatic summarization keeps
   memory bounded. Essential for running on constrained devices.

### What Not to Adopt

1. **No on-device AI at all** -- PicoClaw has zero local inference capability.
   RAVEN should keep local model inference (Whisper, Piper, LLM via vLLM) as an
   option for the central server and phone workers.

2. **No database** -- PicoClaw uses only flat files. RAVEN's PostgreSQL + pgvector
   is essential for long-term memory, semantic search, and time-series sensor data.
   This stays on the central brain.

3. **No safety system** -- PicoClaw has basic shell command blocking but no content
   classification, IoT safety gates, or PII protection. RAVEN's 8-layer safety
   system is a significant differentiator and must be preserved.

4. **No sensor integration** -- PicoClaw only connects to MaixCAM for person
   detection. RAVEN's MQTT-based sensor network with anomaly detection is far
   more comprehensive.

---

## Part 7: Process Sharing -- Running AI Anywhere

### 7.1 The Vision: "Your AI Runs on Whatever is Available"

The ultimate goal is that RAVEN intelligently distributes its AI workload across
whatever compute resources are available at any given moment:

```
Scenario: You ask RAVEN "What's the weather forecast and should I take an umbrella?"

RAVEN Brain evaluates available workers:
  ├── Your phone (in your pocket): Battery 72%, WiFi connected, has phi-3-mini loaded
  ├── Living room laptop: Sleeping (unavailable)
  ├── Kitchen LicheeRV-Nano: Online, no AI capability, but has sensors
  └── Cloud (Groq): Always available, 200ms latency

Decision:
  1. Weather API call → RAVEN brain (no AI needed, just HTTP)
  2. Generate natural response → Phone worker (phi-3-mini, 0ms queue, 15ms latency)
  3. TTS if voice → Phone worker (piper, already loaded)

Result: Entire request handled without any cloud AI costs.
```

### 7.2 Model Splitting Across Devices (Future)

For larger models (13B+), RAVEN could split inference across multiple devices using
pipeline parallelism:

```
Llama 3 13B split across 2 phones:

Phone A (layers 0-19):
  Input → Embedding → Transformer layers 0-19 → intermediate tensor →

Phone B (layers 20-39):  
  → intermediate tensor → Transformer layers 20-39 → LM head → Output

Communication: ~2MB intermediate tensor sent over WiFi per token
Latency overhead: ~5-10ms per token (negligible vs compute time)
```

This is an advanced feature for future exploration, but the architecture should be
designed to support it from the start.

### 7.3 WebGPU/WebNN for Browser-Based Workers

Any device with a modern browser could contribute compute via WebGPU:

```
Browser tab running raven-worker-web:
  - Connects to RAVEN brain via WebSocket
  - Loads ONNX/GGUF models via WebGPU
  - Runs inference tasks assigned by scheduler
  - Works on any device: phone, tablet, PC, TV
  
Frameworks: Transformers.js, ONNX Runtime Web, WebLLM
```

This means even a smart TV or tablet could contribute AI processing power to RAVEN.

---

## Conclusion

By combining PicoClaw's ultra-lightweight approach with RAVEN's comprehensive AI companion
architecture, we can build a system where:

1. **IoT costs drop 75%** -- $10 SBCs replace expensive Raspberry Pis for edge computing
2. **AI runs for free** -- phones provide local inference, cloud free tiers handle overflow
3. **No single point of failure** -- distributed compute mesh means AI works even if the
   server is down (phone can handle basic requests directly)
4. **Privacy is preserved** -- most inference happens on local devices, not in the cloud
5. **Scales naturally** -- every new phone/laptop added to the household increases total
   compute capacity

The key insight from PicoClaw is that **you don't need expensive hardware to run AI agents
-- you just need to be smart about where the compute happens.** RAVEN should embrace this
philosophy: lightweight edge nodes for sensing, phones for inference, cloud as fallback,
and a central brain for orchestration.
