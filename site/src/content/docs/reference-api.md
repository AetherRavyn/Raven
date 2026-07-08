---
title: "API Reference"
---

# API Reference

> **Document level**: Hermes  
> **Last updated**: 2026-06-30  
> **Server**: FastAPI at `http://localhost:8090`

---

## Response Format Convention

All API responses follow a uniform `ok`/`error` pattern:

```json
{
  "ok": true,
  ...data fields...
}
```

On failure:

```json
{
  "ok": false,
  "error": "human-readable message"
}
```

Legacy endpoints (non-dashboard REST APIs) may use `{"status": "ok"}` or `{"success": true}` — these are being migrated to the unified convention.

---

## Rate Limiting

Every response includes these headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

Default window: 100 requests per 60 seconds. Configurable via `RateLimitMiddleware`.

---

## Authentication

The API does **not** require authentication when bound to `127.0.0.1` (default). When bound to `0.0.0.0` or exposed publicly, authentication is provided via:

- **Bearer token** — set `API_BEARER_TOKEN` in `.env`
- **Header**: `Authorization: Bearer <token>`

Requests without a valid token receive `401 Unauthorized`. All endpoints respect this; the dashboard login page POSTs to `/api/auth/login`.

---

## Core REST Endpoints

### `GET /health`

System health and operating mode.

**Response**:

```json
{
  "status": "ok",
  "mode": "online",
  "timestamp": "2026-06-30T12:00:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` if the server is running |
| `mode` | string | `"online"`, `"degraded"`, or `"offline"` |
| `timestamp` | string | ISO 8601 UTC timestamp |

---

### `POST /api/v1/chat`

Synchronous chat endpoint (fallback — prefer WebSocket for production use).

**Request Body** (`application/json`):

```json
{
  "user_id": "alice",
  "message": "Hello, Raven!",
  "platform": "web",
  "chat_id": "default_chat"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `user_id` | string | — | User identifier |
| `message` | string | — | Message text |
| `platform` | string | `"web"` | Source platform |
| `chat_id` | string | `"default_chat"` | Conversation identifier |

**Response** (`ChatResponse`):

```json
{
  "success": true,
  "reply": "Hello! How can I help you today?",
  "state": "Completed",
  "timestamp": "2026-06-30T12:00:00+00:00"
}
```

Timeout: 30 seconds. Returns `{"success": false, "reply": "Timeout..."}` on timeout.

---

### `GET /api/v1/inbox/{user_id}`

Retrieve task inbox for a user.

**Response**:

```json
{
  "summary": { "total": 3, "pending": 2, "completed": 1 },
  "items": [
    { "task_id": "t_001", "title": "Review PR #42", "status": "pending" }
  ]
}
```

---

### `GET /api/v1/brief/{user_id}`

Get daily briefing for a user (weather, calendar, reminders).

**Response**: Arbitrary dict with briefing data.

---

### `GET /api/v1/goals/{user_id}`

List active goals for a user.

**Response**:

```json
{
  "goals": [
    { "id": "g_001", "title": "Learn Rust", "progress": 0.3 }
  ]
}
```

---

### `GET /api/v1/ledger/{user_id}`

List task ledger entries.

**Response**:

```json
{
  "tasks": [
    { "task_id": "t_001", "title": "System update", "status": "completed" }
  ]
}
```

---

## WebSocket Streaming

### `ws://localhost:8090/ws/v1/chat/{user_id}`

Real-time bidirectional chat with live state updates.

**Client → Server** (text frames):

```
Hello, Raven!
```

**Server → Client** (JSON frames):

```json
{"type": "status", "state": "Thinking", "icon": "🧠"}
{"type": "message", "role": "assistant", "content": "Hello!", "source_kind": "chat", "tool_traces": []}
{"type": "status", "state": "Idle", "icon": "💤"}
```

| Message Type | Fields | Description |
|---|---|---|
| `status` | `state`, `icon` | Cognitive state transitions |
| `message` | `role`, `content`, `source_kind`, `tool_traces` | Assistant response |
| `error` | `content` | Error message |

**Tool traces** format:

```json
{
  "tool": "web_search",
  "action": "execute",
  "success": true,
  "detail": "Found 3 results"
}
```

---

### `ws://localhost:8090/ws/ui`

Presence UI WebSocket — pushes system telemetry every 2 seconds.

**Server → Client**:

```json
{
  "type": "update",
  "cognitive": { "status": "Idle", "active_task": "None", "ledger_count": 5 },
  "hardware": { "cpu": 23.5, "memory": 45.1, "disk": 62.3 },
  "swarm": { "router": "AutoModelRouter", "active_model": "GPT-4o", "last_fallback": "None" },
  "edge": [{"id": "node-alpha", "status": "online"}],
  "mirofish": { "forecast": "Stable", "confidence": 85 },
  "approvals": [{"id": "task_abc", "summary": "Review PR #42"}]
}
```

---

## Edge Node API

All endpoints under `/api/v1/edge`.

### `POST /api/v1/edge/register`

Register an edge node.

**Request**:

```json
{
  "node_id": "living-room-pi",
  "capabilities": ["bash", "python", "docker"],
  "location": "Living Room",
  "sensors": ["temperature", "humidity"]
}
```

**Response**: `{"status": "ok", "message": "Registered living-room-pi"}`

### `GET /api/v1/edge/nodes`

List active edge nodes (seen within 5 minutes).

**Response**:

```json
{
  "nodes": {
    "living-room-pi": {
      "capabilities": ["bash", "python"],
      "location": "Living Room",
      "last_seen": 1234567890.0
    }
  }
}
```

### `POST /api/v1/edge/sensor_event`

Report a sensor reading from an edge node.

**Request**:

```json
{
  "node_id": "living-room-pi",
  "sensor": "temperature",
  "value": 22.5,
  "is_anomaly": false
}
```

**Response**: `{"status": "ok"}`

Anomalous readings (`is_anomaly: true`) automatically create a task in the ledger.

### `GET /api/v1/edge/tasks/{node_id}`

Claim a task for an edge node.

**Response**:

```json
{
  "task": {
    "task_id": "t_001",
    "task_type": "shell_exec",
    "title": "Run backup script",
    "metadata": {}
  }
}
```

Returns `{"task": null}` if no tasks available.

### `POST /api/v1/edge/tasks/{task_id}/complete`

Report task completion.

**Request**:

```json
{
  "result": {"output": "Backup complete", "exit_code": 0},
  "success": true
}
```

**Response**: `{"status": "ok"}`

---

## ACP (Agent Communication Protocol)

### `POST /acp`

Agent Communication Protocol endpoint for IDE/tool integration.

**Request**: Arbitrary JSON-RPC-style payload.

**Response**: `{"success": true, ...handler-specific fields...}`

### `GET /acp/health`

ACP health check.

**Response**: `{"status": "ok", "protocol": "acp/1.0"}`

---

## OpenAI-Compatible API

Routes registered at `/v1/...` when the OpenAI API bridge is active (see `app/web/openai_api.py`). Supports standard OpenAI chat completions format.

---

## Dashboard Page Routes

These serve HTML pages rendered from Jinja2 templates under `app/web/templates/pages/`.

| Route | Page Description |
|-------|-----------------|
| `/` or `/page/home` | Home dashboard |
| `/page/chat` | Chat interface |
| `/page/sessions` | Session history |
| `/page/models` | Model configuration |
| `/page/providers` | Provider status |
| `/page/provider-manage` | Provider management |
| `/page/cowork` | Coworking sessions |
| `/page/knowledge-graph` | Knowledge graph explorer |
| `/page/memory` | Memory browser |
| `/page/logs` | Audit/log viewer |
| `/page/cron` | Cron job management |
| `/page/skills` | Skills registry |
| `/page/plugins` | Plugin management |
| `/page/mcp` | MCP server management |
| `/page/channels` | Platform channel status |
| `/page/webhooks` | Webhook management |
| `/page/pairing` | DM pairing requests |
| `/page/profiles` | User profiles |
| `/page/kanban` | Kanban board |
| `/page/blueprints` | Automation blueprints |
| `/page/automation` | Automation dashboard |
| `/page/learning` | Learning system |
| `/page/learned-skills` | Crystallized skills |
| `/page/personality` | Personality traits |
| `/page/modules` | A2A modules |

Short redirects exist (e.g., `/chat` → `/page/chat`) for all slugs listed above.

---

## Learning API

### `GET /api/learning/stats`

Learning store statistics.

**Response**:

```json
{
  "stats": {
    "total": 142,
    "by_type": {"correction": 30, "fact": 80, "pattern": 20, "feedback": 12},
    "avg_confidence": 0.87
  }
}
```

### `GET /api/learning/recent`

Recent learning items.

**Query params**: `type` (string, optional), `limit` (int, default 20).

**Response**:

```json
{
  "items": [
    {"id": 1, "type": "fact", "content": "User prefers dark mode", "confidence": 0.95}
  ]
}
```

### `GET /api/learning/search`

Full-text search across learning store.

**Query params**: `q` (string, required), `limit` (int, default 10).

**Response**:

```json
{
  "results": [...],
  "query": "dark mode"
}
```

### `GET /api/learning/events`

Recent learning events.

**Query params**: `kind` (string, optional), `limit` (int, default 20).

**Response**:

```json
{
  "events": [...]
}
```

### `GET /api/learning/health`

Learning system health snapshot.

**Response**:

```json
{
  "health": { "status": "healthy", "last_consolidation": "..." }
}
```

### `GET /api/learning/skills`

List crystallized skills.

**Response**:

```json
{
  "skills": [
    {"name": "daily_briefing", "version": "1.0", "run_count": 42}
  ]
}
```

### `GET /api/learning/contradictions`

Report contradictions in the knowledge store.

**Response**:

```json
{
  "contradictions": [...]
}
```

### `GET /api/learning/most-used`

Most-used learning items.

**Query params**: `limit` (int, default 10).

### `GET /api/learning/verification`

Self-improvement verification stats.

**Response**:

```json
{
  "verification": {
    "total_checks": 500,
    "passed": 480,
    "failed": 20,
    "correction_rate": 0.96
  }
}
```

### `GET /api/learning/topic-trends`

Topic trend analysis.

**Query params**: `limit` (int, default 20).

---

## Cron API

### `GET /api/cron/list`

List all cron jobs.

**Response**: `{"ok": true, "jobs": [...], "count": N}`

### `POST /api/cron/toggle`

Enable/disable a cron job.

**Body**: `{"job_id": "..."}`

**Response**: `{"ok": true, "job_id": "..."}`

### `POST /api/cron/add`

Add a cron job.

**Body**:

```json
{
  "job_id": "morning_briefing",
  "name": "Morning Briefing",
  "description": "Send daily briefing",
  "schedule_type": "daily",
  "action_description": "briefing",
  "time_str": "08:00"
}
```

**Response**: `{"ok": true, "job": {...}}`

### `POST /api/cron/remove`

Remove a cron job.

**Body**: `{"job_id": "..."}`

---

## Channels API

### `GET /api/channels/status`

Gateway daemon status.

**Response**: `{"ok": true, "gateway": {"telegram": "running", "discord": "stopped", ...}}`

### `POST /api/channels/start`

Start a channel.

**Body**: `{"name": "telegram"}`

### `POST /api/channels/stop`

Stop a channel.

**Body**: `{"name": "telegram"}`

### `POST /api/channels/restart`

Restart a channel.

**Body**: `{"name": "telegram"}`

### `GET /api/calls/status`

Active call status.

### `POST /api/calls/make`

Initiate an outbound call.

**Body**: `{"target": "+15551234567", "platform": "telegram"}`

### `POST /api/calls/hangup`

End a call.

**Body**: `{"call_id": "..."}`

### `POST /api/calls/answer`

Answer an incoming call.

**Body**: `{"call_id": "..."}`

---

## Pairing API

### `GET /api/pairing/list`

List pending and approved pairing requests.

**Response**: `{"ok": true, "pending": [...], "paired": [...], "pending_count": N, "paired_count": N}`

### `POST /api/pairing/approve`

Approve a pairing code.

**Body**: `{"code": "ABC123", "approved_by": "admin"}`

### `POST /api/pairing/revoke`

Revoke a pairing.

**Body**: `{"user_id": "...", "platform": "telegram"}`

---

## MCP API

### `GET /api/mcp/status`

MCP server connection status.

**Response**: `{"ok": true, "servers": [...], "tool_names": [...], "connected": true, "tool_count": N}`

### `POST /api/mcp/connect`

Connect to MCP servers.

**Body**: `{"servers": [{"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}]}`

---

## Webhooks API

### `GET /api/webhooks/list`

List registered webhooks.

**Response**: `{"ok": true, "webhooks": [...], "count": N}`

### `POST /api/webhooks/test`

Test a webhook.

**Body**: `{"webhook_id": "wh_123"}`

### `POST /api/webhooks/add`

Register a new webhook.

**Body**: `{"url": "https://example.com/hook", "events": ["*"], "secret": "abc", "name": "My Hook"}`

### `POST /api/webhooks/remove`

Remove a webhook.

**Body**: `{"webhook_id": "wh_123"}`

---

## Plugins API

### `GET /api/plugins/list`

List all plugins.

**Response**: `{"ok": true, "plugins": [...], "count": N}`

### `GET /api/plugins/summary`

Plugin health summary.

**Response**: `{"ok": true, "summary": {"count": 5, "healthy": 4, "degraded": 1, "unhealthy": 0}}`

### `POST /api/plugins/enable`

Enable a plugin.

**Body**: `{"plugin_id": "..."}`

### `POST /api/plugins/disable`

Disable a plugin.

**Body**: `{"plugin_id": "..."}`

### `POST /api/plugins/remove`

Remove a plugin.

**Body**: `{"plugin_id": "..."}`

---

## Profiles API

### `GET /api/profiles/list`

List all user profiles.

**Response**: `{"ok": true, "user_ids": ["alice", "bob"], "count": 2}`

### `GET /api/profiles/load`

Load a specific profile.

**Query params**: `user_id` (required).

**Response**: `{"ok": true, "user_id": "alice", "display_name": "Alice", "preferences": {...}, "facts": [...], "projects": [...], "pinned": [...], "updated_at": "..."}`

### `POST /api/profiles/save`

Save a user profile.

**Body**: `{"user_id": "alice", "display_name": "Alice", "preferences": {...}}`

### `POST /api/profiles/delete`

Delete a user profile.

**Body**: `{"user_id": "alice"}`

---

## Skills API

### `GET /api/skills/list`

List all skills from the registry.

**Response**: `{"ok": true, "skills": [...], "count": N}`

### `GET /api/skills/summary`

Skills registry summary.

**Response**: `{"ok": true, "summary": {...}}`

### `GET /api/skills/onboarding`

Skills onboarding queue.

**Response**: `{"ok": true, "queue": [...], "count": N}`

### `POST /api/skills/enable`

Enable a skill.

**Body**: `{"skill_id": "..."}`

### `POST /api/skills/disable`

Disable a skill.

**Body**: `{"skill_id": "..."}`

### `POST /api/skills/uninstall`

Uninstall a skill.

**Body**: `{"skill_id": "..."}`

---

## Kanban API

### `GET /api/kanban/list`

List kanban cards.

**Query params**: `status` (optional), `agent_id` (optional).

**Response**:

```json
{
  "ok": true,
  "count": 5,
  "cards": [
    {
      "id": 1,
      "title": "Implement login",
      "description": "...",
      "status": "in_progress",
      "agent_id": "dev",
      "priority": 1,
      "tags": ["auth"],
      "blocked_reason": null,
      "created_at": "2026-06-01T12:00:00"
    }
  ]
}
```

### `GET /api/kanban/summary`

Board summary statistics.

**Response**: `{"ok": true, "by_status": {"todo": 3, "in_progress": 5, "done": 12}}`

### `POST /api/kanban/add`

Create a new card.

**Body**:

```json
{
  "title": "Fix bug #42",
  "description": "Investigate race condition",
  "agent_id": "dev",
  "priority": 2
}
```

### `POST /api/kanban/move`

Move a card to a different status column.

**Body**: `{"card_id": 1, "status": "done"}`

---

## Blueprints API

### `GET /api/blueprints/list`

List automation blueprints.

**Response**: `{"ok": true, "count": N, "blueprints": [{"name": "...", "version": "1.0", ...}]}`

### `POST /api/blueprints/install`

Install a blueprint from YAML content.

**Body**: `{"name": "backup", "content": "name: backup\nversion: '1.0'\nsteps:\n  - ..."}`

### `POST /api/blueprints/run`

Execute a blueprint.

**Body**: `{"blueprint_id": "backup"}`

**Response**: `{"ok": true, "success": true, "steps_completed": 3, "steps_total": 3, "duration_ms": 1200}`

### `POST /api/blueprints/enable`

Enable a blueprint.

**Body**: `{"blueprint_id": "backup"}`

### `POST /api/blueprints/disable`

Disable a blueprint.

**Body**: `{"blueprint_id": "backup"}`

---

## Automation API

### `GET /api/automation/health`

System health with services, agents, scheduler info.

**Response**:

```json
{
  "ok": true,
  "health": { "cpu": 23.5, "memory": 45.1, "disk": 62.3, "uptime": 72.5 },
  "services": { "kanban": true, "blueprints": true, "hooks": true, ... },
  "agents": { "orchestrator": true, "dev": true, ... },
  "scheduler": { "daily_briefing": { "enabled": true, "interval": 24 } },
  "rateLimit": { "enabled": true }
}
```

### `GET /api/hooks/stats`

Hook delivery statistics.

**Response**: `{"ok": true, "total_hooks": 10, "total_deliveries": 500, "success_rate": 0.98, "pending_retries": 0}`

### `POST /api/automation/service/toggle`

Start/stop/restart a service.

**Body**: `{"service": "kanban", "action": "start"}`

### `POST /api/automation/rate-limit/toggle`

Toggle rate limiting.

**Body**: `{"enabled": true}`

---

## Audit API

9 endpoints mounted from `app.core.audit.api.build_router()`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/audit/events` | List audit events with filtering |
| GET | `/api/audit/stats` | Audit statistics |
| GET | `/api/audit/timeline` | Event timeline |
| GET | `/api/audit/export` | CSV export of audit events |
| GET | `/api/audit/approvals/pending` | Pending approvals |
| POST | `/api/audit/approvals/{id}/resolve` | Resolve an approval |
| GET | `/api/audit/health` | Audit log health |

---

## Search API

### `GET /api/search`

Global search across sessions and learning store.

**Query params**: `q` (string, required), `limit` (int, default 10).

**Response**:

```json
{
  "ok": true,
  "results": [
    {"type": "session", "label": "alice", "url": "/page/sessions"},
    {"type": "memory", "label": "User prefers dark mode...", "url": "/page/learning"}
  ],
  "count": 2
}
```

---

## Onboarding API

### `GET /api/onboarding/status`

Check if onboarding has been completed.

**Response**: `{"ok": true, "onboarded": true, "step": "done"}`

### `POST /api/onboarding/complete`

Mark onboarding as complete.

**Response**: `{"ok": true}`

---

## Config Editor API

### `GET /api/config/show`

Show current configuration.

**Response**: Config key-value pairs.

### `POST /api/config/update`

Update configuration values.

**Body** (form-encoded): key-value pairs to update.

### `POST /api/config/reset`

Reset configuration to defaults.

---

## BotSignal Message Bus Protocol

BotSignal is Raven's unified output API. Every platform connector registers a sender function; all tool execution and cognitive output routes through a single `BotSignal.send()` call.

### Architecture

```
Tool/Cognitive Module
        │
        ▼
   BotSignal.send(target, payload)
        │
        ▼
   Outbox.enqueue(idempotency_key, channel, target, action, payload)
        │
        ▼
   Platform Sender (registered per channel)
        │
        ▼
   Platform API (Telegram, Discord, WebSocket, etc.)
```

### SignalPayload Fields

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Message text content |
| `source_kind` | string | Origin context: `"chat"`, `"briefing"`, `"alert"`, `"tool_result"` |
| `evidence` | list[string] | Supporting evidence citations |
| `tool_traces` | list[ToolTrace] | Tool execution trace log |
| `reply_to_id` | string | Optional message ID being replied to |

### ToolTrace Fields

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Tool name (e.g., `"web_search"`) |
| `action` | string | Action performed (e.g., `"execute"`) |
| `success` | bool | Whether the tool call succeeded |
| `detail` | string | Human-readable result summary |

### Idempotency

Every `send()` call generates a unique nonce from a process-wide monotonic counter combined with a nanosecond timestamp. The outbox deduplicates on `(channel, chat_id, payload_hash, nonce)` — two identical messages with different nonces are distinct entries.

### Retry Safety

The outbox drains once per tick. Failed sends (platform API error) are retried with exponential backoff. The idempotency key prevents duplicate delivery on retry.

---

## A2A Module Protocol

Agent-to-Agent (A2A) modules are self-contained capability packages discovered by `SkillRegistry` and callable through the `raven modules` CLI or the dashboard.

### Module Interface

Each module exports a `CardDescriptor` (from `raven_protocol`) with:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Module name (e.g., `"memory"`) |
| `description` | string | Human-readable description |
| `version` | string | Semver version |
| `transport` | string | Transport type (`"local"`, `"http"`, `"grpc"`) |
| `skills` | list[SkillDescriptor] | Exposed skill methods |
| `tags` | list[string] | Discovery tags |

### SkillDescriptor Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill method name |
| `description` | string | What this skill does |
| `parameters` | dict | JSON Schema for parameters |
| `returns` | dict | JSON Schema for return value |

### Invocation

Modules are invoked via the CLI:

```bash
raven modules call <module> <method> '<json_params>'
```

Or programmatically through the `ModuleRegistry`:

```python
registry = get_registry()
result = await registry.call("memory", "memory.recall", {"query": "hello"})
```

### Discovery

```bash
raven modules discover <tags...>
```

Filters modules by skill tags for composable capability discovery.

### Registry

The process-wide `ModuleRegistry` is populated at startup by `SkillRegistry.discover()`. Modules can be added at runtime. Each module should have a `SKILL.md` and `module.yaml` manifest in its directory.
