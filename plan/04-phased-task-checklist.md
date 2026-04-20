# 04 - Phased Implementation Checklist with Exact Files to Create / Modify

**Project:** SARAS  
**Purpose:** Turn the master plan into an execution-ready checklist with exact files and folders to create or modify.  
**Scope:** Low-compute, modular, JARVIS / FRIDAY-class SARAS roadmap  
**Date:** 2026-03-29

---

## 0. How to Use This Document

This document is intentionally practical.

Each phase includes:

- **goal**
- **why it matters**
- **deliverables**
- **exact files to create**
- **exact files to modify**
- **checklist**
- **exit criteria**

Legend:

- `[CREATE]` = create a new file
- `[MODIFY]` = update an existing file
- `[REVIEW]` = inspect and refactor where needed
- `[OPTIONAL]` = useful but not required for the phase to complete

---

# Phase 0 — Stabilize the Current System

## Goal
Before building the future architecture, stabilize and clean the current SARAS runtime so the next phases are built on something trustworthy.

## Why this phase matters
A JARVIS-like system becomes frustrating if the existing runtime is inconsistent, partially wired, or difficult to inspect.

## Key outcomes
- startup behavior is consistent
- current integrations are validated
- memory/tool registration gaps are fixed
- web/dashboard rough edges are reduced
- long-running jobs stop blocking interactive use

---

## Files to Create

### Core operational cleanup
- `[CREATE] SARAS/plan/05-runtime-validation-checklist.md`
- `[CREATE] SARAS/app/core/background_jobs.py`
- `[CREATE] SARAS/app/core/task_models.py`

### Diagnostics / visibility
- `[CREATE] SARAS/app/core/trace.py`
- `[CREATE] SARAS/app/core/health.py`

---

## Files to Modify

### Startup and orchestration
- `[MODIFY] SARAS/main.py`
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/core/runtime.py`
- `[MODIFY] SARAS/app/core/__init__.py`

### Current memory and session consistency
- `[MODIFY] SARAS/app/core/memory.py`
- `[MODIFY] SARAS/app/core/session.py`
- `[MODIFY] SARAS/app/tools/memorytool.py`

### Connector cleanup
- `[MODIFY] SARAS/app/telegram/bot.py`
- `[MODIFY] SARAS/app/telegram/command.py`
- `[MODIFY] SARAS/app/discord/discordapp.py`
- `[MODIFY] SARAS/app/slack/slackapp.py`
- `[MODIFY] SARAS/app/whatsapp/whatsappapp.py`
- `[MODIFY] SARAS/app/web/server.py`

### Settings / validation
- `[MODIFY] SARAS/app/settings/config.py`
- `[MODIFY] SARAS/app/settings/validate.py`

---

## Phase 0 Checklist

### Runtime cleanup
- [ ] Create background job manager for long-running tasks
- [ ] Add generic task model for async jobs
- [ ] Ensure long tasks can run without blocking core chat loop
- [ ] Add basic trace IDs through orchestrator/runtime flow
- [ ] Add system-wide health/status helpers

### Memory cleanup
- [ ] Verify `MemoryTool` is registered in the main tool runtime
- [ ] Fix or redesign missing methods expected by web endpoints
- [ ] Separate session history from semantic memory responsibilities
- [ ] Ensure memory retrieval and memory writing are both production-safe

### Connector cleanup
- [ ] Make startup behavior consistent for Telegram / Discord / Slack / WhatsApp / Web / MQTT / Voice
- [ ] Ensure optional connectors fail gracefully when not configured
- [ ] Add connector health reporting
- [ ] Standardize sender registration and error handling

### Web cleanup
- [ ] Fix session APIs so they return real data
- [ ] Add clean status endpoint for all active modules/connectors
- [ ] Ensure web UI can inspect active jobs and health state

---

## Exit Criteria
- interactive requests are non-blocking
- startup is deterministic
- connector health can be inspected
- memory interfaces are not half-implemented
- current system is stable enough to modularize

---

# Phase 1 — Build the Modular Kernel

## Goal
Create a real module system that every major SARAS subsystem can plug into.

## Why this phase matters
This is the foundation for extensibility, low-compute routing, policy, observability, UI composition, and future prediction modules.

## Key outcomes
- module lifecycle exists
- modules declare capabilities and dependencies
- modules can emit/consume standard events
- runtime can discover and manage modules centrally

---

## Files to Create

### Kernel
- `[CREATE] SARAS/app/kernel/__init__.py`
- `[CREATE] SARAS/app/kernel/base.py`
- `[CREATE] SARAS/app/kernel/manifest.py`
- `[CREATE] SARAS/app/kernel/registry.py`
- `[CREATE] SARAS/app/kernel/loader.py`
- `[CREATE] SARAS/app/kernel/lifecycle.py`
- `[CREATE] SARAS/app/kernel/capabilities.py`
- `[CREATE] SARAS/app/kernel/resource_governor.py`

### Event system
- `[CREATE] SARAS/app/events/__init__.py`
- `[CREATE] SARAS/app/events/types.py`
- `[CREATE] SARAS/app/events/schema.py`
- `[CREATE] SARAS/app/events/bus.py`
- `[CREATE] SARAS/app/events/router.py`

### Module manifests
- `[CREATE] SARAS/app/modules/__init__.py`
- `[CREATE] SARAS/app/modules/manifests/telegram.yaml`
- `[CREATE] SARAS/app/modules/manifests/discord.yaml`
- `[CREATE] SARAS/app/modules/manifests/slack.yaml`
- `[CREATE] SARAS/app/modules/manifests/whatsapp.yaml`
- `[CREATE] SARAS/app/modules/manifests/web.yaml`
- `[CREATE] SARAS/app/modules/manifests/voice.yaml`
- `[CREATE] SARAS/app/modules/manifests/memory.yaml`
- `[CREATE] SARAS/app/modules/manifests/runtime.yaml`

### Plan docs
- `[CREATE] SARAS/plan/03-module-manifest-and-event-schema.md`

---

## Files to Modify

### Runtime integration
- `[MODIFY] SARAS/main.py`
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/core/runtime.py`
- `[MODIFY] SARAS/app/core/botsignal.py`

### Existing connectors as modules
- `[MODIFY] SARAS/app/telegram/bot.py`
- `[MODIFY] SARAS/app/discord/discordapp.py`
- `[MODIFY] SARAS/app/slack/slackapp.py`
- `[MODIFY] SARAS/app/whatsapp/whatsappapp.py`
- `[MODIFY] SARAS/app/web/server.py`
- `[MODIFY] SARAS/app/voice/pipeline.py`

---

## Phase 1 Checklist

### Kernel
- [ ] Define base module contract
- [ ] Define module lifecycle states
- [ ] Define module manifest schema
- [ ] Create module registry
- [ ] Create capability registry
- [ ] Create resource governor
- [ ] Create module loader

### Event model
- [ ] Define standard event envelope
- [ ] Define event types
- [ ] Implement event bus
- [ ] Implement event routing rules
- [ ] Add trace IDs and source module metadata

### Connector registration
- [ ] Wrap major connectors as modules
- [ ] Register core memory/runtime/voice subsystems as modules
- [ ] Expose connector capabilities to the registry

---

## Exit Criteria
- every major subsystem can be represented as a module
- modules can be discovered/loaded centrally
- module manifests are validated
- event bus exists and is usable by core runtime

---

# Phase 2 — Build Policy, Permissions, and Audit

## Goal
Create the safety/control layer inspired by stronger NeMo/enterprise patterns, but adapted for a personal assistant.

## Why this phase matters
A powerful assistant that can message, browse, control devices, and run tools must be governed.

## Key outcomes
- explicit permission model
- action risk classification
- approvals for dangerous actions
- durable audit trail

---

## Files to Create

### Policy engine
- `[CREATE] SARAS/app/policy/__init__.py`
- `[CREATE] SARAS/app/policy/models.py`
- `[CREATE] SARAS/app/policy/rules.py`
- `[CREATE] SARAS/app/policy/engine.py`
- `[CREATE] SARAS/app/policy/permissions.py`
- `[CREATE] SARAS/app/policy/approvals.py`

### Audit and trust
- `[CREATE] SARAS/app/audit/__init__.py`
- `[CREATE] SARAS/app/audit/models.py`
- `[CREATE] SARAS/app/audit/store.py`
- `[CREATE] SARAS/app/audit/trail.py`
- `[CREATE] SARAS/app/audit/explainer.py`

### Safety docs/config
- `[CREATE] SARAS/app/modules/manifests/policy.yaml`
- `[CREATE] SARAS/app/modules/manifests/audit.yaml`
- `[CREATE] SARAS/app/settings/policy_defaults.py`

---

## Files to Modify

### Existing security and runtime
- `[MODIFY] SARAS/app/core/security.py`
- `[MODIFY] SARAS/app/core/runtime.py`
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/tools/base.py`

### High-risk tools
- `[MODIFY] SARAS/app/tools/exectool.py`
- `[MODIFY] SARAS/app/tools/filetool.py`
- `[MODIFY] SARAS/app/tools/gittool.py`
- `[MODIFY] SARAS/app/tools/browsertool.py`
- `[MODIFY] SARAS/app/tools/messagingtool.py`
- `[MODIFY] SARAS/app/tools/smarthometool.py`

### Web/UI exposure
- `[MODIFY] SARAS/app/web/server.py`

---

## Phase 2 Checklist

### Permissions
- [ ] Define permission classes
- [ ] Define risk levels for tools/actions
- [ ] Map tools to required permissions
- [ ] Add deny-by-default handling for dangerous actions

### Approvals
- [ ] Add approval request data model
- [ ] Add approval endpoints/UI hooks
- [ ] Add approval state transitions
- [ ] Require approvals for high-risk actions

### Audit
- [ ] Persist structured audit records
- [ ] Store action summaries and results
- [ ] Attach trace IDs to audits
- [ ] Add explainable action summaries

---

## Exit Criteria
- dangerous actions are governed
- all important tool actions are auditable
- approval flow exists
- permissions are explicit, not implicit

---

# Phase 3 — Build PersonalityCore

## Goal
Create a real personality system so SARAS feels like one coherent being across text, voice, alerts, and UI.

## Why this phase matters
JARVIS/FRIDAY-like feel is impossible if personality only lives in an unstructured system prompt.

## Key outcomes
- stable identity model
- tone selection logic
- mode switching
- voice/text alignment
- personality-aware UI states

---

## Files to Create

### Personality core
- `[CREATE] SARAS/app/personality/__init__.py`
- `[CREATE] SARAS/app/personality/models.py`
- `[CREATE] SARAS/app/personality/core.py`
- `[CREATE] SARAS/app/personality/tone.py`
- `[CREATE] SARAS/app/personality/modes.py`
- `[CREATE] SARAS/app/personality/relationship.py`
- `[CREATE] SARAS/app/personality/render.py`
- `[CREATE] SARAS/app/personality/voice_profile.py`

### Persona config
- `[CREATE] SARAS/app/personality/profiles/default.yaml`
- `[CREATE] SARAS/app/personality/profiles/jarvis.yaml`
- `[CREATE] SARAS/app/personality/profiles/friday.yaml`

### UI state hooks
- `[CREATE] SARAS/app/presence/__init__.py`
- `[CREATE] SARAS/app/presence/state.py`

---

## Files to Modify

### Prompt/bootstrap flow
- `[MODIFY] SARAS/app/core/bootstrapper.py`
- `[MODIFY] SARAS/app/core/runtime.py`
- `[MODIFY] SARAS/app/core/orchestrator.py`

### Voice and rendering
- `[MODIFY] SARAS/app/core/render.py`
- `[MODIFY] SARAS/app/telegram/bot.py`
- `[MODIFY] SARAS/app/voice/pipeline.py`

### Config
- `[MODIFY] SARAS/app/settings/config.py`

---

## Phase 3 Checklist

### Personality model
- [ ] Define identity model
- [ ] Define mode model
- [ ] Define tone dimensions
- [ ] Define relationship memory hooks
- [ ] Define voice persona mapping

### Runtime integration
- [ ] Select tone/mode per request
- [ ] Inject personality state into prompt building
- [ ] Control response length by channel and modality
- [ ] Add special handling for voice brevity and alerts

### Presence
- [ ] Add public state model: listening / thinking / briefing / alert / companion / analyst
- [ ] Expose state to dashboard/web UI

---

## Exit Criteria
- SARAS speaks consistently across modalities
- personality can be changed/configured without rewriting runtime
- UI can reflect current personality mode/state

---

# Phase 4 — Build UserModel, Episodic Memory, and Project Memory

## Goal
Upgrade memory from “retrieved facts” to a real long-term personal intelligence memory.

## Why this phase matters
A personal assistant becomes magical when it understands the user over time, not just the current chat.

## Key outcomes
- structured user model
- episodic memory
- project memory
- prediction memory foundation
- memory quality rules

---

## Files to Create

### Advanced memory
- `[CREATE] SARAS/app/memory/__init__.py`
- `[CREATE] SARAS/app/memory/models.py`
- `[CREATE] SARAS/app/memory/user_model.py`
- `[CREATE] SARAS/app/memory/episodic.py`
- `[CREATE] SARAS/app/memory/project.py`
- `[CREATE] SARAS/app/memory/prediction_history.py`
- `[CREATE] SARAS/app/memory/hygiene.py`
- `[CREATE] SARAS/app/memory/scoring.py`
- `[CREATE] SARAS/app/memory/summarizer.py`

### DB models
- `[CREATE] SARAS/app/db/migrations/` 
- `[CREATE] SARAS/app/db/migrations/README.md`

---

## Files to Modify

### Existing memory layer
- `[MODIFY] SARAS/app/core/memory.py`
- `[MODIFY] SARAS/app/core/session.py`
- `[MODIFY] SARAS/app/tools/memorytool.py`
- `[MODIFY] SARAS/app/db/models.py`
- `[MODIFY] SARAS/app/db/session.py`

### Bootstrap/context
- `[MODIFY] SARAS/app/core/bootstrapper.py`

### Web/dashboard
- `[MODIFY] SARAS/app/web/server.py`

---

## Phase 4 Checklist

### User model
- [ ] Add user preferences storage
- [ ] Add communication preferences
- [ ] Add routine preferences
- [ ] Add relationship metadata

### Episodic memory
- [ ] Store meaningful events with timestamps
- [ ] Store context and participants
- [ ] Retrieve by recency + relevance

### Project memory
- [ ] Track goals, blockers, milestones, decisions
- [ ] Link project memories to users and tasks

### Hygiene
- [ ] Add importance scoring
- [ ] Add contradiction detection
- [ ] Add stale memory management
- [ ] Add summarization of old sessions

---

## Exit Criteria
- SARAS can remember user preferences structurally
- SARAS can recall meaningful past events
- ongoing projects survive across sessions
- memory growth is governed

---

# Phase 5 — Integrate AgentReach as the Internet Vision Layer

## Goal
Turn `agent_reach` into SARAS’s first-class internet perception subsystem.

## Why this phase matters
This is the “eyes on the internet” layer needed for research, briefings, and later prediction.

## Key outcomes
- source routing
- cross-source ingestion
- topic monitoring
- source health registry
- evidence normalization

---

## Files to Create

### Reach integration
- `[CREATE] SARAS/app/reach/__init__.py`
- `[CREATE] SARAS/app/reach/models.py`
- `[CREATE] SARAS/app/reach/adapter.py`
- `[CREATE] SARAS/app/reach/router.py`
- `[CREATE] SARAS/app/reach/doctor.py`
- `[CREATE] SARAS/app/reach/ingestion.py`
- `[CREATE] SARAS/app/reach/normalizer.py`
- `[CREATE] SARAS/app/reach/source_registry.py`
- `[CREATE] SARAS/app/reach/trust.py`
- `[CREATE] SARAS/app/reach/watchlists.py`

### Scheduler/jobs
- `[CREATE] SARAS/app/routines/internet_watch.py`

### Manifests
- `[CREATE] SARAS/app/modules/manifests/reach.yaml`

---

## Files to Modify

### Runtime integration
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/core/runtime.py`

### Existing web/search ecosystem
- `[MODIFY] SARAS/app/tools/websearch.py`
- `[MODIFY] SARAS/app/tools/webfetch.py`
- `[MODIFY] SARAS/app/tools/rssreadertool.py`
- `[MODIFY] SARAS/app/tools/reddittool.py`
- `[MODIFY] SARAS/app/tools/twittertool.py`
- `[MODIFY] SARAS/app/tools/youtube.py`

### Dashboard/web
- `[MODIFY] SARAS/app/web/server.py`
- `[MODIFY] SARAS/app/dashboard/dashboard.py`

---

## Phase 5 Checklist

### Integration
- [ ] Wrap AgentReach access behind SARAS adapter
- [ ] Add source registry and channel health model
- [ ] Normalize evidence into a common schema
- [ ] Add watchlists for users/projects/topics

### Ingestion
- [ ] Feed normalized evidence into memory
- [ ] Feed extracted entities into graph/world model foundation
- [ ] Add scheduled topic monitoring jobs

### UI
- [ ] Show internet/source health
- [ ] Show watched topics/entities
- [ ] Show latest collected evidence

---

## Exit Criteria
- SARAS can gather internet information in a structured, repeatable way
- source health and trust are visible
- internet evidence feeds later cognitive layers

---

# Phase 6 — Build ExecutiveLoop, Goal Manager, and Opportunity Engine

## Goal
Move SARAS from reactive assistant to proactive operator.

## Why this phase matters
This is where SARAS starts to feel like it is actively helping manage life, work, and risk.

## Key outcomes
- goals
- plans
- blockers
- briefings
- proactive recommendations
- ongoing tasks

---

## Files to Create

### Planning and autonomy
- `[CREATE] SARAS/app/executive/__init__.py`
- `[CREATE] SARAS/app/executive/models.py`
- `[CREATE] SARAS/app/executive/goals.py`
- `[CREATE] SARAS/app/executive/planner.py`
- `[CREATE] SARAS/app/executive/blockers.py`
- `[CREATE] SARAS/app/executive/opportunities.py`
- `[CREATE] SARAS/app/executive/briefing.py`
- `[CREATE] SARAS/app/executive/loop.py`

### Routines
- `[CREATE] SARAS/app/routines/daily_planning.py`
- `[CREATE] SARAS/app/routines/nightly_summary.py`

---

## Files to Modify

### Scheduler
- `[MODIFY] SARAS/app/core/scheduler.py`
- `[MODIFY] SARAS/app/tools/remindertool.py`

### Runtime/orchestrator
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/core/runtime.py`

### Existing routines
- `[MODIFY] SARAS/app/routines/morning_briefing.py`

### UI/web
- `[MODIFY] SARAS/app/web/server.py`
- `[MODIFY] SARAS/app/dashboard/dashboard.py`

---

## Phase 6 Checklist

### Goals/planning
- [ ] Add goal model
- [ ] Add milestone and blocker tracking
- [ ] Add task/project state machine
- [ ] Add user-visible plan summaries

### Executive loop
- [ ] Add daily briefing generation
- [ ] Add risk/opportunity detection
- [ ] Add “next best action” logic
- [ ] Add bounded proactive messaging policy

### UI
- [ ] Show active goals
- [ ] Show blockers and opportunities
- [ ] Show current executive recommendations

---

## Exit Criteria
- SARAS can manage ongoing goals
- SARAS can proactively suggest useful actions
- briefings and project updates become first-class outputs

---

# Phase 7 — Build Prediction Engine v1 (Low-Compute Forecasting)

## Goal
Introduce structured prediction with real data, while staying cheap and explainable.

## Why this phase matters
This is the MiroFish-inspired layer, but starting practically.

## Key outcomes
- event graph
- simple forecasting
- causal/risk rules
- confidence output
- prediction history

---

## Files to Create

### Forecast subsystem
- `[CREATE] SARAS/app/forecast/__init__.py`
- `[CREATE] SARAS/app/forecast/models.py`
- `[CREATE] SARAS/app/forecast/engine.py`
- `[CREATE] SARAS/app/forecast/signals.py`
- `[CREATE] SARAS/app/forecast/events.py`
- `[CREATE] SARAS/app/forecast/scenarios.py`
- `[CREATE] SARAS/app/forecast/causal.py`
- `[CREATE] SARAS/app/forecast/statistics.py`
- `[CREATE] SARAS/app/forecast/confidence.py`
- `[CREATE] SARAS/app/forecast/explainer.py`
- `[CREATE] SARAS/app/forecast/backtesting.py`

### World model foundation
- `[CREATE] SARAS/app/world/__init__.py`
- `[CREATE] SARAS/app/world/entities.py`
- `[CREATE] SARAS/app/world/event_graph.py`
- `[CREATE] SARAS/app/world/claims.py`

### Manifests
- `[CREATE] SARAS/app/modules/manifests/forecast.yaml`
- `[CREATE] SARAS/app/modules/manifests/world.yaml`

---

## Files to Modify

### Memory integration
- `[MODIFY] SARAS/app/memory/prediction_history.py`
- `[MODIFY] SARAS/app/core/bootstrapper.py`

### Reach and sensors
- `[MODIFY] SARAS/app/reach/ingestion.py`
- `[MODIFY] SARAS/app/sensors/mqtt_listener.py`
- `[MODIFY] SARAS/app/sensors/webhook_server.py`

### Runtime/orchestrator
- `[MODIFY] SARAS/app/core/orchestrator.py`
- `[MODIFY] SARAS/app/core/runtime.py`

### UI/web
- `[MODIFY] SARAS/app/web/server.py`
- `[MODIFY] SARAS/app/dashboard/dashboard.py`

---

## Phase 7 Checklist

### Core forecasting
- [ ] Define forecast request/response schema
- [ ] Build event graph foundation
- [ ] Extract signals from memory/reach/sensors
- [ ] Build simple statistical forecasting layer
- [ ] Build causal/risk rule engine
- [ ] Add confidence scoring

### Explainability
- [ ] Explain evidence used
- [ ] Explain assumptions
- [ ] Explain confidence
- [ ] Expose “what to watch next”

### History/backtesting
- [ ] Save predictions
- [ ] Save later outcomes
- [ ] Compare prediction vs actual
- [ ] Track calibration over time

---

## Exit Criteria
- SARAS can generate useful, evidence-grounded low-compute forecasts
- each forecast includes confidence and rationale
- predictions are stored and can be evaluated later

---

# Phase 8 — Build Prediction Engine v2 (Selective Micro-Simulation)

## Goal
Add bounded multi-agent simulation for high-value uncertain scenarios.

## Why this phase matters
This is how SARAS gains a stronger “foresight” layer without forcing huge compute all the time.

## Key outcomes
- small stakeholder simulation
- branching scenarios
- simulation-backed forecasts
- selective invocation only

---

## Files to Create

### Simulation subsystem
- `[CREATE] SARAS/app/simulation/__init__.py`
- `[CREATE] SARAS/app/simulation/models.py`
- `[CREATE] SARAS/app/simulation/engine.py`
- `[CREATE] SARAS/app/simulation/actors.py`
- `[CREATE] SARAS/app/simulation/personas.py`
- `[CREATE] SARAS/app/simulation/rounds.py`
- `[CREATE] SARAS/app/simulation/outcomes.py`
- `[CREATE] SARAS/app/simulation/selective_router.py`

### Manifests
- `[CREATE] SARAS/app/modules/manifests/simulation.yaml`

---

## Files to Modify

### Forecast subsystem
- `[MODIFY] SARAS/app/forecast/engine.py`
- `[MODIFY] SARAS/app/forecast/scenarios.py`
- `[MODIFY] SARAS/app/forecast/confidence.py`

### World model
- `[MODIFY] SARAS/app/world/event_graph.py`
- `[MODIFY] SARAS/app/world/entities.py`

### Swarm/advisory layer
- `[MODIFY] SARAS/app/core/agency.py`
- `[MODIFY] SARAS/app/core/orchestrator.py`

### UI
- `[MODIFY] SARAS/app/web/server.py`
- `[MODIFY] SARAS/app/dashboard/dashboard.py`

---

## Phase 8 Checklist

### Simulation
- [ ] Define stakeholder/actor schema
- [ ] Define bounded simulation rounds
- [ ] Generate baseline/optimistic/pessimistic scenarios
- [ ] Aggregate simulation outcomes into forecast reports

### Cost governance
- [ ] Add selective routing so heavy simulation is not default
- [ ] Gate simulation behind confidence/complexity thresholds
- [ ] Support user opt-in for expensive forecast mode

### UX
- [ ] Show simulated scenarios
- [ ] Show why simulation was invoked
- [ ] Show disagreement/uncertainty

---

## Exit Criteria
- SARAS can run small-scale scenario simulations
- simulation is bounded and explainable
- heavy reasoning remains optional

---

# Phase 9 — Build Command Center UI and Presence Layer

## Goal
Create the visible JARVIS/FRIDAY-style interface.

## Why this phase matters
The assistant must feel alive and inspectable, not hidden behind plain chat.

## Key outcomes
- command center
- live activity state
- memory pane
- forecast pane
- module pane
- voice visualization
- personality expression

---

## Files to Create

### Frontend structure
- `[CREATE] SARAS/app/web/static/command-center.html`
- `[CREATE] SARAS/app/web/static/command-center.css`
- `[CREATE] SARAS/app/web/static/command-center.js`
- `[CREATE] SARAS/app/web/static/components/`
- `[CREATE] SARAS/app/web/static/components/README.md`

### Presence widgets
- `[CREATE] SARAS/app/presence/widgets.py`
- `[CREATE] SARAS/app/presence/panels.py`

### Dashboard expansion
- `[CREATE] SARAS/app/dashboard/pages/01_command_center.py`
- `[CREATE] SARAS/app/dashboard/pages/02_predictions.py`
- `[CREATE] SARAS/app/dashboard/pages/03_memory.py`
- `[CREATE] SARAS/app/dashboard/pages/04_modules.py`

---

## Files to Modify

### Web server
- `[MODIFY] SARAS/app/web/server.py`

### Dashboard
- `[MODIFY] SARAS/app/dashboard/dashboard.py`
- `[MODIFY] SARAS/app/dashboard/utils.py`

### Presence/personality
- `[MODIFY] SARAS/app/presence/state.py`
- `[MODIFY] SARAS/app/personality/render.py`

### Voice integration
- `[MODIFY] SARAS/app/voice/pipeline.py`

---

## Phase 9 Checklist

### Core UI
- [ ] Create companion view
- [ ] Create operations view
- [ ] Create intelligence/forecast view
- [ ] Create memory view
- [ ] Create module health view

### Presence
- [ ] Show listening / thinking / speaking state
- [ ] Show active tasks
- [ ] Show current briefing mode
- [ ] Show current personality mode
- [ ] Show current predictions and alerts

### Inspectability
- [ ] Show traces
- [ ] Show audits
- [ ] Show module capability state
- [ ] Show source health
- [ ] Show prediction explanations

---

## Exit Criteria
- SARAS has a coherent “presence”
- users can inspect what SARAS is doing
- UI feels like a personal intelligence console

---

# Phase 10 — Build Edge / Low-Compute Distributed Mode

## Goal
Make SARAS usable as a distributed low-cost intelligence system.

## Why this phase matters
This is how SARAS becomes always-on without requiring a powerful central box for everything.

## Key outcomes
- edge nodes
- cheap watcher architecture
- remote worker support
- degraded-mode execution

---

## Files to Create

### Edge runtime
- `[CREATE] SARAS/app/edge/__init__.py`
- `[CREATE] SARAS/app/edge/models.py`
- `[CREATE] SARAS/app/edge/protocol.py`
- `[CREATE] SARAS/app/edge/registry.py`
- `[CREATE] SARAS/app/edge/router.py`
- `[CREATE] SARAS/app/edge/worker.py`

### Deployment docs
- `[CREATE] SARAS/docs/12-edge-runtime-plan.md`

### Optional external worker notes
- `[CREATE] SARAS/infra/edge/README.md`

---

## Files to Modify

### Kernel/resource governance
- `[MODIFY] SARAS/app/kernel/resource_governor.py`
- `[MODIFY] SARAS/app/kernel/capabilities.py`

### Voice/sensors/reach/forecast
- `[MODIFY] SARAS/app/voice/pipeline.py`
- `[MODIFY] SARAS/app/sensors/mqtt_listener.py`
- `[MODIFY] SARAS/app/reach/router.py`
- `[MODIFY] SARAS/app/forecast/engine.py`

### Config
- `[MODIFY] SARAS/app/settings/config.py`

---

## Phase 10 Checklist

### Edge support
- [ ] Define edge worker protocol
- [ ] Register edge workers centrally
- [ ] Route cheap/continuous work to edge where possible
- [ ] Support degraded operation if central resources are limited

### Low-compute routing
- [ ] Prefer cache/rules/small local paths first
- [ ] Route high-cost jobs only when necessary
- [ ] Expose resource and routing decisions in UI

---

## Exit Criteria
- SARAS can run in low-compute distributed mode
- watcher/perception tasks can be offloaded
- system remains coherent under degraded resources

---

# Cross-Phase Shared Files Likely to Be Touched Often

These files will likely be modified across many phases:

## Core
- `SARAS/main.py`
- `SARAS/app/core/orchestrator.py`
- `SARAS/app/core/runtime.py`
- `SARAS/app/core/bootstrapper.py`
- `SARAS/app/core/botsignal.py`
- `SARAS/app/settings/config.py`

## Web/UI
- `SARAS/app/web/server.py`
- `SARAS/app/dashboard/dashboard.py`

## DB/Models
- `SARAS/app/db/models.py`
- `SARAS/app/db/session.py`

## Voice
- `SARAS/app/voice/pipeline.py`

## Memory
- `SARAS/app/core/memory.py`
- `SARAS/app/core/session.py`

---

# Recommended Execution Order

If implementation starts now, the best order is:

1. **Phase 0** — stabilize what already exists  
2. **Phase 1** — modular kernel  
3. **Phase 2** — policy, permissions, audit  
4. **Phase 3** — personality core  
5. **Phase 4** — advanced memory and user model  
6. **Phase 5** — AgentReach integration  
7. **Phase 6** — executive loop and proactive planning  
8. **Phase 7** — prediction engine v1  
9. **Phase 8** — prediction engine v2 micro-simulation  
10. **Phase 9** — command center UI  
11. **Phase 10** — edge / distributed low-compute mode

---

# Final Definition of Success

SARAS reaches the target standard when all of these are true:

- it is modular
- it is inspectable
- it is safe enough for real use
- it feels like one personality everywhere
- it remembers the user meaningfully
- it sees the internet through structured sources
- it plans and briefs proactively
- it predicts with evidence and confidence
- it presents itself through a strong interface
- it can degrade gracefully to low-compute environments

---

# Immediate Next Files to Write After This Checklist

The best next planning docs would be:

- `SARAS/plan/03-module-manifest-and-event-schema.md`
- `SARAS/plan/06-personality-core-spec.md`
- `SARAS/plan/07-prediction-engine-spec.md`
- `SARAS/plan/08-command-center-ui-spec.md`

These would convert the checklist into exact implementation contracts.

---