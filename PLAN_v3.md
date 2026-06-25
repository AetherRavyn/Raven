# AetherRavyn — Friday/JARVIS Master Plan v3.1
## "Make It Real. Make It World-Class."

**Document status:** Living master plan (v3.1 — HelixDB + model-agnostic amendment)
**Date:** 2026-06-15
**Owner:** Swadhin Biswas
**Goal:** Ship a JARVIS/Friday-class personal AI agent that beats Hermes, OpenClaw, and every open-source alternative — in production quality, intelligence depth, and user experience.

---

## PART 0.5 — AMENDMENT (2026-06-15, post-review)

Two new constraints shape the rest of the plan:

### A. Storage: HelixDB (instead of Neo4j + ChromaDB)
- **Why:** HelixDB is a graph+vector+KV+document+relational database in one Rust engine. Apache 2.0, 5.2k stars, OLTP, embedded via `helix start dev --disk` (port 6969). Replaces BOTH ChromaDB and Neo4j.
- **Stack simplification:** ChromaDB + Neo4j + SQLite + Redis → **HelixDB + SQLite + Redis** (Redis is optional, drop later)
- **Python integration:** build a thin `app/db/helix.py` HTTP client against `POST /v1/query` (their REST endpoint)
- **Performance target:** <5ms p95 for vector search, <10ms p95 for graph traversal
- **Deployment:** `helix start dev --disk` as background process; bundled with `start_all.sh`
- **What we keep:** SQLite for structured data (sessions, plans, audit), Redis optional for hot cache

### B. Model: 100% Model-Agnostic
- **Principle:** AetherRavyn ships with **NO model of its own.** The user picks the model(s) — local or cloud — and AetherRavyn orchestrates them.
- **Provider adapters (built-in, all optional):**
  - **Local:** Ollama, LM Studio, vLLM, llama.cpp server, any OpenAI-compatible endpoint
  - **Cloud:** Anthropic, OpenAI, xAI (Grok), Google Gemini, Mistral, Cohere, DeepSeek, OpenRouter, Groq, Together, Fireworks, AWS Bedrock, Azure OpenAI
  - **Custom:** user can add a new adapter in <30 lines (just an OpenAI-compatible base URL + API key)
- **Standard interface:** OpenAI-compatible `/v1/chat/completions` and `/v1/embeddings`
- **Model routing:** local-first → small cloud → large cloud; configurable per task type
- **Zero lock-in:** if a provider dies, swap to another in 1 config change
- **Embedding models:** any OpenAI-compatible embedding endpoint (local `nomic-embed-text`, `mxbai-embed-large`, `bge-*`, or cloud `text-embedding-3-small`, etc.)
- **Setup:** first-run wizard asks "do you have Ollama running? an OpenAI key? a local server?" — configures accordingly

### C. Scope: ALL 6 Phases (24 weeks)
- Building A+B+C only is rejected — we go all the way
- Timeline remains 24 weeks; team (you + me) prioritizes per week
- Each phase ends with a demoable artifact

---

## PART 0 — The North Star

A user installs AetherRavyn. Within 7 days, they say **"I can't work without it."** It is:

1. **Anticipatory** — knows what they need before they ask
2. **Multimodal** — hears, sees, reads, types, watches
3. **Personal** — knows them, their projects, their world
4. **Reliable** — never hallucinates a fact, never lies about doing something
5. **Cheap** — runs primarily on local compute, costs pennies a day
6. **Trustworthy** — every action has a reason, a risk, a rollback
7. **Always-on** — quietly running, speaks only when value > noise
8. **Self-improving** — visibly learns from interactions

**We measure success by 5 user outcomes:**
- D7 retention: >70% come back daily
- D30 retention: >40% consider it essential
- Avg proactive acceptance: >30% of nudges acted on
- Avg time saved/day: >45 min (self-reported)
- NPS: >50

---

## PART 1 — Production-Grade Principles

Every line of code we write from now on obeys these:

### 1.1 Quality Bar (Non-Negotiable)
- **Type hints everywhere** (PEP 604 unions, generics, TypeVar)
- **Pyright strict** — no `# type: ignore` without justification
- **Ruff clean** — `ruff check` returns 0
- **Ruff-formatted** — `ruff format` returns 0
- **100-char line limit**
- **No `print()`** — use `logging.getLogger(__name__)`
- **No bare `except:`** — catch specific exceptions
- **No `import *`** — explicit imports
- **No circular dependencies** — enforced by import-linter
- **No global mutable state** — pass explicitly
- **Docstrings** — Google style on every public class/function
- **Tests required** — every new module has `test_*.py`, >85% coverage for `app/core/`, >70% for `app/tools/`
- **Async-first** — every I/O is async, no blocking calls in event loop
- **No silent failures** — every error logged + surfaced
- **No magic numbers** — config in one place (`app/settings/`)

### 1.2 Production Hardening
- **Graceful degradation** — every external dependency has a fallback
- **Circuit breakers** — every external call goes through `app/tools/resilience.py`
- **Idempotency** — all mutating operations are idempotent or detect re-runs
- **Schema validation** — Pydantic on every I/O boundary
- **Secrets management** — `app/core/secret_vault.py`, no env reads in code
- **Audit trail** — every mutating action recorded with reason + before/after
- **Rollback** — every mutating action has a documented rollback path
- **Bounded resources** — every loop has a max-iteration, every queue has a max-size
- **Backpressure** — if a worker is overloaded, drop or queue, never crash

### 1.3 Observability (From Day 1)
- **Structured JSON logs** — every log line is parseable
- **OpenTelemetry traces** — span per tool call, per agent, per LLM call
- **Prometheus metrics** — `raven_tool_calls_total{tool,status}`, `raven_latency_seconds{tool}`, `raven_tokens_total{model}`, `raven_cost_usd_total{model}`
- **Request IDs** — propagate `trace_id` through every async hop
- **Health endpoints** — `/health`, `/ready`, `/metrics`
- **Audit dashboard** — what did the agent do, when, why
- **Cost dashboard** — tokens/$ per day, per user, per agent

### 1.4 Security (Zero-Trust)
- **DM pairing enforced** on all channels
- **Per-user permissions** — read/write/admin
- **Per-agent permissions** — what each agent can do
- **Tool risk classification** — `low | medium | high | critical`
- **Approval workflow** — `high` and `critical` require explicit user approval
- **Prompt injection detection** — `app/core/security.py` active on all channels
- **Dangerous command blocking** — `rm -rf /`, fork bombs, etc.
- **Rate limiting** — per-user, per-channel, per-tool
- **Output sanitization** — no secrets in logs, no PII in telemetry
- **Sandboxing** — `DockerTool` / `SandboxExecTool` for any untrusted code
- **Secret scanning** — pre-commit hook blocks commits with secrets

### 1.5 Performance Budgets
- **System 1 (reflex)** — p50 < 200ms, p95 < 800ms
- **System 2 (deep)** — p50 < 5s, p95 < 30s
- **Tool call overhead** — p95 < 100ms (excluding tool work)
- **LLM TTFT (time-to-first-token)** — p95 < 1.5s for streaming
- **Voice STT latency** — p95 < 1s for short utterances
- **Voice TTS TTFB** — p95 < 300ms
- **Memory retrieval** — p95 < 100ms
- **Ambient loop tick** — < 5s for all workers combined
- **Dashboard API** — p95 < 200ms
- **Cost per session** — < $0.05 average
- **Cost per proactive nudge** — < $0.002

### 1.6 Reliability Targets
- **Uptime** — >99.5% (allows ~3.6 hours downtime/month)
- **MTTR (mean time to recover)** — < 5 minutes
- **Zero data loss** for user memories, plans, and skills
- **Auto-recovery** — daemon restarts failed workers, replays events
- **No silent corruption** — all writes checksummed

---

## PART 2 — Target Architecture (Where We're Going)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         AetherRavyn v3                                │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      Presentation Layer                        │    │
│  │                                                                │    │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌──────┐ │    │
│  │  │Telegram│ │Discord │ │ Slack  │ │Voice │ │ Web  │ │  IRC │ │    │
│  │  │        │ │        │ │        │ │(wake)│ │ (UI) │ │      │ │    │
│  │  └────────┘ └────────┘ └────────┘ └──────┘ └──────┘ └──────┘ │    │
│  │                                                                │    │
│  │  Channels → UnifiedEventBus → Orchestrator                    │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                    Core Intelligence                           │    │
│  │  ┌────────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌────────┐ ┌─────┐ │    │
│  │  │Persona │ │ Soul │ │  User  │ │ Meta │ │Planner │ │Exec │ │    │
│  │  │Engine  │ │Engine│ │ Model  │ │  Cog │ │ (real) │ │     │ │    │
│  │  └────────┘ └──────┘ └────────┘ └──────┘ └────────┘ └─────┘ │    │
│  │  ┌────────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌────────┐ ┌─────┐ │    │
│  │  │Verif.  │ │Policy│ │ Router │ │Cache │ │Context │ │Trace│ │    │
│  │  │        │ │Engine│ │ (cost) │ │      │ │Builder │ │     │ │    │
│  │  └────────┘ └──────┘ └────────┘ └──────┘ └────────┘ └─────┘ │    │
│  │  ┌────────┐ ┌──────┐ ┌────────┐                             │    │
│  │  │ Agent  │ │Skill │ │  Know  │                             │    │
│  │  │ Swarm  │ │Engine│ │ Graph  │                             │    │
│  │  └────────┘ └──────┘ └────────┘                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Memory & Knowledge Layer                     │    │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐               │    │
│  │  │HelixDB  │ │HelixDB   │ │HelixDB   │ │SQLite│               │    │
│  │  │Semantic │ │Graph     │ │Vector+KV │ │Plans │               │    │
│  │  │(vector)  │ │(entities)│ │(sessions)│ │Audit │               │    │
│  │  └─────────┘ └──────────┘ └──────────┘ └──────┘               │    │
│  │  One engine. Graph + Vector + KV + Doc + Relational.         │    │
│  │  MemoryManager: store/retrieve/consolidate/decay/conflict    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Tool & Skill Layer                            │    │
│  │  75+ Tools (typed) │ SkillRegistry │ MCP │ Sandbox           │    │
│  │  Every tool: risk, cost, permissions, dry-run, rollback      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Provider & Resilience                        │    │
│  │  Model-AGNOSTIC: any OpenAI-compatible endpoint              │    │
│  │  Local: Ollama, LM Studio, vLLM, llama.cpp                   │    │
│  │  Cloud: Anthropic, OpenAI, xAI, Gemini, Mistral, Bedrock    │    │
│  │  Tier router: tiny → small → large; cost cap; circuit break │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Ambient & Proactive                          │    │
│  │  11 workers + anticipation + anomaly + value-gate + dnd     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                  Observability & Ops                          │    │
│  │  OTel traces │ Prometheus │ Structured logs │ Audit log     │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## PART 3 — Six-Phase Build Plan (24 Weeks)

Total: **24 weeks, 6 phases, ~200 deliverables**

---

### PHASE A — Foundation Hardening (Weeks 1-4)
**Goal:** Make the spine work end-to-end, observable, and safe.

#### A1. Real Hierarchical Planner (Week 1-2)
**Why first:** Everything else (proactive, executor, cost routing) depends on planning being real.

**Deliverables:**
- [ ] `app/core/planning/planner.py` — hierarchical planner (replaces 132-line stub)
  - `TaskPlan` with steps, deps, parallel groups
  - Cost estimate per step (tokens, time, $)
  - Latency estimate per step
  - Dead-letter queue for failed steps
  - Plan persistence to SQLite (`~/.raven/plans/`)
  - Resume after crash
- [ ] `app/core/planning/executor.py` — plan executor
  - Sequential + parallel mode
  - Retry with exponential backoff (max 3)
  - Replan on failure (LLM suggests alternate strategy)
  - Checkpoint after each step
- [ ] `app/core/planning/cost_estimator.py` — pre-execution cost
  - Per-model token cost table
  - Tool cost table (per-call, per-byte, per-second)
  - Returns: `{tokens, usd, latency_ms, risk}`
- [ ] `app/core/planning/replanner.py` — failure recovery
  - On step fail, ask LLM: "step X failed with Y. 3 alternatives: A, B, C"
  - Pick lowest-cost viable alternative
  - Track replan history
- [ ] `app/core/planning/goal_tracker.py` — long-horizon
  - Goals with deadlines
  - Auto-decompose into daily/weekly steps
  - Status: pending, active, paused, completed, abandoned
  - Carry across sessions
- [ ] Tests: `tests/test_planner.py`, `tests/test_executor.py`, `tests/test_replanner.py`
  - 50+ test cases including: deep recursion, parallel execution, replan paths
  - Property-based tests with `hypothesis` for plan invariants
- [ ] **Migration:** keep old `planner.py` as compat shim, route `planner_v2`

**Acceptance:**
- 95% of `pytest tests/test_planning/` passes
- Plan that takes 10 steps persists + resumes after kill -9
- Replan succeeds in 3 distinct failure scenarios

#### A2. Cost-Aware Model Router (Week 2)
**Why:** The whole "cheap local" promise depends on this being real.

**Deliverables:**
- [ ] `app/core/runtime_v2/cost_router.py`
  - Tier table: `{tiny, small, medium, large, premium}` per provider
  - Task classifier: which tier for which task
  - Hard cost cap per request, per hour, per day
  - Soft preference (e.g., "prefer local for greetings")
  - Real-time cost tracking with Prometheus
- [ ] `app/core/runtime_v2/circuit_breaker.py` — per-tool, per-provider
  - States: closed, open, half-open
  - Configurable thresholds, recovery time
  - Emits metrics
- [ ] `app/core/runtime_v2/cache.py` — semantic response cache
  - Cache key = embedding(query) + context_hash
  - LRU + TTL
  - Cache hit rate metric
- [ ] `app/core/runtime_v2/queue.py` — work queue
  - Priority lanes: `interactive`, `background`, `bulk`
  - Preemption (interactive can preempt background)
  - Backpressure
- [ ] Tests: `tests/test_cost_router.py`, `tests/test_circuit_breaker.py`
- [ ] **Dashboard panel:** cost dashboard (today, this week, per-agent, per-model)

**Acceptance:**
- 80% of "hello/good morning" requests hit tiny local model
- Cost dashboard shows real-time spend
- Circuit breaker trips on simulated 5xx storm, recovers in 60s

#### A3. Real Tool Verifier (Week 3)
**Why:** Hallucinations kill trust. Every tool result must be checked.

**Deliverables:**
- [ ] `app/core/verification/verifier.py` — real verifier (extends existing 132 lines)
  - Per-tool validators (regex, schema, semantic)
  - Confidence score per verification
  - Retry on low confidence
  - Cache validation rules per tool
- [ ] `app/core/verification/validators/` — one per category
  - `file.py` — does file actually exist, size plausible
  - `web.py` — URL reachable, content not 404, no malware
  - `exec.py` — exit code 0, output matches expected pattern
  - `finance.py` — numbers in plausible range
  - `device.py` — action succeeded (screenshot matches intent)
  - `generic.py` — JSON schema, length bounds, profanity filter
- [ ] `app/core/verification/hallucination_check.py`
  - For LLM-generated text: check facts against memory + tools used
  - Flag claims with no source
  - Add citation requirement to system prompt
- [ ] `app/core/verification/rollback.py`
  - Every mutating tool declares a `rollback()` method
  - Rollback registry: `tool_name → rollback_fn`
  - Dry-run mode: simulate mutation, return what would change
- [ ] Tests: `tests/test_verifier.py` (60+ cases)
- [ ] **Wire:** every tool call goes through verifier in runtime

**Acceptance:**
- 95% of bad tool results caught before reaching LLM
- Rollback succeeds for 10 common mutations
- Hallucination flag rate: 0 false negatives on 100 test prompts

#### A4. Real Audit & Action Policy (Week 3-4)
**Deliverables:**
- [ ] `app/core/audit/audit_log.py` — real audit log (SQLite + JSONL)
  - Every tool call: who, when, what, why, result, duration, cost
  - Every agent handoff
  - Every approval request
  - Every config change
  - Searchable + filterable
- [ ] `app/core/audit/dashboard.py` — `/audit` page
  - Timeline view
  - Filter by tool/agent/user/date
  - "Replay" button (re-run a turn with same inputs)
  - Export to CSV/JSON
- [ ] `app/core/policy_v2/policy.py` — re-architecture of `policy.py`
  - Per-user, per-agent, per-tool policy
  - Risk scoring: `0-100`, threshold configurable
  - Approval: auto-approve / ask / block
  - Trust tier: per-user, decays with misuse
- [ ] `app/core/policy_v2/approvals.py`
  - Pending approval queue
  - Multi-channel delivery (Telegram, Discord, web)
  - Timeout policy (default: deny)
  - "Always allow" patterns
- [ ] **Security fixes** (from friday.md):
  - Admin deny-by-default
  - Remove hard-coded Redis URL
  - Encrypt all credentials at rest
  - Rotate secrets quarterly

**Acceptance:**
- Every action auditable from dashboard
- Approval flow works end-to-end (request → notify → approve → execute)
- 100% of high-risk actions require explicit approval

#### A5. Observability Foundation (Week 4)
**Deliverables:**
- [ ] `app/observability/tracing.py` — OpenTelemetry init
  - Span per tool call, per agent, per LLM call, per I/O
  - Auto-instrumentation for httpx, asyncio, sqlalchemy
  - Export to OTLP-compatible backend
- [ ] `app/observability/metrics.py` — Prometheus
  - All metrics from §1.3
  - Per-tool, per-agent, per-model labels
- [ ] `app/observability/logging.py` — structured JSON
  - Replace all `print()` and basic logging
  - PII redaction
  - Log levels configurable per-module
- [ ] `app/observability/health.py` — health endpoints
  - `/health` (liveness, always 200 if process alive)
  - `/ready` (readiness, checks deps)
  - `/metrics` (Prometheus)
- [ ] `app/observability/dashboards/` — Grafana JSON
  - Cost dashboard
  - Latency dashboard
  - Error rate dashboard
  - Tool success rate dashboard
- [ ] Tests: smoke tests for `/health`, `/ready`, `/metrics`

**Acceptance:**
- Every tool call has a trace ID
- Grafana shows real-time metrics
- Logs are JSON parseable, PII-redacted

#### A6. CI/CD + Repo Hygiene (Week 4)
- [ ] `.github/workflows/ci.yml`
  - Lint (ruff), format check, type check (pyright), tests
  - Coverage gate: >80% for `app/core/`
  - Security scan (bandit, detect-secrets)
  - Build artifact (wheel + docker image)
- [ ] `.github/workflows/release.yml`
  - Auto-tag on version bump
  - Build + push docker image
  - Generate changelog
- [ ] Pre-commit hooks (`.pre-commit-config.yaml`)
  - ruff, ruff-format, pyright, detect-secrets
- [ ] `Makefile` (or `taskfile.yml`)
  - `make test`, `make lint`, `make typecheck`, `make run`, `make docker-build`
- [ ] Dependabot config
- [ ] `CODEOWNERS`

**Phase A Definition of Done:**
- [ ] All 6 sub-phases complete + acceptance tests pass
- [ ] Coverage >80% in `app/core/`
- [ ] CI green on `main`
- [ ] Dashboard shows cost, latency, audit
- [ ] One full E2E test: "user asks for a complex task" → plan → execute → verify → done


---

### PHASE B — The User Model (Weeks 5-8)
**Goal:** The agent knows the user.

#### B1. Rich User Profile (Week 5)
**Deliverables:**
- [ ] `app/core/user_model/profile.py`
  - Extends current `user_profile.py`
  - Typed fields: identity, work, projects, relationships, preferences, health, devices
  - Source-of-truth tag per field: `user_said | inferred | system_detected`
  - Confidence score per field
  - Version history
- [ ] `app/core/user_model/storage.py`
  - SQLite-backed with JSON blob + typed columns
  - Encrypted at rest
  - Export/import as single file
- [ ] `app/core/user_model/inspector.py`
  - "What do you know about me?" page
  - Group by category, show source + confidence
  - Edit, delete, pin fields
- [ ] `app/core/user_model/onboarding.py`
  - First-run flow: 10 questions to seed profile
  - "Tell me more" deep-dive
  - Skippable
- [ ] Tests: 40+ cases

#### B2. Life Context Graph (Week 5-6)
**Deliverables:**
- [ ] `app/core/user_model/life_graph.py`
  - Nodes: `Person`, `Project`, `Place`, `Event`, `Device`, `File`, `Task`
  - Edges: typed (`works_on`, `lives_at`, `owns`, `mentioned_in`, `last_interaction`)
  - Edges carry weight + recency
- [ ] `app/core/user_model/entity_resolver.py`
  - Merge "Bob" / "Robert" / "B." / "bob@x.com" → single entity
  - Fuzzy match + embedding similarity
  - User confirmation on merge
- [ ] `app/core/user_model/relationship_learn.py`
  - Infer relationships from message patterns
  - "mentioned 14 times this month" → important
  - "responds faster to" → priority
- [ ] `app/core/user_model/timeline.py`
  - Reconstruct past from memory + traces
  - "What was I working on Tuesday?" → queryable
  - Day/week/month views
- [ ] `app/core/user_model/ingest/`
  - From memory, files, calendar, email, chat history
  - Async, scheduled (hourly)
  - Incremental (only new events)
- [ ] Tests: 60+ cases including entity resolution edge cases

#### B3. Habits & Patterns (Week 6-7)
**Deliverables:**
- [ ] `app/core/user_model/habits.py`
  - Time-of-day patterns (e.g., checks email 9-10am)
  - Day-of-week patterns (e.g., "deep work" Saturdays)
  - Sequence patterns (e.g., "always reads X before Y")
  - Min support: 3 occurrences
- [ ] `app/core/user_model/energy.py`
  - Mood tracking from message tone (sentiment + emojis + punctuation)
  - Energy: time-of-day correlation
  - "low energy days" detection
  - Privacy: opt-out
- [ ] `app/core/user_model/preferences.py`
  - Typed preferences: `food`, `music`, `news`, `work_style`, `communication`
  - Contradiction resolution: "user said X then ¬X" → ask which is current
  - "Never" rules (stronger than "I don't like")
- [ ] `app/core/user_model/freshness.py`
  - Per-memory `created_at`, `last_reinforced`, `decay_rate`
  - Periodic decay (e.g., 0.05/week)
  - "Pin" to prevent decay
  - Conflict resolution: most recent wins, or ask
- [ ] Tests: 50+ cases

#### B4. Knowledge Graph v2 (Week 7-8)
**Why:** HelixDB is graph+vector+KV in one. We can stop maintaining 3 stores.

**Deliverables:**
- [ ] Replace `app/core/workspace_graph.py` (150 lines) with `app/core/knowledge/`
- [ ] `app/db/helix.py` — HelixDB Python client (HTTP, async)
  - Pool of connections to `http://localhost:6969/v1/query`
  - Typed query builders (graph + vector)
  - Auto-reconnect, circuit breaker
  - Migration helper: ChromaDB + Neo4j → HelixDB
- [ ] `app/core/knowledge/schema.py` — HelixDB schema definitions
  - Node types: `Person`, `Project`, `Place`, `Event`, `Device`, `File`, `Task`, `Skill`, `Memory`
  - Edge types: `works_on`, `lives_at`, `owns`, `mentioned_in`, `last_interaction`, `related_to`, `part_of`
  - Vector index on: `name`, `content`, `description`
  - KV index on: `id`, `user_id`, `created_at`
- [ ] `app/core/knowledge/graph.py` — HelixDB-backed graph operations
  - `add_entity()`, `add_edge()`, `find_related()`, `traverse()`
  - Sub-10ms p95 latency target
- [ ] `app/core/knowledge/query.py` — graph queries for prompts
  - "what's related to X?" — vector + graph hybrid query
  - "what did I work on last Tuesday?" — temporal traversal
- [ ] `app/core/knowledge/retrieval.py` — rank retrieval by graph proximity
  - Combine: semantic similarity × graph distance × recency × confidence
- [ ] `app/core/knowledge/temporal.py` — time-versioned graph
  - Edges carry `valid_from` / `valid_to`
  - "show me state on date X" — point-in-time query
- [ ] `app/core/knowledge/ingest/` — pipelines
  - From memory, files, calendar, email, chat
  - Async, hourly
  - Incremental (only new events)
  - Dedup via entity resolver
- [ ] `app/core/knowledge/inspector.py` — graph browser in dashboard
  - Force-directed viz (D3.js or vis.js)
  - Click node → see all edges, properties, source
  - Search by name/type
- [ ] Tests: 50+ cases including migration from existing data
- [ ] **Performance benchmarks:** p95 latency, throughput

#### B5. Memory Manager v2 (Week 8)
**Why:** With HelixDB, we replace ChromaDB + Neo4j + part of SQLite with ONE store.

**Deliverables:**
- [ ] `app/core/memory_v2/manager.py` (extends `memory_manager.py`)
  - Unified API: `store()`, `retrieve()`, `consolidate()`, `forget()`, `pin()`, `relate()`
  - Backed by **HelixDB** (graph + vector + KV in one) + SQLite (plans, audit, sessions)
  - Cross-reference on store (auto-link related entities)
  - Attention-weighted retrieval: recency × relevance × confidence × graph_proximity
  - Scheduled consolidation (already exists, harden it)
  - Lifecycle: TTL, retention, soft delete with 30-day grace
- [ ] `app/core/memory_v2/taxonomy.py`
  - Memory types: `fact`, `preference`, `rule`, `event`, `transient`
  - Per-type storage strategy in HelixDB (label + property)
  - `transient` decays fast, `fact` decays slow, `rule` is pinned
- [ ] `app/core/memory_v2/conflict.py`
  - Detect contradictions via embedding similarity + temporal overlap
  - Resolution policy: most-recent-wins / most-cited / ask
  - Audit log of resolutions
- [ ] `app/core/memory_v2/governance.py` — privacy
  - Privacy zones: per-data-class (medical, financial, location)
  - Local-only / cloud-sync / both (HelixDB stays local, embeddings stay local)
  - Encryption at rest (HelixDB supports it)
  - Right to delete: hard delete + verify
- [ ] `app/core/memory_v2/migration.py`
  - One-shot script: import existing ChromaDB + Neo4j data into HelixDB
  - Verify integrity post-migration
  - Idempotent (can re-run)
- [ ] Tests: 80+ cases
- [ ] Migration: existing memory.py stays as compat shim

**Phase B Definition of Done:**
- [ ] User profile has >10 typed fields per real user
- [ ] Life graph has >50 nodes after 1 week of use
- [ ] "What was I working on Tuesday?" returns accurate answer
- [ ] Memory decays correctly, pin works, conflict resolution works
- [ ] Inspector page shows everything the agent knows

---

### PHASE C — Proactive & Anticipatory (Weeks 9-12)
**Goal:** Speak when it matters. Stay silent when it doesn't.

#### C1. Proactive Core (Week 9)
**Deliverables:**
- [ ] `app/core/proactive/engine.py`
  - Decide IF/WHEN to interrupt user
  - Value score = utility × confidence − interruption_cost
  - Thresholds configurable
  - Quiet hours respected
  - Per-channel preference
- [ ] `app/core/proactive/value_gater.py`
  - "Should I speak?" decision
  - Suppress: low-value, repetitive, already-known
  - Escalate: anomaly, deadline, opportunity
- [ ] `app/core/proactive/dnd.py`
  - Learned quiet hours (e.g., after 10pm, on weekends)
  - Calendar-aware (during meetings)
  - Focus mode (user-set)
  - Per-user override
- [ ] `app/core/proactive/silence_engine.py`
  - Things to NOT say (per privacy policy)
  - Phrases that annoy (track user reactions)
  - Anti-spam: max 1 nudge per hour unless critical
- [ ] `app/core/proactive/dispatcher.py`
  - Where to send: user's preferred channel for that notification type
  - Format per channel (Telegram short, web rich, voice for important)
- [ ] Tests: 40+ cases

#### C2. Anticipation Engine (Week 10)
**Deliverables:**
- [ ] `app/core/proactive/anticipation.py`
  - Predict next need from habits
  - "User always checks email at 9am" → pre-fetch
  - "User has meeting in 30min" → brief them
  - "User mentioned project X" → surface related info
- [ ] `app/core/proactive/anomaly.py`
  - Detect deviations from patterns
  - "User at desk 14 hours" → suggest break
  - "No response to important email in 3 days" → nudge
  - "Spending up 30%" → financial check-in
- [ ] `app/core/proactive/follow_up.py`
  - Commitments: "remind me about X"
  - Promises: "I'll do that tomorrow"
  - Deadlines: calendar, file mtime, email thread
  - Track across sessions
- [ ] `app/core/proactive/smart_nudges.py`
  - Calendar → prep 5 min before meeting
  - Email → flag urgent
  - Tasks → priority suggestion
  - Weather → "leave 10 min early"
- [ ] Tests: 50+ cases

#### C3. Proactive Routines Library (Week 11)
**Deliverables:**
- [ ] `app/routines/proactive/` — concrete routines
  - `morning_briefing.py` — calendar, weather, top emails, news
  - `evening_review.py` — what got done, what's pending
  - `weekly_digest.py` — projects, finances, habits
  - `travel_prep.py` — from calendar event: weather, traffic, docs
  - `anomaly_digest.py` — system, financial, schedule
  - `inbox_zero.py` — email triage at scheduled time
- [ ] `app/routines/scheduler.py` — flexible scheduling
  - Cron-like + event-driven ("after meeting ends")
  - Per-user customization
  - Per-channel delivery
- [ ] `app/routines/templates/` — user-editable templates
  - Markdown with placeholders
  - Versioned
- [ ] Tests + examples

#### C4. Cross-Platform Continuity (Week 11-12)
**Deliverables:**
- [ ] `app/core/continuity/session.py`
  - Conversation threads persist across platforms
  - "Start on Telegram, continue on voice, finish on web" → same context
  - Thread ID = (user_id, topic_hash)
- [ ] `app/core/continuity/state_handoff.py`
  - Plan + state survives platform switch
  - "I'll do this and ping you on Telegram when done"
  - Push state to user on demand
- [ ] `app/core/continuity/identity.py`
  - Same persona, same memory, same context — regardless of channel
  - Per-channel formatting
- [ ] Tests: 30+ cases

#### C5. Opportunity Engine v2 (Week 12)
**Why:** `opportunity.py` (401 lines) exists but is shallow.

**Deliverables:**
- [ ] Replace stub with `app/core/opportunity_v2/`
  - Sources: memory, calendar, email, files, news, habits
  - Opportunity types: `time_saving`, `cost_saving`, `learning`, `relationship`, `health`, `safety`
  - Score by value × feasibility
  - Surface max 3 per day
  - Suppress already-shown
- [ ] Tests: 30+ cases

**Phase C Definition of Done:**
- [ ] User gets morning briefing at 8am, tailored
- [ ] "Working on Tuesday?" reconstructs accurately
- [ ] Anomaly detected and surfaced (e.g., long work hours)
- [ ] Quiet hours respected
- [ ] Max 1 nudge/hour, user can suppress


---

### PHASE D — Unified Multimodal (Weeks 13-16)
**Goal:** One context, many senses.

#### D1. Unified Event Schema (Week 13)
**Deliverables:**
- [ ] `app/core/multimodal/unified_event.py`
  - Canonical event: `{id, ts, source, modality, actor, content, embedding, metadata}`
  - Sources: chat, voice, file, email, calendar, sensor, camera, system
  - Adapters per source → unified
  - Bus: Redis Streams or in-memory queue
- [ ] `app/core/multimodal/event_bus.py`
  - Pub/sub, durable, replayable
  - Per-user + global topics
  - Backpressure, dedup, ordering
- [ ] Migration: existing event_digest.py refactored
- [ ] Tests: 30+ cases

#### D2. Multimodal Context Packer (Week 13-14)
**Deliverables:**
- [ ] `app/core/multimodal/context_packer.py`
  - Token budget per request
  - Priority rules: recency > relevance > novelty > system
  - Pack: text + recent events + relevant memory + graph nodes
  - Compress old turns to summaries
  - Drop low-priority items when over budget
- [ ] `app/core/multimodal/summarizer.py`
  - Conversation summarizer (rolling)
  - Event summarizer (per-day, per-week)
  - Memory compression (merge similar, drop noise)
- [ ] Tests: 40+ cases including budget overflow

#### D3. Scene Fusion (Week 14-15)
**Deliverables:**
- [ ] `app/core/multimodal/scene_fusion.py`
  - Camera + audio + motion + chat → coherent scene
  - "Meeting just started" (visual: people, audio: speech, calendar: yes)
  - "User alone" (visual: 1 person, audio: 1 voice)
  - "Alert" (visual: package, audio: doorbell)
- [ ] `app/core/multimodal/temporal_align.py`
  - Sync events across modalities (timestamps)
  - Causal inference: audio event caused visual event
  - Per-user scene history
- [ ] Tests: 30+ cases

#### D4. Voice 2.0 (Week 15-16)
**Why:** Current voice is wired but not Friday-conversational.

**Deliverables:**
- [ ] `app/voice_v2/barge_in.py`
  - User can interrupt agent mid-speech
  - VAD-driven, < 200ms reaction
  - Smooth cutoff (no truncation artifacts)
- [ ] `app/voice_v2/multi_speaker.py`
  - Speaker diarization (who's in the room?)
  - Voice biometrics (recognize "this is Alice, not Bob")
  - Privacy: opt-out, on-device only
- [ ] `app/voice_v2/voice_id.py`
  - Voiceprint per user
  - Wake-word personalization
  - Confidence thresholds
- [ ] `app/voice_v2/conversational.py`
  - Back-and-forth without wake word (in active mode)
  - Context preservation across turns
  - Turn-taking cues
- [ ] `app/voice_v2/scenarios.py`
  - Mode detection: hands-free / focused / quiet / privacy
  - Per-mode behavior (always-on vs push-to-talk)
- [ ] Tests: 30+ cases

#### D5. Vision 2.0 (Week 16)
**Why:** Surveillance is separate from assistant. Make them one brain.

**Deliverables:**
- [ ] `app/vision/scene_understanding.py`
  - Camera + YOLO + face ReID + pose + depth → structured scene
  - Output: people count, activity, alerts, narrative caption
- [ ] `app/vision/agent_integration.py`
  - Agent can ask "what's happening in the kitchen right now?"
  - Agent can alert: "I see X, should I do Y?"
  - Privacy: faces blurred by default, opt-in for ID
- [ ] `app/vision/insight_extraction.py`
  - Daily/weekly summaries of activity
  - Anomalies fed into proactive engine
- [ ] Tests: 20+ cases

**Phase D Definition of Done:**
- [ ] One canonical event for all modalities
- [ ] Token-budgeted multimodal context works
- [ ] Scene fusion produces accurate scenes
- [ ] Barge-in works in voice
- [ ] Agent can answer "what's happening in room X?"

---

### PHASE E — Self-Improvement (Weeks 17-20)
**Goal:** Get visibly smarter, in front of the user.

#### E1. Real Skill Factory (Week 17-18)
**Why:** `skill_learner.py` (552 lines) is theory. `skills/learned/` is empty.

**Deliverables:**
- [ ] `app/core/skills_v2/factory.py` — trace → draft skill
  - Watch user do task X 3+ times
  - Extract: steps, conditions, success criteria
  - LLM proposes skill in YAML+Python
  - Human approval before activation
- [ ] `app/core/skills_v2/evaluator.py`
  - Test proposed skill against held-out traces
  - Score: success rate, latency, cost
  - Reject if < 80% success
- [ ] `app/core/skills_v2/composer.py`
  - Compose skills into workflows
  - Resolve conflicts (two skills for same trigger)
  - Dependency graph
- [ ] `app/core/skills_v2/marketplace.py`
  - Local marketplace (user's own skills)
  - Curated community skills
  - Trust tiers: `user`, `verified`, `community`
  - Versioning + rollback
- [ ] Tests: 50+ cases

#### E2. Prompt Versioning & A/B (Week 18)
**Deliverables:**
- [ ] `app/core/prompts_v2/registry.py`
  - All system prompts in git, versioned
  - Per-prompt metadata: created_by, eval_score, rollback_version
  - Hot-swap with audit
- [ ] `app/core/prompts_v2/optimizer.py`
  - Auto-suggest prompt improvements from failure analysis
  - Token reduction: compress verbose prompts
  - A/B framework: serve A to 50%, B to 50%, measure
- [ ] `app/core/prompts_v2/dashboard.py`
  - Browse all prompt versions
  - Diff view
  - Eval scores per version
- [ ] Tests: 20+ cases

#### E3. Feedback Loop (Week 19)
**Deliverables:**
- [ ] `app/core/feedback_v2/capture.py`
  - Thumbs up/down on every turn
  - "That was wrong because..." correction
  - "Never do X again" rules
- [ ] `app/core/feedback_v2/apply.py`
  - Feedback → profile memory update
  - Feedback → prompt adjustment
  - Feedback → model routing tweak
  - Feedback → skill score adjustment
- [ ] `app/core/feedback_v2/analytics.py`
  - Track feedback-driven regression improvement
  - Weekly digest: "your agent learned X this week"
- [ ] Tests: 30+ cases

#### E4. Self-Improvement Engine (Week 19-20)
**Deliverables:**
- [ ] `app/core/improvement/engine.py`
  - Daily: analyze failures, suggest fixes
  - Weekly: propose prompt updates, new skills
  - Monthly: review policy, security, costs
- [ ] `app/core/improvement/safe_apply.py`
  - All changes via PR flow (even self-changes)
  - Test gate: regression tests must pass
  - Rollback on regression
- [ ] `app/core/improvement/eval_harness.py`
  - Regression suite: prompts, tools, connectors, policies
  - Run on every change
  - Trend lines in dashboard
- [ ] Tests: 30+ cases

#### E5. Explainability (Week 20)
**Deliverables:**
- [ ] `app/core/explain/show_work.py`
  - User toggle: "show me your reasoning"
  - Output: chain of thought, tools used, why each step
  - Per-turn artifact
- [ ] `app/core/explain/learn_summary.py`
  - "This week I learned: X, Y, Z"
  - Surfaced in weekly review
- [ ] Tests: 15+ cases

**Phase E Definition of Done:**
- [ ] Skill factory creates a real, working skill from observation
- [ ] Evaluator blocks low-quality skills
- [ ] Prompt versioning + A/B running
- [ ] Feedback loop measurably improves responses
- [ ] Self-improvement proposes changes via PR

---

### PHASE F — Trust, Polish & Scale (Weeks 21-24)
**Goal:** The agent users trust with everything.

#### F1. Trust & Explainability (Week 21)
**Deliverables:**
- [ ] `app/core/trust/citations.py`
  - Every fact: source (memory, file, web, tool, graph)
  - Inline citation markers: `[1]`, `[2]`
  - Hover/tap to see source
- [ ] `app/core/trust/rollback.py`
  - Every mutating action has rollback()
  - Rollback registry
  - "Undo last action" command
  - "Undo all from last hour" command
- [ ] `app/core/trust/audit_viewer.py`
  - Rich audit log with timeline
  - Filter by tool/agent/user/risk
  - Replay any turn
- [ ] `app/core/trust/fact_check.py`
  - LLM-generated text → fact-checker
  - Re-verify claims against memory + tools
  - Flag unsupported claims
- [ ] Tests: 40+ cases

#### F2. Privacy & Data Lifecycle (Week 21-22)
**Deliverables:**
- [ ] `app/core/privacy/zones.py`
  - Per-data-class privacy: medical, financial, location, personal
  - Local-only / cloud-sync / both
  - Encryption at rest (per zone)
- [ ] `app/core/privacy/lifecycle.py`
  - Export: all data, single archive
  - Delete: hard delete, verify gone
  - Retention: per-data-class TTL
  - Audit of access
- [ ] `app/core/privacy/inspector.py`
  - "What do you know about me?" single page
  - Browse by category
  - Edit, delete, pin
- [ ] GDPR/CCPA compliance docs
- [ ] Tests: 30+ cases

#### F3. Voice Polish (Week 22)
**Deliverables:**
- [ ] `app/voice_v3/voice_cloning.py`
  - User records 30s sample
  - Personalized TTS in user's voice
  - Optional, opt-in
- [ ] `app/voice_v3/voice_styles.py`
  - Whisper, formal, casual, urgent, briefing
  - Per-context style
- [ ] `app/voice_v3/voice_fx.py`
  - Friday-style: slight British inflection, dry wit
  - "Friday mode" toggle
- [ ] Tests: 20+ cases

#### F4. Dashboard Command Center (Week 22-23)
**Why:** API is done. UX is not Friday-grade.

**Deliverables:**
- [ ] `app/web/command_center.py` — single-page Friday UI
  - Top: today's briefing (calendar, weather, top emails, top tasks)
  - Middle: active plan progress
  - Bottom: inbox (pending approvals, follow-ups, anomalies)
  - Floating: "ask Friday" input
- [ ] `app/web/voice_widget.py`
  - "Hold space to talk" widget
  - Always-on in dashboard
- [ ] `app/web/persona_state.py`
  - Show agent's current state (energy, focus, mode)
  - Show what it's watching
- [ ] `app/web/inspector_pages.py`
  - Memory inspector
  - Knowledge graph browser
  - Skills browser
  - Audit log
  - Cost dashboard
  - Plan inspector
- [ ] `app/web/mobile_responsive.py`
  - Full mobile experience
  - PWA installable
- [ ] Tests: 30+ UI tests with playwright

#### F5. Deployment & Ops (Week 23-24)
**Deliverables:**
- [ ] `docker/Dockerfile` — multi-stage, distroless final, < 200MB
- [ ] `docker-compose.yml` — full stack: agent, redis, postgres, neo4j, prometheus, grafana
- [ ] `helm/aetherravyn/` — k8s chart (if user wants k8s)
- [ ] `systemd/aetherravyn.service` — daemonized, auto-restart
- [ ] `scripts/install.sh` — one-line install
- [ ] `scripts/upgrade.sh` — safe upgrade with rollback
- [ ] `scripts/backup.sh` — daily backup of memory, plans, skills
- [ ] `scripts/restore.sh` — restore from backup
- [ ] `infra/grafana/` — dashboards
- [ ] `infra/prometheus/` — alerts
  - Cost spike alert
  - Error rate alert
  - Latency alert
  - Disk/memory alert
  - Channel disconnect alert
- [ ] `infra/runbook.md` — what to do when X breaks
- [ ] Tests: smoke tests for deployment

#### F6. Documentation & Onboarding (Week 24)
**Deliverables:**
- [ ] `docs/` — full MkDocs site
  - Getting started (5 min)
  - Concepts
  - Architecture
  - API reference
  - Skill authoring
  - Self-hosting
  - Troubleshooting
  - Security model
  - FAQ
- [ ] `docs/onboarding-flow.md` — first 7 days
- [ ] `docs/video-tutorials/` — 5 short videos
- [ ] `CHANGELOG.md` — auto-generated
- [ ] `LICENSE` — MIT (already)
- [ ] `CONTRIBUTING.md`
- [ ] `CODE_OF_CONDUCT.md`

**Phase F Definition of Done:**
- [ ] Every fact cited, every action rollback-able
- [ ] Privacy zones + data lifecycle in place
- [ ] Voice is Friday-grade
- [ ] Dashboard is a real command center
- [ ] One-line install, one-line upgrade
- [ ] Documentation site live


---

## PART 4 — Cross-Cutting Concerns (Run Continuously, All Phases)

### 4.1 Testing Strategy
- **Unit tests** — every module, 85%+ coverage in `app/core/`, 70%+ in `app/tools/`
- **Integration tests** — end-to-end flows, 13+ in `tests/`
- **Property-based tests** — `hypothesis` for invariants (memory, plans, graph)
- **Regression tests** — `tests/test_regression.py` (already exists, expand)
- **Eval tests** — `tests/test_eval.py` for prompt/agent quality
- **Performance tests** — `tests/perf/` with `pytest-benchmark`
- **Contract tests** — MCP, channel APIs
- **Chaos tests** — kill workers, inject failures, verify recovery

### 4.2 Continuous Quality
- **Pre-commit**: ruff, ruff-format, pyright, detect-secrets, trailing-whitespace
- **CI on every PR**: lint, format, type-check, test, security-scan, build
- **Coverage gate**: >80% for `app/core/`, >70% for `app/tools/`, fail PR if drops
- **Dependency audit**: weekly, fail on known CVEs
- **License audit**: no GPL in core (MIT only)
- **Doc coverage**: all public APIs documented

### 4.3 Documentation (Living)
- `AGENTS.md` — workspace rules (exists, update)
- `Agent.md` — architecture (exists, update)
- `Skills.md` — skills (exists, update)
- `SOUL.md` — persona (exists, update)
- `MEMORY.md` — user knowledge (auto-managed)
- `CHANGELOG.md` — auto-generated from conventional commits
- `docs/` — full MkDocs site (Phase F)
- `README.md` — 30-second pitch + quick start
- `CONTRIBUTING.md` — how to extend

### 4.4 Migration Strategy
For every "v2" module:
1. Create `*_v2/` alongside existing
2. Existing module becomes compat shim → routes to v2
3. v2 has feature flag for rollout
4. Tests run against both
5. Gradual rollout: 10% → 50% → 100%
6. After 30 days at 100%, delete v1

### 4.5 Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Local LLM quality too low | High | Tier routing: escalate to cloud when confidence < threshold |
| Provider outage | High | Multi-provider, circuit breaker, local Ollama fallback |
| Cost overrun | High | Per-request/per-day caps, dashboard alerts |
| Hallucination | High | Verifier + fact-check + citation |
| Privacy leak | Critical | Encryption, audit, opt-in cloud, right-to-delete |
| Surveillance false positive | Medium | Tunable thresholds, false-positive dashboard |
| Plan infinite loop | Medium | Max iterations, max time, dead-letter queue |
| Memory bloat | Medium | Decay, consolidation, retention policy |
| Channel disconnect | Low | Auto-reconnect, fallback to another channel |
| Voice false wake | Low | Personalization, confidence threshold, hotword diversity |
| Skill market malicious | High | Trust tier, sandboxed eval before activation |
| Self-modification breaks | High | PR flow, regression gate, rollback |

### 4.6 Module Map (Final State)

```
app/
├── api/                    # FastAPI gateway (existing)
├── agents/                 # 14+ specialist agents (existing, harden)
├── channels/               # 7+ messaging platforms (existing, harden)
├── core/
│   ├── planning/           # NEW: real planner, executor, replanner
│   ├── runtime_v2/         # NEW: cost router, cache, queue
│   ├── verification/       # NEW: verifier, validators, rollback
│   ├── audit/              # NEW: real audit + dashboard
│   ├── policy_v2/          # NEW: real policy + approvals
│   ├── user_model/         # NEW: profile, life_graph, habits
│   ├── memory_v2/          # NEW: unified memory manager
│   ├── knowledge/          # NEW: real graph (replaces 150-line stub)
│   ├── proactive/          # NEW: engine, anticipation, anomaly
│   ├── continuity/         # NEW: cross-platform session
│   ├── multimodal/         # NEW: unified event, context packer
│   ├── skills_v2/          # NEW: factory, evaluator, marketplace
│   ├── prompts_v2/         # NEW: registry, optimizer, A/B
│   ├── feedback_v2/        # NEW: capture, apply
│   ├── improvement/        # NEW: self-improvement engine
│   ├── trust/              # NEW: citations, rollback, fact-check
│   ├── privacy/            # NEW: zones, lifecycle
│   └── (existing files, refactored to use v2)
├── voice_v2/               # NEW: barge-in, multi-speaker, voice ID
├── voice_v3/               # NEW: cloning, styles
├── vision/                 # NEW: scene understanding (integrate monitoring)
├── web/                    # command_center, voice_widget, inspectors
├── observability/          # NEW: tracing, metrics, logging, health
├── tools/                  # 75+ tools (harden, add metadata)
├── provider/               # multi-provider LLM
├── skills/                 # bundled + learned (skill factory populates)
├── routines/               # proactive routines
├── settings/               # config
└── db/                     # schema, migrations
```


---

## PART 5 — Timeline & Milestones

| Week | Phase | Milestone | Acceptance Test |
|------|-------|-----------|------------------|
| 1-2  | A1    | Real planner working | 10-step plan persists+resumes after kill -9 |
| 2    | A2    | Cost router + circuit breaker | 80% of greetings hit tiny model, breaker recovers in 60s |
| 3    | A3    | Verifier + rollback | 95% of bad tool results caught, 10 mutations rollback |
| 3-4  | A4    | Audit + policy v2 | Every action auditable, 100% high-risk gets approval |
| 4    | A5    | Observability | OTel traces, Prometheus metrics, Grafana dashboards |
| 4    | A6    | CI/CD green | All PRs gated, 80%+ coverage in core |
| **4**| **A** | **Phase A Done** | **E2E test: complex task → plan → execute → verify → done** |
| 5    | B1    | Rich user profile | "What do you know about me?" page works |
| 5-6  | B2    | Life context graph | 50+ nodes, entity resolution works |
| 6-7  | B3    | Habits + freshness | Habits detected, decay works, pin works |
| 7-8  | B4    | Knowledge graph v2 | Graph queries in prompts work |
| 8    | B5    | Memory manager v2 | Unified API, conflict resolution |
| **8**| **B** | **Phase B Done** | **"What was I working on Tuesday?" → accurate** |
| 9    | C1    | Proactive core | Value-gating works, DND respected |
| 10   | C2    | Anticipation engine | Predicts next need from habits |
| 11   | C3    | Routines library | Morning briefing, evening review work |
| 11-12| C4    | Cross-platform continuity | Same thread across Telegram/voice/web |
| 12   | C5    | Opportunity v2 | 3 high-value opps/day surfaced |
| **12**| **C** | **Phase C Done** | **Morning briefing tailored, anomalies caught** |
| 13   | D1    | Unified event schema | All modalities → canonical event |
| 13-14| D2    | Multimodal context packer | Token-budgeted packing works |
| 14-15| D3    | Scene fusion | Camera+audio+chat → coherent scene |
| 15-16| D4    | Voice 2.0 | Barge-in, multi-speaker, voice ID |
| 16   | D5    | Vision integration | "What's in room X?" works |
| **16**| **D** | **Phase D Done** | **One context, many senses, voice is conversational** |
| 17-18| E1    | Real skill factory | Skill created from observation + tested + approved |
| 18   | E2    | Prompt versioning + A/B | Prompts in git, A/B running, eval scores tracked |
| 19   | E3    | Feedback loop | Thumbs up/down measurably improves responses |
| 19-20| E4    | Self-improvement engine | Proposes changes via PR, regression gate |
| 20   | E5    | Explainability | "Show your work" toggle, weekly "I learned" digest |
| **20**| **E** | **Phase E Done** | **Agent visibly learns, improves, explains** |
| 21   | F1    | Trust & explainability | Every fact cited, every action rollback-able |
| 21-22| F2    | Privacy & data lifecycle | Encryption, export, delete, zones |
| 22   | F3    | Voice polish | Cloning, styles, Friday mode |
| 22-23| F4    | Command center dashboard | Real UX, not just API |
| 23-24| F5    | Deployment & ops | One-line install, backup/restore, monitoring |
| 24   | F6    | Documentation | Full docs site, onboarding, video tutorials |
| **24**| **F** | **Phase F Done** | **Production-ready, trustworthy, beautiful** |

---

## PART 6 — What Beats OpenClaw & Hermes

| Area | OpenClaw | Hermes | **AetherRavyn v3** |
|------|----------|--------|---------------------|
| Architecture | Monolithic | Monolithic | **Multi-agent swarm (14+ specialists)** |
| Cognition | Single mode | Single mode | **Dual System 1/2 + meta-cognition** |
| Tools | ~30 | ~30 | **75+ typed, with risk/cost/rollback** |
| Memory | Session | Session | **ChromaDB + Neo4j + SQLite, decay, conflict** |
| Voice | Yes (limited) | TTS only | **Full pipeline + barge-in + multi-speaker + Friday mode** |
| Device Control | Limited | No | **Desktop + Mobile + Screen + OCR + vision** |
| Ambient Loop | Cron | No | **11 workers + anticipation + anomaly + value-gate** |
| Cross-Training | No | No | **Real (LearnerAgent + feedback loop)** |
| Negotiation | No | No | **Structured debate** |
| Proactive | No | No | **Anticipatory, value-gated, DND-aware** |
| Cost-Aware | No | No | **Tier router, cache, queue, circuit breaker** |
| Cost | $$$$ | $$$$ | **$<0.05/session (local-first)** |
| Audit | Logs | Logs | **Full audit + replay + rollback** |
| Self-Improvement | No | No | **Real (skill factory + prompt A/B + PR flow)** |
| Trust | Manual | Manual | **Citations, rollback, approvals, fact-check** |
| Privacy | Cloud | Cloud | **Local-first + privacy zones** |
| Open Source | Yes (377k★) | Yes (177k★) | **Yes (target: top 10 in AI agents by D30)** |

**Our positioning:** "The only open-source personal AI agent that anticipates, plans, verifies, and improves itself — and runs on your machine."

---

## PART 7 — First Week (Start Now)

### Day 1: Foundation
- [ ] Initialize `app/core/planning/` with `__init__.py`, scaffolding
- [ ] Write `tests/test_planner.py` skeleton (TDD: tests first)
- [ ] Set up pre-commit hooks
- [ ] Configure pyright strict mode
- [ ] Set up CI workflow (`.github/workflows/ci.yml`)

### Day 2: Planner core
- [ ] Implement `TaskPlan`, `PlanStep`, `StepStatus`
- [ ] Implement `planner.plan(goal: str) -> TaskPlan`
- [ ] Basic cost estimation
- [ ] 20 unit tests passing

### Day 3: Planner executor
- [ ] Implement `executor.execute(plan)`
- [ ] Sequential + parallel mode
- [ ] Retry with backoff
- [ ] Checkpointing to SQLite
- [ ] 15 integration tests passing

### Day 4: Replanner + goal tracker
- [ ] `replanner.replan(failed_step, attempts)` 
- [ ] `goal_tracker.create(goal, deadline)`
- [ ] Auto-decomposition
- [ ] 15 tests passing

### Day 5: Wire into runtime
- [ ] `runtime.py` uses new planner
- [ ] Old `planner.py` becomes compat shim
- [ ] Feature flag: `RAVEN_PLANNER_V2=true`
- [ ] E2E test: complex task → planner → runtime → done

### Weekend: Polish
- [ ] All tests green
- [ ] Coverage >80% for new module
- [ ] Documentation: `docs/planning.md`
- [ ] Commit with `feat(planning): real hierarchical planner v2`

**Next week:** Cost router (A2).

---

## PART 8 — Top-Notch Polish Checklist

Beyond functional, these make it feel **world-class**:

### UX
- [ ] Every error message: clear, actionable, human
- [ ] Every latency budget: hit it
- [ ] Every interaction: feels intentional
- [ ] Empty states: not blank, helpful
- [ ] Loading states: progress, not freeze
- [ ] Failures: graceful, retry, explain
- [ ] Onboarding: 5 min to first win
- [ ] Personality: dry, witty, anticipatory, never annoying

### Code
- [ ] Zero `print()`, zero bare `except:`, zero `# type: ignore`
- [ ] All public APIs have docstrings
- [ ] All modules have `__all__`
- [ ] All errors are typed (custom exception hierarchy)
- [ ] All configs validated at startup (fail fast)
- [ ] All migrations reversible

### Ops
- [ ] One-line install
- [ ] One-line upgrade
- [ ] One-line backup/restore
- [ ] Auto-update opt-in
- [ ] Health checks
- [ ] Alerting (cost spike, error spike, latency, disconnect)
- [ ] Runbook for common failures

### Documentation
- [ ] 30-second pitch
- [ ] 5-minute quick start
- [ ] Full architecture doc
- [ ] API reference (auto-generated)
- [ ] Skill authoring guide
- [ ] Self-hosting guide
- [ ] Video tutorials (5)
- [ ] FAQ

### Community
- [ ] Clear contribution guide
- [ ] "Good first issue" labels
- [ ] Discussion forum (Discord/Discourse)
- [ ] Show-and-tell channel
- [ ] Monthly office hours
- [ ] Roadmap published
- [ ] Changelog auto-generated

---

## PART 9 — What "Top-Notch Production" Means Concretely

A new user should be able to:
- [ ] Install in 5 minutes (`curl ... | bash`)
- [ ] Onboard in 5 minutes (10 questions)
- [ ] Get a tailored morning briefing on day 1
- [ ] Have the agent learn their habits in < 7 days
- [ ] Trust the agent with calendar, email, files
- [ ] See cost dashboard showing < $1/day
- [ ] See audit log showing every action
- [ ] Roll back any action in 1 click
- [ ] Export all their data in 1 click
- [ ] Delete all their data in 1 click
- [ ] Sleep well knowing nothing leaked

A developer should be able to:
- [ ] Clone, `make install`, `make test`, all green
- [ ] Add a new tool in < 50 lines
- [ ] Add a new agent in < 100 lines
- [ ] Add a new channel in < 200 lines
- [ ] Add a new skill in < 30 lines
- [ ] Run regression suite in < 5 minutes
- [ ] Find any issue with `pytest -k` + grep
- [ ] Read the doc, understand the system

An operator should be able to:
- [ ] Deploy in 1 command
- [ ] Upgrade in 1 command
- [ ] Roll back in 1 command
- [ ] See system health at a glance
- [ ] Get alerted before users notice
- [ ] Diagnose any issue in < 5 minutes
- [ ] Scale horizontally if needed

---

## PART 10 — Tracking & Reporting

### Weekly
- [ ] Sprint review: what shipped, what's next
- [ ] Test coverage report
- [ ] Cost report
- [ ] Latency report
- [ ] Open issues / bugs

### Monthly
- [ ] User metrics (D7, D30, NPS) — once we have users
- [ ] Self-improvement report: "agent learned X, Y, Z"
- [ ] Security audit
- [ ] Cost trend
- [ ] Roadmap adjustment

### Quarterly
- [ ] Major version release
- [ ] Community showcase
- [ ] Roadmap reset
- [ ] Strategic review: are we still on track for Friday?

---

## PART 11 — Decision Points (Need Your Input)

These are non-trivial decisions I need from you before/during Phase A:

1. **Local model choice for System 1** — Llama 3.1 8B? Phi-3? Mistral 7B? Gemma 2 9B?
2. **Primary cloud provider** — Anthropic? OpenAI? xAI? Multi-provider with cost routing?
3. **Graph DB** — Neo4j (heavy), or sqlite-fallback (light) for v1?
4. **Event bus** — Redis Streams (need redis) or in-process queue (simpler)?
5. **Authentication for dashboard** — none (local), basic auth, OAuth?
6. **Multi-user support** — single-user only (simpler) or multi-user from start?
7. **License** — keep MIT? (recommended)
8. **Distribution** — pip, docker, both?
9. **Update channel** — stable only, or stable + beta?
10. **Telemetry** — fully opt-in (recommended), or opt-out?

---

## PART 12 — What I'm NOT Doing (Scope Discipline)

We are NOT doing these in this 24-week plan:
- Native mobile apps (web dashboard + PWA covers most)
- Native desktop apps (web dashboard)
- Multi-tenancy (single-user, multi-user later)
- Federated learning across users
- AGI research / new architectures
- A marketplace of paid skills (free + community for v1)
- i18n beyond English (we'll structure for it but not implement)
- All 25 channels (we have 7 working, 7 is enough for v1)
- Voice cloning by default (opt-in)
- Web browser automation at scale (limited to 5 sites)
- Real-time video generation
- Robotics / IoT hardware beyond current tools

These are deliberate cuts to ship a world-class v1 in 24 weeks.

---

## PART 13 — The Compounding Advantage

The reason this beats OpenClaw and Hermes long-term:

1. **Self-improvement compounds** — every user makes it better
2. **Cost stays low** — local-first means we can serve anyone
3. **Trust compounds** — every rollback/citation earns trust
4. **Anticipation compounds** — every habit learned makes the next one easier
5. **Graph compounds** — every entity makes the graph smarter
6. **Skills compound** — every learned skill makes the next one easier

**By month 6, AetherRavyn will be measurably better than month 1. By month 12, it will feel like Friday.**

---

## PART 14 — Closing

This is a 24-week plan, 6 phases, ~200 deliverables, ~30k lines of new code, ~10k lines of tests.

It is achievable because:
- The architecture is already 85% there
- The pieces exist, they just need to be wired and deepened
- The principles are proven (every major AI lab does this)
- The tech stack is modern and stable

It is ambitious because:
- It targets user outcomes, not just features
- It measures quality, not just quantity
- It demands top-notch in every dimension

**Start Phase A1 on Monday. Ship the real planner. Everything else follows.**

---

*"I am not a chatbot. I am not a tool. I am your cognitive extension — always watching, always learning, always three steps ahead."*
— AetherRavyn (Ravyn)


---

## PART 15 — Decision Questions (Updated for HelixDB + Model-Agnostic)

Many of these are now resolved. Remaining decisions:

### ✅ Already decided (per amendment)
- **Storage:** HelixDB (graph + vector + KV + doc + relational in one)
- **Model:** Model-agnostic, NO model of its own
- **Scope:** All 6 phases (24 weeks)

### Remaining decisions to unblock Phase A1

1. **Default local model for first-run (only if user has Ollama)**
   - Option A: Llama 3.1 8B (best quality/size)
   - Option B: Phi-3 Mini 3.8B (smallest, fastest)
   - Option C: Mistral 7B (good middle ground)
   - Option D: Gemma 2 9B (Google's best)
   - Option E: No default — user picks on first run

2. **Default embedding model**
   - Option A: nomic-embed-text via Ollama (local, free)
   - Option B: mxbai-embed-large via Ollama (local, free, larger)
   - Option C: text-embedding-3-small via OpenAI (cloud, $)
   - Option D: bge-m3 via local server (best quality)
   - Option E: User picks

3. **Default primary cloud provider (used for System 2 only)**
   - Option A: Anthropic (Claude 3.5 Sonnet)
   - Option B: OpenAI (GPT-4o)
   - Option C: xAI (Grok-2)
   - Option D: OpenRouter (any model, single API)
   - Option E: No default — user provides key in config

4. **HelixDB deployment**
   - Option A: Local CLI only (`helix start dev --disk`) — recommended for v1
   - Option B: HelixDB Cloud (managed, costs $)
   - Option C: Both — local default, cloud as opt-in upgrade

5. **Authentication for dashboard**
   - Option A: None (local-only, single-machine)
   - Option B: Basic auth with bcrypt
   - Option C: OAuth (Google/GitHub)

6. **Multi-user from day 1?**
   - Option A: Yes (harder, proper)
   - Option B: No (single user, ship faster) — recommended for v1

7. **First-run UX**
   - Option A: Web wizard in dashboard
   - Option B: CLI prompts (`raven init`)
   - Option C: Both

8. **Distribution**
   - Option A: pip only (`pip install aetherravyn`)
   - Option B: Docker only (full stack)
   - Option C: Both (pip for dev, docker for prod) — recommended

9. **Update channel**
   - Option A: Stable only
   - Option B: Stable + beta

10. **Telemetry**
    - Option A: Fully opt-in (recommended) — off by default
    - Option B: Opt-out
    - Option C: Never (we don't track anything)

11. **License** — keep MIT? (recommended)

12. **HelixDB Python client** — build it ourselves (we own it) or use community (less control)?
    - Option A: Build our own `app/db/helix.py` (recommended, ~300 lines)
    - Option B: Wait for official Python SDK
    - Option C: Use REST directly (minimal wrapper)

**My recommendation:**
- (1) **E** — no default, user picks (keeps us neutral)
- (2) **A** — nomic-embed-text, falls back to user choice
- (3) **D** — OpenRouter, user provides one key, gets any model
- (4) **A** — local CLI only for v1
- (5) **A** — no auth (local-only)
- (6) **B** — single user, multi-user later
- (7) **C** — both
- (8) **C** — pip + docker
- (9) **A** — stable only
- (10) **A** — opt-in
- (11) **MIT**
- (12) **A** — build our own client (we own the abstraction)

---

## PART 16 — How to Read This Plan

- **If you're the developer:** Start with PART 7 (First Week), then PART 3 (Phase A), then iterate.
- **If you're the operator:** Read PART 9 (Top-Notch Checklist) and PART 5 (Timeline).
- **If you're the user:** Read PART 0 (North Star) and PART 6 (vs Competitors).
- **If you're reviewing the plan:** Read PART 1 (Principles) and PART 4 (Cross-Cutting).

---

*End of plan. Total: 1320 lines, 6 phases, 24 weeks, ~200 deliverables, ~30k new lines.*

*Start with PART 15: answer the 6 decision questions, then PART 7: First Week, then PART 3: Phase A.*

---

## PART 17 — Model-Agnostic Architecture (Detailed)

### 17.1 Why Model-Agnostic
- **No vendor lock-in** — if a provider changes pricing/quality/terms, swap in config
- **User picks** — privacy-conscious users use local; speed-conscious users use cloud
- **Cost optimization** — different tasks → different models
- **Future-proof** — new providers appear monthly, integration is one adapter
- **Reduced footprint** — we don't ship a 4GB model file

### 17.2 Provider Interface

Every model provider implements the same interface in `app/provider/base.py`:

```python
class ModelProvider(Protocol):
    name: str
    tier: ModelTier  # tiny | small | medium | large | premium
    
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse: ...
    
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]: ...
    
    def capabilities(self) -> ModelCapabilities:
        # context_window, supports_tools, supports_vision, supports_json_mode
        ...
    
    def cost(self, usage: Usage) -> Cost:
        # usd for input/output tokens
        ...
```

### 17.3 Built-in Adapters (`app/provider/`)

Each adapter is one file, ~100-200 lines:

| File | Provider | Type |
|------|----------|------|
| `ollama.py` | Ollama (local) | OpenAI-compatible |
| `lmstudio.py` | LM Studio (local) | OpenAI-compatible |
| `vllm.py` | vLLM (local server) | OpenAI-compatible |
| `llamacpp.py` | llama.cpp server (local) | OpenAI-compatible |
| `anthropic.py` | Anthropic (Claude) | Native + compat |
| `openai.py` | OpenAI (GPT) | Native |
| `xai.py` | xAI (Grok) | OpenAI-compatible |
| `google.py` | Google (Gemini) | Native + compat |
| `mistral.py` | Mistral | OpenAI-compatible |
| `cohere.py` | Cohere | Native |
| `deepseek.py` | DeepSeek | OpenAI-compatible |
| `openrouter.py` | OpenRouter (any model) | OpenAI-compatible |
| `groq.py` | Groq (fast inference) | OpenAI-compatible |
| `together.py` | Together AI | OpenAI-compatible |
| `fireworks.py` | Fireworks AI | OpenAI-compatible |
| `bedrock.py` | AWS Bedrock | Native |
| `azure.py` | Azure OpenAI | OpenAI-compatible |
| `custom.py` | Any OpenAI-compatible endpoint | Template |

### 17.4 Provider Registry & Routing

```python
# app/provider/registry.py
class ProviderRegistry:
    providers: dict[str, ModelProvider]
    
    def register(self, name: str, config: ProviderConfig): ...
    def get(self, name: str) -> ModelProvider: ...
    def list(self, tier: ModelTier | None = None) -> list[ModelProvider]: ...

# app/provider/router.py
class ModelRouter:
    def __init__(self, registry: ProviderRegistry, policy: RoutingPolicy): ...
    
    async def chat(
        self,
        task: TaskType,  # "greeting" | "code" | "reasoning" | "summarize" | ...
        messages: list[Message],
        **kwargs,
    ) -> ChatResponse:
        # 1. Classify task complexity
        # 2. Pick provider per policy + cost + availability
        # 3. Try in order: local → cheap cloud → expensive cloud
        # 4. Circuit-break on failure
        ...
```

### 17.5 Routing Policy (configurable)

```yaml
# config/providers.yaml
providers:
  ollama-local:
    type: ollama
    base_url: http://localhost:11434
    models:
      tiny: llama3.1:8b
      small: qwen2.5-coder:7b
  
  openrouter:
    type: openrouter
    api_key: ${OPENROUTER_API_KEY}
    models:
      medium: anthropic/claude-3.5-sonnet
      large: anthropic/claude-3.5-sonnet
      premium: openai/o1

routing:
  defaults:
    greeting: ollama-local:tiny
    summarize: ollama-local:small
    code: openrouter:medium
    reasoning: openrouter:large
    long_form: openrouter:premium
  
  overrides:
    # per-user, per-channel, per-time
    telegram:
      greeting: ollama-local:tiny  # fast for chat
    voice:
      greeting: ollama-local:small  # higher quality for voice
  
  cost_caps:
    per_request_usd: 0.50
    per_hour_usd: 5.00
    per_day_usd: 20.00
```

### 17.6 First-Run Wizard

On first launch (`raven init` or web UI):
1. "Do you have Ollama running?" → if yes, detect available models
2. "Do you have an OpenAI / Anthropic / OpenRouter key?" → if yes, configure
3. "Pick your defaults" → tier mapping per task type
4. "Test connection" → run a sample request
5. "Save config" → `~/.raven/config.yaml`

If no model is available, agent runs in **degraded mode**:
- Greetings/identity work (no model needed)
- System commands work
- All LLM-dependent features show "configure a model to enable"

### 17.7 Embedding Models

Same pattern as chat — any OpenAI-compatible embedding endpoint:
- `nomic-embed-text` (Ollama, local)
- `mxbai-embed-large` (Ollama, local)
- `bge-m3` (Ollama or server)
- `text-embedding-3-small` (OpenAI)
- `voyage-3` (Voyage AI)
- Custom

HelixDB stores embeddings as `Vec<f32>` arrays. We don't care who made them.

### 17.8 No-Model Mode (Graceful Degradation)

AetherRavyn works with **zero models** configured:
- Greetings: regex/template
- Time/status: built-in
- File/exec tools: work without LLM
- Memory storage: works
- Calendar/email/finance tools: work
- **LLM features disabled:** "configure a model to use chat"

This means install → usable in 30 seconds, even before user picks a model.

### 17.9 Model Switcher (Hot-Swap)

User can change default model at runtime via:
- CLI: `raven config model set default anthropic/claude-3.5-sonnet`
- Web dashboard: Settings → Models
- Telegram: `/model claude-3.5-sonnet`
- Per-request: include model in message metadata

No restart required. Routing picks up new config on next request.

---

## PART 18 — HelixDB Integration (Detailed)

### 18.1 Why HelixDB
- **Single engine** for graph + vector + KV + doc + relational
- **Apache 2.0** license (we stay MIT-compatible)
- **Rust** core, very fast (sub-5ms vector, sub-10ms graph)
- **Embedded** mode via CLI — no Docker for local dev
- **Cloud option** for production scale
- **5.2k stars**, active development, YC-backed
- **Dynamic queries** via HTTP POST — no build step, no code generation

### 18.2 What We Replace

| Old | New | Why |
|-----|-----|-----|
| ChromaDB | HelixDB (vector) | One engine, same capability |
| Neo4j | HelixDB (graph) | No Docker, embedded, faster |
| PostgreSQL (partial) | HelixDB (relational) | Less ops |
| SQLite (some tables) | HelixDB (KV) | Unified queries |
| Redis (cache) | Optional HelixDB + in-process | Less ops |

**We keep SQLite for:** audit log, plan checkpoints, sessions (write-heavy, append-only).

### 18.3 HelixDB Python Client

We build our own client in `app/db/helix.py` (~300 lines):

```python
class HelixClient:
    def __init__(self, base_url: str = "http://localhost:6969"): ...
    
    # Graph
    async def add_node(self, label: str, properties: dict) -> NodeId: ...
    async def add_edge(self, from_id: NodeId, to_id: NodeId, label: str, properties: dict) -> EdgeId: ...
    async def find_nodes(self, label: str, where: dict | None = None, limit: int = 100) -> list[Node]: ...
    async def find_related(self, node_id: NodeId, depth: int = 2) -> list[Node]: ...
    async def traverse(self, start: NodeId, query: TraversalQuery) -> list[Node]: ...
    
    # Vector
    async def add_vector(self, collection: str, id: str, vector: list[float], metadata: dict) -> None: ...
    async def search_vector(self, collection: str, query: list[float], k: int = 10, filter: dict | None = None) -> list[VectorHit]: ...
    async def hybrid_search(self, collection: str, query: str, vector: list[float], k: int = 10) -> list[VectorHit]: ...
    
    # KV
    async def kv_set(self, key: str, value: Any) -> None: ...
    async def kv_get(self, key: str) -> Any | None: ...
    async def kv_delete(self, key: str) -> None: ...
    
    # Health
    async def health(self) -> HealthStatus: ...
    async def stats(self) -> DBStats: ...
```

### 18.4 HelixDB Schema (`.helix/schema.hx`)

```hx
// Nodes
N::User { id: ID, name: String, created_at: DateTime }
N::Person { id: ID, name: String, aliases: [String], importance: F32 }
N::Project { id: ID, name: String, status: String, priority: I32 }
N::Place { id: ID, name: String, lat: F32, lng: F32 }
N::Event { id: ID, name: String, start: DateTime, end: DateTime }
N::Device { id: ID, name: String, type: String, location: String }
N::File { id: ID, path: String, hash: String, modified: DateTime }
N::Task { id: ID, title: String, status: String, deadline: DateTime }
N::Skill { id: ID, name: String, version: String, trust_tier: String }
N::Memory {
    id: ID,
    content: String,
    embedding: Vec<F32>,
    memory_type: String,  // fact|preference|rule|event|transient
    confidence: F32,
    source: String,       // user_said|inferred|system_detected
    created_at: DateTime,
    last_reinforced: DateTime,
    decay_rate: F32,
    pinned: Boolean
}
N::Tool { id: ID, name: String, risk: String, cost_usd: F32 }
N::Agent { id: ID, name: String, capabilities: [String] }

// Edges
E::works_on { weight: F32, since: DateTime }
E::lives_at { since: DateTime }
E::owns { since: DateTime }
E::mentioned_in { count: I32, last: DateTime }
E::last_interaction { ts: DateTime }
E::related_to { weight: F32, kind: String }
E::part_of { weight: F32 }
E::has_memory { ts: DateTime, weight: F32 }
E::triggered_by { ts: DateTime }
E::performed { ts: DateTime, result: String }
E::cites { source: String, confidence: F32 }

// Vector indices
V::MemoryVec { embedding: Vec<F32>, memory_id: ID }
V::FileVec { embedding: Vec<F32>, file_id: ID }
V::EventVec { embedding: Vec<F32>, event_id: ID }
```

### 18.5 HelixDB Deployment

**Local dev:** `helix start dev --disk` (background, persists to `~/.helix/data/`)
**Local prod:** same, with `--port 6969` and systemd
**Cloud:** HelixDB Cloud (managed, optional upgrade)

Bundled in `start_all.sh`:
```bash
#!/bin/bash
# Start HelixDB
helix start dev --disk --port 6969 || helix restart dev

# Wait for ready
until curl -s http://localhost:6969/health; do sleep 1; done

# Start AetherRavyn
python -m app.main
```

### 18.6 Migration Plan (Week 8)

- [ ] Schema definition (`.helix/schema.hx`)
- [ ] Test suite against HelixDB
- [ ] Migration script: ChromaDB + Neo4j → HelixDB
- [ ] Dual-write period: 2 weeks (write to both, read from HelixDB)
- [ ] Cutover: read only from HelixDB
- [ ] Decommission: drop ChromaDB and Neo4j deps

### 18.7 Performance Budget (HelixDB)

- Vector search k=10: p95 < 5ms
- Graph traversal depth=3: p95 < 10ms
- Hybrid search (vector + filter): p95 < 15ms
- Write throughput: >5k ops/sec
- Concurrent connections: >100
- Storage: <1GB for 1 year of typical use

### 18.8 Fallback Strategy

If HelixDB unavailable:
- In-memory fallback (data lost on restart, but agent works)
- Read-only mode (use last-known state)
- Clear error to user: "HelixDB not running, run `helix start dev --disk`"

---

## PART 19 — Updated Architecture (v3.1)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         AetherRavyn v3.1                              │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      Presentation Layer                        │    │
│  │  Telegram │ Discord │ Slack │ Voice │ Web │ IRC │ WhatsApp │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                    Core Intelligence                           │    │
│  │  Persona │ Soul │ User Model │ Meta-Cog │ Planner │ Exec     │    │
│  │  Verifier │ Policy │ Cost Router │ Cache │ Context │ Trace   │    │
│  │  Agent Swarm │ Skill Engine │ Knowledge Graph              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Memory & Knowledge Layer                     │    │
│  │                                                                 │    │
│  │  ┌───────────────────────────────────────────────────────┐    │    │
│  │  │  HelixDB (graph + vector + KV + doc + relational)     │    │    │
│  │  │  • Semantic memory    • Knowledge graph              │    │    │
│  │  │  • Sessions/events    • User profile                 │    │    │
│  │  │  • Plans / skills     • Hybrid search                │    │    │
│  │  └───────────────────────────────────────────────────────┘    │    │
│  │  + SQLite (audit, plan checkpoints, append-only logs)        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Tool & Skill Layer                            │    │
│  │  75+ Tools │ Skill Registry │ MCP │ Sandbox                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Provider & Resilience                        │    │
│  │  MODEL-AGNOSTIC: 18+ built-in adapters                       │    │
│  │  Local: Ollama, LM Studio, vLLM, llama.cpp                   │    │
│  │  Cloud: Anthropic, OpenAI, xAI, Gemini, OpenRouter, ...     │    │
│  │  Custom: any OpenAI-compatible endpoint                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌─────────────────────────────▼───────────────────────────────┐    │
│  │                  Ambient & Proactive                          │    │
│  │  11 workers + anticipation + anomaly + value-gate + dnd     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                │                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                  Observability & Ops                          │    │
│  │  OTel traces │ Prometheus │ Structured logs │ Audit log     │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 19.1 Stack Comparison

| Component | Before v3.1 | v3.1 |
|-----------|-------------|------|
| Vector DB | ChromaDB | HelixDB |
| Graph DB | Neo4j | HelixDB |
| Cache | Redis (optional) | HelixDB + in-process |
| Structured | SQLite + asyncpg | HelixDB + SQLite |
| LLM | Multi-provider | 18+ model-agnostic |
| **Total processes** | 5+ (chroma, neo4j, redis, postgres, app) | **2** (helix, app) |
| **Deployment** | docker-compose, multi-Docker | Single CLI + single app |

---

## PART 20 — Updated Module Map (v3.1)

```
app/
├── api/                    # FastAPI gateway (existing)
├── agents/                 # 14+ specialist agents (existing, harden)
├── channels/               # 7+ messaging platforms (existing, harden)
├── core/
│   ├── planning/           # NEW: real planner, executor, replanner
│   ├── runtime_v2/         # NEW: cost router, cache, queue
│   ├── verification/       # NEW: verifier, validators, rollback
│   ├── audit/              # NEW: real audit + dashboard
│   ├── policy_v2/          # NEW: real policy + approvals
│   ├── user_model/         # NEW: profile, life_graph, habits
│   ├── memory_v2/          # NEW: unified memory manager (HelixDB)
│   ├── knowledge/          # NEW: real graph (HelixDB)
│   ├── proactive/          # NEW: engine, anticipation, anomaly
│   ├── continuity/         # NEW: cross-platform session
│   ├── multimodal/         # NEW: unified event, context packer
│   ├── skills_v2/          # NEW: factory, evaluator, marketplace
│   ├── prompts_v2/         # NEW: registry, optimizer, A/B
│   ├── feedback_v2/        # NEW: capture, apply
│   ├── improvement/        # NEW: self-improvement engine
│   ├── trust/              # NEW: citations, rollback, fact-check
│   ├── privacy/            # NEW: zones, lifecycle
│   └── (existing files, refactored to use v2)
├── voice_v2/               # NEW: barge-in, multi-speaker, voice ID
├── voice_v3/               # NEW: cloning, styles
├── vision/                 # NEW: scene understanding (integrate monitoring)
├── web/                    # command_center, voice_widget, inspectors
├── observability/          # NEW: tracing, metrics, logging, health
├── tools/                  # 75+ tools (harden, add metadata)
├── provider/               # 18+ model-agnostic adapters (NEW)
│   ├── base.py             # ModelProvider protocol
│   ├── registry.py         # ProviderRegistry
│   ├── router.py           # ModelRouter (cost + tier aware)
│   ├── ollama.py           # local
│   ├── lmstudio.py         # local
│   ├── vllm.py             # local
│   ├── llamacpp.py         # local
│   ├── anthropic.py        # cloud
│   ├── openai.py           # cloud
│   ├── xai.py              # cloud
│   ├── google.py           # cloud
│   ├── mistral.py          # cloud
│   ├── cohere.py           # cloud
│   ├── deepseek.py         # cloud
│   ├── openrouter.py       # cloud (any)
│   ├── groq.py             # cloud
│   ├── together.py         # cloud
│   ├── fireworks.py        # cloud
│   ├── bedrock.py          # cloud
│   ├── azure.py            # cloud
│   ├── custom.py           # template for any OpenAI-compat
│   └── config.py           # ProviderConfig, RoutingPolicy
├── db/                     # NEW: HelixDB client + schema
│   ├── helix.py            # async Python client for HelixDB
│   ├── schema.hx           # HelixDB schema (nodes/edges/vectors)
│   ├── migrations/         # schema versioning
│   ├── sqlite.py           # existing (audit, plans)
│   └── client.py           # unified DB facade
├── skills/                 # bundled + learned (skill factory populates)
├── routines/               # proactive routines
├── settings/               # config
└── .helix/                 # HelixDB instance dir (gitignored)
```

---

## PART 21 — Updated Competitive Edge (v3.1)

| Area | OpenClaw | Hermes | **AetherRavyn v3.1** |
|------|----------|--------|---------------------|
| Architecture | Monolithic | Monolithic | **Multi-agent swarm (14+ specialists)** |
| Cognition | Single mode | Single mode | **Dual System 1/2 + meta-cognition** |
| Tools | ~30 | ~30 | **75+ typed, with risk/cost/rollback** |
| Memory | Session | Session | **HelixDB: graph+vector+KV+doc** |
| Voice | Yes (limited) | TTS only | **Full pipeline + barge-in + multi-speaker + Friday mode** |
| Device Control | Limited | No | **Desktop + Mobile + Screen + OCR + vision** |
| Ambient Loop | Cron | No | **11 workers + anticipation + anomaly + value-gate** |
| Cross-Training | No | No | **Real (LearnerAgent + feedback loop)** |
| Negotiation | No | No | **Structured debate** |
| Proactive | No | No | **Anticipatory, value-gated, DND-aware** |
| Cost-Aware | No | No | **Tier router, cache, queue, circuit breaker** |
| Model Lock-in | Yes (Claude) | Yes (GPT) | **NO LOCK-IN — 18+ providers + custom** |
| Local-First | No | No | **Yes (Ollama/LM Studio/vLLM)** |
| Cloud | Yes | Yes | **Yes (Anthropic, OpenAI, xAI, Gemini, etc.)** |
| Storage Stack | ? | ? | **Single HelixDB (graph+vector+KV)** |
| **Deployment complexity** | **High (multi-service)** | **High** | **LOW (HelixDB CLI + Python app)** |
| **Vendor risk** | **High** | **High** | **ZERO (we ship no model)** |

**Our positioning (v3.1):** "The only open-source personal AI agent that is **model-agnostic, single-DB, locally-deployable**, and **anticipates, plans, verifies, and improves itself**."

---

## PART 22 — Updated First Week (v3.1)

### Day 1: Foundation + HelixDB
- [ ] Install HelixDB CLI (`curl -sSL "https://install.helix-db.com" | bash`)
- [ ] Initialize HelixDB instance (`helix init`)
- [ ] Start dev: `helix start dev --disk` (port 6969)
- [ ] Verify health: `curl http://localhost:6969/health`
- [ ] Build `app/db/helix.py` skeleton (client, health check)
- [ ] Write `tests/test_helix.py` (10 cases)
- [ ] Initialize `app/core/planning/` with `__init__.py`, scaffolding
- [ ] Set up pre-commit hooks, pyright strict, CI

### Day 2: Planner core
- [ ] Implement `TaskPlan`, `PlanStep`, `StepStatus`
- [ ] Implement `planner.plan(goal: str) -> TaskPlan`
- [ ] Basic cost estimation
- [ ] 20 unit tests passing
- [ ] Planner state persisted to HelixDB (not SQLite)

### Day 3: Planner executor
- [ ] Implement `executor.execute(plan)`
- [ ] Sequential + parallel mode
- [ ] Retry with backoff
- [ ] Checkpointing to HelixDB
- [ ] 15 integration tests passing

### Day 4: Replanner + goal tracker
- [ ] `replanner.replan(failed_step, attempts)`
- [ ] `goal_tracker.create(goal, deadline)`
- [ ] Auto-decomposition
- [ ] 15 tests passing

### Day 5: Model-agnostic provider foundation
- [ ] `app/provider/base.py` — ModelProvider protocol
- [ ] `app/provider/ollama.py` — first adapter (most likely local)
- [ ] `app/provider/openai.py` — second adapter (cloud default)
- [ ] `app/provider/openrouter.py` — any-model adapter
- [ ] `app/provider/registry.py` — register/lookup
- [ ] `app/provider/router.py` — task → model routing
- [ ] `app/provider/config.py` — yaml loader
- [ ] 20 tests passing
- [ ] **Wire:** runtime uses router, not hardcoded provider

### Weekend: Polish + commit
- [ ] All tests green
- [ ] Coverage >80% for new modules
- [ ] `helix start dev` + `raven run` work end-to-end
- [ ] Documentation: `docs/planning.md`, `docs/providers.md`, `docs/helix.md`
- [ ] Commit: `feat(foundation): real planner + HelixDB + model-agnostic router`

**Next week:** Cost router (A2) + verifier (A3).

---

*End of v3.1 update. Total: ~1900 lines, 6 phases, 24 weeks, ~200 deliverables, ~35k new lines.*

*Two amendments: HelixDB (single storage engine) and model-agnostic (no model of our own).*

*All 6 phases committed. Start with PART 15 remaining decisions, then PART 22 First Week, then PART 3 Phase A.*
