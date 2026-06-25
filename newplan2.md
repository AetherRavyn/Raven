# AetherRavyn → Friday/JARVIS Level — Gap Analysis & Roadmap

**Date:** 2026-06-15
**Author:** OpenCode
**Goal:** Make AetherRavyn the best-in-class personal AI agent — exceeding Hermes, OpenClaw, and any current open-source JARVIS clone.

---

## TL;DR — Where We Stand vs. Where We Need To Be

We have a **strong skeleton** (14 agents, 75+ tools, voice, 7 channels, ambient loop, memory consolidation, verifier, planner, persona engine). But the bones are mostly **architecturally present, not behaviorally alive**.

**Friday/JARVIS-level means:**
1. **Anticipates** you (not just responds) — proactive in a useful, non-spammy way
2. **Reasons across modalities** — sees your screen, hears your room, knows your schedule, reads your files, all in one context
3. **Has a real model of you** — your life, projects, relationships, habits, not just keyword memories
4. **Plans + verifies** — breaks goals into steps, checks each step, recovers from failure
5. **Costs nothing to keep on** — local-first routing, cheap models for 80% of work
6. **Trustworthy by default** — explainable decisions, source citations, safe autonomy with confirmation
7. **Always-on but not annoying** — silence is a feature; speaks only when value > noise
8. **Improves itself visibly** — learns skills, fixes bugs, optimizes workflows, in front of you

We are at **~50%** of that — strong in breadth, weak in depth and integration.

---

## The 8 Critical Gap Categories (Friday-Level)

### GAP 1 — True Persistent User Model ❌ (HIGHEST PRIORITY)
**What we have:** SOUL.md, MEMORY.md, MEMORY.md auto-update, basic user_profile.py
**What Friday has:** A rich, continuously-evolving model of: schedule, relationships, projects, habits, mood patterns, energy levels, location patterns, device ecosystem, work patterns, communication style

**Specific missing pieces:**
- [ ] **No life context graph** — life_context.py exists (192 lines) but is shallow: no projects, no relationships-as-graph, no recurring patterns learned
- [ ] **No habit/routine inference** — agent doesn't learn "user usually checks email at 9am"
- [ ] **No energy/mood tracking** — no correlation between time of day / day of week / message tone and user energy
- [ ] **No project model** — `workspace_graph.py` (150 lines) exists but is not populated from real interactions
- [ ] **No relationship graph** — doesn't track who the user talks about, their importance, communication frequency
- [ ] **No preference contradiction resolution** — when user says "I love X" then later "X is bad", no reconciliation
- [ ] **No source-of-truth distinction** — user-said vs inferred vs system-detected all stored the same
- [ ] **No memory decay/freshness scoring** — attention.py has decay (131 lines) but not wired into retrieval
- [ ] **No timeline reconstruction** — can't answer "what was I working on last Tuesday?"

**Build:**
```
app/core/user_model/
  __init__.py
  profile.py          # rich UserModel (extends current user_profile.py)
  life_graph.py       # person, project, place, event, relationship
  habits.py           # pattern detection from interaction history
  energy.py           # mood/energy tracking + time-of-day correlation
  preferences.py      # typed preferences with contradiction resolution
  timeline.py         # reconstruct past from memory + traces
  freshness.py        # relevance decay, conflict resolution
```

---

### GAP 2 — Real Planner & Executor ❌ (CRITICAL)
**What we have:** `planner.py` (132 lines) with `TaskPlan`, `verifier.verify()` exists, `task_decomposer.py` exists
**What Friday has:** Hierarchical planning with retries, replanning on failure, parallel sub-tasks, cost estimation, deadline awareness

**Specific missing pieces:**
- [ ] **Planner is shallow** — 132 lines, no real plan-and-execute, no replanning
- [ ] **No cost/latency estimation** before executing
- [ ] **No plan persistence** — if interrupted, plans are lost
- [ ] **No parallel plan execution** — TaskPlan is linear
- [ ] **No plan decomposition with sub-agents** — `agency.py` has swarm but doesn't plan-then-delegate
- [ ] **No replanning loop** — on failure, just errors out, no alternate strategy
- [ ] **No goal decomposition** — no "this is a 3-day goal, break into 12 daily steps"
- [ ] **No dead-letter queue** for failed tasks
- [ ] **No progress tracking** with checkpoints

**Build:**
```
app/core/planning/
  __init__.py
  planner.py          # real hierarchical planner (replaces 132-line stub)
  executor.py         # plan executor with retry + replan
  cost_estimator.py   # estimate tokens, time, $ before execution
  checkpoint.py       # plan persistence + resume
  goal_tracker.py     # long-horizon goals with deadlines
  replanner.py        # on failure, generate alternate plan
  parallel_runner.py  # sub-tasks in parallel with deps
```

---

### GAP 3 — Proactive Intelligence ❌ (CRITICAL — Friday's signature)
**What we have:** Ambient loop (11 workers), opportunities worker, morning_briefing skill (markdown only)
**What Friday has:** Proactive but not annoying; knows when to speak; predicts needs from patterns; surfaces anomalies

**Specific missing pieces:**
- [ ] **No anomaly detection on user patterns** — agent doesn't notice "user has been at desk 14 hours"
- [ ] **No calendar-aware suggestions** — calendar tool exists but not actually integrated into ambient loop
- [ ] **No smart nudges** — "you said you'd send the report Friday, today is Saturday"
- [ ] **No follow-up tracking** — when user says "remind me about X next week", no chain
- [ ] **No spam filter for self** — ambient loop can fire too often
- [ ] **No value-gating** — should speak only when value > cost of interruption
- [ ] **No "do not disturb" hours learned** — Friday would learn when not to ping
- [ ] **No context-aware news** — news_agent exists but doesn't curate for current projects
- [ ] **No anticipation engine** — pattern: "user always asks about X before meetings" → proactively surface X

**Build:**
```
app/core/proactive/
  __init__.py
  anomaly_detector.py   # user pattern anomalies
  anticipation.py       # predict next need from patterns
  value_gater.py        # speak only when value > interruption cost
  do_not_disturb.py     # learned quiet hours
  follow_up_tracker.py  # promises/commitments made by user
  smart_nudges.py       # calendar/email/deadline aware
  context_news.py       # news filtered by user's current focus
  silence_engine.py     # what's better not said
```

---

### GAP 4 — Unified Cross-Modal Context ❌ (HIGH)
**What we have:** multimodal.py, multimodal_retrieval.py, image/audio in tools
**What Friday has:** Single context that blends text, voice tone, screen, camera, file, email, calendar, sensor

**Specific missing pieces:**
- [ ] **No unified event schema** — voice events, chat events, file events, sensor events all use different shapes
- [ ] **No token-budgeted multimodal packing** — just dumps everything into prompt
- [ ] **No priority rules for context** — what wins when context overflows
- [ ] **No cross-modal linking** — "the email about Q3" + "the meeting Thursday" + "the file uploaded yesterday" should be linked
- [ ] **No scene understanding** — camera + audio + motion → "looks like a meeting just started"
- [ ] **No real-time multimodal fusion** — surveillance + voice + chat are still partly separate systems
- [ ] **No temporal alignment** — events from different modalities at different times not synced

**Build:**
```
app/core/multimodal/
  __init__.py
  unified_event.py      # canonical event schema for all modalities
  context_packer.py     # token-budgeted multimodal context with priority
  scene_fusion.py       # camera+audio+chat+file → coherent scene
  temporal_align.py     # align events across modalities
  priority.py           # context overflow rules (recency > relevance > novelty)
  cross_link.py         # link related events across modalities
```

---

### GAP 5 — Knowledge Graph (Real, Not Toy) ❌ (HIGH)
**What we have:** workspace_graph.py (150 lines), kgtool.py, Neo4j tool exists
**What Friday has:** Real-time knowledge graph: people, places, projects, devices, files, events, relationships, last-interacted, importance

**Specific missing pieces:**
- [ ] **Graph is shallow** — 150 lines, basic nodes
- [ ] **No automatic population** — no pipeline that ingests from memory, files, calendar, email
- [ ] **No relationship inference** — "user mentioned Alice 14 times in last month" → important
- [ ] **No graph queries in prompts** — agent doesn't ask "what's related to X?"
- [ ] **No temporal graph** — relationships change over time
- [ ] **No entity resolution** — "Bob", "Robert", "B." should merge
- [ ] **No graph-based retrieval** — should rank by graph proximity
- [ ] **No graph editor/inspector in dashboard** — exists as API only

**Build:**
```
app/core/knowledge/
  __init__.py
  graph.py            # real graph (replaces 150-line stub)
  entity_resolver.py  # merge "Bob" / "Robert" / "B."
  relationship_learn.py # infer relationships from interactions
  temporal.py         # time-versioned graph
  graph_query.py      # "what's related to X?" for prompts
  graph_retrieval.py  # rank results by graph proximity
  ingest/             # pipelines from memory, files, calendar, email
    from_memory.py
    from_files.py
    from_calendar.py
    from_email.py
```

---

### GAP 6 — Self-Improvement Loop (Genuine) ❌ (HIGH)
**What we have:** skill_learner.py (552 lines), self_improvement.py exists, regression.py exists, eval.py exists
**What Friday has:** Visible self-improvement: learns new skills from observation, fixes own bugs, optimizes own workflows, shows diffs

**Specific missing pieces:**
- [ ] **SkillLearner is theory** — 552 lines but `skills/learned/` is EMPTY
- [ ] **No trace → skill pipeline** — no actual end-to-end "watch user do X 3 times, propose skill"
- [ ] **No skill evaluation** — created skills aren't tested
- [ ] **No self-modification review** — when agent edits its own code, no PR/approval flow
- [ ] **No regression gates** — regression.py exists but unclear if running in CI
- [ ] **No A/B testing of prompts** — can't compare "did this prompt change help?"
- [ ] **No user feedback → action** — feedback.py exists but unclear wiring
- [ ] **No prompt versioning** — system prompts change without history
- [ ] **No "explain what you learned"** — agent doesn't tell user what it learned

**Build:**
```
app/core/improvement/
  __init__.py
  skill_factory.py       # trace → draft skill (real, not theory)
  skill_evaluator.py     # test learned skills against benchmarks
  prompt_versioning.py   # git-tracked prompt history
  ab_test.py             # A/B prompt comparison
  feedback_loop.py       # thumbs up/down → real model updates
  self_modify.py         # propose code changes with PR flow
  regression_gate.py     # CI gate on regressions
  explain_learning.py    # "I learned: X" surface to user
```

---

### GAP 7 — Cost-Aware & Resilient Runtime ❌ (HIGH)
**What we have:** model_router.py, resilience.py, provider fallback to Ollama
**What Friday has:** Always responsive, always cheap, never breaks, degrades gracefully

**Specific missing pieces:**
- [ ] **No real cost tracking** — tokens used, $ spent per session
- [ ] **No degradation policy** — when cloud down, what's the offline experience?
- [ ] **No response caching** — same question twice, full re-compute
- [ ] **No streaming-first architecture** — many places still wait for full completion
- [ ] **No timeout policies per tool** — long tool = no timeout = hangs
- [ ] **No circuit breakers per tool** — failing tool retries forever
- [ ] **No prompt optimization** — system prompts are static, not token-efficient
- [ ] **No early exit on cheap answers** — simple Q routed to tiny model
- [ ] **No work stealing / queue** — heavy work blocks light work

**Build:**
```
app/core/runtime_v2/
  __init__.py
  cost_router.py         # cost-tier aware routing
  cache.py               # response cache (semantic, not exact)
  streaming.py           # unified streaming everywhere
  circuit_breaker.py     # per-tool circuit breakers
  timeout_policy.py      # per-tool/per-agent timeouts
  degradation.py         # offline/low-compute modes
  queue.py               # work queue with priority + preemption
  prompt_compress.py     # context compression for cost
```

---

### GAP 8 — Trust, Safety & Explainability ❌ (HIGH)
**What we have:** security.py, policy.py, counterfactual.py, prompt injection detection
**What Friday has:** Every action has reason + risk + reversibility; user always knows what agent did and why

**Specific missing pieces:**
- [ ] **No action explainability** — "why did you do that?" not answered well
- [ ] **No source citation in answers** — agent cites memory, file, web — but not consistently
- [ ] **No risk scoring consistency** — counterfactual.py exists but not always invoked
- [ ] **No rollback for every action** — some actions can be undone, some can't, no record
- [ ] **No action audit log surfaced to user** — exists in audit.py but not in dashboard
- [ ] **No "show your work" mode** — toggle to see full reasoning chain
- [ ] **No privacy zones** — certain memories never leave device
- [ ] **No data export / delete** — GDPR/right-to-delete missing
- [ ] **No "what do you know about me?" inspector** — single page showing everything stored
- [ ] **No hallucination self-check** — agent should re-verify factual claims

**Build:**
```
app/core/trust/
  __init__.py
  explainer.py          # "why did you..." → trace + reasons
  citations.py          # every fact → source
  rollback.py           # every action has rollback plan
  audit_log.py          # rich audit with user-facing viewer
  show_work.py          # toggle full reasoning chain
  privacy_zones.py      # per-data-class privacy
  data_lifecycle.py     # export, delete, retention
  user_inspector.py     # "what do you know about me?" page
  fact_check.py         # self-verify factual claims
```

---

## Cross-Cutting Gaps (Affect All of Above)

### A. Skills System is Half-Alive
- 18 bundled skills exist
- `learned/` is EMPTY — auto-learning doesn't actually work
- No skill marketplace (Phase 6 deferred)
- No skill composition (chaining skills)
- No skill versioning
- No skill trust tiers

### B. Channels Are Working But Shallow
- 7 channels work but none have full **persona-aware responses** (tone shifts per platform)
- No message threading persistence (start on Telegram, reply on web, lose context)
- No cross-channel task handoff ("I'll do this and ping you on Telegram when done")
- No read-receipts / delivery confirmation

### C. Dashboard is API-First, Not Product-First
- 40+ API endpoints but UX is not Friday-grade
- No command center view ("what's happening now, what needs me")
- No quick-glance persona state
- No voice control of dashboard
- No "ask Friday" floating widget everywhere

### D. Voice Pipeline is Wired But Not Conversational
- Wake word + TTS + STT work
- No barge-in (interrupt agent mid-speech)
- No multi-speaker awareness (who's in the room?)
- No voice activity correlation with camera (speak only when user is alone)
- No voice biometrics (knows it's you, not someone else)
- No voice cloning (your voice, not generic TTS)

### E. Missing Friday-isms
- **Humor calibration** — Friday is witty but knows when not to be
- **Anticipatory briefings** — "sir, you have 3 meetings, low battery on phone, traffic on the way"
- **Crisis mode** — Friday gets terse and decisive in emergencies
- **Defense mode** — actively protects user (blocks, warns, isolates)
- **Companion mode** — checks in, not just task-completes

---

## What Beats OpenClaw & Hermes — Our Edge

| Area | OpenClaw (377k★) | Hermes (177k★) | **Our Edge** |
|------|------------------|-----------------|--------------|
| Architecture | Monolithic agent | Monolithic | **Multi-agent swarm** (14 specialists) |
| Cognition | Single mode | Single mode | **Dual System 1/2 + meta-cognitive monitor** |
| Tools | ~30 | ~30 | **75+ tools** |
| Memory | Session | Session | **ChromaDB + Neo4j + consolidation** |
| Voice | Yes (limited) | TTS only | **Full local pipeline + channels** |
| Device Control | Limited | No | **Desktop + Mobile + Screen + OCR** |
| Ambient Loop | Cron | No | **11-worker heartbeat** |
| Cross-Training | No | No | **LearnerAgent + meta-cognition** |
| Negotiation | No | No | **Structured debate protocol** |
| Proactive | No | No | **Opportunity detection** |
| Cost-aware | No | No | **Local-first, Ollama fallback** |

**Our disadvantage:** ecosystem, community, polish, brand.

**Our weapon:** **smarter, not bigger.** A truly intelligent, multi-agent, self-improving, anticipatory, multimodal assistant that actually feels like Friday.

---

## Build Order (Friday in 6 Phases)

### Phase A — Foundation Hardening (Week 1-2)
**Goal:** Make the spine work end-to-end, not just exist.
1. Real planner with retries + replan (replaces 132-line stub)
2. Real cost router with token/$ tracking
3. Real verifier wired into every tool result
4. Real audit log surfaced in dashboard
5. Fix: admin deny-by-default, secret handling, dependency injection

### Phase B — The User Model (Week 3-4)
**Goal:** Know the user.
1. Build user_model/ — profile, life_graph, habits, energy
2. Wire workspace_graph into memory + calendar + email
3. Build entity resolver + relationship inference
4. Build timeline reconstruction
5. Wire freshness/decay into retrieval

### Phase C — Proactive + Anticipatory (Week 5-6)
**Goal:** Speak when it matters, stay silent when not.
1. Build proactive/ — anomaly, anticipation, value_gater, dnd
2. Wire calendar → smart_nudges
3. Build follow_up_tracker (commitments, promises, deadlines)
4. Wire opportunity detection into ambient loop
5. Build silence_engine (what NOT to say)

### Phase D — Unified Multimodal (Week 7-8)
**Goal:** One context, many senses.
1. Build unified_event schema (voice/chat/file/sensor all same shape)
2. Build context_packer with token budgets + priority
3. Build scene_fusion (camera+audio+chat+file)
4. Wire surveillance events into ambient loop
5. Add cross-modal linking

### Phase E — Self-Improvement (Real) (Week 9-10)
**Goal:** Get visibly smarter.
1. skill_factory: trace → draft skill (end-to-end)
2. skill_evaluator: test learned skills
3. prompt_versioning: git-track all system prompts
4. feedback_loop: thumbs → real updates
5. regression_gate: CI runs regressions
6. explain_learning: "I learned: X" surface

### Phase F — Trust & Polish (Week 11-12)
**Goal:** Be the agent you'd trust with everything.
1. explainer + citations + rollback for every action
2. user_inspector: "what do you know about me?"
3. data_lifecycle: export, delete, retention
4. voice: barge-in, multi-speaker, voice ID
5. dashboard: command center view, floating widget
6. persona: humor calibration, crisis mode, defense mode

---

## Immediate Next Steps (This Week)

1. **Read** `Agent.md`, `friday.md`, `GAP_ANALYSIS_2026_06.md` end-to-end
2. **Decide** which Phase A item to start with (recommend: real planner)
3. **Write tests first** for the new planner, cost router, verifier
4. **Build the spine** — every subsequent feature depends on it
5. **Don't add more tools** — we have 75+; we need depth, not breadth

---

## Success Criteria — What "Friday-Level" Means Concretely

A user should be able to:
- [ ] Say "good morning" and get a briefing tailored to today, not generic
- [ ] Ask "what was I working on Tuesday?" and get a real answer
- [ ] Set a goal and have it broken into a tracked plan that survives restarts
- [ ] Have the agent notice anomalies (long screen time, missed break, calendar conflicts)
- [ ] Trust that every action has a reason and can be undone
- [ ] See what the agent knows about them in one page
- [ ] Watch the agent learn a new skill from observing their workflow
- [ ] Use voice, text, or web — same context follows them
- [ ] Have the agent cost effectively nothing on a local GPU box
- [ ] Trust the agent enough to give it calendar/email/files

**We are not there. We can be in 12 weeks.**

---

*End of gap analysis. Recommend: pick Phase A item, start coding Monday.*
