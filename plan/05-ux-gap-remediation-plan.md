# SARAS UX Gap Remediation Plan

## Goal
Make SARAS feel like a coherent, inspectable, companion-style product instead of a powerful but fragmented system.

## UX Principles
- Show state before action.
- Make every important action explainable.
- Keep one mental model across chat, voice, and web.
- Prefer progressive disclosure over dense control panels.
- Surface uncertainty, not just answers.
- Keep low-compute paths the default.

## Gap-to-UX Map

### 1. Product-level cohesion
Problem: SARAS has many strong subsystems, but users do not yet get one unified product feel.

UX fix:
- Add one command-center home screen.
- Use a single navigation model across dashboard, web, voice, and chat.
- Standardize names, icons, and statuses for all core modules.

### 2. Unified onboarding
Problem: setup is fragmented.

UX fix:
- Add a guided first-run wizard.
- Ask for identity, timezone, style, channels, and safety preferences.
- Show which skills, memories, and channels are enabled.
- End onboarding with a visible “ready state”.

### 3. Skill and module packaging
Problem: modules are not presented as a coherent ecosystem.

UX fix:
- Show a registry page with manifest, health, version, trust level, and capabilities.
- Add install, enable, disable, and update actions.
- Show onboarding queue for missing or incomplete manifests.

### 4. Central operator UI
Problem: there is no single place to inspect tasks, memory, forecasts, conversations, and health.

UX fix:
- Build an operator center with tabs for registry, tasks, memory, feedback, and predictions.
- Add a compact system status strip at the top.
- Keep the operator UI readable on desktop and usable on mobile.

### 5. Presence layer
Problem: SARAS feels backend-heavy instead of companion-like.

UX fix:
- Add presence states: listening, thinking, briefing, alerting, companion, idle.
- Show live activity, recent actions, and current briefings.
- Add a persona panel so the assistant has a visible identity.

### 6. Memory and continuity
Problem: memory exists, but users cannot manage it well.

UX fix:
- Add memory views for facts, preferences, rules, and recent context.
- Allow pin, edit, and delete from the UI.
- Show why a memory was used in an answer.

### 7. Forecast and prediction
Problem: forecasting is planned, but not yet user-facing.

UX fix:
- Add a forecast panel with scenarios, confidence, and rationale.
- Show baseline / optimistic / pessimistic outcomes.
- Make simulation invocation explicit and opt-in for expensive cases.

### 8. Safety and approvals
Problem: risky actions are not yet framed as a clear UX flow.

UX fix:
- Add a confirmation modal for destructive or external actions.
- Show risk level, required permissions, and expected side effects.
- Add an approvals inbox for pending actions.

### 9. Traceability and audits
Problem: actions are not easy to inspect end to end.

UX fix:
- Show a visible timeline for each turn: request, plan, tool calls, verification, result.
- Add filterable audit logs.
- Show source health and verification status next to outputs.

### 10. Cross-device continuity
Problem: a conversation should move cleanly between Telegram, voice, web, and Discord.

UX fix:
- Preserve thread identity and turn state.
- Show resume points and thread handoff prompts.
- Keep the same labels, actions, and confirmations across channels.

### 11. Proactive UX
Problem: SARAS is still mostly reactive.

UX fix:
- Add a daily brief.
- Add follow-up cards for unanswered questions.
- Add event digests for reminders, alerts, and new signals.

### 12. Edge and degraded mode
Problem: the product should still feel usable when connectivity is limited.

UX fix:
- Show online/degraded/offline mode in the header.
- Make fallback behavior visible.
- Queue actions for later sync when needed.

## Phase Plan

### Phase A: Command Center First
Build the operator home, status strip, registry, tasks, memory, and feedback views.

### Phase B: Onboarding And Identity
Build guided setup, persona selection, safety defaults, and channel selection.

### Phase C: Presence And Continuity
Add presence states, live activity, handoff, and a stronger companion surface.

### Phase D: Forecast And Explainability
Add forecast panels, simulation display, and answer provenance.

### Phase E: Safety And Audit
Add confirmations, approvals, trace timelines, and action logs.

### Phase F: Proactive And Edge UX
Add briefs, follow-ups, degraded mode, and edge companion views.

## Exit Criteria
- A new user can onboard in one flow.
- A user can understand what SARAS is doing at a glance.
- The operator UI shows module health, memory, tasks, and feedback in one place.
- Risky actions are explicit and reviewable.
- SARAS feels like one assistant across all surfaces.
