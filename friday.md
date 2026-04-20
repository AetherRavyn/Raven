# Friday Audit for SARAS

This is a codebase audit based on the current workspace. SARAS is already a multi-platform assistant platform with agents, tools, memory, voice, and a separate surveillance stack. It is not yet a full Friday or Jarvis-style assistant because the missing pieces are mostly memory policy, proactive planning, safe autonomy, and unified orchestration.

## What SARAS Already Has
- Multi-platform connectors: Telegram, Discord, Slack, WhatsApp, web, voice, MQTT, webhook receiver, and Streamlit admin UI.
- Unified output layer with `BotSignal` and platform-specific rendering for Telegram, Discord, and Slack.
- Fast reflex router (`MiniEngine`) for greetings, identity, time, OS status, server health, and internet checks.
- ReAct-style `AgentRuntime` with tool calling, session handling, streaming responses, and multimodal image input.
- Swarm delegation for parallel specialist agents.
- Provider abstraction with resilient fallback to Ollama.
- Memory: workspace prompts, per-agent markdown memory, ChromaDB semantic memory, and optional pgvector.
- Safety: prompt-injection detection, dangerous-command blocking, rate limiting, admin gating, and output annotations.
- Scheduling and recurring reminders with APScheduler.
- Observability: rotating logs and Prometheus metrics.
- Voice pipeline: wake word, VAD, faster-whisper, Vosk fallback, and edge-tts.
- Tool ecosystem: files, git, browser, web search/fetch, finance, weather, todo, reminders, calendar, smart home, system stats, network, social, media, camera, database, and security tools.
- Monitoring stack: RTSP/MJPEG/WebSocket camera ingest, YOLO detection, ByteTrack tracking, face ReID, anomaly detection, alerting, semantic search, risk analysis, P2P IoT bridge, storage, and vision overlays.
- MCP server for higher-level control and external LLM integration.

## What Is Missing For A Friday-Level Assistant
- True persistent user profiles, preferences, and life context.
- A real planner/executor that breaks goals into steps, checks results, and recovers from failure.
- Proactive behavior: reminders, follow-ups, summaries, and event-driven nudges without being asked.
- Unified memory across chat, voice, files, email, calendar, cameras, and sensors.
- Strong tool permissions per user, per agent, and per action.
- Confirmation workflows for risky actions.
- Better tool-result verification and post-action validation.
- Full multimodal reasoning across text, audio, image, and video in one context flow.
- Local-first model routing so cheap models handle simple tasks and expensive models are used only when needed.
- Evaluation harnesses for agent quality, safety, and regression testing.
- A skill/plugin registry with versioning and health checks.
- A better knowledge graph layer for people, devices, tasks, locations, and events.
- A real conversation memory policy: summarize, compress, prune, and restore context safely.
- Cross-device continuity: start on Telegram, continue on voice, finish on web.

## Weaknesses In The Current Code
- `MessageBus` has a hard-coded Redis URL with embedded credentials.
- `SecurityGuard.is_admin()` effectively allows everyone when `ADMIN_USER_IDS` is empty, despite the warning text.
- Some monitoring features are placeholders or overlays only, not real algorithms.
- `SemanticSearchEngine` uses MobileNet logits, which is coarse, not strong semantic retrieval.
- The bot is multi-process in spirit, but many services still share one runtime and can stop together on failure.
- `P2P` and bus traffic are not application-level authenticated or encrypted.
- Several APIs return static or stubbed data instead of live state.
- There is no centralized audit log for who triggered which tool and why.
- No first-class memory compaction or knowledge lifecycle management.
- Vision, voice, and assistant are still partly separate systems instead of one unified assistant brain.

## Missing Pieces To Implement
- A `TaskPlanner` that creates plans, substeps, dependencies, and success checks.
- A `ModelRouter` that chooses small local models first and escalates only when required.
- A `MemoryManager` that stores preferences, summaries, and long-term facts.
- A `PolicyEngine` for tool permissions, confirmations, and action risk scores.
- A `ProactiveLoop` for daily briefs, follow-ups, anomalies, and suggested actions.
- A `SkillRegistry` for tools, agents, and versioned capabilities.
- A `MultimodalContextBuilder` that merges text, audio, image, and event memory.
- A `VerificationLayer` for tool outputs, especially network, file, and actuation tools.
- A `UnifiedEventBus` for assistant events, surveillance events, and automations.
- A `TelemetryAndEval` suite for latency, accuracy, tool success, and safety regressions.

## Low-Compute Strategy
- Use small local models for routing, classification, intent detection, summaries, and quick replies.
- Keep expensive models only for hard reasoning, complex writing, or deep research.
- Cache tool results, embeddings, summaries, and common responses.
- Prefer event-driven automation over polling.
- Reduce vision frequency adaptively with frame skipping and resolution throttling.
- Keep STT and TTS lightweight and lazy-loaded.
- Summarize old context instead of replaying full chat history.
- Use background workers for heavy jobs and keep the main chat loop fast.
- Disable vision, face ReID, and pose features unless they are needed.
- Prefer structured outputs over free-form answers when actions are involved.

## Detailed Implementation Plan

### Phase 0: Fix The Foundation
- Remove hard-coded secrets and move all runtime URLs, tokens, and credentials into validated config.
- Fix admin authorization so empty admin lists default to deny, not allow.
- Add a central action log for every tool call, agent handoff, and alert.
- Define a single `ActionContext` object that carries user, platform, risk, memory, and request metadata.
- Add basic tool capability metadata: required permissions, risk level, cost tier, and confirmation policy.
- Add tests for security, routing, memory retrieval, and connector registration.

### Phase 1: Make The Assistant Reliable
- Build a real planner that converts a goal into steps, tool calls, and validation checks.
- Add a result verifier that checks tool output before the model sees it.
- Add a unified memory summary flow:
  - short-term chat memory
  - long-term user profile memory
  - task memory
  - factual memory
- Add conversation compression so older turns become compact summaries.
- Add a model router that chooses local/small models for low-risk tasks.

### Phase 2: Add Proactive Behavior
- Add scheduled briefings, reminders, anomaly digests, and daily summaries.
- Add event-driven assistant triggers from calendar, MQTT, cameras, and monitoring alerts.
- Add follow-up workflows for unanswered questions and incomplete tasks.
- Add cross-platform continuity so the same thread can move between Telegram, voice, web, and Discord.

### Phase 3: Unify Multimodal Intelligence
- Merge text, voice, image, sensor, and surveillance events into one event schema.
- Add multimodal context packing with token budgets and priority rules.
- Add better image/video semantic retrieval.
- Add a knowledge graph for people, devices, rooms, tasks, alerts, and relationships.

### Phase 4: Harden Autonomy
- Add approval flows for risky actions like shell exec, network changes, device actuation, and message sending.
- Add per-user and per-agent permission policy.
- Add rollback and safety checks for destructive or irreversible actions.
- Add offline/degraded modes for voice, chat, and surveillance.

### Phase 5: Measure And Improve
- Add automated evaluation for tool success, answer quality, latency, and hallucinations.
- Add regression tests for prompts, tools, and connector behavior.
- Add observability dashboards for cost, latency, memory growth, and model usage.

## Module-By-Module Feature Matrix

| Module | What It Has | What It Lacks | Priority |
|---|---|---|---|
| `app/core/orchestrator.py` | Multi-agent routing, security checks, rate limiting, reflex + deep reasoning split | Planner, cost-aware model selection, action approval policy | P0 |
| `app/core/runtime.py` | ReAct loop, tool calling, streaming, multimodal image input, fallback provider logic | Structured task plans, post-tool verification, memory-aware context budgeting | P0 |
| `app/core/bootstrapper.py` | Dynamic system prompt injection, markdown memory, basic temporal context | Memory summarization lifecycle, memory scoring, profile compression | P1 |
| `app/core/memory.py` | ChromaDB + pgvector semantic memory | Explicit memory taxonomy, compaction, freshness scoring, preference memory | P1 |
| `app/core/security.py` | Prompt injection detection, dangerous command detection, admin concept | Correct deny-by-default admin policy, tool-level permissions, approval workflow | P0 |
| `app/core/ratelimit.py` | In-memory and Redis rate limiting | Per-tool rate limits, per-agent quotas, request cost budget | P1 |
| `app/core/scheduler.py` | Reminder scheduling and recurring jobs | Event-driven task planner integration, retries, job state introspection | P1 |
| `app/core/botsignal.py` | Platform-agnostic outgoing message layer | Message policy, delivery receipts, retry queue, escalation routing | P1 |
| `app/minichat/minichat.py` | Fast reflex responses for time, OS, server, internet | Intent learning, user preferences, richer command catalog | P2 |
| `app/voice/pipeline.py` | Wake word, VAD, STT, TTS, local pipeline | Voice personalization, wake-word tuning per user, command confirmation loop | P1 |
| `app/voice/transcribe.py` | Low-resource STT with Whisper tiny + Vosk fallback | Speaker diarization, language detection policy, confidence-based routing | P2 |
| `app/voice/tts.py` | Low-compute cloud TTS path | Offline fallback TTS, voice profiles, style control | P2 |
| `app/telegram/*` | Telegram receive/send, voice notes, rich formatting | Message threading policy, action confirmations, proactive push rules | P1 |
| `app/discord/*` | Discord text/audio ingestion, rich output, reply threading | Message content fallback for privileged intent-disabled mode | P1 |
| `app/slack/*` | Slack Socket Mode, file upload, threaded replies | Message summarization, action approval UI, channel policy controls | P1 |
| `app/whatsapp/*` | WhatsApp bridge integration | Authentication, message receipts, media handling, retry policy | P2 |
| `app/web/server.py` | Web chat UI, sessions, metrics, camera alert endpoint | Auth, role separation, audit views, task dashboard | P1 |
| `app/tools/*` | Large tool ecosystem across files, web, finance, calendar, smart home, security, media | Standard tool metadata, tool cost tiering, validation and dry-run mode | P1 |
| `app/agents/*` | Specialist roles, swarm execution, enhanced prompts | Shared policy layer, agent capability registry, memory scoping per agent | P1 |
| `monitoring/main.py` | Multi-camera ingest, YOLO, tracking, ReID, anomaly detection, alerts, semantic search, P2P IoT | Secure config, model fallback strategy, event schema standardization | P0 |
| `monitoring/src/anomaly.py` | Event detection across loitering, static object, baggage, weapon, restricted entry, pet escape | Real calibration, per-zone policies, score explainability, better post-processing | P1 |
| `monitoring/src/vision_analytics.py` | Heatmap, counter, blur, speed overlay, workout placeholder | Real pose analytics, privacy masks, active-tool budget control | P2 |
| `monitoring/src/semantic_search.py` | Local ONNX image embedding index | Stronger embeddings, incremental index maintenance, query fusion | P2 |
| `monitoring/src/risk_analysis.py` | Suspicion scoring and alert escalation | Policy-based severity, context-aware confidence, audit trail | P1 |
| `monitoring/src/storage.py` | Clip recording, metadata, retention cleanup | Event-based clip triggers, storage quotas, upload/export workflows | P2 |
| `monitoring/src/p2p.py` | UDP peer discovery, IoT bridge, identity sharing, graph sync | Authenticated transport, encryption, retries, topology control | P1 |
| `monitoring/src/message_bus.py` | Redis pub/sub microservice bus | Secret management, message durability, auth, backpressure | P0 |
| `monitoring/src/reid.py` | Face identity matching and Neo4j sync | Better calibration, privacy controls, confidence explanation | P1 |
| `monitoring/src/detection.py` | YOLO detection with optional GPU use | Dynamic model selection, adaptive frame skipping, detector benchmarking | P1 |
| `monitoring/src/tracker.py` | ByteTrack-style tracking with optional ReID | Health metrics, track lifecycle analytics, per-camera tuning | P2 |

## Low-Compute Architecture Roadmap

### Core Principle
Use the cheapest reliable compute path for each job.

### Runtime Layers
1. Edge reflex layer
- Rules, cache, command parsing, and tiny intent routing.
- Handles greetings, status, small calculations, and safe canned operations.

2. Small-model layer
- Low-cost local or cheap remote models for classification, summarization, extraction, and simple tool selection.
- Should handle most everyday requests.

3. Heavy reasoning layer
- Only for complex planning, deep research, code changes, and long-form synthesis.
- Must be invoked explicitly by the router.

4. Tool execution layer
- Tools run with strict permissions, dry-run support, and output validation.
- Long jobs should run in background workers.

5. Memory layer
- Store facts, preferences, and summaries separately.
- Compress aggressively and retrieve only what matters.

### Compute-Saving Rules
- Never send raw long history when a summary will do.
- Never use a heavy model for a task that can be solved by routing or a tool.
- Cache tool outputs that are deterministic or slow-changing.
- Skip vision and tracking work when no relevant event is active.
- Use adaptive frame skipping in monitoring.
- Prefer event-driven triggers over constant polling.
- Use lazy imports for all heavy dependencies.
- Use streaming only when it improves perceived latency.

### Suggested Model Routing Policy
- Tiny local model: intent detection, safety classification, summary drafting, next-step suggestion.
- Small local/cheap cloud model: general Q&A, tool selection, simple writing, code review summaries.
- Medium model: planning, tool-heavy reasoning, multi-step workflows.
- Large model: only when quality matters more than cost.

### Suggested Execution Flow
1. Receive message.
2. Run safety and permission checks.
3. Check cache and reflex rules.
4. Route to small model if needed.
5. Expand to planner only if multi-step.
6. Execute tool calls with validation.
7. Summarize results.
8. Store compressed memory.
9. Emit audit and telemetry.

### Monitoring Compute Strategy
- Lower camera resolution during idle periods.
- Increase frame skip when CPU or RAM crosses thresholds.
- Disable ReID and pose models when not needed.
- Run detection only on selected cameras or zones.
- Keep clip generation event-driven.
- Push alerts only when risk crosses a threshold.

## Execution Order
1. Security and config fixes.
2. Model router and action policy.
3. Memory summarization and user profiles.
4. Planner/executor with verification.
5. Proactive routines and cross-platform continuity.
6. Monitoring hardening and event standardization.
7. Evaluation, dashboards, and optimization.

## Next Roadmap

### Phase 6: Personal Workspace Graph
- Add a graph model for people, projects, tasks, files, decisions, devices, and relations.
- Sync graph nodes from memory, tools, scheduler, and assistants.
- Make graph queries available to prompts as concise evidence.
- Add a graph browser in the dashboard.

### Phase 7: Evidence-Backed Answers
- Attach source lineage to major answers: memory, file, tool, web, or graph.
- Add citations and confidence hints to final replies.
- Require source-backed summaries for important tasks and facts.
- Expose evidence trails in the dashboard and eval output.

### Phase 8: Task Inbox And Long-Horizon State
- Add a unified action inbox for pending approvals, reminders, suggestions, and unresolved tasks.
- Track goals, subtasks, dependencies, deadlines, and follow-up state.
- Keep tasks alive across platforms until resolved.
- Auto-promote unfinished items into reminders or follow-ups.

### Phase 9: Workflow Building
- Add user-defined macros and automations.
- Support rules like "when X happens, do Y" with dry-run previews.
- Let workflows trigger from events, schedules, and monitoring alerts.
- Store workflow versions and execution history.

### Phase 10: Memory Governance
- Add freshness scoring, expiry, and conflict resolution for memories.
- Let users edit, delete, and pin learned preferences.
- Separate facts, preferences, rules, and noisy transient context.
- Add memory audit views in the dashboard.

### Phase 11: Feedback Learning
- Add thumbs up/down and correction capture.
- Store "never do this again" preferences and safety exclusions.
- Feed feedback into profile memory and routing policy.
- Track feedback-driven regression improvements over time.

### Phase 12: Broader Integrations
- Expand email, calendar, docs, notes, contacts, browser history, and file sync.
- Normalize external data into the graph and task inbox.
- Keep all integrations optional and lazy-loaded.
- Prefer event-driven sync over polling.

### Phase 13: Offline And Degraded Modes
- Add local fallback for core chat, memory lookup, and simple actions.
- Keep voice and chat usable when network or provider access is limited.
- Make monitoring emit compact local summaries even when disconnected.
- Record degraded-mode events for later sync.

### Phase 14: Benchmarking And Drift Control
- Schedule regression runs for prompts, connectors, tools, and policies.
- Track model usage, latency, memory growth, and hallucination regressions.
- Gate changes on benchmark stability.
- Show trend lines in the dashboard.

### Phase 15: OpenClaw Parity And Presence Layer
- Add a versioned skill/plugin registry with manifests, health checks, and trust tiers.
- Normalize channel behavior, confirmations, and identity across chat, voice, and web.
- Add a central operator UI for tasks, memory, forecasts, conversations, and module state.
- Add interactive assistant surfaces: cards, canvases, and long-running task views.
- Split the assistant into a central brain plus lightweight edge companions for always-on presence.
- Treat onboarding and companion presence as product features, not just backend capabilities.

### UX Remediation Plan
- See `plan/05-ux-gap-remediation-plan.md` for the user-facing implementation order.
- Use it as the design source for command center, onboarding, presence, safety, and audit UX.

## Bottom Line
SARAS already has strong breadth. The next step is not adding random features, but tightening the architecture so every action is cheaper, safer, and more intentional.

## Bottom Line
SARAS already has the skeleton of a serious assistant platform. To feel like Friday or Jarvis, it needs less "more tools" and more "better orchestration, memory, safety, and proactive behavior."
