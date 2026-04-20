# 02 - Modular Architecture Blueprint & Module Contract Plan

**Project:** SARAS  
**Goal:** Turn SARAS into a **modular, low-compute, JARVIS/FRIDAY-style personal intelligence system** that can grow safely over time.  
**Date:** 2026-03-29

---

## 1. Why This Document Exists

SARAS already has many important pieces:

- multi-platform connectors
- orchestrator + agent runtime
- tools
- memory
- voice pipeline
- sensors
- web/dashboard pieces
- WhatsApp bridge
- `agent_reach/` for internet visibility

But the current system is still partially **feature-first** instead of fully **module-first**.

If we want a true **Iron Man fantasy system** — ambient, predictive, personality-rich, proactive, low-compute, and endlessly extensible — then the next step is not just adding more code.

The next step is defining a **clean modular operating model**.

This blueprint defines:

1. the target module architecture
2. what each module owns
3. how modules communicate
4. what is still missing compared with:
   - OpenClaw
   - NemoClaw / NeMo Agent Toolkit style systems
   - ZeroClaw / PicoClaw style low-resource systems
   - MiroFish-style predictive simulation systems
5. the implementation contracts needed to make SARAS a real long-term platform

---

# 2. Design Principles

## 2.1 One Brain, Many Bodies
SARAS must feel like **one personality** everywhere:

- Telegram
- Discord
- Slack
- WhatsApp
- Web UI
- Local microphone/speaker
- future mobile/desktop/AR interfaces

Different channels are only surfaces.  
The mind must remain one.

## 2.2 Modular by Contract, Not by Convention
Every major subsystem must have:

- explicit responsibility
- clear input/output contracts
- no hidden cross-dependencies
- replaceable implementation

This means we should be able to replace:

- memory backend
- voice engine
- prediction engine
- LLM provider
- internet ingestion layer
- UI frontend
- safety runtime

without rewriting the whole system.

## 2.3 Low Compute First
SARAS should be designed to work in **three compute tiers**:

### Tier A — Ultra-light
- CPU only
- external APIs allowed
- suitable for laptop / mini VPS / home server

### Tier B — Balanced local
- consumer GPU optional
- small local models + cloud fallback
- best for daily personal use

### Tier C — Full power
- local LLMs
- multimodal reasoning
- prediction sandboxes
- advanced monitoring + simulation

The architecture must degrade gracefully from C → B → A.

## 2.4 Predictive, Not Just Reactive
Like MiroFish, SARAS should not only answer.  
It should:

- ingest real data
- build situational models
- estimate outcomes
- present confidence and alternative scenarios

But unlike MiroFish, SARAS must do this in a **compute-aware** way:
- small simulations first
- statistical forecasting first
- only escalate to larger agent-world simulations when needed

## 2.5 Personality Is a Product Surface
A JARVIS/FRIDAY-like assistant is not only about tools.  
It must have:

- stable identity
- emotional style
- voice style
- conversational memory
- situational tone adaptation
- visual interface cues that express personality

So personality must be a **first-class module**, not a prompt afterthought.

## 2.6 Agent Reach Is the Internet Eye Layer
`agent_reach/` should become SARAS's **Internet Observation Layer**.

It is not just an external utility. It should be integrated as:
- discovery layer
- source ingestion layer
- channel-health layer
- trend and signal collector
- predictive engine feed source

---

# 3. Comparison Against Other Systems

This section is practical: what others do well, what SARAS already has, and what SARAS still lacks.

---

## 3.1 SARAS vs OpenClaw

### OpenClaw strengths
- huge channel ecosystem
- polished personal assistant UX
- strong onboarding and multi-platform presence
- opinionated product experience
- large plugin/skill ecosystem
- rich interaction surfaces

### SARAS already has
- multi-platform design
- tool ecosystem
- memory direction
- voice support
- swarm direction
- stronger IoT/home/security ambitions
- richer local research / deep investigation orientation

### SARAS still lacks vs OpenClaw
1. **Product-level cohesion**
   - more of a powerful system than a polished assistant product
2. **consistent onboarding**
   - setup is still fragmented
3. **uniform skill/module packaging**
   - modules/tools are not yet standardized enough
4. **clean human-facing identity across all surfaces**
   - same assistant should feel visually and behaviorally consistent everywhere
5. **central operator UI**
   - module status, data sources, tasks, forecasts, conversations, voice state, system state

---

## 3.2 SARAS vs NemoClaw / NeMo-style stacks

### NemoClaw / NeMo-style strengths
- observability
- evaluation
- enterprise reliability mindset
- policy-driven execution
- audit trails
- instrumented workflows
- stronger governance

### SARAS already has
- some security controls
- metrics beginnings
- orchestrator + runtime split
- modular potential
- logging and diagnostics in places

### SARAS still lacks
1. **full tracing**
   - every request should produce a structured execution trace
2. **evaluation harness**
   - benchmark tasks, response quality, tool correctness, memory retrieval quality, voice quality, forecast quality
3. **policy engine**
   - declarative module policies, access policies, action approval levels
4. **sandbox matrix**
   - tools should declare filesystem/network/process privileges
5. **operator-grade audit view**
   - who did what, which module, what source, what side effects
6. **confidence and reliability scoring**
   - especially for prediction and autonomous actions

---

## 3.3 SARAS vs ZeroClaw

### ZeroClaw strengths
- trait/interface-driven architecture
- strongly modular runtime boundaries
- security-aware runtime design
- clean backend abstractions
- lightweight systems mindset

### SARAS already has
- some modularity
- separate connectors
- distinct tool/runtime layers
- replaceable providers in parts

### SARAS still lacks
1. **formal interface layer**
   - many modules are still concrete classes instead of stable contracts
2. **uniform registry system**
   - one module registry for tools, channels, memories, forecasts, sensors, personalities
3. **runtime isolation model**
   - module capabilities should be explicit and controllable
4. **module lifecycle management**
   - install, enable, disable, restart, healthcheck, version
5. **clear separation between control plane and execution plane**

---

## 3.4 SARAS vs PicoClaw

### PicoClaw strengths
- tiny runtime
- low hardware needs
- cheap edge deployment
- simple architecture
- cloud-offload strategy

### SARAS already has
- CPU-friendly paths in some areas
- optional cloud/provider model use
- edge/IoT ambition
- distributed thinking in docs

### SARAS still lacks
1. **true edge modules**
   - tiny sensor/voice/observer nodes
2. **lightweight sidecar services**
   - very small components for always-on local tasks
3. **explicit compute scheduler**
   - decide where to run work:
     - API
     - local CPU
     - local GPU
     - phone
     - edge node
4. **module resource profiles**
   - each module should know:
     - memory cost
     - CPU cost
     - network cost
     - startup time
5. **graceful low-resource mode**
   - reduced features, same personality

---

## 3.5 SARAS vs MiroFish

### MiroFish strengths
- real-data ingestion
- knowledge graph grounding
- multi-agent social simulation
- predictive scenario generation
- alternative futures, not just answers

### SARAS already has
- agents
- tools
- memory direction
- knowledge graph tooling
- internet search/fetch capability
- `agent_reach` as a strong future feed layer

### SARAS still lacks
1. **prediction engine**
   - first-class forecasting subsystem does not exist yet
2. **scenario model layer**
   - world model / event graph / actor graph
3. **small-to-large simulation pipeline**
   - rule/statistical forecast → agent scenario simulation
4. **confidence, uncertainty, and scenario branching**
5. **forecast dashboard**
   - visual explanation of why SARAS predicts something
6. **event ingestion pipeline**
   - continuously ingest news, feeds, market signals, sensor changes, user context
7. **forecast evaluation loop**
   - compare predictions to real outcomes and improve

---

# 4. What Is Missing for a True JARVIS / FRIDAY-Class System

This is the direct missing-feature list.

## 4.1 Core Missing Capabilities

### A. Stable Personality Engine
Needed:
- identity model
- relationship model
- tone controller
- humor style
- emotional moderation
- context-sensitive speaking modes:
  - friend
  - operator
  - analyst
  - urgent alert mode
  - quiet mode

### B. Proactive Intelligence Engine
Needed:
- detect opportunities
- detect risk
- detect anomalies
- create suggestions
- propose actions before user asks

### C. Prediction / Foresight Engine
Needed:
- ingest real-world structured and unstructured data
- detect trends
- run forecasts
- estimate outcomes
- explain confidence
- simulate alternatives

### D. Modular UI Personality Layer
Needed:
- interface that shows SARAS as a character
- status, speaking state, mood/state indicators
- memory cards, active goals, alerts, forecasts
- voice and waveform presentation
- visual presence that feels like an assistant, not just a dashboard

### E. Unified Module System
Needed:
- every subsystem as a module
- clear manifest
- dependencies
- permissions
- health endpoints
- input/output contract
- enable/disable at runtime

### F. Control Plane
Needed:
- inspect modules
- inspect memory stores
- inspect tool calls
- inspect data feeds
- inspect predictions
- inspect active tasks/goals
- manage permissions and compute budgets

### G. Low-Compute Scheduling Layer
Needed:
- choose cheapest adequate execution path
- cache aggressively
- batch expensive work
- use tiny local models first
- use external APIs only when needed
- optionally use remote workers / phones / edge devices

### H. Continuous Learning Layer
Needed:
- learn from outcomes
- learn user preferences
- learn prediction accuracy
- learn what proactive suggestions are useful
- adapt personality without drifting identity

---

# 5. Target Modular Architecture

The target architecture should be:

```text
┌──────────────────────────────────────────────────────────────┐
│                      SARAS CONTROL PLANE                    │
│  module registry • policy • observability • eval • config   │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                    SARAS COGNITIVE CORE                     │
│ orchestration • personality • memory • planning • context   │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                   EXECUTION / CAPABILITY BUS                │
│ tool router • event bus • task bus • forecast bus           │
└──────────────────────────────────────────────────────────────┘
      │              │              │              │
      ▼              ▼              ▼              ▼
 Connectors      Intelligence     Environment     Interface
 Modules         Modules          Modules         Modules
```

---

# 6. Module Families

---

## 6.1 Connector Modules

These are input/output surfaces.

### Modules
- Telegram module
- Discord module
- Slack module
- WhatsApp module
- Web module
- Voice local module
- future desktop/mobile module

### Responsibilities
- receive messages/events
- normalize into common format
- deliver replies/actions
- handle platform-specific attachments/media

### Must not own
- reasoning
- memory logic
- forecasting logic
- personality generation

### Contract
Input:
- external platform event

Output:
- `UnifiedEvent`

---

## 6.2 Personality Modules

These define how SARAS feels.

### Core submodules
- Identity module
- Tone engine
- Relationship memory adapter
- Persona rendering adapter
- Mood/state controller
- Voice persona adapter
- UI persona adapter

### Responsibilities
- stable self-description
- response style selection
- user-specific tone adaptation
- emergency vs casual tone switching
- prevent personality drift

### Missing today
- explicit contract and state model
- persistent persona variables
- UI/voice linked personality model

---

## 6.3 Memory Modules

### Core submodules
- Session memory
- Semantic memory
- Episodic memory
- User profile memory
- Preference memory
- Graph memory
- Forecast memory
- Reflection memory

### Responsibilities
- store and retrieve relevant context
- summarize
- score importance
- forget safely
- separate facts from speculation

### Missing today
- stronger user profile system
- episodic memory model
- reflection/outcome storage
- memory quality evaluation
- consistent memory contracts

---

## 6.4 Tool & Action Modules

### Core submodules
- Tool registry
- Permission model
- Side-effect classifier
- Approval engine
- Sandbox adapters
- Action replay / audit

### Responsibilities
- expose capabilities to the brain
- classify risk
- enforce policies
- record side effects

### Missing today
- explicit permission manifest per tool
- risk/approval policy matrix
- full audit schema

---

## 6.5 Planning & Goal Modules

### Core submodules
- Goal manager
- Task decomposition
- Long-horizon planner
- Routine manager
- Reminder and scheduler bridge
- Proactive suggestions engine

### Responsibilities
- convert requests into plans
- track goals over time
- work asynchronously
- push proactive follow-ups

### Missing today
- durable goal model
- blocker management
- project/mission tracking
- proactive action planner

---

## 6.6 Prediction Modules

This is one of the most important missing pieces.

### Core submodules
- Data ingestion layer
- Signal extractor
- Event graph builder
- Statistical forecasting engine
- Multi-agent scenario simulator
- Confidence calibrator
- Outcome evaluator
- Forecast UI layer

### Responsibilities
- use real data to produce forecasts
- explain assumptions
- produce scenarios:
  - likely
  - optimistic
  - worst case
- track accuracy over time

### Low-compute strategy
Prediction must happen in levels:

#### Level 1 — Cheap
- moving averages
- trend detection
- anomaly detection
- event correlation
- lightweight classification

#### Level 2 — Moderate
- small local model reasoning over event graph
- ranking alternative scenarios
- confidence scoring

#### Level 3 — Heavy
- multi-agent simulation inspired by MiroFish
- used only for:
  - complex market/social/policy scenarios
  - major personal planning decisions
  - high-value forecast tasks

### Missing today
- almost all of this as a first-class system

---

## 6.7 Agent Reach Modules

`agent_reach` should be treated as a modular subsystem, not an isolated package.

### Proposed role
**Internet Sensory Cortex**

### Submodules
- Source discovery
- Channel health doctor
- Platform-specific readers
- Feed ingestion
- trend and topic extractor
- source trust scorer
- watchlist monitor
- forecast feed adapter

### Responsibilities
- gather external world data
- monitor internet channels
- support research and prediction
- feed the event graph

### Missing today
- direct integration into SARAS event bus
- continuous watcher mode
- source scoring and deduplication
- ingestion to memory and forecast modules

---

## 6.8 Environment Modules

### Modules
- Sensors
- Camera bridge
- Smart home
- System monitor
- Docker/system services
- network awareness
- local device map

### Responsibilities
- physical and digital environment awareness
- anomaly detection
- safe actuation

### Missing today
- unified environment state model
- home/device registry
- stronger environment reasoning layer

---

## 6.9 Interface Modules

### Modules
- web chat UI
- operator dashboard
- personality panel
- timeline/activity view
- memory explorer
- forecast explorer
- voice interface visualizer
- module manager UI

### Responsibilities
- make SARAS visible
- make personality visible
- make reasoning inspectable
- make forecasts understandable

### Missing today
- unified visual identity
- personality-first interface
- forecast and module control views

---

## 6.10 Control Plane Modules

### Modules
- module registry
- module loader
- module manifest validator
- policy engine
- observability/tracing
- evaluation harness
- config store
- compute budget scheduler

### Responsibilities
- supervise all modules
- expose health and metrics
- enforce policies
- drive reliability and upgrades

### Missing today
- this whole layer as a proper first-class system

---

# 7. Canonical Module Contract

Every module in SARAS should implement a common contract.

## 7.1 Required Metadata

Each module must declare:

- `module_id`
- `display_name`
- `version`
- `category`
- `owner`
- `description`
- `capabilities`
- `dependencies`
- `required_config`
- `optional_config`
- `resource_profile`
- `permissions`
- `health_checks`
- `events_in`
- `events_out`

---

## 7.2 Required Lifecycle Methods

Every module should support:

- `load()`
- `start()`
- `stop()`
- `health()`
- `status()`
- `reload_config()`

Optional:
- `pause()`
- `resume()`
- `drain()`

---

## 7.3 Required Resource Profile

Each module must publish:

- startup latency
- steady RAM
- peak RAM
- CPU class
- network class
- storage class
- GPU required? yes/no
- offline capable? yes/no

Example classes:
- CPU: `tiny`, `small`, `medium`, `large`
- network: `none`, `light`, `moderate`, `heavy`

---

## 7.4 Required Permission Model

Each module must declare whether it needs:

- file read
- file write
- workspace write
- shell execute
- network outbound
- local device access
- microphone
- speaker
- camera
- database access
- message send
- autonomous action permission

Permissions should be reviewable in the operator UI.

---

## 7.5 Required Event Contracts

Each module must state what it accepts and emits.

Examples:
- `message.received`
- `message.reply`
- `sensor.changed`
- `forecast.requested`
- `forecast.completed`
- `memory.saved`
- `task.started`
- `task.completed`
- `policy.blocked`
- `voice.transcribed`

---

# 8. Core Event Model

All modules should use a shared event schema.

## 8.1 Unified Event Fields

- `event_id`
- `event_type`
- `timestamp`
- `source_module`
- `target_module`
- `user_id`
- `session_id`
- `priority`
- `trace_id`
- `payload`
- `metadata`

This is critical for:
- observability
- replay
- audit
- simulation
- debugging

---

# 9. Proposed Module Categories

## 9.1 Minimum official categories
- `connector`
- `personality`
- `memory`
- `tool`
- `planner`
- `prediction`
- `environment`
- `interface`
- `control`
- `provider`
- `voice`
- `safety`
- `analytics`

---

# 10. Low-Compute Blueprint

This section is essential.

A JARVIS-like system can become too expensive or too heavy.  
So SARAS should be designed as a **layered intelligence stack**.

## 10.1 Compute routing policy

### Route 1 — Reflex path
Use:
- rules
- cache
- MiniEngine
- local lightweight models

Best for:
- greetings
- simple commands
- reminders
- quick facts
- environment lookups

### Route 2 — Standard reasoning
Use:
- one main provider/model
- limited tool set
- small memory retrieval
- no heavy simulation

Best for:
- normal chat
- planning
- research requests
- code assistance

### Route 3 — Advanced reasoning
Use:
- multi-agent or swarm
- broader source retrieval
- external data fusion
- deep synthesis

Best for:
- long research
- strategic planning
- investigation
- rich analysis

### Route 4 — Forecast mode
Use:
- event graph
- historical + live data
- light stats first
- then simulation only if needed

Best for:
- market/news impact
- planning outcomes
- risk and opportunity analysis

---

## 10.2 Cheap-first module policy

The system must prefer:

1. cache
2. rule
3. local tiny model
4. local standard model
5. API model
6. swarm
7. simulation

This order should be enforced by the control plane.

---

# 11. Personality System Blueprint

To achieve JARVIS/FRIDAY feel, SARAS needs a real personality framework.

## 11.1 Personality dimensions
- warmth
- brevity
- wit
- confidence
- calmness
- urgency
- formality
- protectiveness
- initiative

## 11.2 Personality modes
- companion mode
- analyst mode
- operator mode
- guardian mode
- briefing mode
- silent/background mode

## 11.3 Personality state inputs
- user profile
- time of day
- current task
- urgency
- recent conversation mood
- platform
- whether response is spoken or written

## 11.4 Interface expression
The UI should reflect personality using:
- color/state palette
- animations
- voice state visualization
- response rhythm
- “thinking / observing / alert / briefing” states

---

# 12. Prediction Engine Blueprint

This is the MiroFish-inspired but low-compute practical version.

## 12.1 Pipeline

### Step 1 — Real data ingestion
From:
- `agent_reach`
- RSS/news
- social platforms
- finance feeds
- user tasks/calendar
- sensors/home events
- internal logs/system events

### Step 2 — Entity and event extraction
Build:
- actors
- locations
- assets
- topics
- risks
- dependencies
- time sequence

### Step 3 — Event graph
Store:
- what happened
- who affects whom
- what dependencies exist
- what uncertainty remains

### Step 4 — Fast forecast
Use:
- heuristics
- statistical trend models
- event similarity retrieval
- graph-based reasoning

### Step 5 — Scenario simulation
If required:
- instantiate small agent populations
- assign perspectives/roles
- run short bounded simulations
- compare outcomes

### Step 6 — Confidence and explanation
Output:
- forecast
- confidence score
- assumptions
- alternative outcomes
- sources used

### Step 7 — Outcome tracking
Later compare:
- predicted vs actual
- confidence vs reality
- where model failed

## 12.2 Use cases
- market movement hints
- social/news narrative changes
- operational anomaly forecast
- user planning forecast:
  - “if you delay this project 2 weeks…”
  - “if this spending trend continues…”
- home risk forecast:
  - unusual sensor patterns
  - likely intrusion / maintenance risk
- research forecasting

---

# 13. Interface Blueprint

A fantasy assistant needs presence.

## 13.1 UI goals
- feel alive
- show cognition without clutter
- expose forecasts and plans visually
- show memory and awareness
- show current mode/personality

## 13.2 Core screens
1. Chat
2. Voice console
3. Situation room
4. Forecast panel
5. Module control panel
6. Memory/profile explorer
7. Tasks/goals planner
8. Environment/home panel
9. Source intelligence panel powered by `agent_reach`

## 13.3 Situation room
This should become the “JARVIS room” screen:
- active goals
- environment status
- ongoing tasks
- internet watchlist
- forecasts
- alerts
- module health
- voice state
- memory cues

---

# 14. What Should Be Built First

This is the practical phased plan.

---

## Phase 1 — Foundation Modularization
**Goal:** define contracts and remove hidden coupling

### Build
- module base contract
- module registry
- module manifest format
- event schema
- health/status interface
- permission declarations
- resource profiles

### Result
SARAS becomes a true platform, not just a growing app.

---

## Phase 2 — Control Plane
**Goal:** operational visibility and reliability

### Build
- execution traces
- structured logs
- policy engine
- operator dashboard
- module lifecycle manager
- evaluation harness skeleton

### Result
SARAS becomes inspectable, governable, and safer.

---

## Phase 3 — Personality Engine
**Goal:** make SARAS feel like one coherent assistant

### Build
- personality state model
- relationship memory
- tone controller
- voice persona mapping
- UI persona layer

### Result
JARVIS/FRIDAY feel becomes real.

---

## Phase 4 — Agent Reach Integration
**Goal:** give SARAS continuous internet eyes

### Build
- `agent_reach` adapter module
- source ingestion scheduler
- source trust and dedup layer
- event graph feed
- watchlists and topic monitors

### Result
SARAS gets persistent awareness of the external world.

---

## Phase 5 — Prediction Core
**Goal:** real forecasting from real data

### Build
- event graph
- signal extraction
- lightweight forecasting
- forecast memory
- confidence calibration
- outcome tracking

### Result
SARAS stops being only reactive.

---

## Phase 6 — Scenario Simulation
**Goal:** MiroFish-style foresight, but bounded and efficient

### Build
- simulation environment
- actor templates
- scenario runner
- branching forecasts
- high-cost escalation policy

### Result
advanced predictive intelligence without making every request expensive.

---

## Phase 7 — Interface & Presence
**Goal:** visible assistant identity

### Build
- personality-first web UI
- forecast panel
- situation room
- voice console
- module manager
- operator controls

### Result
SARAS feels alive, inspectable, and premium.

---

## Phase 8 — Edge / Low-Compute Mesh
**Goal:** make the system cheap and ubiquitous

### Build
- tiny edge observer nodes
- compute router
- remote worker support
- low-resource operating mode
- phone/edge offload experiments

### Result
SARAS becomes deployable anywhere.

---

# 15. Concrete Missing Items Checklist

This is the clean checklist version.

## Must-have missing items
- [ ] formal module contract system
- [ ] module registry and manifests
- [ ] module lifecycle manager
- [ ] event bus with shared schema
- [ ] control plane UI
- [ ] policy and permission engine
- [ ] full tracing and audit logs
- [ ] evaluation harness
- [ ] compute-aware routing engine
- [ ] explicit personality engine
- [ ] relationship/user profile model
- [ ] proactive suggestion engine
- [ ] durable goal/project system
- [ ] `agent_reach` live integration
- [ ] event graph / world model
- [ ] lightweight forecasting engine
- [ ] scenario simulation engine
- [ ] forecast quality scoring
- [ ] forecast/situation room UI
- [ ] edge/low-compute deployment mode

## Strongly recommended
- [ ] memory quality benchmarks
- [ ] module permission review screen
- [ ] action approval workflow
- [ ] source trust scoring
- [ ] module dependency resolver
- [ ] adaptive voice persona layer
- [ ] offline-first fallback profiles
- [ ] module packaging conventions

---

# 16. Final Recommendation

The right path is **not** to copy OpenClaw, NemoClaw, PicoClaw, ZeroClaw, or MiroFish directly.

The right path is to build SARAS as a **hybrid**:

- **OpenClaw-like** in assistant presence and channel reach
- **Nemo-style** in observability, evaluation, and safety
- **ZeroClaw-like** in strong modular interfaces
- **PicoClaw-like** in low-compute and edge design
- **MiroFish-like** in predictive scenario intelligence
- **SARAS-like** in ambient intelligence, home awareness, personality, and deep investigation

That combination is stronger than any one of them alone.

SARAS should become:

> a modular personal intelligence operating system with one personality, many interfaces, real-world awareness, low-compute defaults, and predictive foresight.

That is the correct architecture for a true JARVIS / FRIDAY-class system.

---

# 17. Next Document To Write

The next plan document should be:

**`03-module-manifest-and-event-schema.md`**

It should define:
- exact module manifest JSON/YAML schema
- event types
- capability declarations
- permission declarations
- resource profile enums
- lifecycle/state machine
- validation rules

That document is the next necessary foundation before implementation.