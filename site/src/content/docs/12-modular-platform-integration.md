---
title: "Modular Platform ↔ Mother Module- Integration Options"
---

# Modular Platform ↔ Mother Module: Integration Options

*Documented: 2026-06-20 (after the v1 → v2 skill migration audit)*

Companion to [`docs/newfind.md`](newfind.md) — the J.A.R.V.I.S. roadmap.
That document describes the **what** (multi-agent swarm, dual-core
processing, ubiquitous voice mesh, omnipresent network control,
proactive monitoring). This document describes the **how** — three
distinct ways the modular extension platform (`app/modules/`) can
be wired into the orchestrator / kernel / API surface so that a
new module (surveillance, OSINT, internet-profiling, …) actually
shows up at runtime.

The motivation is concrete: today `app/modules/` is fully built
(loader, registry, manifest schema, permission broker, secret
resolver, health monitor, event bridge, CLI, dashboard, 11 test
files, and one example module `skills/community/home_protection/`)
**but it is not wired into the boot path**. No code outside
`app/modules/` imports from `app.modules`; `main.py` does not
instantiate a `ModuleLoader`; the orchestrator does not query
the module registry; the API does not expose module endpoints.

This document lays out three integration options, with code-level
sketches, trade-offs, and a recommendation.

---

## 0. Where the gap is, precisely

| Surface | Has it? | Where |
|---|---|---|
| Module manifest schema (the contract) | ✅ | `app/modules/manifest.py` (7 `provides` types) |
| Module loader / lifecycle (validate → permit → register → enable → disable → uninstall) | ✅ | `app/modules/loader.py` |
| Module registry (typed record cache + capability graph) | ✅ | `app/modules/registry.py` |
| Permission broker | ✅ | `app/modules/permissions.py` |
| Secret resolver | ✅ | `app/modules/secrets.py` |
| Health monitor | ✅ | `app/modules/health.py` |
| Event bridge | ✅ | `app/modules/event_bridge.py` |
| Module CLI (`raven modules ...`) | ✅ | `app/modules/cli.py` |
| Module dashboard | ✅ | `app/modules/dashboard.py` |
| Example module | ✅ | `skills/community/home_protection/` |
| Loader-aware of kernel | ✅ | `app/modules/loader.py` calls `kernel.register_tool()` etc. |
| **Loader started at boot** | ❌ | `main.py` does not import `app.modules.loader` |
| **Orchestrator consults module registry** | ❌ | `app/core/orchestrator.py` does not query `ModuleRegistry` |
| **API exposes module endpoints** | ❌ | `app/api/` does not import from `app.modules` |
| **Module events reach the orchestrator's ReAct loop** | ❌ | `EventBridge` is built but no subscriber wires it in |

The two `ModuleManifest` classes — one in `app/core/kernel.py`
(the active capability graph, used by `app/core/policy.py`) and
one in `app/modules/manifest.py` (the module-platform schema) —
are deliberately separate. The module loader translates between
them by calling `kernel.register_tool()` etc. on each module's
contribution. That translation already exists.

What is missing is the **call site** that turns the loader on.

---

## 1. The three options at a glance

| | Option A — Boot-time eager | Option B — Lazy / on-demand | Option C — Event-bridge mediated |
|---|---|---|---|
| When do modules load? | At `main.py` startup, before the orchestrator | First time the orchestrator needs a tool / agent / skill / event_source | At startup, but their events flow through `EventBridge` and the orchestrator subscribes |
| Latency on first call | None (already loaded) | One-time module-discovery + permit cost | None for registered modules; event delivery is async |
| Memory footprint | All enabled modules loaded at boot | Only requested modules loaded | All enabled modules loaded; events buffered |
| Reversibility | `ModuleLoader.uninstall()` works at runtime | `uninstall()` works; lazy loader caches | `uninstall()` works; bridge subscribers must unsubscribe |
| Failure mode | A broken module prevents boot | A broken module fails the first call only | A broken module's events are dropped; rest of system runs |
| Best for | "Always-on" personal assistant — JARVIS style | Many optional capabilities, low-RAM hosts | Surveillance / monitoring modules that produce event streams |
| Risk | Boot fragility | First-call latency surprise | Event-loop coupling |

All three share the same **bridge code** that already exists in
`app/modules/loader.py` — they differ only in **when** the bridge
runs and **how** the orchestrator consumes it.

---

## 2. Option A — Boot-time eager registration

### Sketch

```python
# main.py (sketch — not committed)
import asyncio
from app.core import BotSignal, MessageOrchestrator, get_botsignal
from app.core.kernel import get_kernel
from app.core.executor import DaemonExecutor
from app.modules.loader import ModuleLoader
from app.modules.registry import ModuleRegistry
from app.modules.cli import ModuleCLI
from app.modules.permissions import PermissionBroker
from app.modules.secrets import SecretResolver

async def boot():
    # 1. Existing core wiring (unchanged)
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    kernel = get_kernel()

    # 2. Module platform — NEW
    registry = ModuleRegistry(kernel=kernel)
    registry.discover()  # scans configured module roots

    loader = ModuleLoader(
        registry=registry,
        kernel=kernel,
        permissions=PermissionBroker(),
        secrets=SecretResolver(),
    )
    await loader.load_all_enabled()  # validate → permit → hot-load
    loader.start_health_monitor()

    # 3. Hand the loaded tools/agents/skills to the orchestrator
    orchestrator.attach_module_registry(registry)

    # 4. Expose the CLI surface (existing)
    cli = ModuleCLI(registry=registry, loader=loader)
    cli.register_into(cli_root)

    # 5. Existing platform-connector wiring (unchanged)
    ...
```

### What changes in the codebase

* `main.py` — add a module-platform section between the core boot
  and the platform-connector boot. ~30 lines.
* `app/core/orchestrator.py` — add `attach_module_registry(registry)`
  that lets the orchestrator discover tools via the registry in
  addition to its hard-coded list. ~20 lines.
* `app/api/` — add a module router that exposes the registry as
  REST endpoints (list / get / enable / disable / install / uninstall).
  ~80 lines, mostly plumbing.

### Trade-offs

* **Pro:** "It just works" mental model. Once a module is dropped
  into `modules/` (or `skills/community/<name>/`) and its manifest
  declares `enabled_by_default: true`, it shows up at the next
  restart. This matches the JARVIS feel — every installed
  capability is part of the system.
* **Pro:** Failures surface at boot. A module with a syntax error
  or invalid manifest blocks startup, which is the right place to
  catch it for a personal-assistant context.
* **Con:** Boot time grows with the number of modules.
* **Con:** Memory grows linearly. On a constrained host (Pi,
  cheap VPS) this matters.

---

## 3. Option B — Lazy / on-demand registration

### Sketch

```python
# main.py (sketch — not committed)
async def boot():
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    kernel = get_kernel()

    # Module platform exists but does not auto-load.
    registry = ModuleRegistry(kernel=kernel)
    registry.discover_metadata_only()  # manifest scan, no Python imports
    loader = ModuleLoader(
        registry=registry,
        kernel=kernel,
        permissions=PermissionBroker(),
        secrets=SecretResolver(),
    )

    # Lazy loader is consulted by the orchestrator on first use.
    orchestrator.attach_module_registry(registry, loader=loader)

    # ...
```

```python
# app/core/orchestrator.py (sketch)
class MessageOrchestrator:
    def __init__(self, ...):
        self._module_registry: ModuleRegistry | None = None
        self._module_loader: ModuleLoader | None = None

    def attach_module_registry(
        self,
        registry: ModuleRegistry,
        loader: ModuleLoader | None = None,
    ) -> None:
        self._module_registry = registry
        self._module_loader = loader

    async def resolve_tool(self, name: str) -> BaseTool | None:
        """Look up a tool by name.  Triggers lazy load if needed."""
        tool = self._agent_runtime.tools.get(name)
        if tool is not None:
            return tool
        # Module-provided tool?  Try to lazy-load it.
        if self._module_registry is not None:
            record = self._module_registry.get_by_provides("tool", name)
            if record is not None and self._module_loader is not None:
                await self._module_loader.hot_load(record.module_id)
                return self._agent_runtime.tools.get(name)
        return None
```

### What changes in the codebase

* `main.py` — same as A but `load_all_enabled()` is replaced with
  `discover_metadata_only()`.
* `app/core/orchestrator.py` — add `attach_module_registry()` and
  thread `resolve_tool()` / `resolve_agent()` through the ReAct
  loop. ~50 lines.
* `app/modules/registry.py` — add a `get_by_provides(type, name)`
  index. ~15 lines.

### Trade-offs

* **Pro:** Memory-efficient on hosts with many installed modules.
* **Pro:** A broken module doesn't prevent boot — only the first
  call to that module fails.
* **Con:** Latency on first call (Python import + permit + register).
* **Con:** More moving parts in the orchestrator's hot path.

---

## 4. Option C — Event-bridge mediated

### Sketch

```python
# main.py (sketch — not committed)
async def boot():
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    kernel = get_kernel()

    # Module platform starts the bridge first.
    registry = ModuleRegistry(kernel=kernel)
    registry.discover()
    bridge = EventBridge()
    bridge.attach_registry(registry)  # bridge reads registry for routing

    loader = ModuleLoader(
        registry=registry,
        kernel=kernel,
        bridge=bridge,  # bridge injected
    )
    await loader.load_all_enabled()

    # Orchestrator subscribes to event categories it cares about.
    orchestrator.attach_event_bridge(bridge)
    await bridge.start()  # starts the dispatch loop

    # ...
```

```python
# Surveillance module — example of an event_source
# skills/community/surveillance/module.yaml
provides:
  - type: event_source
    name: front_door_camera
    entrypoint: sources.py:FrontDoorCamera
    config: { camera_id: front_door, fps: 5 }
  - type: anomaly_detector
    name: stranger_detector
    entrypoint: detectors.py:StrangerDetector
    listens_to: front_door_camera
  - type: proactive_reaction
    name: intruder_alert
    condition: "event.type == 'stranger' and event.confidence > 0.7"
```

```python
# Anomaly detector publishes via the bridge
class StrangerDetector:
    async def on_event(self, event):
        if event.kind == "person_detected" and event.confidence > 0.7:
            await self._bridge.publish(
                topic="anomaly.front_door.stranger",
                payload={"camera_id": event.source, "ts": event.ts,
                         "snapshot_path": event.attachment},
            )

# Proactive reaction subscribes to the topic
class IntruderAlert:
    async def start(self):
        await self._bridge.subscribe(
            topic="anomaly.front_door.stranger",
            handler=self._handle,
        )

    async def _handle(self, event):
        # Trigger an orchestrator ReAct loop with a specific intent.
        await self._orchestrator.run_goal(
            goal_id="intruder_response",
            inputs={"event": event.payload},
        )
```

### What changes in the codebase

* `app/modules/event_bridge.py` — already built; needs the
  `subscribe(topic, handler)` API exposed (currently it's
  publish-only from the loader side).
* `app/core/orchestrator.py` — add `attach_event_bridge(bridge)`
  and a `run_goal(goal_id, inputs)` entry point. ~30 lines.
* `main.py` — start the bridge between core boot and platform boot.

### Trade-offs

* **Pro:** The natural shape for **event_source / anomaly_detector /
  proactive_reaction** module types — exactly the surveillance
  / monitoring shape from `docs/newfind.md`.
* **Pro:** Decouples module authors from the orchestrator's ReAct
  loop. A new module can publish events without knowing how the
  orchestrator consumes them.
* **Pro:** Backpressure / drop-on-overflow semantics are easier
  to reason about in a single bridge than in scattered callers.
* **Con:** Event ordering and at-least-once delivery need careful
  design (the current `EventBridge` is fire-and-forget).
* **Con:** Debugging gets harder — events flow asynchronously and
  the audit trail must bridge the gap.

---

## 5. Hybrid (recommended)

No single option is best for every module type. The recommended
design is a **hybrid**:

| Module `provides` type | Boot path |
|---|---|
| `tool`, `agent`, `skill` | **Option A** (eager) — these are synchronous, called from the ReAct loop |
| `ui_surface` | **Option A** (eager) — UI panels must exist at dashboard render time |
| `event_source`, `anomaly_detector` | **Option C** (event-bridge) — these produce events, not calls |
| `proactive_reaction` | **Option C** (event-bridge) — these consume events and may trigger goals |

**Option B (lazy)** is useful only if the operator explicitly opts
into it (e.g., `--modules=lazy` flag) for very large module sets
on memory-constrained hosts. Default is eager + bridge.

Concretely:

```python
# main.py — recommended boot (sketch)
async def boot():
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    kernel = get_kernel()

    # 1. Start the event bridge BEFORE modules, so they can
    #    subscribe during load_all_enabled().
    bridge = EventBridge()
    await bridge.start()

    # 2. Module platform — eager for tool/agent/skill/ui,
    #    bridge-mediated for event_source/anomaly/proactive.
    registry = ModuleRegistry(kernel=kernel)
    registry.discover()
    loader = ModuleLoader(
        registry=registry, kernel=kernel, bridge=bridge,
    )
    await loader.load_all_enabled()

    # 3. Hand off to orchestrator.
    orchestrator.attach_module_registry(registry)
    orchestrator.attach_event_bridge(bridge)

    # 4. Existing platform-connector boot...
```

The hybrid is the shape that fits RAVEN as J.A.R.V.I.S.: always-on
tools, event-driven sensors and reactions, no lazy surprises.

---

## 6. Open questions before any code lands

1. **Atomic install at runtime.** `ModuleLoader.install()` /
   `uninstall()` is wired but never exercised. The first place to
   validate this is via a CLI smoke test, not in `main.py`.
2. **At-least-once event delivery.** `EventBridge` is fire-and-forget
   today. For surveillance (a stranger at the door) we want at
   least one observer to receive each event. Either:
   * ack-on-publish (publisher waits for at least one subscriber
     to acknowledge), or
   * outbox + replay (publish to a persistent log, subscribers
     consume at their own pace).
   The outbox pattern already exists in `app/runtime/outbox.py`
   (Phase 10) and could be reused.
3. **Trust gating for community modules.** `home_protection`
   declares `trust_level: community` and `enabled_by_default: false`.
   The boot path must NOT auto-load community modules on a fresh
   install. The kernel's `register_tool()` should refuse or warn.
4. **Audit hook.** Every module lifecycle event (install / enable /
   disable / uninstall / hot_load) should land in the audit log
   via `app.core.audit`. The loader already records some events;
   the API surface needs to do the same.
5. **Test isolation.** Module tests run against a fresh tmp module
   root. If we wire modules into `main.py`, the existing test
   suite needs an "ignore modules" escape hatch (env var or
   explicit `MODULE_ROOTS=[]`).

---

## 7. What this document is NOT

* Not a phased plan with deadlines. The three options above are
  shape choices, not commits.
* Not a guarantee that any of A / B / C will be shipped next. The
  current §7 backlog is empty at the code/infra layer; the operator-
  action items (real-hardware DoDs) take priority over new wiring.
* Not a substitute for reading the actual module-system source.
  Every section above assumes the reader has skimmed
  `app/modules/loader.py`, `app/modules/registry.py`, and
  `app/core/kernel.py` at least once.

---

## 8. Pointers into the code

| File | Lines | Role |
|---|---|---|
| `app/core/kernel.py` | 1–100 | Active capability graph; `register_tool` / `register_agent` / `get_capability_graph` |
| `app/modules/manifest.py` | 1–80 | Module manifest schema; `parse_manifest`; 7 `provides` types |
| `app/modules/loader.py` | 147–500 | `ModuleLoader`; the bridge between the two module systems |
| `app/modules/registry.py` | 70–210 | `ModuleRegistry`; typed record cache + graph hooks into the kernel |
| `app/modules/event_bridge.py` | 1–end | `EventBridge`; the pub/sub primitive for events and anomalies |
| `app/modules/cli.py` | 1–end | `ModuleCLI`; the `raven modules ...` command surface |
| `app/modules/dashboard.py` | 1–end | Module dashboard panel |
| `skills/community/home_protection/module.yaml` | 1–end | The one example module — surveillance, anomaly, proactive |
| `main.py` | 1–end | **Currently does not import from `app.modules`** — the gap |

---

*— end of integration options —*