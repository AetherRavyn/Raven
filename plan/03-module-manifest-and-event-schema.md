# 03 - Module Manifest and Event Schema Specification

**Project:** SARAS  
**Document purpose:** Define the canonical specification for SARAS modules, manifests, capabilities, permissions, lifecycle, health, and event contracts.  
**Scope:** This document is the foundation for building SARAS as a low-compute, modular, JARVIS / FRIDAY-class personal intelligence operating system.  
**Status:** Draft specification, intended to become the contract all future modules follow.  
**Date:** 2026-03-29

---

# 1. Why This Document Exists

SARAS is evolving from a large application into a **modular intelligence platform**.

That means every major subsystem must become a well-defined module:

- connectors
- memory backends
- voice engines
- prediction engines
- sensors
- planners
- safety/policy systems
- UI surfaces
- external perception systems like `agent_reach`

Without a strict module manifest and event schema, SARAS will become harder to extend, harder to reason about, and harder to operate safely.

This document defines:

1. the canonical **module manifest**
2. the canonical **event schema**
3. capability declarations
4. permission declarations
5. resource profiles
6. lifecycle/state model
7. health and status contracts
8. validation rules
9. examples for real SARAS module types

This document should be treated as the **contract layer** for all future architecture work.

---

# 2. Design Goals

The specification is designed to support these goals:

## 2.1 Replaceability
A module should be swappable without rewriting the entire system.

Examples:
- replace Chroma memory with pgvector
- replace local TTS with cloud TTS
- replace one web UI with another
- add a new connector
- add a new forecast engine

## 2.2 Safe extensibility
A module must explicitly declare:
- what it can do
- what it needs
- what resources it consumes
- what permissions it requires
- what events it accepts and emits

## 2.3 Low-compute routing
The system must know:
- which module is cheaper
- which one is faster
- which one can work offline
- which one needs GPU
- which one can run on edge devices

## 2.4 Observability
Every module must expose enough metadata to support:
- tracing
- audit
- health views
- debugging
- evaluation
- simulation replay

## 2.5 Product coherence
Modules are technical units, but SARAS must still feel like one intelligence.
So manifests must support:
- persona-linked modules
- presence-linked modules
- context-linked modules

---

# 3. Core Concepts

This spec introduces the following core objects:

- **Module**
- **Manifest**
- **Capability**
- **Permission**
- **Resource Profile**
- **Lifecycle State**
- **Health Report**
- **Event**
- **Event Payload**
- **Trace Context**
- **Dependency Contract**

---

# 4. Module Definition

A **module** is a runtime-loadable SARAS subsystem with:

- a unique identity
- a manifest
- lifecycle hooks
- optional config
- explicit dependencies
- explicit capabilities
- explicit permissions
- explicit event contracts
- health reporting
- status reporting

A module may be:

- built-in
- optional
- remote
- local
- edge
- experimental
- disabled by policy
- dynamically loaded in future versions

---

# 5. Canonical Module Categories

Every module must declare a `category`.

Allowed categories:

- `kernel`
- `connector`
- `memory`
- `voice`
- `provider`
- `tool`
- `planner`
- `prediction`
- `personality`
- `presence`
- `environment`
- `sensor`
- `safety`
- `policy`
- `audit`
- `analytics`
- `interface`
- `storage`
- `integration`
- `runtime`
- `worker`
- `utility`

A module may also declare `subcategories`.

Examples:
- `connector/telegram`
- `prediction/forecasting`
- `voice/stt`
- `voice/tts`
- `memory/episodic`
- `interface/dashboard`
- `integration/agent_reach`

---

# 6. Canonical Module Manifest

Every module must have a manifest file.

Recommended locations:

- `app/modules/<module_name>/module.yaml`
- `app/<domain>/<module_name>.module.yaml`
- `skills/<skill_name>/module.yaml`
- future remote registry location

Recommended formats:
- YAML preferred for readability
- JSON allowed for machine-only generation
- TOML allowed only if later standardized globally

The canonical field names below are format-agnostic.

---

# 7. Required Manifest Fields

Every manifest must include these required top-level fields.

## 7.1 Identity Fields

- `schema_version`
- `module_id`
- `display_name`
- `version`
- `category`
- `description`

### Rules

#### `schema_version`
Version of this manifest spec.
Example:
- `1.0`

#### `module_id`
Globally unique identifier in SARAS namespace.

Rules:
- lowercase
- dot-separated recommended
- must be stable over time
- should not change across patch versions

Examples:
- `connector.telegram`
- `memory.semantic.pgvector`
- `voice.tts.piper`
- `integration.agent_reach`
- `prediction.forecast.core`

#### `display_name`
Human-readable name.

Examples:
- `Telegram Connector`
- `Agent Reach Integration`
- `Piper TTS`
- `Forecast Core`

#### `version`
Semantic version string.

Examples:
- `1.0.0`
- `0.4.2`
- `2.1.0-beta.1`

#### `category`
One of the allowed categories.

#### `description`
Short human-readable summary.

---

# 8. Strongly Recommended Manifest Fields

These should exist on almost every module.

- `owner`
- `maintainers`
- `tags`
- `subcategory`
- `stability`
- `maturity`
- `homepage`
- `docs`
- `source_path`
- `entrypoint`
- `license`
- `enabled_by_default`

## 8.1 `stability`
Allowed values:
- `experimental`
- `alpha`
- `beta`
- `stable`
- `deprecated`

## 8.2 `maturity`
Allowed values:
- `prototype`
- `development`
- `production_candidate`
- `production`

---

# 9. Capability Declaration

A capability describes what a module can do.

Every module must declare at least one capability.

## 9.1 Capability Structure

Each capability object should include:

- `name`
- `kind`
- `description`
- `inputs`
- `outputs`
- `cost_class`
- `latency_class`
- `availability`
- `confidence_support`
- `side_effect_level`

## 9.2 Capability Field Rules

### `name`
Short unique name within module scope.

Examples:
- `send_message`
- `transcribe_audio`
- `store_memory`
- `generate_forecast`
- `fetch_topic_feed`

### `kind`
Allowed examples:
- `ingest`
- `retrieve`
- `transform`
- `reason`
- `predict`
- `actuate`
- `render`
- `route`
- `monitor`
- `analyze`

### `cost_class`
Allowed values:
- `tiny`
- `small`
- `medium`
- `large`
- `xlarge`

### `latency_class`
Allowed values:
- `realtime`
- `interactive`
- `background`
- `batch`

### `availability`
Allowed values:
- `always_on`
- `on_demand`
- `scheduled`
- `conditional`

### `confidence_support`
Whether output includes confidence metadata.
Allowed values:
- `none`
- `optional`
- `required`

### `side_effect_level`
Allowed values:
- `none`
- `low`
- `moderate`
- `high`
- `critical`

---

# 10. Permission Declaration

Every module must declare permissions explicitly.

Permissions are not implementation details.
They are part of the public contract.

## 10.1 Permission Categories

Permissions should be grouped under:

- `filesystem`
- `process`
- `network`
- `device`
- `database`
- `messaging`
- `identity`
- `autonomy`
- `external_accounts`

## 10.2 Standard Permission Names

### Filesystem
- `fs.read_workspace`
- `fs.write_workspace`
- `fs.read_external`
- `fs.write_external`
- `fs.delete_workspace`
- `fs.delete_external`
- `fs.create_temp`
- `fs.read_media`
- `fs.write_media`

### Process
- `proc.spawn_safe`
- `proc.spawn_shell`
- `proc.spawn_privileged`
- `proc.manage_services`

### Network
- `net.outbound_http`
- `net.outbound_https`
- `net.outbound_custom`
- `net.local_lan_access`
- `net.listen_local`
- `net.listen_public`
- `net.websocket_client`
- `net.websocket_server`

### Device
- `dev.microphone`
- `dev.speaker`
- `dev.camera`
- `dev.gpu`
- `dev.serial`
- `dev.gpio`
- `dev.bluetooth`

### Database
- `db.read`
- `db.write`
- `db.schema_migrate`
- `db.admin`

### Messaging
- `msg.send`
- `msg.receive`
- `msg.reply`
- `msg.proactive_send`
- `msg.mass_send`

### Identity / Secrets
- `secret.read_scoped`
- `secret.read_global`
- `secret.write`
- `identity.act_as_user`

### Autonomy
- `auto.schedule_task`
- `auto.execute_without_confirmation`
- `auto.trigger_modules`
- `auto.create_goal`

### External Accounts
- `acct.social_read`
- `acct.social_post`
- `acct.email_read`
- `acct.email_send`
- `acct.calendar_read`
- `acct.calendar_write`
- `acct.home_assistant_control`
- `acct.financial_api_access`

---

# 11. Permission Risk Levels

Each permission entry should also declare:

- `risk_level`
- `requires_approval`
- `scope`

## 11.1 Allowed `risk_level`
- `low`
- `moderate`
- `high`
- `critical`

## 11.2 Allowed `scope`
Examples:
- `workspace_only`
- `temp_only`
- `configured_hosts_only`
- `local_network_only`
- `specific_service_only`
- `global`
- `per_user`
- `admin_only`

---

# 12. Resource Profile Declaration

This is essential for low-compute SARAS.

Every module must declare a resource profile.

## 12.1 Required Resource Fields

- `startup_time_class`
- `steady_state_cpu`
- `burst_cpu`
- `steady_state_ram`
- `peak_ram`
- `network_usage`
- `storage_usage`
- `gpu_required`
- `offline_capable`
- `edge_capable`
- `remote_capable`
- `concurrency_class`

## 12.2 Allowed Values

### `startup_time_class`
- `instant`
- `fast`
- `moderate`
- `slow`
- `very_slow`

### `steady_state_cpu` / `burst_cpu`
- `tiny`
- `small`
- `medium`
- `large`
- `xlarge`

### `steady_state_ram` / `peak_ram`
- `tiny`
- `small`
- `medium`
- `large`
- `xlarge`

### `network_usage`
- `none`
- `light`
- `moderate`
- `heavy`

### `storage_usage`
- `none`
- `light`
- `moderate`
- `heavy`

### `gpu_required`
- `true`
- `false`
- `optional`

### `offline_capable`
- `true`
- `false`
- `partial`

### `edge_capable`
- `true`
- `false`
- `partial`

### `remote_capable`
- `true`
- `false`
- `partial`

### `concurrency_class`
- `single`
- `low_parallel`
- `medium_parallel`
- `high_parallel`

---

# 13. Dependency Declaration

Every module must declare dependencies explicitly.

## 13.1 Dependency Types

- `hard`
- `soft`
- `optional`
- `runtime_only`
- `dev_only`

## 13.2 Dependency Targets

Dependencies may point to:

- other SARAS modules
- Python packages
- Node services
- system binaries
- environment variables
- secrets
- network services
- ports
- storage backends
- model files

## 13.3 Recommended Dependency Fields

- `target`
- `type`
- `version_constraint`
- `reason`
- `fallback`
- `required_for_capabilities`

---

# 14. Config Schema Declaration

Each module should declare config requirements.

## 14.1 Required Config Metadata

- `required_config`
- `optional_config`

Each config item should define:

- `name`
- `type`
- `description`
- `sensitive`
- `default`
- `example`
- `validation`
- `scope`

## 14.2 Allowed Config Types

- `string`
- `integer`
- `float`
- `boolean`
- `array`
- `object`
- `enum`
- `duration`
- `url`
- `path`
- `secret_ref`

## 14.3 Allowed Config Scope

- `global`
- `per_user`
- `per_workspace`
- `per_module`
- `per_environment`

---

# 15. Lifecycle Contract

Every module must support a defined lifecycle.

## 15.1 Canonical Lifecycle States

- `discovered`
- `validated`
- `loaded`
- `initialized`
- `starting`
- `running`
- `degraded`
- `paused`
- `stopping`
- `stopped`
- `failed`
- `disabled`
- `uninstalled`

## 15.2 Required Lifecycle Methods

Each module implementation should expose these methods conceptually:

- `validate_manifest()`
- `validate_environment()`
- `load()`
- `initialize()`
- `start()`
- `stop()`
- `health()`
- `status()`
- `reload_config()`

## 15.3 Optional Lifecycle Methods

- `pause()`
- `resume()`
- `drain()`
- `self_test()`
- `migrate()`
- `cleanup()`

## 15.4 Lifecycle Rules

### Rule A
A module cannot enter `running` unless:
- manifest validates
- hard dependencies are satisfied
- required config is present
- required permissions are allowed by policy

### Rule B
A module may enter `degraded` if:
- soft dependency missing
- optional capability unavailable
- remote service partially down
- fallback mode available

### Rule C
A module must enter `failed` if:
- core capability broken
- dependency lost with no fallback
- policy violation blocks startup
- repeated health failure crosses threshold

---

# 16. Health Contract

Every module must provide health reports.

## 16.1 Health States

Allowed:
- `healthy`
- `degraded`
- `unhealthy`
- `unknown`

## 16.2 Required Health Report Fields

- `module_id`
- `state`
- `timestamp`
- `summary`
- `checks`
- `active_capabilities`
- `degraded_capabilities`
- `dependency_status`
- `last_error`
- `uptime_seconds`

## 16.3 Health Check Entry Fields

Each check should include:
- `name`
- `status`
- `severity`
- `message`
- `last_success_at`
- `last_failure_at`

## 16.4 Severity Levels

- `info`
- `warning`
- `error`
- `critical`

---

# 17. Status Contract

Health is about viability.
Status is about operating context.

## 17.1 Required Status Fields

- `module_id`
- `lifecycle_state`
- `health_state`
- `enabled`
- `version`
- `active_mode`
- `current_load_class`
- `queue_depth`
- `last_event_at`
- `metrics`
- `policy_state`

## 17.2 Example Metrics

Metrics are module-specific, but common fields may include:
- `requests_total`
- `errors_total`
- `avg_latency_ms`
- `peak_latency_ms`
- `events_in_total`
- `events_out_total`
- `cpu_hint`
- `ram_hint`

---

# 18. Event System Overview

The SARAS event schema is the backbone of modular communication.

Everything meaningful should be representable as an event.

Examples:
- message received
- voice transcription completed
- memory stored
- goal created
- forecast requested
- forecast completed
- policy denied
- approval requested
- sensor anomaly detected
- module degraded

---

# 19. Canonical Event Envelope

Every event must use a canonical envelope.

## 19.1 Required Event Fields

- `event_id`
- `event_type`
- `event_version`
- `timestamp`
- `source_module`
- `source_instance`
- `target_module`
- `target_scope`
- `trace_id`
- `span_id`
- `correlation_id`
- `priority`
- `delivery_mode`
- `payload`
- `metadata`

## 19.2 Field Definitions

### `event_id`
Unique event identifier.

### `event_type`
Dot-separated canonical event type.

Examples:
- `message.received`
- `voice.transcription.completed`
- `memory.semantic.saved`
- `forecast.requested`
- `forecast.completed`
- `policy.denied`
- `module.health.changed`

### `event_version`
Version of the event contract for this type.

### `timestamp`
RFC 3339 timestamp in UTC.

### `source_module`
Module emitting the event.

### `source_instance`
Instance identifier if multiple instances exist.

### `target_module`
Optional explicit recipient module.

### `target_scope`
Allowed values:
- `direct`
- `broadcast`
- `domain`
- `system`
- `user_session`

### `trace_id`
Cross-event trace identifier for full request chain.

### `span_id`
Step-level operation identifier.

### `correlation_id`
Group related events across retries/branches.

### `priority`
Allowed values:
- `low`
- `normal`
- `high`
- `urgent`
- `critical`

### `delivery_mode`
Allowed values:
- `sync`
- `async`
- `queued`
- `scheduled`
- `best_effort`

### `payload`
Event-specific object.

### `metadata`
Additional annotations.

---

# 20. Trace Context Specification

Traceability is mandatory.

## 20.1 Required Trace Fields in `metadata.trace`

- `request_id`
- `user_id`
- `session_id`
- `conversation_id`
- `goal_id`
- `task_id`
- `forecast_id`
- `policy_decision_id`
- `approval_id`

Not all are required on every event, but event producers should populate all relevant fields.

---

# 21. Canonical Metadata Fields

Recommended `metadata` structure:

- `trace`
- `tags`
- `source_kind`
- `security`
- `confidence`
- `cost`
- `locale`
- `platform`
- `user_context`
- `retention`

## 21.1 `metadata.security`
Suggested fields:
- `classification`
- `contains_sensitive_data`
- `requires_redaction`
- `policy_checked`
- `approval_required`

## 21.2 `metadata.confidence`
Suggested fields:
- `score`
- `method`
- `calibrated`
- `uncertainty_reasons`

## 21.3 `metadata.cost`
Suggested fields:
- `compute_class`
- `api_cost_estimate`
- `latency_budget_ms`

---

# 22. Event Type Taxonomy

SARAS should standardize event types by domain.

## 22.1 Message Events
- `message.received`
- `message.normalized`
- `message.routed`
- `message.reply.requested`
- `message.reply.sent`
- `message.failed`

## 22.2 Voice Events
- `voice.audio.received`
- `voice.transcription.requested`
- `voice.transcription.completed`
- `voice.transcription.failed`
- `voice.tts.requested`
- `voice.tts.completed`
- `voice.playback.started`
- `voice.playback.completed`

## 22.3 Memory Events
- `memory.session.appended`
- `memory.semantic.saved`
- `memory.semantic.retrieved`
- `memory.episodic.saved`
- `memory.profile.updated`
- `memory.conflict.detected`
- `memory.pruned`

## 22.4 Goal / Planning Events
- `goal.created`
- `goal.updated`
- `goal.completed`
- `task.created`
- `task.started`
- `task.blocked`
- `task.completed`
- `routine.triggered`

## 22.5 Prediction Events
- `forecast.requested`
- `forecast.started`
- `forecast.scenario.generated`
- `forecast.completed`
- `forecast.failed`
- `forecast.outcome.recorded`
- `forecast.calibration.updated`

## 22.6 Sensor / Environment Events
- `sensor.reading.received`
- `sensor.anomaly.detected`
- `camera.alert.received`
- `environment.state.changed`
- `home.action.requested`
- `home.action.executed`

## 22.7 Policy / Safety Events
- `policy.checked`
- `policy.denied`
- `approval.requested`
- `approval.granted`
- `approval.rejected`
- `audit.recorded`

## 22.8 Module / Runtime Events
- `module.loaded`
- `module.started`
- `module.stopped`
- `module.failed`
- `module.health.changed`
- `module.status.updated`

## 22.9 Reach / Internet Events
- `reach.query.requested`
- `reach.query.completed`
- `reach.source.ingested`
- `reach.topic.watch.updated`
- `reach.source.failed`
- `reach.signal.detected`

---

# 23. Event Payload Design Rules

The `payload` field is event-specific, but should follow universal rules.

## 23.1 Universal Rules

### Rule A
Payloads must be JSON-serializable.

### Rule B
Payloads must contain structured fields, not only freeform text.

### Rule C
Payloads should distinguish:
- raw input
- normalized representation
- derived fields

### Rule D
Payloads should support redaction where needed.

### Rule E
Payloads should preserve source attribution.

### Rule F
Prediction and recommendation payloads must support confidence fields.

---

# 24. Canonical Payload Schemas by Domain

## 24.1 `message.received` Payload

Required fields:
- `platform`
- `user_id`
- `chat_id`
- `message_id`
- `content_type`
- `text`
- `attachments`
- `reply_to_id`

Optional:
- `image_urls`
- `audio_url`
- `thread_id`
- `platform_metadata`

## 24.2 `voice.transcription.completed` Payload

Required:
- `audio_ref`
- `text`
- `language`
- `engine`
- `duration_ms`

Optional:
- `confidence`
- `segments`
- `hallucination_filtered`

## 24.3 `forecast.completed` Payload

Required:
- `forecast_id`
- `question`
- `domain`
- `method`
- `time_horizon`
- `primary_outcome`
- `confidence_score`
- `scenarios`
- `evidence`
- `assumptions`
- `recommended_actions`

Optional:
- `calibration_reference`
- `simulation_rounds`
- `cost_profile`
- `watch_signals`

## 24.4 `sensor.anomaly.detected` Payload

Required:
- `sensor_id`
- `location`
- `anomaly_type`
- `severity`
- `observed_value`
- `expected_range`
- `detected_at`

Optional:
- `supporting_sensors`
- `recommended_action`
- `confidence_score`

---

# 25. Canonical Confidence Schema

Some modules produce confidence-bearing outputs.
This must be standardized.

## 25.1 Confidence Object Fields

- `score`
- `scale`
- `method`
- `calibrated`
- `reasons`
- `counter_evidence`
- `uncertainty_sources`

## 25.2 Example

- `score`: `0.72`
- `scale`: `0_to_1`
- `method`: `ensemble_weighted`
- `calibrated`: `true`

---

# 26. Canonical Cost Schema

Useful for low-compute governance.

## 26.1 Cost Object Fields

- `compute_class`
- `estimated_cpu_ms`
- `estimated_ram_mb`
- `estimated_network_kb`
- `estimated_api_cost_usd`
- `cacheable`
- `cache_ttl_seconds`

---

# 27. Retention and Privacy Metadata

Each event should optionally declare retention hints.

## 27.1 Retention Fields

- `retention_class`
- `contains_pii`
- `contains_secrets`
- `redaction_policy`
- `storage_target`

## 27.2 Allowed `retention_class`
- `ephemeral`
- `session`
- `short_term`
- `long_term`
- `audit_permanent`

---

# 28. Validation Rules for Manifests

A manifest is invalid if any of the following occur:

1. missing required identity fields
2. invalid category
3. duplicate `module_id`
4. invalid semantic version
5. undeclared capability
6. permission declared with invalid name
7. missing resource profile
8. hard dependency missing target identifier
9. required config item missing type
10. lifecycle unsupported by runtime
11. illegal permission for module policy class
12. event types malformed
13. event payload schema absent for core event producers
14. module claims `offline_capable=true` but hard-depends on required remote service
15. module claims `edge_capable=true` while `gpu_required=true`

---

# 29. Validation Rules for Events

An event is invalid if:

1. missing `event_id`
2. missing `event_type`
3. missing `timestamp`
4. missing `source_module`
5. missing `payload`
6. malformed `event_type`
7. invalid `priority`
8. invalid `delivery_mode`
9. payload not serializable
10. trace fields malformed
11. confidence object malformed when required
12. policy-required metadata missing for sensitive event class

---

# 30. Recommended Manifest Example — Telegram Connector

```yaml
schema_version: "1.0"
module_id: "connector.telegram"
display_name: "Telegram Connector"
version: "1.0.0"
category: "connector"
subcategory: "telegram"
description: "Receives and sends Telegram messages, media, and replies."
owner: "SARAS Core"
stability: "beta"
maturity: "development"
enabled_by_default: true

capabilities:
  - name: "receive_message"
    kind: "ingest"
    description: "Receive Telegram updates and normalize them into SARAS events."
    inputs: ["telegram_update"]
    outputs: ["message.received"]
    cost_class: "small"
    latency_class: "realtime"
    availability: "always_on"
    confidence_support: "none"
    side_effect_level: "none"

  - name: "send_reply"
    kind: "actuate"
    description: "Send replies, files, and media to Telegram chats."
    inputs: ["message.reply.requested"]
    outputs: ["message.reply.sent"]
    cost_class: "small"
    latency_class: "interactive"
    availability: "always_on"
    confidence_support: "none"
    side_effect_level: "low"

permissions:
  - name: "msg.receive"
    risk_level: "low"
    requires_approval: false
    scope: "specific_service_only"

  - name: "msg.send"
    risk_level: "low"
    requires_approval: false
    scope: "specific_service_only"

  - name: "net.outbound_https"
    risk_level: "low"
    requires_approval: false
    scope: "specific_service_only"

resource_profile:
  startup_time_class: "fast"
  steady_state_cpu: "small"
  burst_cpu: "medium"
  steady_state_ram: "small"
  peak_ram: "small"
  network_usage: "moderate"
  storage_usage: "light"
  gpu_required: false
  offline_capable: false
  edge_capable: false
  remote_capable: true
  concurrency_class: "medium_parallel"

dependencies:
  - target: "python:python-telegram-bot"
    type: "hard"
    version_constraint: ">=22"
    reason: "Telegram API runtime"
    fallback: null
    required_for_capabilities: ["receive_message", "send_reply"]

required_config:
  - name: "TELEGRAM_BOT_TOKEN"
    type: "secret_ref"
    description: "Telegram bot token"
    sensitive: true
    default: null
    example: "secret://telegram/bot_token"
    validation: "non_empty"
    scope: "global"

optional_config: []

events_consumed:
  - "message.reply.requested"

events_emitted:
  - "message.received"
  - "message.reply.sent"
  - "message.failed"
  - "module.health.changed"
```

---

# 31. Recommended Manifest Example — Agent Reach Integration

```yaml
schema_version: "1.0"
module_id: "integration.agent_reach"
display_name: "Agent Reach Integration"
version: "1.0.0"
category: "integration"
subcategory: "internet_perception"
description: "Provides internet retrieval, source routing, and external signal ingestion using Agent Reach."

capabilities:
  - name: "source_query"
    kind: "retrieve"
    description: "Query supported internet sources and normalize results."
    inputs: ["reach.query.requested"]
    outputs: ["reach.query.completed"]
    cost_class: "medium"
    latency_class: "interactive"
    availability: "on_demand"
    confidence_support: "optional"
    side_effect_level: "none"

  - name: "source_ingest"
    kind: "ingest"
    description: "Ingest internet content into world and memory systems."
    inputs: ["reach.query.completed"]
    outputs: ["reach.source.ingested"]
    cost_class: "medium"
    latency_class: "background"
    availability: "on_demand"
    confidence_support: "optional"
    side_effect_level: "none"

permissions:
  - name: "net.outbound_https"
    risk_level: "moderate"
    requires_approval: false
    scope: "configured_hosts_only"

  - name: "secret.read_scoped"
    risk_level: "moderate"
    requires_approval: false
    scope: "per_module"

resource_profile:
  startup_time_class: "fast"
  steady_state_cpu: "small"
  burst_cpu: "medium"
  steady_state_ram: "small"
  peak_ram: "medium"
  network_usage: "heavy"
  storage_usage: "light"
  gpu_required: false
  offline_capable: "partial"
  edge_capable: false
  remote_capable: true
  concurrency_class: "medium_parallel"

events_consumed:
  - "reach.query.requested"

events_emitted:
  - "reach.query.completed"
  - "reach.source.ingested"
  - "reach.source.failed"
```

---

# 32. Recommended Manifest Example — Forecast Core

```yaml
schema_version: "1.0"
module_id: "prediction.forecast.core"
display_name: "Forecast Core"
version: "1.0.0"
category: "prediction"
subcategory: "forecasting"
description: "Low-compute forecast engine for structured scenario generation and confidence-scored outcome estimation."

capabilities:
  - name: "generate_forecast"
    kind: "predict"
    description: "Generate forecasts from event graphs, signals, and memory."
    inputs: ["forecast.requested"]
    outputs: ["forecast.completed"]
    cost_class: "medium"
    latency_class: "background"
    availability: "on_demand"
    confidence_support: "required"
    side_effect_level: "none"

permissions:
  - name: "db.read"
    risk_level: "low"
    requires_approval: false
    scope: "specific_service_only"

  - name: "db.write"
    risk_level: "moderate"
    requires_approval: false
    scope: "specific_service_only"

resource_profile:
  startup_time_class: "moderate"
  steady_state_cpu: "small"
  burst_cpu: "large"
  steady_state_ram: "medium"
  peak_ram: "large"
  network_usage: "light"
  storage_usage: "moderate"
  gpu_required: optional
  offline_capable: true
  edge_capable: false
  remote_capable: true
  concurrency_class: "low_parallel"

events_consumed:
  - "forecast.requested"

events_emitted:
  - "forecast.started"
  - "forecast.completed"
  - "forecast.failed"
  - "forecast.calibration.updated"
```

---

# 33. Canonical JSON Event Example — `message.received`

```json
{
  "event_id": "evt_01JZEXAMPLE0001",
  "event_type": "message.received",
  "event_version": "1.0",
  "timestamp": "2026-03-29T12:00:00Z",
  "source_module": "connector.telegram",
  "source_instance": "telegram-main",
  "target_module": "runtime.orchestrator",
  "target_scope": "direct",
  "trace_id": "trc_01JZTRACE0001",
  "span_id": "spn_01JZSPAN0001",
  "correlation_id": "cor_01JZCORR0001",
  "priority": "normal",
  "delivery_mode": "async",
  "payload": {
    "platform": "telegram",
    "user_id": "123456789",
    "chat_id": "123456789",
    "message_id": "98765",
    "content_type": "text",
    "text": "Help me plan tomorrow",
    "attachments": [],
    "reply_to_id": null
  },
  "metadata": {
    "trace": {
      "request_id": "req_01JZREQ0001",
      "user_id": "123456789",
      "session_id": "telegram_123456789",
      "conversation_id": "conv_01JZCONV0001"
    },
    "platform": "telegram",
    "source_kind": "prompt",
    "security": {
      "classification": "normal",
      "contains_sensitive_data": false,
      "requires_redaction": false,
      "policy_checked": false,
      "approval_required": false
    },
    "retention": {
      "retention_class": "session",
      "contains_pii": true,
      "contains_secrets": false,
      "redaction_policy": "standard_user_data",
      "storage_target": "conversation_store"
    }
  }
}
```

---

# 34. Canonical JSON Event Example — `forecast.completed`

```json
{
  "event_id": "evt_01JZFORECAST0001",
  "event_type": "forecast.completed",
  "event_version": "1.0",
  "timestamp": "2026-03-29T12:10:00Z",
  "source_module": "prediction.forecast.core",
  "source_instance": "forecast-main",
  "target_module": "interface.dashboard",
  "target_scope": "system",
  "trace_id": "trc_01JZTRACE0002",
  "span_id": "spn_01JZSPAN0042",
  "correlation_id": "cor_01JZCORR0042",
  "priority": "high",
  "delivery_mode": "queued",
  "payload": {
    "forecast_id": "fc_01JZFC0001",
    "question": "Will the current project likely slip this week?",
    "domain": "project",
    "method": "causal_rule_plus_pattern_match",
    "time_horizon": "7d",
    "primary_outcome": "Moderate delay risk",
    "confidence_score": 0.71,
    "scenarios": [
      {
        "name": "baseline",
        "likelihood": 0.53,
        "summary": "Project slips by 2 to 4 days."
      },
      {
        "name": "recovered",
        "likelihood": 0.31,
        "summary": "Delay avoided if blocker A is resolved within 48 hours."
      },
      {
        "name": "worse_case",
        "likelihood": 0.16,
        "summary": "Delay exceeds one week if scope expands."
      }
    ],
    "evidence": [
      "Two unresolved blockers remain open",
      "Recent output velocity declined over last three days",
      "Calendar load is significantly above norm"
    ],
    "assumptions": [
      "No scope reduction occurs",
      "Current staffing remains unchanged"
    ],
    "recommended_actions": [
      "Resolve blocker A within 48 hours",
      "Reduce meeting load tomorrow",
      "Freeze scope for remaining sprint"
    ],
    "watch_signals": [
      "Blocker A unresolved by Wednesday",
      "Design review introduces additional scope"
    ]
  },
  "metadata": {
    "trace": {
      "request_id": "req_01JZREQ9001",
      "user_id": "local",
      "session_id": "web_local",
      "conversation_id": "conv_01JZCONV9001",
      "forecast_id": "fc_01JZFC0001",
      "task_id": "tsk_01JZTASK8888"
    },
    "confidence": {
      "score": 0.71,
      "method": "ensemble_weighted",
      "calibrated": true,
      "uncertainty_reasons": [
        "Recent work velocity may be noisy",
        "Blocker resolution timing uncertain"
      ]
    },
    "cost": {
      "compute_class": "medium",
      "estimated_cpu_ms": 420,
      "estimated_ram_mb": 180,
      "estimated_network_kb": 12,
      "estimated_api_cost_usd": 0.0,
      "cacheable": true,
      "cache_ttl_seconds": 900
    },
    "security": {
      "classification": "analysis",
      "contains_sensitive_data": false,
      "requires_redaction": false,
      "policy_checked": true,
      "approval_required": false
    }
  }
}
```

---

# 35. Module UI Contract

Some modules expose UI widgets.

This should be declared in the manifest.

## 35.1 Widget Declaration Fields

- `widget_id`
- `title`
- `kind`
- `description`
- `supported_views`
- `required_events`
- `refresh_mode`

## 35.2 Allowed Widget Kinds

- `status_card`
- `timeline_panel`
- `chart_panel`
- `forecast_panel`
- `memory_panel`
- `voice_panel`
- `control_panel`
- `approval_inbox`
- `alert_feed`
- `module_metrics`

---

# 36. Policy Compatibility Contract

Module manifests must be checkable against policy.

A module may be blocked from load/start if:

- its permissions exceed allowed environment policy
- its risk profile exceeds deployment tier
- it requires secrets unavailable in current mode
- it requires GPU in a non-GPU deployment
- it requires public network binding in a restricted mode

Recommended policy classes:

- `personal_light`
- `personal_full`
- `home_guardian`
- `developer_lab`
- `restricted_safe_mode`
- `edge_node`
- `prediction_lab`

---

# 37. Deployment Tier Compatibility

Each module should optionally declare deployment tier compatibility.

## 37.1 Tiers

- `tier_a_ultralight`
- `tier_b_balanced`
- `tier_c_full`
- `tier_edge`
- `tier_remote_worker`

## 37.2 Example Usage

A module like `voice.tts.piper` may support:
- `tier_a_ultralight`
- `tier_b_balanced`
- `tier_c_full`

A simulation-heavy forecast engine may support:
- `tier_c_full`
- `tier_remote_worker`

---

# 38. Backward Compatibility Rules

## 38.1 Manifest Compatibility
- Patch updates must not break existing required fields.
- Minor updates may add optional fields.
- Major updates may change field meaning or structure.

## 38.2 Event Compatibility
- Event payloads must evolve compatibly when possible.
- Removing required fields requires event major version change.
- Adding optional fields is allowed in minor version updates.

---

# 39. Recommended File Naming Convention

Recommended names:

- `module.yaml`
- `module.json`
- `events.yaml`
- `health.schema.yaml`
- `ui.widgets.yaml`

For prediction modules:
- `forecast.schema.yaml`

For policy-heavy modules:
- `permissions.yaml`

---

# 40. Validation Checklist for Every New Module

Before a module is accepted into SARAS, verify:

- [ ] `module_id` is unique
- [ ] manifest validates against spec
- [ ] capabilities are declared clearly
- [ ] permissions are minimal and justified
- [ ] resource profile is realistic
- [ ] dependencies are explicit
- [ ] required config is documented
- [ ] lifecycle hooks exist
- [ ] health report contract exists
- [ ] status report contract exists
- [ ] event inputs are declared
- [ ] event outputs are declared
- [ ] sensitive data handling is declared
- [ ] tier compatibility is declared
- [ ] policy compatibility reviewed
- [ ] module has at least one example event
- [ ] module has test plan or self-test hook

---

# 41. Validation Checklist for Every New Event Type

Before a new event type is accepted:

- [ ] event name follows taxonomy
- [ ] event version defined
- [ ] payload contract documented
- [ ] producer module documented
- [ ] consumer modules documented
- [ ] retention/privacy rules defined
- [ ] confidence contract defined if applicable
- [ ] cost metadata defined if useful
- [ ] replay behavior understood
- [ ] failure mode understood

---

# 42. Implementation Guidance for SARAS

This document is specification, but it also implies implementation priorities.

## 42.1 First implementation targets
The first modules that should receive full manifests under this spec are:

1. `connector.telegram`
2. `connector.discord`
3. `connector.slack`
4. `connector.whatsapp`
5. `interface.web.dashboard`
6. `voice.stt.core`
7. `voice.tts.core`
8. `memory.semantic.core`
9. `runtime.orchestrator`
10. `integration.agent_reach`
11. `prediction.forecast.core`
12. `policy.core`
13. `audit.core`

## 42.2 First event families to standardize
1. `message.*`
2. `voice.*`
3. `module.*`
4. `memory.*`
5. `policy.*`
6. `forecast.*`
7. `sensor.*`
8. `reach.*`

---

# 43. Recommended Next Documents

After this document, the next planning documents should be:

1. `04-phased-task-checklist-with-file-map.md`
2. `05-policy-and-permission-matrix.md`
3. `06-health-status-and-observability-contracts.md`
4. `07-prediction-engine-event-and-payload-spec.md`
5. `08-ui-widget-and-command-center-spec.md`

---

# 44. Final Summary

This specification makes SARAS buildable as a real modular platform.

With this manifest and event schema in place, SARAS can support:

- low-compute routing
- safer module loading
- traceable actions
- auditable decisions
- richer dashboards
- replaceable subsystems
- future prediction engines
- first-class Agent Reach integration
- stronger personality/presence systems

In short:

> The module manifest defines **what a module is**.  
> The event schema defines **how modules talk**.  
> Together, they define **how SARAS becomes a real operating intelligence system**.

---

# 45. One-Sentence Doctrine

**Every SARAS capability must declare what it is, what it needs, what it costs, what it can emit, what it can consume, and how safely it can operate.**