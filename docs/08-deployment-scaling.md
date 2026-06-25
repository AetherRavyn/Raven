# 08 - Deployment and Scaling

## Deployment Overview

RAVEN runs as a single-server deployment. Every component -- the Python async bot process,
the WhatsApp bridge, the databases, the ML models -- lives on one machine. There is no
service mesh, no container orchestration platform, no multi-node cluster. A single GPU
server handles everything.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         SINGLE SERVER (GPU-equipped)                              │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                          APPLICATION LAYER                                 │  │
│  │                                                                            │  │
│  │  ┌──────────────────────────┐    ┌──────────────────────────────────────┐  │  │
│  │  │  raven-bot (Python)      │    │  whatsapp-bridge (Node.js)           │  │  │
│  │  │                          │    │                                      │  │  │
│  │  │  - Async event loop      │    │  - Baileys library                   │  │  │
│  │  │  - All connectors        │    │  - WebSocket link to raven-bot      │  │  │
│  │  │    (Telegram, Discord,   │    │  - Runs as separate process         │  │  │
│  │  │     Voice, Web API)      │    │                                      │  │  │
│  │  │  - Brain / LLM caller    │    └──────────────────────────────────────┘  │  │
│  │  │  - Tool executor         │                                              │  │
│  │  │  - STT / TTS pipeline    │                                              │  │
│  │  │  - IoT MQTT handler      │                                              │  │
│  │  │  - Prometheus metrics    │                                              │  │
│  │  └──────────────────────────┘                                              │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                          ML INFERENCE (GPU)                                │  │
│  │                                                                            │  │
│  │  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────────────────┐  │  │
│  │  │  vLLM         │  │  faster-whisper   │  │  XTTS v2 / Piper TTS       │  │  │
│  │  │  Mistral 7B   │  │  STT engine       │  │  Text-to-speech            │  │  │
│  │  │  AWQ 4-bit    │  │  medium model     │  │  XTTS: GPU  Piper: CPU     │  │  │
│  │  │  ~4-5 GB VRAM │  │  ~1.5 GB VRAM     │  │  ~1-2 GB VRAM (XTTS)      │  │  │
│  │  └──────────────┘  └──────────────────┘  └─────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                          DATA / INFRASTRUCTURE                             │  │
│  │                                                                            │  │
│  │  ┌────────────┐  ┌────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐  │  │
│  │  │ PostgreSQL │  │ Redis  │  │ Mosquitto │  │ SearXNG  │  │ Caddy     │  │  │
│  │  │ + pgvector │  │        │  │ MQTT      │  │ search   │  │ reverse   │  │  │
│  │  │            │  │        │  │ broker    │  │ engine   │  │ proxy     │  │  │
│  │  └────────────┘  └────────┘  └───────────┘  └──────────┘  └───────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                          MONITORING                                        │  │
│  │                                                                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────────────────┐  │  │
│  │  │ Prometheus  │  │ Grafana     │  │ nvidia-smi (GPU monitoring)       │  │  │
│  │  └─────────────┘  └─────────────┘  └───────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Two processes compose the application:

1. **raven-bot** -- the single Python async process that handles all connectors, the brain,
   memory, tool execution, STT/TTS, IoT, and metrics. This is the core of RAVEN.
2. **whatsapp-bridge** -- a small Node.js process running Baileys. It connects to WhatsApp
   Web and forwards messages to raven-bot over a local WebSocket.

Everything else (PostgreSQL, Redis, Mosquitto, SearXNG, Caddy, Prometheus, Grafana)
is off-the-shelf infrastructure.

---

## Hardware Requirements

### Minimum (development and light personal use)

| Component | Specification |
|-----------|--------------|
| CPU | 4+ cores (Intel i5 / AMD Ryzen 5) |
| RAM | 16 GB |
| GPU | NVIDIA RTX 3060 or 3070 (8 GB VRAM) |
| Disk | 50 GB SSD |
| OS | Ubuntu 22.04 / Debian 12 |
| NVIDIA Driver | 535+ with CUDA 12.x |

### Recommended (daily personal use with all features)

| Component | Specification |
|-----------|--------------|
| CPU | 8+ cores (Intel i7 / AMD Ryzen 7) |
| RAM | 32 GB |
| GPU | NVIDIA RTX 3090 or 4080 (12+ GB VRAM) |
| Disk | 100 GB NVMe SSD |
| OS | Ubuntu 22.04 / Debian 12 |
| NVIDIA Driver | 545+ with CUDA 12.x |

### CPU-Only Fallback

Not everyone has a GPU. Here is what works and what does not without one:

| Component | CPU-Only? | Notes |
|-----------|-----------|-------|
| Piper TTS | Yes | Designed for CPU, fast enough for real-time |
| faster-whisper (tiny/base) | Yes | Works but slower (~2-3x real-time on base model) |
| faster-whisper (medium/large) | Impractical | Too slow for interactive use |
| vLLM (Mistral 7B) | No | vLLM requires CUDA |
| llama.cpp (Mistral 7B GGUF) | Yes | Use as CPU fallback for LLM inference (~3-5 tok/s on 8 cores) |
| XTTS v2 | No | Requires GPU for real-time synthesis |
| External API (OpenAI/Anthropic) | Yes | Replace local LLM with API calls, no GPU needed |

For CPU-only deployments, set these in `config.yaml`:

```yaml
llm:
  backend: "llamacpp"           # instead of "vllm"
  model_path: "./models/mistral-7b-instruct-v0.3.Q4_K_M.gguf"
  n_threads: 8

stt:
  backend: "faster-whisper"
  model_size: "tiny"            # or "base" for better accuracy
  device: "cpu"
  compute_type: "int8"

tts:
  backend: "piper"              # CPU-only, no XTTS
  model: "en_US-lessac-medium"
```

---

## Docker Compose Setup

This is the recommended deployment method. All services are defined in a single
`docker-compose.yml`.

### Prerequisites

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install NVIDIA Container Toolkit (for GPU passthrough)
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L "https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list" \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU access in Docker
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### docker-compose.yml

```yaml
# docker-compose.yml
version: "3.8"

services:
  # ── Application ──────────────────────────────────────────────

  raven-bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: raven-bot
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      DATABASE_URL: "postgresql+asyncpg://raven:${POSTGRES_PASSWORD}@postgres:5432/raven"
      REDIS_URL: "redis://redis:6379/0"
      MQTT_BROKER_HOST: "mosquitto"
      MQTT_BROKER_PORT: "1883"
      SEARXNG_URL: "http://searxng:8080"
      TELEGRAM_BOT_TOKEN: "${TELEGRAM_BOT_TOKEN}"
      DISCORD_BOT_TOKEN: "${DISCORD_BOT_TOKEN}"
      WHATSAPP_BRIDGE_URL: "ws://whatsapp-bridge:3100"
      VLLM_API_URL: "http://localhost:8000"
      CONFIG_PATH: "/app/config.yaml"
      LOG_LEVEL: "INFO"
      LOG_FORMAT: "json"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./models:/app/models:ro
      - model_cache:/root/.cache/huggingface
      - raven_data:/app/data
      - raven_logs:/app/logs
    ports:
      - "127.0.0.1:8500:8500"    # Web API (behind Caddy)
      - "127.0.0.1:9090:9090"    # Prometheus metrics endpoint
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      mosquitto:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8500/health')"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    networks:
      - raven

  whatsapp-bridge:
    build:
      context: ./whatsapp-bridge
      dockerfile: Dockerfile
    container_name: whatsapp-bridge
    restart: unless-stopped
    environment:
      RAVEN_BOT_URL: "ws://raven-bot:8500/ws/whatsapp"
      AUTH_DIR: "/data/auth"
      LOG_LEVEL: "info"
    volumes:
      - whatsapp_auth:/data/auth
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3100/health', r => { process.exit(r.statusCode === 200 ? 0 : 1) })"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    networks:
      - raven

  # ── Databases ────────────────────────────────────────────────

  postgres:
    image: pgvector/pgvector:pg16
    container_name: raven-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: raven
      POSTGRES_USER: raven
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U raven -d raven"]
      interval: 10s
      timeout: 5s
      retries: 5
    shm_size: 256mb
    command:
      - "postgres"
      - "-c"
      - "shared_buffers=512MB"
      - "-c"
      - "effective_cache_size=1536MB"
      - "-c"
      - "work_mem=16MB"
      - "-c"
      - "maintenance_work_mem=128MB"
    networks:
      - raven

  redis:
    image: redis:7-alpine
    container_name: raven-redis
    restart: unless-stopped
    command: >
      redis-server
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --save 900 1
      --save 300 10
      --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - raven

  # ── Infrastructure Services ──────────────────────────────────

  mosquitto:
    image: eclipse-mosquitto:2
    container_name: raven-mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
      - "127.0.0.1:9001:9001"
    volumes:
      - ./config/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto_data:/mosquitto/data
      - mosquitto_logs:/mosquitto/log
    networks:
      - raven

  searxng:
    image: searxng/searxng:latest
    container_name: raven-searxng
    restart: unless-stopped
    environment:
      SEARXNG_BASE_URL: "http://searxng:8080/"
    volumes:
      - ./config/searxng:/etc/searxng:ro
    ports:
      - "127.0.0.1:8080:8080"
    networks:
      - raven

  # ── Reverse Proxy ────────────────────────────────────────────

  caddy:
    image: caddy:2-alpine
    container_name: raven-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - raven

  # ── Monitoring ───────────────────────────────────────────────

  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: raven-prometheus
    restart: unless-stopped
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./config/alerts:/etc/prometheus/alerts:ro
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9091:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"
    networks:
      - raven

  grafana:
    image: grafana/grafana:10.4.0
    container_name: raven-grafana
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GRAFANA_PASSWORD}"
      GF_SERVER_ROOT_URL: "https://${DOMAIN}/grafana/"
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./config/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    ports:
      - "127.0.0.1:3000:3000"
    networks:
      - raven

volumes:
  postgres_data:
  redis_data:
  mosquitto_data:
  mosquitto_logs:
  model_cache:
  raven_data:
  raven_logs:
  whatsapp_auth:
  caddy_data:
  caddy_config:
  prometheus_data:
  grafana_data:

networks:
  raven:
    driver: bridge
```

### Environment Variables

Create a `.env` file alongside `docker-compose.yml`. This file is git-ignored.

```bash
# .env (never commit this file)
POSTGRES_PASSWORD=changeme-use-a-strong-password
TELEGRAM_BOT_TOKEN=123456:ABC-your-telegram-bot-token
DISCORD_BOT_TOKEN=your-discord-bot-token
GRAFANA_PASSWORD=changeme-grafana-admin
DOMAIN=raven.yourdomain.com
```

### Starting the Stack

```bash
# First run: build and start everything
docker compose up -d --build

# Check all containers are healthy
docker compose ps

# View logs
docker compose logs -f raven-bot

# Restart just the bot after config changes
docker compose restart raven-bot

# Full stop
docker compose down

# Full stop and destroy all data (careful)
docker compose down -v
```

---

## Systemd Deployment (Alternative to Docker)

For those who prefer running services natively without Docker. This is useful when you
want maximum GPU performance (no container overhead) or fine-grained control.

### Install System Dependencies

```bash
# PostgreSQL 16 with pgvector
sudo apt-get install -y postgresql-16 postgresql-16-pgvector

# Redis
sudo apt-get install -y redis-server

# Mosquitto MQTT broker
sudo apt-get install -y mosquitto mosquitto-clients

# Node.js 20 (for WhatsApp bridge)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Python 3.11+
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# NVIDIA CUDA Toolkit (if GPU present)
sudo apt-get install -y nvidia-cuda-toolkit
```

### Python Virtual Environment

```bash
# Create a dedicated user
sudo useradd -r -m -s /bin/bash raven

# Set up the project
sudo -u raven bash -c '
  cd /home/raven
  git clone https://github.com/your-org/raven.git
  cd raven
  python3.11 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -e ".[all]"
'
```

### Systemd Service: raven-bot

```ini
# /etc/systemd/system/raven-bot.service
[Unit]
Description=RAVEN AI Companion Bot
After=network.target postgresql.service redis-server.service mosquitto.service
Wants=postgresql.service redis-server.service mosquitto.service

[Service]
Type=exec
User=raven
Group=raven
WorkingDirectory=/home/raven/raven
ExecStart=/home/raven/raven/.venv/bin/python -m raven.main
Restart=on-failure
RestartSec=10
TimeoutStartSec=180

# Environment
EnvironmentFile=/home/raven/raven/.env
Environment=CONFIG_PATH=/home/raven/raven/config.yaml
Environment=LOG_LEVEL=INFO
Environment=LOG_FORMAT=json

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/raven/raven/data /home/raven/raven/logs /tmp
PrivateTmp=true

# Resource limits
LimitNOFILE=65536
MemoryMax=8G

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=raven-bot

[Install]
WantedBy=multi-user.target
```

### Systemd Service: whatsapp-bridge

```ini
# /etc/systemd/system/raven-whatsapp.service
[Unit]
Description=RAVEN WhatsApp Bridge (Baileys)
After=network.target raven-bot.service
Wants=raven-bot.service

[Service]
Type=exec
User=raven
Group=raven
WorkingDirectory=/home/raven/raven/whatsapp-bridge
ExecStart=/usr/bin/node src/index.js
Restart=on-failure
RestartSec=5

EnvironmentFile=/home/raven/raven/.env
Environment=RAVEN_BOT_URL=ws://127.0.0.1:8500/ws/whatsapp
Environment=AUTH_DIR=/home/raven/raven/data/whatsapp-auth
Environment=LOG_LEVEL=info

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/raven/raven/data
PrivateTmp=true

StandardOutput=journal
StandardError=journal
SyslogIdentifier=raven-whatsapp

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable raven-bot raven-whatsapp
sudo systemctl start raven-bot raven-whatsapp

# Check status
sudo systemctl status raven-bot
sudo journalctl -u raven-bot -f
```

---

## Cloud VPS Options

### GPU VPS Providers

| Provider | GPU | VRAM | RAM | Storage | Monthly Cost | Notes |
|----------|-----|------|-----|---------|-------------|-------|
| **Hetzner GEX44** | RTX 4000 SFF Ada | 20 GB | 64 GB | 512 GB NVMe | ~$200/mo | Best value, EU data centers |
| **Lambda Labs** | A10 | 24 GB | 30 GB | 512 GB SSD | ~$0.75/hr (~$540/mo) | Easy setup, US/EU |
| **Vast.ai** | RTX 3090 | 24 GB | 32 GB | varies | ~$0.20-0.40/hr | Community GPUs, cheapest |
| **RunPod** | RTX 3090 | 24 GB | 32 GB | 100 GB | ~$0.44/hr (~$320/mo) | Good for persistent pods |
| **Hetzner AX102** | No GPU | -- | 128 GB | 2x NVMe | ~$85/mo | CPU-only, use external API |

### Monthly Cost Estimates

**Tier 1: Full self-hosted with GPU (~$200-350/mo)**

Everything runs on one GPU server. No external API costs.

- GPU VPS: $200-320/mo
- Domain + DNS: $0 (Cloudflare free tier)
- Total: $200-350/mo

**Tier 2: Hybrid -- external LLM API, self-hosted everything else (~$50-100/mo)**

Use OpenAI or Anthropic for the LLM. Self-host STT (Whisper tiny on CPU), TTS (Piper on CPU),
databases, and all connectors on a cheap CPU VPS.

- CPU VPS (Hetzner CPX31, 8 vCPU, 16 GB): ~$15/mo
- OpenAI API (GPT-4o-mini, estimated usage): ~$20-60/mo
- Total: $35-75/mo

**Tier 3: Local workstation ($0/mo ongoing)**

Run on your own desktop with a GPU. No cloud costs. Requires the machine to be on
and connected to the internet for always-on availability.

### Non-GPU Alternative: External API for LLM

If you do not have a GPU, replace vLLM with API calls. In `config.yaml`:

```yaml
llm:
  backend: "openai_api"
  api_key_env: "OPENAI_API_KEY"  # read from environment variable
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  # Or use Anthropic:
  # backend: "anthropic_api"
  # model: "claude-3-haiku-20240307"
```

Everything else (STT, TTS, memory, connectors, IoT) still runs locally.

---

## GPU Memory Planning

### How VRAM Is Allocated

RAVEN loads three GPU-accelerated models simultaneously. They share a single GPU.

```
┌──────────────────────────────────────────────────────────┐
│                    GPU VRAM LAYOUT                         │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  vLLM - Mistral 7B AWQ 4-bit                       │  │
│  │  Model weights: ~4 GB                               │  │
│  │  KV cache (varies by concurrent requests): 1-4 GB   │  │
│  │  Total: 4-8 GB                                      │  │
│  ├─────────────────────────────────────────────────────┤  │
│  │  faster-whisper - medium model                      │  │
│  │  Model weights: ~1.5 GB                             │  │
│  │  Working memory: ~0.5 GB                            │  │
│  │  Total: ~2 GB                                       │  │
│  ├─────────────────────────────────────────────────────┤  │
│  │  XTTS v2 - text-to-speech                           │  │
│  │  Model weights: ~1.5 GB                             │  │
│  │  Working memory: ~0.5 GB                            │  │
│  │  Total: ~2 GB                                       │  │
│  ├─────────────────────────────────────────────────────┤  │
│  │  CUDA overhead + PyTorch runtime: ~0.5-1 GB         │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  Total: 8.5 - 13 GB                                      │
└──────────────────────────────────────────────────────────┘
```

### Memory Profiles by GPU Size

**8 GB VRAM (RTX 3060/3070)**

| Model | Config | VRAM |
|-------|--------|------|
| vLLM Mistral 7B AWQ | `gpu_memory_utilization=0.45`, `max_model_len=2048` | ~4 GB |
| faster-whisper | `model_size=small`, `compute_type=int8` | ~1 GB |
| TTS | Piper (CPU only, no GPU needed) | 0 GB |
| Overhead | CUDA runtime | ~0.5 GB |
| **Total** | | **~5.5 GB** (leaves headroom) |

With 8 GB, use Piper TTS (CPU) instead of XTTS to stay within budget. Use the small
Whisper model. Limit context length to 2048 tokens.

**12 GB VRAM (RTX 3060 12GB / RTX 3080)**

| Model | Config | VRAM |
|-------|--------|------|
| vLLM Mistral 7B AWQ | `gpu_memory_utilization=0.50`, `max_model_len=4096` | ~5.5 GB |
| faster-whisper | `model_size=medium`, `compute_type=int8_float16` | ~1.5 GB |
| XTTS v2 | Full model | ~2 GB |
| Overhead | CUDA runtime | ~0.5 GB |
| **Total** | | **~9.5 GB** (comfortable) |

This is the sweet spot. All three GPU models fit with room to spare.

**24 GB VRAM (RTX 3090 / RTX 4090)**

| Model | Config | VRAM |
|-------|--------|------|
| vLLM Mistral 7B AWQ | `gpu_memory_utilization=0.60`, `max_model_len=8192` | ~8 GB |
| faster-whisper | `model_size=large-v3`, `compute_type=float16` | ~3 GB |
| XTTS v2 | Full model | ~2 GB |
| Overhead | CUDA runtime | ~1 GB |
| **Total** | | **~14 GB** (plenty of headroom) |

Extra VRAM can be used for larger KV cache (more concurrent requests or longer
context), or loading additional models (vision model, safety classifier on GPU).

### Techniques to Reduce VRAM

1. **AWQ 4-bit quantization** -- Already used. Cuts Mistral 7B from ~14 GB (float16)
   to ~4 GB. No meaningful quality loss for this model size.

2. **Whisper model size** -- Scale down from `large-v3` (3 GB) to `small` (1 GB)
   or `tiny` (0.5 GB) when VRAM is tight. Accuracy drops but latency improves.

3. **Piper TTS instead of XTTS** -- Piper runs on CPU and uses zero VRAM. Quality is
   lower (no voice cloning, less natural prosody) but perfectly usable.

4. **Sequential loading** -- Load only the model currently needed, unload others.
   This works if you rarely have simultaneous STT + LLM + TTS (unlikely for a
   single-user bot). Not recommended for real-time use.

5. **vLLM memory fraction** -- The `gpu_memory_utilization` parameter in vLLM controls
   what fraction of remaining VRAM it claims for KV cache. Lower it to leave room
   for other models.

---

## Backups

### What to Back Up

| Data | Location | Criticality | Method |
|------|----------|-------------|--------|
| PostgreSQL (conversations, memories, user data) | postgres_data volume | Critical | pg_dump daily |
| Redis (session cache, rate limits) | redis_data volume | Low | RDB snapshots |
| WhatsApp auth credentials | whatsapp_auth volume | Medium | File copy |
| config.yaml | Project directory | Critical | Git-tracked |
| .env (secrets) | Project directory | Critical | Encrypted backup |
| Model files | models/ directory | Low | Re-download from HuggingFace |

### Automated Backup Script

```bash
#!/usr/bin/env bash
# scripts/backup.sh -- daily backup for RAVEN
# Run via cron: 0 3 * * * /home/raven/raven/scripts/backup.sh

set -euo pipefail

BACKUP_DIR="/home/raven/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=14

mkdir -p "${BACKUP_DIR}"

echo "[${TIMESTAMP}] Starting RAVEN backup..."

# ── PostgreSQL dump ────────────────────────────────────────
echo "Backing up PostgreSQL..."
if command -v docker &> /dev/null; then
    # Docker deployment
    docker exec raven-postgres pg_dump \
        -U raven \
        -d raven \
        --format=custom \
        --compress=9 \
        > "${BACKUP_DIR}/postgres_${TIMESTAMP}.dump"
else
    # Native deployment
    sudo -u postgres pg_dump \
        -d raven \
        --format=custom \
        --compress=9 \
        > "${BACKUP_DIR}/postgres_${TIMESTAMP}.dump"
fi

# ── Redis snapshot ─────────────────────────────────────────
echo "Backing up Redis..."
if command -v docker &> /dev/null; then
    docker exec raven-redis redis-cli BGSAVE
    sleep 5
    docker cp raven-redis:/data/dump.rdb "${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
else
    redis-cli BGSAVE
    sleep 5
    cp /var/lib/redis/dump.rdb "${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
fi

# ── WhatsApp auth ─────────────────────────────────────────
echo "Backing up WhatsApp auth..."
if command -v docker &> /dev/null; then
    docker cp raven-whatsapp-bridge:/data/auth "${BACKUP_DIR}/whatsapp_auth_${TIMESTAMP}"
else
    cp -r /home/raven/raven/data/whatsapp-auth "${BACKUP_DIR}/whatsapp_auth_${TIMESTAMP}"
fi

# ── Config files ──────────────────────────────────────────
echo "Backing up config..."
tar czf "${BACKUP_DIR}/config_${TIMESTAMP}.tar.gz" \
    -C /home/raven/raven \
    config.yaml \
    config/ \
    .env \
    docker-compose.yml \
    2>/dev/null || true

# ── Compress everything into one archive ──────────────────
echo "Creating final archive..."
tar czf "${BACKUP_DIR}/raven_full_${TIMESTAMP}.tar.gz" \
    -C "${BACKUP_DIR}" \
    "postgres_${TIMESTAMP}.dump" \
    "redis_${TIMESTAMP}.rdb" \
    "whatsapp_auth_${TIMESTAMP}" \
    "config_${TIMESTAMP}.tar.gz"

# Clean up individual files
rm -f "${BACKUP_DIR}/postgres_${TIMESTAMP}.dump"
rm -f "${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
rm -rf "${BACKUP_DIR}/whatsapp_auth_${TIMESTAMP}"
rm -f "${BACKUP_DIR}/config_${TIMESTAMP}.tar.gz"

# ── Prune old backups ─────────────────────────────────────
echo "Pruning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "raven_full_*.tar.gz" -mtime +${RETENTION_DAYS} -delete

# ── Optional: copy to remote storage ─────────────────────
# Uncomment and configure one of these:
# rsync -az "${BACKUP_DIR}/raven_full_${TIMESTAMP}.tar.gz" user@backup-server:/backups/raven/
# aws s3 cp "${BACKUP_DIR}/raven_full_${TIMESTAMP}.tar.gz" s3://your-bucket/raven-backups/
# rclone copy "${BACKUP_DIR}/raven_full_${TIMESTAMP}.tar.gz" remote:raven-backups/

FINAL_SIZE=$(du -h "${BACKUP_DIR}/raven_full_${TIMESTAMP}.tar.gz" | cut -f1)
echo "[$(date +%Y%m%d_%H%M%S)] Backup complete: raven_full_${TIMESTAMP}.tar.gz (${FINAL_SIZE})"
```

### Cron Setup

```bash
# Install the cron job
chmod +x /home/raven/raven/scripts/backup.sh
(crontab -l 2>/dev/null; echo "0 3 * * * /home/raven/raven/scripts/backup.sh >> /home/raven/backups/backup.log 2>&1") | crontab -
```

### Restore Procedure

```bash
# Extract the archive
tar xzf raven_full_20260212_030000.tar.gz

# Restore PostgreSQL
docker exec -i raven-postgres pg_restore \
    -U raven -d raven --clean --if-exists \
    < postgres_20260212_030000.dump

# Restore Redis
docker compose stop redis
docker cp redis_20260212_030000.rdb raven-redis:/data/dump.rdb
docker compose start redis

# Restore WhatsApp auth
docker cp whatsapp_auth_20260212_030000/. raven-whatsapp-bridge:/data/auth/
docker compose restart whatsapp-bridge
```

---

## Monitoring

### Prometheus Metrics in the Bot

The raven-bot process exposes metrics via `prometheus_client` on port 9090.

```python
# raven/metrics.py
"""Prometheus metrics for RAVEN bot."""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    start_http_server,
)

# ── Bot info ───────────────────────────────────────────────
RAVEN_INFO = Info("raven", "RAVEN bot instance information")

# ── Message metrics ────────────────────────────────────────
MESSAGES_RECEIVED = Counter(
    "raven_messages_received_total",
    "Total messages received",
    ["platform", "message_type"],
)
MESSAGES_SENT = Counter(
    "raven_messages_sent_total",
    "Total messages sent",
    ["platform"],
)
MESSAGE_PROCESSING_TIME = Histogram(
    "raven_message_processing_seconds",
    "End-to-end message processing time",
    ["platform"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ── LLM metrics ───────────────────────────────────────────
LLM_INFERENCE_TIME = Histogram(
    "raven_llm_inference_seconds",
    "LLM inference latency (time to first token)",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)
LLM_TOKENS_GENERATED = Counter(
    "raven_llm_tokens_generated_total",
    "Total tokens generated by LLM",
)
LLM_TOKENS_PER_SECOND = Gauge(
    "raven_llm_tokens_per_second",
    "Current LLM generation speed",
)

# ── STT metrics ────────────────────────────────────────────
STT_PROCESSING_TIME = Histogram(
    "raven_stt_processing_seconds",
    "Speech-to-text processing time",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
STT_AUDIO_DURATION = Histogram(
    "raven_stt_audio_duration_seconds",
    "Duration of audio processed by STT",
    buckets=[1, 2, 5, 10, 30, 60],
)

# ── TTS metrics ────────────────────────────────────────────
TTS_PROCESSING_TIME = Histogram(
    "raven_tts_processing_seconds",
    "Text-to-speech synthesis time",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
TTS_CHARACTERS_PROCESSED = Counter(
    "raven_tts_characters_total",
    "Total characters synthesized by TTS",
)

# ── IoT metrics ────────────────────────────────────────────
IOT_SENSOR_COUNT = Gauge(
    "raven_iot_sensors_active",
    "Number of active IoT sensors",
)
IOT_COMMANDS_TOTAL = Counter(
    "raven_iot_commands_total",
    "Total IoT commands executed",
    ["command_type", "status"],
)
IOT_MQTT_MESSAGES = Counter(
    "raven_iot_mqtt_messages_total",
    "Total MQTT messages received",
    ["topic_prefix"],
)

# ── Error metrics ──────────────────────────────────────────
ERRORS_TOTAL = Counter(
    "raven_errors_total",
    "Total errors",
    ["component", "error_type"],
)

# ── GPU metrics ────────────────────────────────────────────
GPU_MEMORY_USED = Gauge(
    "raven_gpu_memory_used_bytes",
    "GPU memory used in bytes",
)
GPU_MEMORY_TOTAL = Gauge(
    "raven_gpu_memory_total_bytes",
    "Total GPU memory in bytes",
)
GPU_UTILIZATION = Gauge(
    "raven_gpu_utilization_percent",
    "GPU utilization percentage",
)


def update_gpu_metrics() -> None:
    """Read GPU stats from nvidia-smi and update gauges."""
    try:
        import subprocess

        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            GPU_MEMORY_USED.set(int(parts[0]) * 1024 * 1024)
            GPU_MEMORY_TOTAL.set(int(parts[1]) * 1024 * 1024)
            GPU_UTILIZATION.set(float(parts[2]))
    except Exception:
        pass


def start_metrics_server(port: int = 9090) -> None:
    """Start the Prometheus metrics HTTP server."""
    RAVEN_INFO.info({"version": "0.1.0", "python": "3.11"})
    start_http_server(port)
```

### Prometheus Configuration

```yaml
# config/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "raven-bot"
    static_configs:
      - targets: ["raven-bot:9090"]
    scrape_interval: 10s

  - job_name: "node-exporter"
    static_configs:
      - targets: ["localhost:9100"]

  - job_name: "caddy"
    static_configs:
      - targets: ["caddy:2019"]

rule_files:
  - "alerts/*.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: []
      # Configure Alertmanager if you want notifications.
      # For a simple setup, Grafana alerting is easier.
```

### Alert Rules

```yaml
# config/alerts/raven-alerts.yml
groups:
  - name: raven-critical
    rules:
      - alert: RavenBotDown
        expr: up{job="raven-bot"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RAVEN bot process is down"
          description: "The raven-bot metrics endpoint has been unreachable for 1 minute."

      - alert: LLMLatencyHigh
        expr: histogram_quantile(0.95, rate(raven_llm_inference_seconds_bucket[5m])) > 5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "LLM inference P95 latency above 5 seconds"

      - alert: MessageProcessingLatencyHigh
        expr: histogram_quantile(0.95, rate(raven_message_processing_seconds_bucket[5m])) > 10
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "End-to-end message processing P95 above 10 seconds"

      - alert: GPUMemoryNearOOM
        expr: raven_gpu_memory_used_bytes / raven_gpu_memory_total_bytes > 0.92
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "GPU memory utilization above 92% -- risk of OOM"
          description: "Consider reducing vLLM gpu_memory_utilization or switching to a smaller Whisper model."

      - alert: HighErrorRate
        expr: rate(raven_errors_total[5m]) > 0.5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Error rate above 0.5/s across all components"

      - alert: STTLatencyHigh
        expr: histogram_quantile(0.95, rate(raven_stt_processing_seconds_bucket[5m])) > 3
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Speech-to-text P95 latency above 3 seconds"
```

### Grafana Dashboard

Import this JSON as a Grafana dashboard. It provides the key operational panels.

```json
{
  "dashboard": {
    "title": "RAVEN Operations",
    "uid": "raven-ops",
    "panels": [
      {
        "title": "Messages Received (rate/min)",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "sum(rate(raven_messages_received_total[5m])) by (platform) * 60",
            "legendFormat": "{{ platform }}"
          }
        ]
      },
      {
        "title": "Message Processing Latency",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
        "targets": [
          {
            "expr": "histogram_quantile(0.50, rate(raven_message_processing_seconds_bucket[5m]))",
            "legendFormat": "p50"
          },
          {
            "expr": "histogram_quantile(0.95, rate(raven_message_processing_seconds_bucket[5m]))",
            "legendFormat": "p95"
          },
          {
            "expr": "histogram_quantile(0.99, rate(raven_message_processing_seconds_bucket[5m]))",
            "legendFormat": "p99"
          }
        ]
      },
      {
        "title": "LLM Inference Latency",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 8, "x": 0, "y": 8 },
        "targets": [
          {
            "expr": "histogram_quantile(0.50, rate(raven_llm_inference_seconds_bucket[5m]))",
            "legendFormat": "p50"
          },
          {
            "expr": "histogram_quantile(0.95, rate(raven_llm_inference_seconds_bucket[5m]))",
            "legendFormat": "p95"
          }
        ]
      },
      {
        "title": "GPU Utilization %",
        "type": "gauge",
        "gridPos": { "h": 8, "w": 4, "x": 8, "y": 8 },
        "targets": [
          { "expr": "raven_gpu_utilization_percent" }
        ],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "steps": [
                { "value": 0, "color": "green" },
                { "value": 70, "color": "yellow" },
                { "value": 90, "color": "red" }
              ]
            },
            "max": 100
          }
        }
      },
      {
        "title": "GPU Memory Used / Total",
        "type": "stat",
        "gridPos": { "h": 8, "w": 4, "x": 12, "y": 8 },
        "targets": [
          {
            "expr": "raven_gpu_memory_used_bytes / 1024 / 1024",
            "legendFormat": "Used (MB)"
          },
          {
            "expr": "raven_gpu_memory_total_bytes / 1024 / 1024",
            "legendFormat": "Total (MB)"
          }
        ]
      },
      {
        "title": "STT / TTS Latency",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 8, "x": 16, "y": 8 },
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(raven_stt_processing_seconds_bucket[5m]))",
            "legendFormat": "STT p95"
          },
          {
            "expr": "histogram_quantile(0.95, rate(raven_tts_processing_seconds_bucket[5m]))",
            "legendFormat": "TTS p95"
          }
        ]
      },
      {
        "title": "Errors by Component",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 16 },
        "targets": [
          {
            "expr": "sum(rate(raven_errors_total[5m])) by (component) * 60",
            "legendFormat": "{{ component }}"
          }
        ]
      },
      {
        "title": "IoT Sensors Active",
        "type": "stat",
        "gridPos": { "h": 8, "w": 4, "x": 12, "y": 16 },
        "targets": [
          { "expr": "raven_iot_sensors_active" }
        ]
      },
      {
        "title": "IoT Commands (success / fail)",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 8, "x": 16, "y": 16 },
        "targets": [
          {
            "expr": "sum(rate(raven_iot_commands_total{status='success'}[5m])) * 60",
            "legendFormat": "success/min"
          },
          {
            "expr": "sum(rate(raven_iot_commands_total{status='error'}[5m])) * 60",
            "legendFormat": "error/min"
          }
        ]
      }
    ]
  }
}
```

---

## CI/CD

### GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install linting tools
        run: pip install ruff mypy

      - name: Ruff check
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Type check
        run: mypy raven/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: raven_test
          POSTGRES_USER: raven
          POSTGRES_PASSWORD: testpassword
        ports: ["5432:5432"]
        options: >-
          --health-cmd="pg_isready -U raven"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd="redis-cli ping"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[test]"

      - name: Run tests
        env:
          DATABASE_URL: "postgresql+asyncpg://raven:testpassword@localhost:5432/raven_test"
          REDIS_URL: "redis://localhost:6379/0"
        run: pytest tests/ -v --cov=raven --cov-report=xml --cov-fail-under=70

      - name: Upload coverage
        if: github.event_name == 'pull_request'
        uses: codecov/codecov-action@v4

  build:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push raven-bot
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/raven-bot:${{ github.sha }}
            ghcr.io/${{ github.repository }}/raven-bot:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Build and push whatsapp-bridge
        uses: docker/build-push-action@v5
        with:
          context: ./whatsapp-bridge
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/whatsapp-bridge:${{ github.sha }}
            ghcr.io/${{ github.repository }}/whatsapp-bridge:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to server via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /home/raven/raven
            git pull origin main
            docker compose pull raven-bot whatsapp-bridge
            docker compose up -d --build raven-bot whatsapp-bridge
            docker compose ps
            echo "Waiting for health check..."
            sleep 30
            curl -sf http://localhost:8500/health || exit 1
            echo "Deployment successful."
```

### Pre-Commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: []
        args: [--ignore-missing-imports]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=500]
```

Install with:

```bash
pip install pre-commit
pre-commit install
```

### Deployment Script (Manual Alternative)

```bash
#!/usr/bin/env bash
# scripts/deploy.sh -- pull latest code, rebuild, and restart
set -euo pipefail

DEPLOY_DIR="/home/raven/raven"

echo "=== RAVEN Deployment ==="
echo "Time: $(date)"

cd "${DEPLOY_DIR}"

# Pull latest code
echo "Pulling latest code..."
git pull origin main

# Rebuild and restart application containers only
echo "Rebuilding containers..."
docker compose build raven-bot whatsapp-bridge

echo "Restarting services..."
docker compose up -d raven-bot whatsapp-bridge

# Wait for health check
echo "Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8500/health > /dev/null 2>&1; then
        echo "Health check passed after ${i}s."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Health check failed after 30s. Rolling back."
        docker compose logs --tail=50 raven-bot
        exit 1
    fi
    sleep 1
done

echo "Deployment complete."
docker compose ps
```

---

## Logging

### Structured Logging Configuration

RAVEN uses `structlog` for structured JSON logging. Every log entry includes the
timestamp, log level, component name, and request context.

```python
# raven/logging_config.py
"""Logging configuration for RAVEN."""

import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure structlog for the entire application."""

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiomqtt").setLevel(logging.WARNING)
```

Usage in application code:

```python
import structlog

log = structlog.get_logger()

async def handle_message(message):
    log.info(
        "message_received",
        platform=message.source,
        user_id=message.user_id,
        message_type=message.input_type,
    )
    # ... process message ...
    log.info(
        "message_processed",
        platform=message.source,
        duration_ms=elapsed_ms,
    )
```

### Log Rotation (logrotate)

For native systemd deployments where logs go to files:

```
# /etc/logrotate.d/raven
/home/raven/raven/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 raven raven
    sharedscripts
    postrotate
        systemctl reload raven-bot 2>/dev/null || true
    endscript
}
```

For Docker deployments, configure Docker's logging driver instead:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
```

Place this in `/etc/docker/daemon.json` and restart Docker.

### Centralized Log Viewing

For Docker deployments, view logs with:

```bash
# All services
docker compose logs -f

# Specific service, last 100 lines
docker compose logs -f --tail=100 raven-bot

# Search logs for errors
docker compose logs raven-bot 2>&1 | grep '"level":"error"'
```

For systemd deployments:

```bash
# Follow bot logs
journalctl -u raven-bot -f

# Errors only, last hour
journalctl -u raven-bot --since "1 hour ago" -p err

# All RAVEN services
journalctl -u 'raven-*' -f
```

---

## Security Hardening

### Firewall Rules (UFW)

Only expose ports that need to be reachable from the internet. Everything else
stays on localhost or the internal Docker network.

```bash
# Reset and set defaults
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (restrict to your IP if possible)
sudo ufw allow 22/tcp

# HTTP and HTTPS (Caddy reverse proxy)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# MQTT (only if IoT devices connect from outside the server)
# sudo ufw allow 1883/tcp

# Enable
sudo ufw enable
sudo ufw status verbose
```

Ports that should NOT be exposed to the internet:

| Port | Service | Why Not |
|------|---------|---------|
| 5432 | PostgreSQL | Database should only be accessed locally |
| 6379 | Redis | No authentication by default |
| 8080 | SearXNG | Internal search proxy only |
| 8500 | raven-bot API | Behind Caddy reverse proxy |
| 9090 | Prometheus metrics | Internal monitoring |
| 9091 | Prometheus UI | Internal monitoring |
| 3000 | Grafana | Accessed through Caddy |

### HTTPS with Let's Encrypt (Caddy)

Caddy automatically obtains and renews TLS certificates from Let's Encrypt.

```
# config/Caddyfile
{
    email your-email@example.com
}

raven.yourdomain.com {
    # Bot API and WebSocket
    handle /api/* {
        reverse_proxy raven-bot:8500
    }
    handle /ws/* {
        reverse_proxy raven-bot:8500
    }

    # Grafana dashboard
    handle_path /grafana/* {
        reverse_proxy grafana:3000
    }

    # Default: return 404 for unknown paths
    handle {
        respond "Not Found" 404
    }

    # Security headers
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }
}
```

### SSH Hardening

```bash
# /etc/ssh/sshd_config (key settings to change)
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
AllowUsers raven

# Restart SSH
sudo systemctl restart sshd
```

Ensure you have your SSH public key in `/home/raven/.ssh/authorized_keys` before
disabling password authentication.

### Non-Root User for All Services

Never run RAVEN as root. The systemd service files above specify `User=raven`.
For Docker, the Dockerfile should use a non-root user:

```dockerfile
# In Dockerfile
FROM python:3.11-slim

RUN useradd -m -r -s /bin/bash raven
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R raven:raven /app

USER raven
CMD ["python", "-m", "raven.main"]
```

### Secrets Management

1. **Never commit secrets to git.** The `.env` file is in `.gitignore`.
2. **Secrets go in environment variables**, not in `config.yaml`.
3. **config.yaml references environment variables** for sensitive values:

```yaml
# config.yaml -- secrets are read from environment
telegram:
  bot_token_env: "TELEGRAM_BOT_TOKEN"   # reads os.environ["TELEGRAM_BOT_TOKEN"]

discord:
  bot_token_env: "DISCORD_BOT_TOKEN"

database:
  url_env: "DATABASE_URL"
```

4. For Docker, the `.env` file is automatically loaded by Docker Compose.
5. For systemd, the `EnvironmentFile` directive loads the `.env` file.

---

## Summary

| Concern | Solution |
|---------|----------|
| Deployment method | Docker Compose (primary) or systemd (alternative) |
| Server count | One machine, all services |
| GPU requirement | NVIDIA 8+ GB VRAM recommended; CPU-only fallback available |
| Reverse proxy / TLS | Caddy with automatic Let's Encrypt |
| Database backups | Automated daily pg_dump with 14-day retention |
| Monitoring | Prometheus metrics from bot + Grafana dashboards |
| CI/CD | GitHub Actions: lint, test, build image, deploy via SSH |
| Logging | structlog (JSON) with Docker log rotation or logrotate |
| Security | Firewall, HTTPS, SSH keys only, non-root user, secrets in env vars |
