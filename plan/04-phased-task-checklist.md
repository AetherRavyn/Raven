# 04 - Phased Implementation Checklist with Exact Files to Create / Modify

**Project:** RAVEN  
**Purpose:** Turn the master plan into an execution-ready checklist with exact files and folders to create or modify.  
**Scope:** Low-compute, modular, JARVIS / FRIDAY-class RAVEN roadmap  
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
Before building the future architecture, stabilize and clean the current RAVEN runtime so the next phases are built on something trustworthy.

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
- `[CREATE] RAVEN/plan/05-runtime-validation-checklist.md`
- `[CREATE] RAVEN/app/core/background_jobs.py`
- `[CREATE] RAVEN/app/core/task_models.py`

### Diagnostics / visibility
- `[CREATE] RAVEN/app/core/trace.py`
- `[CREATE] RAVEN/app/core/health.py`

---

## Files to Modify

### Startup and orchestration
- `[MODIFY] RAVEN/main.py`
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/core/runtime.py`
- `[MODIFY] RAVEN/app/core/__init__.py`

### Current memory and session consistency
- `[MODIFY] RAVEN/app/core/memory.py`
- `[MODIFY] RAVEN/app/core/session.py`
- `[MODIFY] RAVEN/app/tools/memorytool.py`

### Connector cleanup
- `[MODIFY] RAVEN/app/telegram/bot.py`
- `[MODIFY] RAVEN/app/telegram/command.py`
- `[MODIFY] RAVEN/app/discord/discordapp.py`
- `[MODIFY] RAVEN/app/slack/slackapp.py`
- `[MODIFY] RAVEN/app/whatsapp/whatsappapp.py`
- `[MODIFY] RAVEN/app/web/server.py`

### Settings / validation
- `[MODIFY] RAVEN/app/settings/config.py`
- `[MODIFY] RAVEN/app/settings/validate.py`

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
Create a real module system that every major RAVEN subsystem can plug into.

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
- `[CREATE] RAVEN/app/kernel/__init__.py`
- `[CREATE] RAVEN/app/kernel/base.py`
- `[CREATE] RAVEN/app/kernel/manifest.py`
- `[CREATE] RAVEN/app/kernel/registry.py`
- `[CREATE] RAVEN/app/kernel/loader.py`
- `[CREATE] RAVEN/app/kernel/lifecycle.py`
- `[CREATE] RAVEN/app/kernel/capabilities.py`
- `[CREATE] RAVEN/app/kernel/resource_governor.py`

### Event system
- `[CREATE] RAVEN/app/events/__init__.py`
- `[CREATE] RAVEN/app/events/types.py`
- `[CREATE] RAVEN/app/events/schema.py`
- `[CREATE] RAVEN/app/events/bus.py`
- `[CREATE] RAVEN/app/events/router.py`

### Module manifests
- `[CREATE] RAVEN/app/modules/__init__.py`
- `[CREATE] RAVEN/app/modules/manifests/telegram.yaml`
- `[CREATE] RAVEN/app/modules/manifests/discord.yaml`
- `[CREATE] RAVEN/app/modules/manifests/slack.yaml`
- `[CREATE] RAVEN/app/modules/manifests/whatsapp.yaml`
- `[CREATE] RAVEN/app/modules/manifests/web.yaml`
- `[CREATE] RAVEN/app/modules/manifests/voice.yaml`
- `[CREATE] RAVEN/app/modules/manifests/memory.yaml`
- `[CREATE] RAVEN/app/modules/manifests/runtime.yaml`

### Plan docs
- `[CREATE] RAVEN/plan/03-module-manifest-and-event-schema.md`

---

## Files to Modify

### Runtime integration
- `[MODIFY] RAVEN/main.py`
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/core/runtime.py`
- `[MODIFY] RAVEN/app/core/botsignal.py`

### Existing connectors as modules
- `[MODIFY] RAVEN/app/telegram/bot.py`
- `[MODIFY] RAVEN/app/discord/discordapp.py`
- `[MODIFY] RAVEN/app/slack/slackapp.py`
- `[MODIFY] RAVEN/app/whatsapp/whatsappapp.py`
- `[MODIFY] RAVEN/app/web/server.py`
- `[MODIFY] RAVEN/app/voice/pipeline.py`

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
- `[CREATE] RAVEN/app/policy/__init__.py`
- `[CREATE] RAVEN/app/policy/models.py`
- `[CREATE] RAVEN/app/policy/rules.py`
- `[CREATE] RAVEN/app/policy/engine.py`
- `[CREATE] RAVEN/app/policy/permissions.py`
- `[CREATE] RAVEN/app/policy/approvals.py`

### Audit and trust
- `[CREATE] RAVEN/app/audit/__init__.py`
- `[CREATE] RAVEN/app/audit/models.py`
- `[CREATE] RAVEN/app/audit/store.py`
- `[CREATE] RAVEN/app/audit/trail.py`
- `[CREATE] RAVEN/app/audit/explainer.py`

### Safety docs/config
- `[CREATE] RAVEN/app/modules/manifests/policy.yaml`
- `[CREATE] RAVEN/app/modules/manifests/audit.yaml`
- `[CREATE] RAVEN/app/settings/policy_defaults.py`

---

## Files to Modify

### Existing security and runtime
- `[MODIFY] RAVEN/app/core/security.py`
- `[MODIFY] RAVEN/app/core/runtime.py`
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/tools/base.py`

### High-risk tools
- `[MODIFY] RAVEN/app/tools/exectool.py`
- `[MODIFY] RAVEN/app/tools/filetool.py`
- `[MODIFY] RAVEN/app/tools/gittool.py`
- `[MODIFY] RAVEN/app/tools/browsertool.py`
- `[MODIFY] RAVEN/app/tools/messagingtool.py`
- `[MODIFY] RAVEN/app/tools/smarthometool.py`

### Web/UI exposure
- `[MODIFY] RAVEN/app/web/server.py`

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
Create a real personality system so RAVEN feels like one coherent being across text, voice, alerts, and UI.

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
- `[CREATE] RAVEN/app/personality/__init__.py`
- `[CREATE] RAVEN/app/personality/models.py`
- `[CREATE] RAVEN/app/personality/core.py`
- `[CREATE] RAVEN/app/personality/tone.py`
- `[CREATE] RAVEN/app/personality/modes.py`
- `[CREATE] RAVEN/app/personality/relationship.py`
- `[CREATE] RAVEN/app/personality/render.py`
- `[CREATE] RAVEN/app/personality/voice_profile.py`

### Persona config
- `[CREATE] RAVEN/app/personality/profiles/default.yaml`
- `[CREATE] RAVEN/app/personality/profiles/jarvis.yaml`
- `[CREATE] RAVEN/app/personality/profiles/friday.yaml`

### UI state hooks
- `[CREATE] RAVEN/app/presence/__init__.py`
- `[CREATE] RAVEN/app/presence/state.py`

---

## Files to Modify

### Prompt/bootstrap flow
- `[MODIFY] RAVEN/app/core/bootstrapper.py`
- `[MODIFY] RAVEN/app/core/runtime.py`
- `[MODIFY] RAVEN/app/core/orchestrator.py`

### Voice and rendering
- `[MODIFY] RAVEN/app/core/render.py`
- `[MODIFY] RAVEN/app/telegram/bot.py`
- `[MODIFY] RAVEN/app/voice/pipeline.py`

### Config
- `[MODIFY] RAVEN/app/settings/config.py`

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
- RAVEN speaks consistently across modalities
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
- `[CREATE] RAVEN/app/memory/__init__.py`
- `[CREATE] RAVEN/app/memory/models.py`
- `[CREATE] RAVEN/app/memory/user_model.py`
- `[CREATE] RAVEN/app/memory/episodic.py`
- `[CREATE] RAVEN/app/memory/project.py`
- `[CREATE] RAVEN/app/memory/prediction_history.py`
- `[CREATE] RAVEN/app/memory/hygiene.py`
- `[CREATE] RAVEN/app/memory/scoring.py`
- `[CREATE] RAVEN/app/memory/summarizer.py`

### DB models
- `[CREATE] RAVEN/app/db/migrations/` 
- `[CREATE] RAVEN/app/db/migrations/README.md`

---

## Files to Modify

### Existing memory layer
- `[MODIFY] RAVEN/app/core/memory.py`
- `[MODIFY] RAVEN/app/core/session.py`
- `[MODIFY] RAVEN/app/tools/memorytool.py`
- `[MODIFY] RAVEN/app/db/models.py`
- `[MODIFY] RAVEN/app/db/session.py`

### Bootstrap/context
- `[MODIFY] RAVEN/app/core/bootstrapper.py`

### Web/dashboard
- `[MODIFY] RAVEN/app/web/server.py`

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
- RAVEN can remember user preferences structurally
- RAVEN can recall meaningful past events
- ongoing projects survive across sessions
- memory growth is governed

---

# Phase 5 — Integrate AgentReach as the Internet Vision Layer

## Goal
Turn `agent_reach` into RAVEN’s first-class internet perception subsystem.

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
- `[CREATE] RAVEN/app/reach/__init__.py`
- `[CREATE] RAVEN/app/reach/models.py`
- `[CREATE] RAVEN/app/reach/adapter.py`
- `[CREATE] RAVEN/app/reach/router.py`
- `[CREATE] RAVEN/app/reach/doctor.py`
- `[CREATE] RAVEN/app/reach/ingestion.py`
- `[CREATE] RAVEN/app/reach/normalizer.py`
- `[CREATE] RAVEN/app/reach/source_registry.py`
- `[CREATE] RAVEN/app/reach/trust.py`
- `[CREATE] RAVEN/app/reach/watchlists.py`

### Scheduler/jobs
- `[CREATE] RAVEN/app/routines/internet_watch.py`

### Manifests
- `[CREATE] RAVEN/app/modules/manifests/reach.yaml`

---

## Files to Modify

### Runtime integration
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/core/runtime.py`

### Existing web/search ecosystem
- `[MODIFY] RAVEN/app/tools/websearch.py`
- `[MODIFY] RAVEN/app/tools/webfetch.py`
- `[MODIFY] RAVEN/app/tools/rssreadertool.py`
- `[MODIFY] RAVEN/app/tools/reddittool.py`
- `[MODIFY] RAVEN/app/tools/twittertool.py`
- `[MODIFY] RAVEN/app/tools/youtube.py`

### Dashboard/web
- `[MODIFY] RAVEN/app/web/server.py`
- `[MODIFY] RAVEN/app/dashboard/dashboard.py`

---

## Phase 5 Checklist

### Integration
- [ ] Wrap AgentReach access behind RAVEN adapter
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
- RAVEN can gather internet information in a structured, repeatable way
- source health and trust are visible
- internet evidence feeds later cognitive layers

---

# Phase 6 — Build ExecutiveLoop, Goal Manager, and Opportunity Engine

## Goal
Move RAVEN from reactive assistant to proactive operator.

## Why this phase matters
This is where RAVEN starts to feel like it is actively helping manage life, work, and risk.

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
- `[CREATE] RAVEN/app/executive/__init__.py`
- `[CREATE] RAVEN/app/executive/models.py`
- `[CREATE] RAVEN/app/executive/goals.py`
- `[CREATE] RAVEN/app/executive/planner.py`
- `[CREATE] RAVEN/app/executive/blockers.py`
- `[CREATE] RAVEN/app/executive/opportunities.py`
- `[CREATE] RAVEN/app/executive/briefing.py`
- `[CREATE] RAVEN/app/executive/loop.py`

### Routines
- `[CREATE] RAVEN/app/routines/daily_planning.py`
- `[CREATE] RAVEN/app/routines/nightly_summary.py`

---

## Files to Modify

### Scheduler
- `[MODIFY] RAVEN/app/core/scheduler.py`
- `[MODIFY] RAVEN/app/tools/remindertool.py`

### Runtime/orchestrator
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/core/runtime.py`

### Existing routines
- `[MODIFY] RAVEN/app/routines/morning_briefing.py`

### UI/web
- `[MODIFY] RAVEN/app/web/server.py`
- `[MODIFY] RAVEN/app/dashboard/dashboard.py`

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
- RAVEN can manage ongoing goals
- RAVEN can proactively suggest useful actions
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
- `[CREATE] RAVEN/app/forecast/__init__.py`
- `[CREATE] RAVEN/app/forecast/models.py`
- `[CREATE] RAVEN/app/forecast/engine.py`
- `[CREATE] RAVEN/app/forecast/signals.py`
- `[CREATE] RAVEN/app/forecast/events.py`
- `[CREATE] RAVEN/app/forecast/scenarios.py`
- `[CREATE] RAVEN/app/forecast/causal.py`
- `[CREATE] RAVEN/app/forecast/statistics.py`
- `[CREATE] RAVEN/app/forecast/confidence.py`
- `[CREATE] RAVEN/app/forecast/explainer.py`
- `[CREATE] RAVEN/app/forecast/backtesting.py`

### World model foundation
- `[CREATE] RAVEN/app/world/__init__.py`
- `[CREATE] RAVEN/app/world/entities.py`
- `[CREATE] RAVEN/app/world/event_graph.py`
- `[CREATE] RAVEN/app/world/claims.py`

### Manifests
- `[CREATE] RAVEN/app/modules/manifests/forecast.yaml`
- `[CREATE] RAVEN/app/modules/manifests/world.yaml`

---

## Files to Modify

### Memory integration
- `[MODIFY] RAVEN/app/memory/prediction_history.py`
- `[MODIFY] RAVEN/app/core/bootstrapper.py`

### Reach and sensors
- `[MODIFY] RAVEN/app/reach/ingestion.py`
- `[MODIFY] RAVEN/app/sensors/mqtt_listener.py`
- `[MODIFY] RAVEN/app/sensors/webhook_server.py`

### Runtime/orchestrator
- `[MODIFY] RAVEN/app/core/orchestrator.py`
- `[MODIFY] RAVEN/app/core/runtime.py`

### UI/web
- `[MODIFY] RAVEN/app/web/server.py`
- `[MODIFY] RAVEN/app/dashboard/dashboard.py`

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
- RAVEN can generate useful, evidence-grounded low-compute forecasts
- each forecast includes confidence and rationale
- predictions are stored and can be evaluated later

---

# Phase 8 — Build Prediction Engine v2 (Selective Micro-Simulation)

## Goal
Add bounded multi-agent simulation for high-value uncertain scenarios.

## Why this phase matters
This is how RAVEN gains a stronger “foresight” layer without forcing huge compute all the time.

## Key outcomes
- small stakeholder simulation
- branching scenarios
- simulation-backed forecasts
- selective invocation only

---

## Files to Create

### Simulation subsystem
- `[CREATE] RAVEN/app/simulation/__init__.py`
- `[CREATE] RAVEN/app/simulation/models.py`
- `[CREATE] RAVEN/app/simulation/engine.py`
- `[CREATE] RAVEN/app/simulation/actors.py`
- `[CREATE] RAVEN/app/simulation/personas.py`
- `[CREATE] RAVEN/app/simulation/rounds.py`
- `[CREATE] RAVEN/app/simulation/outcomes.py`
- `[CREATE] RAVEN/app/simulation/selective_router.py`

### Manifests
- `[CREATE] RAVEN/app/modules/manifests/simulation.yaml`

---

## Files to Modify

### Forecast subsystem
- `[MODIFY] RAVEN/app/forecast/engine.py`
- `[MODIFY] RAVEN/app/forecast/scenarios.py`
- `[MODIFY] RAVEN/app/forecast/confidence.py`

### World model
- `[MODIFY] RAVEN/app/world/event_graph.py`
- `[MODIFY] RAVEN/app/world/entities.py`

### Swarm/advisory layer
- `[MODIFY] RAVEN/app/core/agency.py`
- `[MODIFY] RAVEN/app/core/orchestrator.py`

### UI
- `[MODIFY] RAVEN/app/web/server.py`
- `[MODIFY] RAVEN/app/dashboard/dashboard.py`

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
- RAVEN can run small-scale scenario simulations
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
- `[CREATE] RAVEN/app/web/static/command-center.html`
- `[CREATE] RAVEN/app/web/static/command-center.css`
- `[CREATE] RAVEN/app/web/static/command-center.js`
- `[CREATE] RAVEN/app/web/static/components/`
- `[CREATE] RAVEN/app/web/static/components/README.md`

### Presence widgets
- `[CREATE] RAVEN/app/presence/widgets.py`
- `[CREATE] RAVEN/app/presence/panels.py`

### Dashboard expansion
- `[CREATE] RAVEN/app/dashboard/pages/01_command_center.py`
- `[CREATE] RAVEN/app/dashboard/pages/02_predictions.py`
- `[CREATE] RAVEN/app/dashboard/pages/03_memory.py`
- `[CREATE] RAVEN/app/dashboard/pages/04_modules.py`

---

## Files to Modify

### Web server
- `[MODIFY] RAVEN/app/web/server.py`

### Dashboard
- `[MODIFY] RAVEN/app/dashboard/dashboard.py`
- `[MODIFY] RAVEN/app/dashboard/utils.py`

### Presence/personality
- `[MODIFY] RAVEN/app/presence/state.py`
- `[MODIFY] RAVEN/app/personality/render.py`

### Voice integration
- `[MODIFY] RAVEN/app/voice/pipeline.py`

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
- RAVEN has a coherent “presence”
- users can inspect what RAVEN is doing
- UI feels like a personal intelligence console

---

# Phase 10 — Build Edge / Low-Compute Distributed Mode

## Goal
Make RAVEN usable as a distributed low-cost intelligence system.

## Why this phase matters
This is how RAVEN becomes always-on without requiring a powerful central box for everything.

## Key outcomes
- edge nodes
- cheap watcher architecture
- remote worker support
- degraded-mode execution

---

## Files to Create

### Edge runtime
- `[CREATE] RAVEN/app/edge/__init__.py`
- `[CREATE] RAVEN/app/edge/models.py`
- `[CREATE] RAVEN/app/edge/protocol.py`
- `[CREATE] RAVEN/app/edge/registry.py`
- `[CREATE] RAVEN/app/edge/router.py`
- `[CREATE] RAVEN/app/edge/worker.py`

### Deployment docs
- `[CREATE] RAVEN/docs/12-edge-runtime-plan.md`

### Optional external worker notes
- `[CREATE] RAVEN/infra/edge/README.md`

---

## Files to Modify

### Kernel/resource governance
- `[MODIFY] RAVEN/app/kernel/resource_governor.py`
- `[MODIFY] RAVEN/app/kernel/capabilities.py`

### Voice/sensors/reach/forecast
- `[MODIFY] RAVEN/app/voice/pipeline.py`
- `[MODIFY] RAVEN/app/sensors/mqtt_listener.py`
- `[MODIFY] RAVEN/app/reach/router.py`
- `[MODIFY] RAVEN/app/forecast/engine.py`

### Config
- `[MODIFY] RAVEN/app/settings/config.py`

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
- RAVEN can run in low-compute distributed mode
- watcher/perception tasks can be offloaded
- system remains coherent under degraded resources

---

# Cross-Phase Shared Files Likely to Be Touched Often

These files will likely be modified across many phases:

## Core
- `RAVEN/main.py`
- `RAVEN/app/core/orchestrator.py`
- `RAVEN/app/core/runtime.py`
- `RAVEN/app/core/bootstrapper.py`
- `RAVEN/app/core/botsignal.py`
- `RAVEN/app/settings/config.py`

## Web/UI
- `RAVEN/app/web/server.py`
- `RAVEN/app/dashboard/dashboard.py`

## DB/Models
- `RAVEN/app/db/models.py`
- `RAVEN/app/db/session.py`

## Voice
- `RAVEN/app/voice/pipeline.py`

## Memory
- `RAVEN/app/core/memory.py`
- `RAVEN/app/core/session.py`

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

RAVEN reaches the target standard when all of these are true:

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

- `RAVEN/plan/03-module-manifest-and-event-schema.md`
- `RAVEN/plan/06-personality-core-spec.md`
- `RAVEN/plan/07-prediction-engine-spec.md`
- `RAVEN/plan/08-command-center-ui-spec.md`

These would convert the checklist into exact implementation contracts.

---