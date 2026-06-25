# Implementation Plan: Modular Extension Platform

## Overview

This plan converts the Module_Platform design into incremental, test-driven coding steps in
`app/modules/` (Python 3.12, async-first, `ruff`/`pyright` clean, max line length 100,
`logging.getLogger(__name__)`). Each step builds on the previous one and ends with the platform
wired into the running system (discovery + auto-load at bootstrap, `ravyn modules` CLI registered,
dashboard panels surfaced).

The five grounding assumptions (A1–A5) each require small additions to existing core code. They are
sequenced early because later tasks depend on them:

- **A1** — adapt `SkillRegistry` dict records into typed `ModuleRecord` (task 5.1).
- **A2** — add `deregister_*` helpers to `SystemKernel`/`SwarmManager`/`StandingOrderStore`
  (task 3.1) plus the authoritative `RegistrationLedger` (task 9.1).
- **A3** — add a trust-level default-grant table layered over `PolicyEngine` (task 6.1).
- **A4** — execute the dependency `check` command through `SandboxManager` (task 4.1).
- **A5** — own the `SentinelBridge` severity ↔ `OutputRouter` `Priority` mapping in `Event_Bridge`
  (task 8.2).

Each of the 16 correctness properties is implemented as a single Hypothesis test in
`app/modules/test_properties.py`, tagged
`# Feature: modular-extension-platform, Property {n}: {property text}` and run at
`@settings(max_examples=100)`.

## Tasks

- [x] 1. Create the `app/modules` package and core data models
  - [x] 1.1 Implement enums, dataclasses, and provides-type protocols in `app/modules/models.py`
    - Create `app/modules/__init__.py` and `app/modules/models.py`
    - Define `ModuleState` and `ProvidesType` enums and the dataclasses: `DependencySpec`,
      `ResolvedDependency`, `Compatibility`, `ProvidesEntry`, `ValidationResult`,
      `CapabilityBundle` (with `is_empty()` and `item_ids()`), `PermissionRequest`,
      `BrokerDecision` (with `needs_approval`), `HealthStatus`, `ModuleEvent`, `RaisedEvent`,
      `UndoEntry`, `LifecycleResult`, `SecretCheck`, and `ModuleRecord` (with `module_id` /
      `is_active`)
    - Define the async `EventSource`, `AnomalyDetector`, and `ProactiveReaction` protocols
    - Apply `slots=True` and the documented default values (absent optional fields default to
      empty lists; `enabled_by_default` defaults false)
    - _Requirements: 1.2, 1.3, 1.4, 6.4_

- [x] 2. Implement the unified Module Manifest schema and validation
  - [x] 2.1 Implement manifest constants and `parse_manifest` in `app/modules/manifest.py`
    - Define `SUPPORTED_SCHEMA_VERSIONS`, `VALID_TRUST_LEVELS`, `VALID_PROVIDES_TYPES`,
      `REQUIRED_FIELDS`, `_MODULE_ID_RE`, `_SEMVER_RE`, and `ModuleManifest` (the full schema
      including `provides`, `required_permissions`, `required_secrets`, `compatibility`)
    - Build `parse_manifest(raw, manifest_path)` from a raw mapping, preserving existing
      `SkillRegistry` field meanings and defaults and parsing legacy fields unchanged
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 1.7, 14.1_

  - [x] 2.2 Implement `validate_manifest` in `app/modules/manifest.py`
    - Confirm required fields, `module_id`/`version` regex, `trust_level` membership, schema
      version support, and minimum-version semver comparison against the running version
    - Return a structured `ValidationResult` (missing fields, invalid `(field, value)` pairs,
      reason) without side effects
    - _Requirements: 1.7, 1.8, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 2.3 Write unit tests for manifest parsing and validation in `app/modules/test_manifest.py`
    - Parse each of the four manifest kinds; verify compatibility parsing and legacy-field
      defaults match `SkillRegistry`; cover each rejection branch in `validate_manifest`
    - _Requirements: 1.5, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5, 14.1_

- [x] 3. Add core deregistration helpers to existing subsystems (A2)
  - [x] 3.1 Add `deregister_*` helpers to `SystemKernel`, `SwarmManager`, and `StandingOrderStore`
    - Add `deregister`/`deregister_tool` to `app/core/kernel.py`, `deregister_agent` to
      `app/core/agency.py`, and reaction removal to `app/core/standing_orders.py`, leaving all
      existing register/parse signatures unchanged
    - Make each helper idempotent (removing an absent item is a no-op) so rollback is safe
    - _Requirements: 10.7, 14.2_

  - [x]* 3.2 Write unit tests for the new deregistration helpers in `app/core/test_deregistration.py`
    - Verify register-then-deregister leaves each subsystem in its pre-register state and that
      deregistering an absent item is a no-op
    - _Requirements: 10.7_

- [x] 4. Implement dependency and secret resolution
  - [x] 4.1 Implement `DependencyResolver` executing `check` via `SandboxManager` (A4) in `app/modules/dependencies.py`
    - `resolve(deps)` runs each declared `check` command through `SandboxManager` (exit 0 =>
      satisfied, non-zero => unsatisfied, error/timeout => unknown), routing external execution
      through the resilience layer
    - Implement `unmet_required(resolved)` returning required deps whose status != satisfied
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.2 Implement `SecretResolver` presence checks in `app/modules/secrets.py`
    - `check_presence(keys)` calls only `SecretVault.has(key)` / `list_keys()` (never `retrieve`),
      returning present/absent key names and never placing a secret value in any output
    - _Requirements: 4.4, 4.5, 4.6, 13.3_

  - [-]* 4.3 Write unit tests in `app/modules/test_dependencies.py` and `app/modules/test_secrets.py`
    - Cover satisfied/unsatisfied/unknown dependency mapping, `unmet_required`, and present/absent
      secret detection with no value leakage
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 5. Implement the Module_Registry
  - [x] 5.1 Implement `ModuleRegistry` discovery and dict→`ModuleRecord` adaptation (A1) in `app/modules/registry.py`
    - Compose a `SkillRegistry`; `discover()` scans every configured root through it, adapts each
      dict record into a typed `ModuleRecord`, records `(module_id, category)` in the kernel
      capability graph, skips/logs missing roots and manifest-less directories at debug level
    - Apply deterministic manifest precedence and lexicographic duplicate-`module_id` resolution
    - Implement `get`, `all` (ordered by `module_id`), `add_skill`, `remove_skill`,
      `record_in_graph`, `remove_from_graph`, and `counts()`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.6, 12.1, 14.1, 14.8_

  - [x]* 5.2 Write unit tests for discovery and adaptation in `app/modules/test_registry.py`
    - Discovery across all four manifest kinds and multiple roots, missing-root skip, empty-dir
      skip, capability-graph recording, duplicate-id resolution, and `counts()`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.6, 14.8_

- [x] 6. Implement the Permission_Broker
  - [x] 6.1 Implement the trust-level default-grant table and `evaluate_module` (A3) in `app/modules/permissions.py`
    - Define `DEFAULT_GRANTS` for `system`/`workspace`/`community` layered over
      `PolicyEngine.evaluate(...)`
    - `evaluate_module(record)` grants only requested permissions within the trust level's grant
      (deny-by-default), routing everything else to pending approval; reuse `PolicyDecision`
    - _Requirements: 5.1, 5.2_

  - [x] 6.2 Implement approval workflow and auditing in `app/modules/permissions.py`
    - Implement `is_pending_approval`, `approve`, and `deny`, keeping a module disabled until the
      operator decides and recording each request/decision through `ActionLogger`
    - _Requirements: 5.6, 5.7, 5.8, 13.4, 13.5_

  - [x] 6.3 Implement runtime tool gating and `sandbox_backend_for` in `app/modules/permissions.py`
    - `evaluate_tool(record, tool)` delegates to `PolicyEngine.evaluate` and intersects with the
      module's granted set (allow / requires-confirmation / deny + `permissions_missing`)
    - Implement the pure `sandbox_backend_for(trust_level, docker_available)` selection function
    - _Requirements: 5.3, 5.4, 5.5, 8.4, 8.5, 8.6_

  - [x]* 6.4 Write unit tests for the broker in `app/modules/test_permissions.py`
    - Approve/deny transitions, allow path executes a tool, requires-confirmation path, deny
      reports missing permissions
    - _Requirements: 5.7, 5.8, 8.4, 8.5, 8.6_

- [x] 7. Implement the Health_Monitor
  - [x] 7.1 Implement `HealthMonitor` in `app/modules/health.py`
    - `check_registration(record)` reuses the `SkillRegistry` health report for manifest/dependency/
      required-secret checks and records the latest `HealthStatus` (no secret values)
    - Implement `record_success` (reset count), `record_failure` (increment; return True and notify
      the operator at HIGH priority through `OutputRouter` at the configurable threshold, default 3,
      integer >= 1), and `guard(coro)` that catches unhandled errors so they never reach core
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [-]* 7.2 Write unit tests for the health monitor in `app/modules/test_health.py`
    - Default threshold 3 and threshold 1, registration health recorded, guard isolates errors and
      resets on success
    - _Requirements: 9.1, 9.2, 9.7_

- [x] 8. Implement the Event_Bridge
  - [x] 8.1 Implement source/detector/reaction registration in `app/modules/event_bridge.py`
    - `register_source`/`deregister_source` (each source wrapped by `HealthMonitor.guard`, failures
      isolated per source), `register_detector`/`deregister_detector` (subscribe to declared
      `listens_to` source), and `register_reaction`/`deregister_reaction` (persist condition +
      response into `StandingOrderStore`)
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 10.7_

  - [x] 8.2 Implement event fan-out and priority mapping (A5) in `app/modules/event_bridge.py`
    - `normalize_priority(value)` maps a declared priority to `OutputRouter` `Priority`, returning
      `(Priority.NORMAL, True)` for missing/invalid values; own the `SentinelBridge` severity ↔
      `Priority` mapping
    - `on_event(...)` delivers an event only to the detectors that declared the emitting source,
      submits raised events to `OutputRouter` at the resolved priority (CRITICAL ignores DND), and
      fires matching reactions through broker-gated tool execution
    - _Requirements: 7.3, 7.4, 7.5, 7.6, 8.2, 8.3_

  - [x]* 8.3 Write unit tests for the event bridge in `app/modules/test_event_bridge.py`
    - Source → `SentinelBridge` wiring, detector fan-out to declared listeners only, priority
      normalization/substitution, CRITICAL ignores DND, isolated source-registration failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 9. Implement the Module_Loader and RegistrationLedger (the lifecycle core)
  - [x] 9.1 Implement `RegistrationLedger` (A2) in `app/modules/loader.py`
    - Implement `push`, `entries`, and `rollback()` replaying `UndoEntry` items in LIFO order and
      collecting non-fatal errors; the ledger is the authoritative source of truth for rollback
    - _Requirements: 6.5, 10.7_

  - [x] 9.2 Implement `_hot_load` provides-type dispatch in `app/modules/loader.py`
    - Register each bundle item with its subsystem (tool/agent → tool layer + `SystemKernel` /
      `SwarmManager`; skill → `ModuleRegistry`; source/detector/reaction → `Event_Bridge`;
      ui_surface → dashboard), pushing an `UndoEntry` immediately after each success
    - Implement the paired `_undo_*` helpers that call the A2 deregistration helpers
    - _Requirements: 6.1, 6.3_

  - [x] 9.3 Implement the `register` pipeline with 5s timeout and rollback in `app/modules/loader.py`
    - Run validate → resolve dependencies → resolve secrets → broker permissions → build
      `CapabilityBundle` → hot-load inside `asyncio.timeout(5.0)`; on any failure or timeout roll
      back via the ledger, set state DISABLED, and return a `LifecycleResult` reporting the failed
      item / timeout; set ENABLED iff `enabled_by_default`
    - _Requirements: 4.2, 4.5, 5.6, 6.1, 6.2, 6.4, 6.5, 14.3, 14.4_

  - [x] 9.4 Implement `_hot_unload`, `enable`, `disable`, and `uninstall` in `app/modules/loader.py`
    - `_hot_unload` replays the module ledger; `enable` re-runs all checks then hot-loads;
      `disable` hot-unloads (idempotent no-op when already disabled, bounded at 5s); re-register
      hot-unloads the existing version first and restores it on failure; `uninstall` hot-unloads,
      removes from registry + capability graph, deletes files (deregistration completes even when
      deletion fails)
    - Emit one structured log per transition (error level on failure) and record install/enable/
      disable/uninstall `AuditEvent`s through `ActionLogger`, never logging secret values
    - _Requirements: 6.6, 6.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 13.1, 13.2, 14.5, 14.6, 14.7_

  - [x]* 9.5 Write unit/integration tests for the loader in `app/modules/test_loader.py`
    - Hot-load < 5s for a representative bundle, tool/agent reachable after registration, rollback
      on item failure and on timeout, enable success, disable idempotence, uninstall with and
      without a file-deletion failure
    - _Requirements: 6.2, 6.3, 6.5, 10.1, 10.2, 10.3, 10.5, 10.6, 14.3, 14.4_

- [~] 10. Checkpoint - core lifecycle verified
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement the Module_CLI and wire it into the dispatcher
  - [x] 11.1 Implement `list_modules` and `inspect` in `app/modules/cli.py`
    - `list_modules` orders by `module_id` (id, display_name, version, trust_level, state) with a
      "no modules" message; `inspect` shows bundle, permissions, secrets (names only), dependency
      status, and latest health ("no health-check result available" when none), with a not-found
      error that leaves the system unchanged
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 11.2 Implement `scaffold` in `app/modules/cli.py`
    - Validate a 1–64 char name and `tool`/`agent` category; atomically create `module.yaml` +
      `SKILL.md` + a placeholder under `app/tools/` or `app/agents/`; the generated `module.yaml`
      passes Requirement 3 validation; invalid/colliding names create no files
    - _Requirements: 11.1, 11.2, 11.3_

  - [-] 11.3 Implement `install` in `app/modules/cli.py`
    - Local-directory install requires no network; marketplace install goes through the resilience
      layer and aborts with no filesystem change when the source is unreachable
    - _Requirements: 11.4, 11.5, 11.6_

  - [~] 11.4 Register `ravyn modules ...` subcommands in `app/cli/main.py`
    - Add the `modules` argparse group (list, inspect, scaffold, install, enable, disable,
      uninstall) mirroring `cmd_skills`, dispatching to `ModuleCLI` and `ModuleLoader`
    - _Requirements: 12.1, 10.1, 10.3, 10.5, 11.1, 11.4_

  - [ ]* 11.5 Write unit tests for the CLI in `app/modules/test_cli.py`
    - Empty-list message, unknown-id inspect, scaffold validation/atomicity, marketplace-unreachable
      abort
    - _Requirements: 11.3, 11.6, 12.2, 12.4_

- [x] 12. Implement the dashboard UI surface
  - [x] 12.1 Implement the panel registry and timeout-guarded rendering in `app/modules/dashboard.py`
    - `register_panel`/`deregister_panel`; render each enabled module's panel inside
      `asyncio.timeout(5.0)`, omitting and flagging a failed/slow panel while rendering the rest;
      modules without a UI surface register their remaining bundle with no panel
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 12.2 Wire the module management view into `app/api/ui.py` and `app/web/server.py`
    - Surface the module list with enabled/disabled state and enable/disable controls that reuse
      the loader behavior; on failure retain prior state and report to the operator
    - _Requirements: 12.5, 12.6, 12.7_

  - [-]* 12.3 Write unit tests for the dashboard surface in `app/modules/test_dashboard.py`
    - Panel rendered when enabled, absent when not declared, removed on disable/hot-unload, and a
      failing panel is omitted while the rest renders
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

- [ ] 13. Wire the Module_Platform into startup
  - [~] 13.1 Bootstrap the platform in `app/core/bootstrapper.py` / `main.py`
    - Construct the registry, broker, resolvers, event bridge, health monitor, loader, and CLI;
      run discovery at startup, auto-load modules with `enabled_by_default`, and register the
      module-health tick alongside the ambient loop's `_check_health` cadence
    - _Requirements: 2.1, 6.4, 9.1, 14.1_

  - [ ]* 13.2 Write a startup integration test in `app/modules/test_integration.py`
    - Discovery + auto-load of an `enabled_by_default` module at bootstrap and the CLI dispatcher
      reaching the loader end-to-end
    - _Requirements: 2.1, 2.3, 6.4, 14.1_

- [x] 14. Build the home-protection worked example
  - [x] 14.1 Create the home-protection module under `skills/community/home_protection/`
    - Author `module.yaml` (event_source + anomaly_detector + tool + proactive_reaction + ui_surface),
      `SKILL.md`, `sources.py` (`FrontDoorCamera`), `detectors.py` (`StrangerDetector`), `tools.py`
      (`SnapshotTool`), and `panel.py` (`render_panel`)
    - _Requirements: 1.2, 7.7_

  - [ ]* 14.2 Write the end-to-end integration test in `app/modules/test_home_protection.py`
    - Load all four contributions from one manifest; a CRITICAL detector event reaches `OutputRouter`
      ignoring DND; the `intruder_response` reaction invokes `SnapshotTool` under the broker decision
    - _Requirements: 7.1, 7.3, 7.4, 7.6, 7.7, 8.1, 8.2, 8.3_

- [x] 15. Implement the property-based test suite (Hypothesis)
  - [x]* 15.1 Scaffold strategies and in-memory fakes in `app/modules/test_properties.py`
    - Add Hypothesis strategies (`trust_levels`, `priorities`, `module_ids`, `semver`,
      `permissions`, `provides_entry`, `@composite manifests`, `@composite bundles`) and fakes
      implementing `BaseTool`/`BaseAgent`/`EventSource`/`AnomalyDetector`/`ProactiveReaction`;
      apply `@settings(max_examples=100)` and the per-test tag convention
    - _Requirements: 6.1, 6.5_

  - [x]* 15.2 Property 1 test in `app/modules/test_properties.py`
    - **Property 1: Hot-unload fully reverses hot-load**
    - **Validates: Requirements 10.7, 10.1, 15.4**

  - [ ]* 15.3 Property 2 test in `app/modules/test_properties.py`
    - **Property 2: Permission grant is deny-by-default and trust-bounded**
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 15.4 Property 3 test in `app/modules/test_properties.py`
    - **Property 3: Secret values never leak**
    - **Validates: Requirements 4.6, 13.3, 14.6, 9.2**

  - [ ]* 15.5 Property 4 test in `app/modules/test_properties.py`
    - **Property 4: Registration is atomic (all-or-nothing) under failure or timeout**
    - **Validates: Requirements 6.5, 14.4, 4.2**

  - [ ]* 15.6 Property 5 test in `app/modules/test_properties.py`
    - **Property 5: Successful registration covers the whole bundle**
    - **Validates: Requirements 6.1, 6.4**

  - [ ]* 15.7 Property 6 test in `app/modules/test_properties.py`
    - **Property 6: Re-registration replaces atomically and restores on failure**
    - **Validates: Requirements 6.6, 6.7**

  - [ ]* 15.8 Property 7 test in `app/modules/test_properties.py`
    - **Property 7: Manifest validation rejects all invalid manifests without side effects**
    - **Validates: Requirements 1.7, 1.8, 3.1, 3.2, 3.3, 3.4, 3.5**

  - [ ]* 15.9 Property 8 test in `app/modules/test_properties.py`
    - **Property 8: Duplicate module ids resolve deterministically**
    - **Validates: Requirements 3.6, 2.4**

  - [ ]* 15.10 Property 9 test in `app/modules/test_properties.py`
    - **Property 9: Manifest defaults are applied consistently**
    - **Validates: Requirements 1.3, 1.4, 1.6, 14.1**

  - [ ]* 15.11 Property 10 test in `app/modules/test_properties.py`
    - **Property 10: Sandbox backend is a deterministic function of trust level**
    - **Validates: Requirements 5.3, 5.4, 5.5**

  - [ ]* 15.12 Property 11 test in `app/modules/test_properties.py`
    - **Property 11: A faulty module never crashes the core and is counted**
    - **Validates: Requirements 9.3, 9.4**

  - [ ]* 15.13 Property 12 test in `app/modules/test_properties.py`
    - **Property 12: Reaching the failure threshold auto-disables and silences the module**
    - **Validates: Requirements 9.5, 9.6, 9.8**

  - [ ]* 15.14 Property 13 test in `app/modules/test_properties.py`
    - **Property 13: Detector events map to the correct delivery priority**
    - **Validates: Requirements 7.4, 7.5**

  - [ ]* 15.15 Property 14 test in `app/modules/test_properties.py`
    - **Property 14: Events fan out only to the registered listening detectors**
    - **Validates: Requirements 7.2, 7.3**

  - [ ]* 15.16 Property 15 test in `app/modules/test_properties.py`
    - **Property 15: Disable is idempotent and enabled/disabled counts are accurate**
    - **Validates: Requirements 10.2, 14.8**

  - [ ]* 15.17 Property 16 test in `app/modules/test_properties.py`
    - **Property 16: Scaffolded manifests always validate; invalid names produce no files**
    - **Validates: Requirements 11.2, 11.3**

- [~] 16. Final checkpoint - full suite green
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP; core
  implementation tasks are never optional.
- Each task references the specific requirements (and, for property tasks, the correctness property)
  it implements, for full traceability.
- A1–A5 are addressed by tasks 5.1 (A1), 3.1 + 9.1 (A2), 6.1 (A3), 4.1 (A4), and 8.2 (A5).
- The five-second hot-load/hot-unload bound, atomic rollback ledger, and timeout handling are
  concentrated in task 9; the feature is wired into the running system in tasks 11.4 (CLI),
  12.2 (dashboard), and 13.1 (bootstrap).
- Each correctness property is one Hypothesis test in `app/modules/test_properties.py` at
  >= 100 iterations, tagged per the design's convention.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1"] },
    { "id": 1, "tasks": ["2.1", "4.1", "4.2", "3.2", "6.1", "7.1"] },
    { "id": 2, "tasks": ["2.2", "5.1", "6.2", "7.2", "8.1", "4.3", "9.1"] },
    { "id": 3, "tasks": ["2.3", "5.2", "6.3", "8.2", "9.2"] },
    { "id": 4, "tasks": ["6.4", "8.3", "9.3"] },
    { "id": 5, "tasks": ["9.4"] },
    { "id": 6, "tasks": ["9.5", "11.1", "12.1", "14.1", "15.1"] },
    { "id": 7, "tasks": ["11.2", "12.2", "15.2"] },
    { "id": 8, "tasks": ["11.3", "12.3", "15.3"] },
    { "id": 9, "tasks": ["11.4", "15.4"] },
    { "id": 10, "tasks": ["11.5", "13.1", "15.5"] },
    { "id": 11, "tasks": ["13.2", "14.2", "15.6"] },
    { "id": 12, "tasks": ["15.7"] },
    { "id": 13, "tasks": ["15.8"] },
    { "id": 14, "tasks": ["15.9"] },
    { "id": 15, "tasks": ["15.10"] },
    { "id": 16, "tasks": ["15.11"] },
    { "id": 17, "tasks": ["15.12"] },
    { "id": 18, "tasks": ["15.13"] },
    { "id": 19, "tasks": ["15.14"] },
    { "id": 20, "tasks": ["15.15"] },
    { "id": 21, "tasks": ["15.16"] },
    { "id": 22, "tasks": ["15.17"] }
  ]
}
```
