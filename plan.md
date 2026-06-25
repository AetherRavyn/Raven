# RAVEN → FRIDAY: Complete Plan to Bridge the Gap
## Low-Compute, High-Fragility-Resilient Path to a Proper Autonomous Assistant

**Date:** 2026-06-18
**Author:** Architecture review
**Target system:** A FRIDAY/JARVIS-class always-on personal intelligence that runs on modest hardware, never falls over silently, and degrades gracefully when it does.

---

## 0. Why this plan exists

The repo contains three conflicting self-assessments:

| Source | Self-score | Staleness |
|---|---|---|
| `friday.md` (pre-transformation) | ~60% of FRIDAY | stale; most items are now built |
| `GAP_ANALYSIS_2026_06.md` (2026-06-07) | ~85% | partially stale; overstates some channels |
| `.skills/jarvis_gap_analysis.md` (2026-04-20) | 93/100 | closest to reality |

Reading the code (not the docs), the **honest position is 88–92/100** — JARVIS-class core, FRIDAY polish missing. This plan closes the last 8–12% with three non-negotiable constraints:

1. **Low compute** — every new subsystem must be cheaper than the one it replaces.
2. **High fragility resilience** — every subsystem must survive the failure of any neighbour (no silent crashes, no shared runtime death, no unauthenticated surface).
3. **End-to-end observability** — every action is auditable, replayable, and reversible where the action is reversible.

If a task below violates any of these, it is redesigned, not approved.

---

## 1. Honest gap inventory (evidence-based)

These are the gaps that **the code itself** proves are still open. Everything else is polish.

### G1. Claimed-vs-real channels
- `app/signal/__init__.py`, `app/matrix/__init__.py`, `app/irc/__init__.py` are empty stubs.
- `GAP_ANALYSIS_2026_06.md` lists them as "working". That claim is false on disk.
- **Resolution:** either implement them or remove them from the working-channels list.

### G2. `skills/learned/` is empty
- `SkillLearner.observe()` exists, but no invocation has ever produced a file.
- This is the most-cited differentiator in the project's marketing and the most clearly false.

### G3. `MEMORY.md` is 0 bytes
- `AutoMemoryUpdater` and `LifeContextEngine` exist.
- They have not written a single byte to `MEMORY.md` since the file was created.

### G4. `NegotiationProtocol.resolve()` has no caller
- `app/agents/negotiation.py` (6.9 KB) defines the protocol; nothing invokes it.
- Swarm delegates but does not coordinate.

### G5. No MCP client
- `app/mcp/server.py` exists; RAVEN cannot consume MCP from peers.

### G6. Surveillance stack is a separate process with a separate DB
- `monitoring/main.py` + `monitoring/raven.db`.
- `friday.md` calls for a unified event schema. It does not exist yet.

### G7. P2P and MessageBus are unencrypted and unauthenticated
- `monitoring/src/p2p.py` and `monitoring/src/message_bus.py` — flagged in `friday.md`, still true.

### G8. `SecurityGuard.requires_approval` is read from a global JSON
- `security.py:190` reads `~/.raven/user_config.json` on every call.
- A live-mutable policy store (`policy_v2/store.py`) exists but `requires_approval` does not use it.

### G9. DM pairing not enforced on every channel
- Code exists; only some channels call it.

### G10. No native companion app
- Web dashboard + Live Canvas are good; no first-class desktop/mobile presence.

### G11. No nightly eval / regression gate
- `regression.py` and `eval.py` exist; nothing runs them on a schedule or gates merges on them.

### G12. Video is split from assistant multimodal context
- `monitoring/src/video_*` and `app/core/video_fusion.py` are separate paths.

### G13. No skill versioning / trust tiers
- `skill_registry.py` discovers and health-checks; no manifest version, no signed trust tier.

### G14. No unified event schema
- `audit/types.py`, `proactive_core/types.py`, `policy_v2/types.py`, `cost_router/types.py`, `verifier/types.py`, `scheduling/signal.py` all define their own.

### G15. Hard-coded `is_admin` admin list behaviour
- Original concern from `friday.md` is now fixed (deny-by-default in `security.py:155-158`).
- **Status:** ✅ resolved. Kept on the list only to confirm.

---

## 2. Design principles for everything that follows

| Principle | Rule |
|---|---|
| **P1. Smallest viable model first** | Intent classification, summaries, routing, compression → 1B–3B local model. Cloud = opt-in per request. |
| **P2. Lazy everything** | No top-level imports of torch, transformers, chromadb, yolo, vosk, piper. Each heavy dep is gated behind a feature flag. |
| **P3. Bounded loops** | Every background loop (ambient, proactive, scheduler) has a hard wall-clock budget per tick. If it overruns, it yields and re-queues. |
| **P4. Process isolation by default** | Voice, surveillance, web dashboard, MCP, scheduler each run in their own process; the orchestrator is the only long-lived monolith. |
| **P5. Outbox pattern for outbound** | A bot never sends directly. It writes to an outbox; a sender process drains with at-least-once semantics and dedup. |
| **P6. Append-only audit** | Every tool call, every agent handoff, every alert lands in an append-only log before the action runs. |
| **P7. Dry-run by default for new tools** | A new tool ships disabled and dry-run-only; promotion to live is a one-line config flip. |
| **P8. Graceful degradation ladder** | cloud → local → cached answer → canned answer → silence. Never throw. |
| **P9. Compute budget per user per day** | Enforced by `cost_router/ledger.py`; per-user USD cap plus token cap. |
| **P10. Cache or it didn't happen** | Tool results, embeddings, summaries, model outputs all cached by (tool_name, args-hash, ttl). |

---

## 3. Architecture target (after this plan)

```
                 ┌────────────────────────────────────┐
                 │   Companion / Web / Voice clients  │
                 └────────────┬───────────────────────┘
                              │ wss + signed JWT
                              ▼
   ┌──────────────────────────────────────────────────────┐
   │                    EDGE GATEWAY                      │
   │  auth, rate-limit, schema-validate, fan-out          │
   └────────────┬─────────────────────────────┬───────────┘
                │                             │
                ▼                             ▼
       ┌────────────────┐           ┌────────────────────┐
       │  ORCHESTRATOR  │  events   │   UNIFORM EVENT    │
       │  (one process) │ ◀──────▶ │   BUS (Redis +     │
       │  in-proc ReAct │           │   signed envelopes)│
       └────┬──────┬────┘           └────────┬───────────┘
            │      │                        │
            ▼      ▼                        ▼
   ┌────────────┐ ┌────────────┐   ┌──────────────────┐
   │ Tool pods  │ │ Agent pods │   │ Sidecar processes│
   │ (Docker /  │ │ (swarm)    │   │ voice, sentinel, │
   │  OCI)      │ │            │   │ mcp, web, mqtt   │
   └────┬───────┘ └─────┬──────┘   └────────┬─────────┘
        │               │                  │
        └───────────────┴──────────────────┘
                        │
                ┌───────▼────────┐
                │  Append-only   │
                │  audit + KG    │
                └────────────────┘
```

Everything inside the box is reachable only via the event bus. The bus is the only place that can fail catastrophically; everything else degrades.

---

## 4. The plan (10 phases, ordered by ROI × fragility-resilience)

Each phase has: **goal → why it matters → exact files → fragility contract → low-compute contract → exit criteria**.

---

### Phase 0 — Stop the bleeding (Week 1, ~3 days)

**Goal:** Make what we have honest and isolated.

**Why:** A FRIDAY-class system is not a system that *has* features; it is a system that *knows what it has and is running*. Today we have lies in the docs and one shared process.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P0.1 | Implement Signal, Matrix, IRC connectors OR strike them from `GAP_ANALYSIS_2026_06.md` and the README. | `app/signal/`, `app/matrix/`, `app/irc/` |
| P0.2 | Wire `SkillLearner.observe()` into the orchestrator so a single chat produces a `skills/learned/<date>-<hash>.md` artifact. | `app/core/orchestrator.py`, `app/core/skill_learner.py` |
| P0.3 | Wire `AutoMemoryUpdater` into the ambient loop so `MEMORY.md` updates at most every 10 minutes from `LifeContextEngine`. | `app/core/auto_memory.py`, `app/core/ambient_loop.py` |
| P0.4 | Migrate `SecurityGuard.requires_approval` to read from `policy_v2/store.py` (cache the read for 30 s). | `app/core/security.py`, `app/core/policy_v2/store.py` |
| P0.5 | Enforce `check_dm_pairing` on every channel adapter; fail-closed on Telegram/Discord/Slack/WhatsApp, fail-open on web with a banner. | `app/telegram/bot.py`, `app/discord/discordapp.py`, `app/slack/slackapp.py`, `app/whatsapp/whatsappapp.py`, `app/web/server.py` |
| P0.6 | Add `scripts/audit_channel_truths.py` that walks `app/*/` and asserts: if a doc claims a channel works, the connector file has ≥ N non-stub functions. Runs in CI. | new |

**Fragility contract**
- No shared process is allowed to die because one connector died. Every channel runs in its own task with its own `try/except` boundary; `main.py` already does this — verify with a fault-injection test.

**Low-compute contract**
- The audit script is a static check, not a runtime one.
- `MEMORY.md` write is bounded to one LLM call (≤ 1k tokens out) every 10 minutes.

**Exit criteria**
- `ls skills/learned/` is non-empty after one chat in CI.
- `MEMORY.md` is non-empty after one ambient tick in CI.
- CI fails if any doc claims a channel is working but the connector has no real handler.

---

### Phase 1 — Process & dependency isolation (Week 2, ~5 days)

**Goal:** No single point of failure. Sidecars die in their own process.

**Why:** A FRIDAY that "goes down because Telegram reconnected" is not FRIDAY. The orchestrator must survive any sidecar.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P1.1 | Introduce a tiny process supervisor (`app/runtime/supervisor.py`) that spawns sidecars as `multiprocessing` children with health pings every 5 s. | new |
| P1.2 | Move voice pipeline into its own sidecar process; orchestrator talks to it over the event bus. | `app/voice/pipeline.py`, new `app/voice/sidecar.py` |
| P1.3 | Move monitoring (sentinel + YOLO) into its own sidecar; orchestrator consumes its events. | `monitoring/main.py`, new `monitoring/sidecar.py` |
| P1.4 | Move MCP server into its own sidecar. | `app/mcp/sidecar.py` |
| P1.5 | Move web dashboard (FastAPI) into its own sidecar. | `app/web/sidecar.py` |
| P1.6 | Move Streamlit into its own sidecar. | `app/dashboard/sidecar.py` |
| P1.7 | Add a process restart policy: exponential backoff capped at 5 min, max 10 restarts/hour, then supervisor alerts and pauses. | `app/runtime/supervisor.py` |
| P1.8 | Add shared memory budget: each sidecar reports RSS every 5 s; orchestrator logs and alerts at 80% of system RAM. | `app/runtime/supervisor.py` |

**Fragility contract**
- Kill -9 any sidecar. Within 10 s the orchestrator logs the death, the supervisor restarts it, and a replay of in-flight outbox messages resumes.

**Low-compute contract**
- The supervisor is one coroutine, no third-party deps. It does not poll; it awaits an `asyncio.Event` set by a single 1 Hz tick.
- Sidecars report a 64-byte JSON line, not a full dict. No serialization overhead.

**Exit criteria**
- `tests/test_supervisor_kill9.py` kills each sidecar in turn and asserts recovery.
- A 24 h soak run leaves no orphan processes and no leaked file descriptors.

---

### Phase 2 — Unified event schema and signed bus (Week 3, ~5 days)

**Goal:** One event shape across assistant, voice, sentinel, web, MCP. Signed envelopes. Schema-validated.

**Why:** "Unified event schema" is the single most important FRIDAY building block. It is also the cheapest: a `dataclass` + a `jsonschema` file.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P2.1 | Define `app/core/events.py` with `Envelope`, `Header`, `Body`, and a `Schema` (JSON-Schema). | new |
| P2.2 | Define a versioned schema directory: `app/core/schemas/v1/{envelope,chat,tool_call,alert,metric,life_event}.json`. | new |
| P2.3 | Add `envelope.sign(ed25519)` and `envelope.verify(ed25519)`. Each sidecar holds a keypair; orchestrator holds the trust store. | new |
| P2.4 | Replace internal pubsub in `monitoring/src/message_bus.py` with a thin Redis Streams wrapper that auto-signs. | modify |
| P2.5 | Add an in-process bus (`app/core/inproc_bus.py`) for high-frequency events (tool traces, metrics) that does not pay Redis cost. | new |
| P2.6 | Wire all `audit/types.py`, `proactive_core/types.py`, `policy_v2/types.py`, `cost_router/types.py`, `verifier/types.py`, `scheduling/signal.py` to use the unified schema as their transport, even if their internal model differs. | modify |
| P2.7 | Add `tests/test_event_schema_roundtrip.py` for every schema. | new |

**Fragility contract**
- Any sidecar that cannot verify an envelope drops it and increments `events.rejected_unsigned` metric. Never throws.
- Bus partition is detected within 30 s (heartbeat); orchestrator switches to in-proc bus and logs a warning.

**Low-compute contract**
- Envelope size capped at 8 KB; larger payloads are content-addressed and the envelope carries the hash.
- JSON-Schema validation only on boundary crossings (sidecar ↔ orchestrator), not on in-proc events.

**Exit criteria**
- An offline `redis-cli MONITOR` shows every message is a tiny JSON envelope, not a Python object.
- A new event type can be added in < 30 lines of schema + dataclass.

---

### Phase 3 — Low-compute cognition (Week 4, ~5 days)

**Goal:** Make the cheap path the default path. Make the expensive path the exception.

**Why:** FRIDAY on a laptop means tiny models handle 80% of work. The router decides.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P3.1 | Add a `tiny` provider (3B local, GGUF, llama.cpp) wired as the **default** for: intent classify, summarize, route, draft reply, extract entities, propose plan steps. | `app/provider/tiny.py` |
| P3.2 | Make `cost_router/router.py` the single entry point; the runtime and orchestrator must call it instead of providers directly. | modify |
| P3.3 | Implement a 4-step ladder: `tiny → small → medium → large`. Each step has a confidence threshold; if confidence ≥ τ, return; else escalate. | `app/core/cost_router/router.py` |
| P3.4 | Add prompt + response cache (`app/core/cache.py`) keyed by `(model, prompt_hash, tool_name)`, LRU + TTL. | new |
| P3.5 | Add tool result cache in `app/tools/base.py`: every tool may declare `cacheable=True, ttl=N, key=arg-hash`. | modify |
| P3.6 | Implement streaming-where-it-helps: only stream for user-facing text; never stream for tool calls or planning. | `app/core/runtime.py` |
| P3.7 | Add a "degraded mode" detector: if local tiny model is unreachable for > 30 s, fall back to canned answers; if cloud is unreachable, fall back to local; if both down, send "I'm rebooting my brain, give me 30 s". | `app/core/cost_router/health.py` |

**Fragility contract**
- If `tiny` model process dies, the router escalates to `small` without dropping the request. The user does not see an error.
- If all models are down, the orchestrator returns the last cached answer for the same intent hash, if any.

**Low-compute contract**
- `tiny` runs at ≤ 4 GB RAM, ≤ 10 tok/s on a 4-core CPU is the success bar.
- Cache hit rate target: ≥ 40% on the second day of operation.

**Exit criteria**
- A request trace shows ≤ 1 LLM call for ≥ 60% of inputs in the eval harness.
- 24 h CPU profile stays under 25% on a 4-core box.

---

### Phase 4 — Resilient tools, no silent failures (Week 5, ~5 days)

**Goal:** Every tool has a fragility contract and lives behind a uniform executor.

**Why:** The current `app/tools/` is a flat directory of 60+ tools. Each has its own error model. One slow tool can stall the loop.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P4.1 | Promote `app/tools/resilience.py` decorators (`@with_retry`, `@with_timeout`, `@with_fallback`, `@with_circuit_breaker`) to a base class `BaseResilientTool`. | new |
| P4.2 | Add per-tool metadata: `risk_level`, `requires_approval`, `cost_tier`, `cacheable`, `side_effect`, `rate_limit_per_min`, `timeout_s`, `retryable`. | `app/tools/base.py` |
| P4.3 | Add a tool manifest loader (`app/tools/manifest.py`) that reads metadata from a YAML next to each tool. CI fails if a tool has no manifest. | new |
| P4.4 | Implement a tool outbox: any tool call that has external side effects is recorded in `audit_log` *before* execution, and the result is recorded *after*. Replay is possible. | `app/core/audit/log.py` |
| P4.5 | Add a tool execution watchdog: any tool exceeding `timeout_s` is cancelled and the result is a structured error. | `app/tools/base.py` |
| P4.6 | Add a dry-run mode: each tool can be invoked with `dry_run=True` to return the call it *would* make, not the side effect. Used by tests and by the proactive "should I do this?" check. | `app/tools/base.py` |
| P4.7 | Convert the 60+ tools to the new base. New tools must use the base. Existing tools are migrated one at a time. | `app/tools/*.py` |
| P4.8 | Add a `tools/registry.json` generated at build time; the runtime refuses to load tools not in the registry. | new |

**Fragility contract**
- A tool that times out 3× in 5 min is circuit-broken for 10 min. The runtime returns a structured error to the model; the model can ask the user to retry or pick a different tool.
- A tool that throws an unhandled exception never crashes the loop; the error is logged + returned to the model with a request to recover.

**Low-compute contract**
- Tool manifests are tiny YAML; loaded once at startup.
- Watchdog uses `asyncio.wait_for`; no extra threads.
- Cache + circuit breaker cost ≤ 1 ms per tool call.

**Exit criteria**
- A fault-injection test (kill the network mid-tool) shows the loop survives, retries, and surfaces a clean error to the model.
- Every tool has a manifest in CI.

---

### Phase 5 — Privacy, audit, and trust as a first-class subsystem (Week 6, ~4 days)

**Goal:** Privacy is a runtime check, not a config file. Audit is searchable. Trust is a number, not a vibe.

**Why:** FRIDAY holds everything about the user. If privacy is not enforced at every layer, the system is unsafe to use in real life.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P5.1 | Promote `app/core/privacy/` to a runtime gate: every tool call, every event, every memory write is checked against a policy *before* execution. The check returns `(allowed, reason, redaction)`. | modify |
| P5.2 | Add a privacy zone model (`app/core/privacy/zones.py`) — already exists. Wire it to channels: a Telegram message from zone `work` is redacted before it touches memory or model. | modify |
| P5.3 | Make `audit/log.py` queryable: add a small `audit query --user X --tool Y --since Z` CLI and a `/api/audit/search` endpoint. | modify |
| P5.4 | Add trust scores per source (`app/core/trust/` — already exists). Wire trust into the cost router: low-trust sources are summarized by `tiny`, never by `large`. | modify |
| P5.5 | Add `app/core/privacy/inspector.py` — already exists. Expose it on the web dashboard so the user can see and edit what is stored. | modify |
| P5.6 | Add per-user data export (`GET /api/user/{id}/export`) and per-user data delete (`DELETE /api/user/{id}`). | new |
| P5.7 | Add secret rotation hooks: a tool that needs `OPENAI_API_KEY` calls `resolve_credential()` which can re-read on rotation. | `app/core/security.py` |

**Fragility contract**
- A privacy violation is never silent. If a check fails, the action is denied and the audit log gets an entry.
- Audit log is append-only and replicated to a write-once sink (`scripts/audit_archive.py`).

**Low-compute contract**
- Privacy check is a single dict lookup; cost ≤ 0.1 ms.
- Audit writes are batched every 1 s, not per-event.

**Exit criteria**
- A user can see, search, export, and delete all data about themselves from the dashboard.
- A red-team prompt that tries to leak another user's data is denied at the policy layer, not at the model layer.

---

### Phase 6 — Plan, execute, verify, learn (Week 7, ~5 days)

**Goal:** The `app/core/planning/` package becomes the single entry point for multi-step work. The new planner is on by default.

**Why:** `planner.py` is a shim; `app/core/planning/planner.py` is the real thing. The shim is fine for backward compat but the new one must lead.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P6.1 | Default `RAVEN_PLANNER_V2=true` in `app/settings/config.py`. Keep the shim for one release. | modify |
| P6.2 | Add a `Replanner` trigger on any verifier failure: the planner re-issues a sub-plan with the failure context. | `app/core/planning/replanner.py` |
| P6.3 | Add `CostEstimator` consultation: before a plan is executed, the router tells the planner the budget; the planner prunes steps that exceed it. | `app/core/planning/cost_estimator.py` |
| P6.4 | Add `PlanStore` persistence: every plan is saved with its steps, results, verifier verdicts, and re-plans. | `app/core/planning/store.py` |
| P6.5 | Add `GoalTracker`: a plan can be part of a long-horizon goal; the goal tracker advances the goal state. | `app/core/planning/goal_tracker.py` |
| P6.6 | Make the agent negotiation protocol actually callable: `app/agents/negotiation.py` exposes a `resolve(topic, proposals)` method that the swarm uses when more than one agent wants the floor. | `app/agents/negotiation.py`, `app/core/agency.py` |
| P6.7 | Add a `tests/test_planner_recovery.py` that breaks a tool mid-plan and asserts a re-plan succeeds. | new |

**Fragility contract**
- If a plan step fails three times, the planner pauses and asks the user. Never infinite-loop.
- The plan store survives a process restart (SQLite, append-only).

**Low-compute contract**
- A plan is generated by `tiny` model with a 2-shot prompt, capped at 500 tokens out.
- The re-planner is invoked only on verifier failure, not on every step.

**Exit criteria**
- 100% of multi-step requests flow through the new planner in CI.
- Re-plan rate is logged and stable (no thrash).

---

### Phase 7 — Native companion + dashboard polish (Week 8, ~5 days)

**Goal:** A first-class always-on presence on the user's devices.

**Why:** "Companion" is the word the user thinks of. Today the closest is the web dashboard. That is not enough.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P7.1 | Tauri (Rust) desktop companion for macOS/Windows/Linux. Single 12 MB binary, system tray, push notifications, WebSocket to orchestrator. | new `companion/desktop/` |
| P7.2 | Capacitor mobile shell wrapping the same WebSocket client. One codebase, three platforms. | new `companion/mobile/` |
| P7.3 | Add a "Live Status" tile: CPU/RAM, queue depth, last action, last error. Tauri shows it in the tray. | new |
| P7.4 | Add a "Quick Command" palette: ⌘K / Ctrl-K opens a command box with intent-routed suggestions. | new |
| P7.5 | Add offline cache: the companion buffers the last 24 h of events and replays when reconnected. | new |
| P7.6 | Add system notifications for: high-priority alerts, morning briefing, anomaly digests. | new |
| P7.7 | Add per-channel mute + per-intent mute (e.g. "never notify me for low-priority inbox items on Sunday"). | new |

**Fragility contract**
- The companion never blocks on the orchestrator. It is a renderer of the event bus, nothing more. If the bus is down, it shows "offline" and queues outgoing actions.

**Low-compute contract**
- Companion uses ≤ 50 MB RAM, ≤ 1% CPU at idle.
- All UI is local-rendered HTML/CSS; no SPA framework.

**Exit criteria**
- macOS / Windows / Linux / iOS / Android builds all show the same Live Status tile.
- A 7-day soak shows the companion recovers from sleep/wake without manual intervention.

---

### Phase 8 — Observability and continuous evaluation (Week 9, ~4 days)

**Goal:** Every metric you need is on a single Grafana board. Every regression is caught before merge.

**Why:** "FRIDAY" without observability is a black box. Without regression gates, every change is a coin flip.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P8.1 | Standardize on Prometheus + Loki + Tempo (or the existing `app/observability/` if it can be made drop-in). | `app/observability/` |
| P8.2 | Add a single Grafana dashboard JSON in `monitoring/dashboards/raven.json` with 12 panels: requests/min, tool success rate, plan replan rate, model escalation rate, cost USD/day, cache hit rate, privacy denials, audit writes/min, sidecar restarts, RAM, CPU, queue depth. | new |
| P8.3 | Add a nightly eval (`scripts/nightly_eval.py`) that runs the 30 hard prompts in `tests/eval/`. It records pass rate, latency, cost, and tool-call count. | new |
| P8.4 | Add a regression gate in CI: any change that drops the pass rate by > 5% or p95 latency by > 20% fails. | new |
| P8.5 | Add drift detection on the cost router: if a model's output diverges from the cached expected shape more than N%, alert. | `app/core/cost_router/health.py` |
| P8.6 | Add a `raven doctor` command (already exists at `app/cli/doctor.py`) that runs all health checks and prints a single page of truth. | modify |

**Fragility contract**
- Prometheus outage does not stop RAVEN. Metrics degrade to local counters; the next scrape picks them up.

**Low-compute contract**
- Metrics: 1 process, 1 MB of counters, scrape every 30 s.
- Eval: nightly only, runs on `tiny` for grading; budget capped at 1k tokens per prompt.

**Exit criteria**
- `make dashboard` opens the full picture in one browser tab.
- A simulated 10× traffic spike shows the ladder (cache → tiny → small → large) absorbs it.

---

### Phase 9 — Skill ecosystem with versioning and trust (Week 10, ~4 days)

**Goal:** Skills are signed, versioned, and discoverable. `skills/learned/` is the actual learning output.

**Why:** This is the most-cited differentiator and the most-clearly-empty.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P9.1 | Add a skill manifest schema (`app/core/skill_manifest.json`) with: `name`, `version`, `author`, `signature`, `permissions`, `risk_level`, `inputs`, `outputs`, `evals`. | new |
| P9.2 | Add `ed25519` signing at skill creation; verification at load. The orchestrator refuses to load an unsigned or untrusted skill in `Strict` mode. | new |
| P9.3 | The `SkillLearner` writes a real artifact: a skill is a directory under `skills/learned/<name>/<version>/` with `SKILL.md`, `manifest.json`, `eval.jsonl`, `signature`. | `app/core/skill_learner.py` |
| P9.4 | Promotion gate: a learned skill must pass 20 invocations in eval before it can be triggered automatically. | new |
| P9.5 | Add a `skills/` API: list, show, install, uninstall, enable, disable, promote. Web dashboard surfaces it. | new |
| P9.6 | Add a community registry (read-only) so users can browse shared skills. | new |
| P9.7 | Migrate the 18 bundled skills to the manifest format. | `skills/bundled/*/` |

**Fragility contract**
- A skill that fails its eval is auto-quarantined. It can be inspected, not auto-invoked.

**Low-compute contract**
- Skill discovery is one directory walk at startup; ≤ 50 ms for 200 skills.
- Skill load is lazy: the skill module is imported only when triggered.

**Exit criteria**
- `ls skills/learned/` has at least one skill after a 30-turn eval run.
- All 18 bundled skills have manifests and pass eval.

---

### Phase 10 — Degraded modes and offline presence (Week 11, ~4 days)

**Goal:** FRIDAY works on a plane.

**Why:** A FRIDAY that disappears when Wi-Fi drops is not a companion. It is a website.

**Tasks**

| ID | Task | File(s) |
|---|---|---|
| P10.1 | Define three modes: `online`, `degraded`, `offline`. Mode is auto-detected by the supervisor every 10 s. | `app/runtime/mode.py` |
| P10.2 | `online` = full features. `degraded` = no cloud, only `tiny` + cache. `offline` = canned answers + the ability to queue actions for when connectivity returns. | same |
| P10.3 | Queue outbound actions in the outbox (already exists for bots; extend to all side effects). On reconnect, drain in order with idempotency keys. | `app/core/botsignal.py` |
| P10.4 | Local voice pipeline stays in `offline` mode; `tiny` model on-device handles intent. | `app/voice/pipeline.py` |
| P10.5 | Local memory stays fully usable in `offline` mode. | `app/core/memory.py` |
| P10.6 | The companion shows the current mode in its status tile. | `companion/desktop/` |
| P10.7 | Add a `raven mode` CLI to inspect and override. | `app/cli/main.py` |

**Fragility contract**
- A mode change never drops a request. It only changes the *answer*.

**Low-compute contract**
- Mode detection is a single TCP probe to a 1.1.1.1-class host every 10 s. ≤ 1 kbps.
- Offline canned answers live in a 200 KB JSON.

**Exit criteria**
- A 1-hour offline soak shows no crashes and queues all outbound actions correctly.
- Reconnecting drains the queue in order, no duplicates.

---

## 5. Cross-cutting contracts (apply to every phase)

### 5.1 Fragility contract (recap)

| Failure | Required behaviour |
|---|---|
| Any sidecar process dies | Supervisor restarts in ≤ 10 s with backoff; orchestrator logs; in-flight outbox replays. |
| Any tool times out | Watchdog cancels; circuit breaker after 3 in 5 min; runtime gets structured error. |
| Any model unreachable | Router escalates tier; if all down, returns cached or canned answer. |
| Any channel dies | Its task is cancelled; other channels continue. |
| Privacy check fails | Action denied; audit log written. Never silent. |
| Network gone | Mode → degraded → offline automatically. |
| Disk full | Sidecars switch to read-only and signal back-pressure. |
| Process killed -9 | Replay from outbox; no lost messages. |

### 5.2 Low-compute contract (recap)

| Resource | Budget |
|---|---|
| RAM (whole system, idle) | ≤ 1.5 GB |
| RAM (whole system, peak) | ≤ 4 GB |
| CPU (idle) | ≤ 5% on 4 cores |
| CPU (under load) | ≤ 60% on 4 cores |
| Disk (logs) | ≤ 50 MB/day, 5 backups |
| Disk (memory) | ≤ 200 MB / user |
| Cost (cloud) | ≤ $0.50 / user / day at moderate use |
| Latency (p50) | ≤ 800 ms for cached, ≤ 3 s for tiny, ≤ 8 s for small |
| Latency (p95) | ≤ 1.5 s cached, ≤ 6 s tiny, ≤ 15 s small |
| Token cost (per chat) | median ≤ 1.5k tokens in, ≤ 600 out |

### 5.3 Observability contract (recap)

| Signal | Where |
|---|---|
| Every tool call | `audit/log.py` |
| Every agent handoff | `audit/log.py` + `cost_router/ledger.py` |
| Every model escalation | `cost_router/health.py` |
| Every privacy denial | `privacy/audit_viewer.py` |
| Every sidecar death | `runtime/supervisor.py` + Prometheus counter |
| Every mode change | `runtime/mode.py` + Prometheus counter |
| Every skill trigger | `skill_registry.py` + `cost_router/ledger.py` |

---

## 6. Sequencing & dependencies

```
P0 ──▶ P1 ──▶ P2 ──▶ P3
                   │
                   ├──▶ P4
                   │      │
                   │      └──▶ P6
                   ├──▶ P5
                   └──▶ P8 (depends on P3, P4, P5)

P7 (companion)        can run in parallel with P3–P6
P9 (skills)           depends on P4 (manifests) + P8 (eval)
P10 (degraded)        depends on P1 (supervisor) + P2 (event bus) + P3 (router)
```

Total: ~11 weeks for one engineer working steadily, ~6 weeks for two engineers in parallel on P7/P3/P4.

---

## 7. What this plan deliberately does *not* do

- **No native iOS/Android from scratch.** Capacitor wraps the web stack. Saves months.
- **No fine-tuning.** We use prompt + retrieval + cache to do almost everything. Fine-tuning is a future lever, not a current need.
- **No custom TTS/STT.** Edge-TTS + faster-whisper + Vosk are already good enough.
- **No "AGI brain" rewrite.** The existing ReAct loop is fine. We isolate it, not replace it.
- **No multi-tenant SaaS.** This plan keeps RAVEN a single-user, self-hosted system. A SaaS is a separate, much larger undertaking.

---

## 8. Definition of done for "proper FRIDAY-grade system"

A reviewer must be able to confirm **all** of the following from a fresh clone on a 4-core / 8 GB box:

1. `make install && make up` brings the system online in < 5 min.
2. Telegram, Discord, Slack, WhatsApp, voice, web all work. (Signal/Matrix/IRC are explicit and honestly labeled.)
3. The companion app installs in < 1 min and survives sleep/wake.
4. A 24 h soak leaves the box at ≤ 25% average CPU, ≤ 1.5 GB RAM.
5. Killing the orchestrator and restarting it loses zero in-flight actions (outbox replay).
6. Killing any sidecar auto-restarts it in < 10 s.
7. The user can see, search, export, and delete all data about themselves from the dashboard.
8. The eval suite runs green for 7 consecutive nights.
9. `MEMORY.md` is up to date and `skills/learned/` is non-empty.
10. The system works offline for 1 h without crashing, queues all actions, and drains them on reconnect.

When all 10 are true, **RAVEN is a proper system in the FRIDAY class**.

---

*End of plan.*
