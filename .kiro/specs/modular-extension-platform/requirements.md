# Requirements Document

## Introduction

The Modular Extension Platform turns AetherRavyn (Ravyn) from a fixed-capability agent into an
extensible platform. Today, skills are discovered through `SkillRegistry` via `module.yaml`
manifests, tools and agents are registered with `SystemKernel`, sensors live under `app/sensors/`,
and events flow into the ambient loop through `SentinelBridge` and `OutputRouter`. Each of these
extension points is wired separately and generally requires core code changes to add new behavior.

This feature defines a single, unified **module contract** that generalizes the existing
`module.yaml` manifest so that any user can package a **capability bundle** (any combination of
tools, specialist agents, skills, event sources, anomaly detectors, proactive reactions, and an
optional UI surface) into one installable **module**. AetherRavyn auto-discovers, validates,
resolves dependencies and secrets, assigns least-privilege permissions and sandboxing by trust
level, registers (hot-loads) the bundle into the running system, health-checks it, and supports
enable/disable and hot-unload/uninstall — without editing core code and, where feasible, without a
restart.

The driving example is a user-built home-protection module: it registers a camera event source,
runs an anomaly detector that raises a prioritized event into the ambient pipeline, grants Ravyn a
surveillance ability through new tools, and triggers a proactive reaction (alert the operator,
snapshot the camera, log the event). The module is bidirectional: it feeds events in, and the
orchestrator can act back through the module's tools.

The platform generalizes and reuses existing components rather than introducing a parallel system:
`SkillRegistry` (discovery, plugin tool loading, health reports), `SystemKernel` (capability graph
and module registration), `PolicyEngine` (permission evaluation and approval), `SandboxManager`
(Docker/subprocess/host isolation), `SecretVault` (encrypted secrets), `OutputRouter`
(priority-based delivery), `SentinelBridge` (event ingestion), `StandingOrderStore` (proactive
rules), `SwarmManager` (agent registration), and the `app/sensors/` plumbing.

## Glossary

- **Module**: A self-contained, installable package living in a single directory under a module
  root (e.g., `skills/`, `app/modules/`, or a user drop-in directory). A Module is described by one
  unified manifest (`module.yaml`) and may contribute any subset of a Capability Bundle. A Module
  generalizes the current notion of a "skill" so that the same contract covers tools, agents,
  sensors, detectors, and reactions.
- **Module Manifest**: The `module.yaml` declaration for a Module. It generalizes the existing
  skill manifest (`schema_version`, `module_id`, `version`, `category`, `capabilities`,
  `trust_level`, `dependencies`, `triggers`) by adding a `provides` section that enumerates the
  Capability Bundle, plus `required_permissions`, `required_secrets`, and
  `compatibility` constraints.
- **Capability Bundle**: The set of contributions a single Module registers with AetherRavyn. A
  bundle may contain any combination of: Tools (extending the tool layer), Agents (extending the
  swarm), Skills (`SKILL.md` procedures), Event Sources, Anomaly Detectors, Proactive Reactions,
  and an optional UI Surface.
- **Event Source**: A Module-provided sensor or input adapter (for example a camera feed, an MQTT
  topic subscription, or a webhook endpoint) that emits events into the ambient pipeline through the
  Event Bridge, reusing the existing `app/sensors/` and `SentinelBridge` plumbing.
- **Anomaly Detector**: A Module-provided component that inspects events or state from an Event
  Source and raises a prioritized event (mapped to an `OutputRouter` priority of CRITICAL, HIGH,
  NORMAL, LOW, or DIGEST) when a defined condition is met (for example motion, an unfamiliar face,
  or an environmental change).
- **Trust Level**: The privilege tier assigned to a Module, one of `system`, `workspace`, or
  `community`, consistent with the existing `trust_level` field. Trust Level determines default
  permission grants, sandboxing requirements, and whether elevated permissions require explicit
  operator approval.
- **Hot-load**: Registering a Module's Capability Bundle into the running AetherRavyn process so it
  becomes immediately usable, without restarting the process. **Hot-unload** is the inverse:
  removing the bundle from the running process.
- **Bidirectional Action**: The property that a Module both feeds events into AetherRavyn (inbound,
  via Event Sources and Anomaly Detectors) and exposes Tools and Agents that the orchestrator can
  invoke to act back through the Module (outbound).
- **Module_Platform**: The overarching system delivered by this feature, composed of the components
  below.
- **Module_Registry**: The component that discovers, validates, and tracks Modules. Generalizes the
  existing `SkillRegistry` and records Module state in the `SystemKernel` capability graph.
- **Module_Loader**: The component that orchestrates the Module lifecycle (validate, resolve,
  sandbox, register, health-check, enable/disable, hot-unload, uninstall).
- **Permission_Broker**: The component that evaluates a Module's requested permissions against its
  Trust Level and operator approvals, built on the existing `PolicyEngine`.
- **Health_Monitor**: The component that runs Module health checks and tracks consecutive failures
  for auto-disable, integrated with the ambient loop.
- **Event_Bridge**: The component that routes Module-emitted events into the ambient pipeline and
  `OutputRouter`, generalizing `SentinelBridge`.
- **Module_CLI**: The `ravyn`-command surface for listing, inspecting, scaffolding, installing,
  enabling, disabling, and uninstalling Modules.
- **Operator**: The authenticated primary user (admin) authorized to approve elevated permissions
  and manage Modules.

## Requirements

### Requirement 1: Unified Module Manifest

**User Story:** As a module author, I want a single declarative manifest that describes everything
my module provides, so that I can package tools, agents, skills, sensors, detectors, and reactions
without editing core code.

#### Acceptance Criteria

1. THE Module_Platform SHALL define a Module Manifest schema that extends the existing `module.yaml`
   fields (`schema_version`, `module_id`, `display_name`, `version`, `category`, `description`,
   `tags`, `capabilities`, `trust_level`, `enabled_by_default`, `stability`, `origin`, `triggers`,
   `dependencies`), designating `schema_version`, `module_id`, `display_name`, `version`, and
   `category` as mandatory fields and all other listed fields as optional with the same default
   values the current `SkillRegistry` applies.
2. THE Module Manifest SHALL include a `provides` section that enumerates zero or more Capability
   Bundle entries, where each entry is exactly one of the following contribution types: tool, agent,
   skill, event source, anomaly detector, proactive reaction, or UI surface.
3. THE Module Manifest SHALL include an optional `required_permissions` field that lists the
   permission identifiers the Module requests, and WHERE `required_permissions` is absent, THE
   Module_Platform SHALL treat the Module as requesting no permissions (an empty list).
4. THE Module Manifest SHALL include an optional `required_secrets` field that lists the secret key
   names the Module requires from the Secret Vault, and WHERE `required_secrets` is absent, THE
   Module_Platform SHALL treat the Module as requiring no secrets (an empty list).
5. THE Module Manifest SHALL include a `compatibility` field that declares the minimum supported
   AetherRavyn version as a semantic version (MAJOR.MINOR.PATCH) and the manifest `schema_version`
   the Module targets.
6. WHERE a manifest field defined by the existing skill manifest is present, THE Module_Platform
   SHALL interpret that field with the same meaning it has in the current `SkillRegistry`.
7. THE Module Manifest SHALL constrain the `trust_level` field to exactly one of the values
   `system`, `workspace`, or `community`.
8. IF a Module Manifest is missing a mandatory field or cannot be parsed, THEN THE Module_Platform
   SHALL reject the Module, SHALL NOT register any part of its Capability Bundle, and SHALL surface
   an error indication identifying the missing or unparseable field through the Module health report.

### Requirement 2: Module Discovery

**User Story:** As an operator, I want AetherRavyn to automatically find modules I drop into a
module directory, so that I do not have to register them manually in core code.

#### Acceptance Criteria

1. WHEN AetherRavyn starts or a discovery invocation is triggered, THE Module_Registry SHALL scan
   every configured module root for Module Manifests using the existing manifest discovery
   mechanism, recognizing `module.yaml`, `module.yml`, `manifest.json`, and `SKILL.md` frontmatter
   as valid Module Manifests.
2. IF a configured module root does not exist on the filesystem, THEN THE Module_Registry SHALL skip
   that module root, continue scanning the remaining configured module roots, and log the skipped
   module root path at debug level.
3. WHEN a Module directory containing at least one recognized Module Manifest is added to a
   configured module root, THE Module_Registry SHALL discover the Module on the next startup or
   discovery invocation without requiring any change to core code.
4. WHEN a discovered Module directory contains more than one recognized Module Manifest, THE
   Module_Registry SHALL select exactly one Module Manifest by applying the deterministic manifest
   precedence order, such that repeated scans of the same directory contents always select the same
   Module Manifest.
5. WHEN the Module_Registry discovers a Module, THE Module_Registry SHALL record the Module and its
   `category` in the SystemKernel capability graph.
6. IF a directory in a configured module root contains no recognized Module Manifest, THEN THE
   Module_Registry SHALL skip the directory, continue scanning the remaining directories, and log
   the skipped path at debug level.

### Requirement 3: Manifest Validation and Version Compatibility

**User Story:** As an operator, I want every module validated before it loads, so that malformed or
incompatible modules cannot destabilize the system.

#### Acceptance Criteria

1. WHEN a Module is discovered, THE Module_Loader SHALL validate the Module Manifest against the
   Module Manifest schema, confirming the presence of the required fields `schema_version`,
   `module_id`, `display_name`, `version`, `category`, and `description`, before any registration
   step.
2. IF a Module Manifest is missing any required field (`schema_version`, `module_id`,
   `display_name`, `version`, `category`, or `description`), THEN THE Module_Loader SHALL reject the
   Module, exclude it from all registration steps, record the names of the missing fields in a
   structured log entry, and leave the running system's set of registered Modules unchanged.
3. IF a Module Manifest contains an invalid field value — a `module_id` that is not lowercase
   alphanumeric segments separated by single dots or underscores, a `version` that is not a
   three-part semantic version (`MAJOR.MINOR.PATCH`), or a `trust_level` that is not one of
   `system`, `workspace`, or `community` — THEN THE Module_Loader SHALL reject the Module, exclude it
   from all registration steps, record the offending field name and value in a structured log entry,
   and leave the running system's set of registered Modules unchanged.
4. IF a Module Manifest declares a `compatibility` minimum AetherRavyn version that, compared as a
   three-part semantic version, is greater than the running AetherRavyn version, THEN THE
   Module_Loader SHALL reject the Module, exclude it from registration, and report a version
   incompatibility identifying both the required minimum version and the running version.
5. IF a Module Manifest declares a manifest `schema_version` that is not in the set of schema
   versions the Module_Platform supports, THEN THE Module_Loader SHALL reject the Module, exclude it
   from registration, and report an unsupported schema version identifying the declared
   `schema_version` value.
6. IF two or more discovered Modules declare the same `module_id`, THEN THE Module_Loader SHALL
   register only the Module whose manifest path sorts first in lexicographic order, reject every
   other Module declaring that `module_id`, and report the conflict identifying the duplicated
   `module_id` and the rejected manifest paths.

### Requirement 4: Dependency and Secret Resolution

**User Story:** As a module author, I want my module's dependencies and required secrets checked
before it activates, so that it never runs in a half-configured state.

#### Acceptance Criteria

1. WHEN a Module passes validation, THE Module_Loader SHALL evaluate each declared dependency using
   the existing dependency-check mechanism and SHALL assign each dependency a resolved status of
   satisfied, unsatisfied, or unknown.
2. IF a dependency marked `required` resolves to a status other than satisfied (unsatisfied or
   unknown), THEN THE Module_Loader SHALL withhold registration of the Module, SHALL retain any
   partially completed registration state in its pre-registration form (no Module artifacts
   persisted), and SHALL report each unmet required dependency by its declared name together with
   its resolved status.
3. WHEN a dependency that is not marked `required` resolves to a status other than satisfied, THE
   Module_Loader SHALL proceed with registration without blocking and SHALL record each such
   unsatisfied optional dependency by its declared name together with its resolved status.
4. WHEN a Module declares `required_secrets`, THE Module_Loader SHALL perform a presence check in the
   Secret Vault for each named secret key and SHALL determine each key as present or absent without
   reading or exposing any secret value.
5. IF one or more required secrets are absent from the Secret Vault, THEN THE Module_Loader SHALL
   withhold registration of the Module and SHALL report every absent secret key by name in a single
   result, without revealing any secret value.
6. WHEN the Module_Loader provides secrets to a Module, THE Module_Loader SHALL retrieve them from
   the Secret Vault at load time and SHALL exclude all secret values from log entries and audit
   entries, recording only secret key names where reference is required.

### Requirement 5: Trust Level, Permissions, and Sandbox Assignment

**User Story:** As an operator, I want untrusted modules to run with least privilege and isolation,
so that community modules cannot exceed the access I have granted.

#### Acceptance Criteria

1. WHEN a Module is loaded, THE Permission_Broker SHALL grant the Module only the permissions listed
   in its `required_permissions` that the existing PolicyEngine evaluates as allowed for the
   Module's Trust Level, and SHALL deny by default every permission not listed in
   `required_permissions`.
2. IF a Module's `required_permissions` includes a permission that the existing PolicyEngine does not
   grant by default for the Module's Trust Level (because the permission is absent from that Trust
   Level's granted set or is flagged as requiring confirmation), THEN THE Permission_Broker SHALL
   withhold that permission and SHALL require explicit Operator approval before granting it.
3. WHILE a Module has Trust Level `community`, THE Module_Loader SHALL execute the Module's
   contributed code within a Sandbox using the existing SandboxManager, selecting the Docker backend
   when Docker is available and falling back to the subprocess backend when Docker is unavailable.
4. WHILE a Module has Trust Level `workspace`, THE Module_Loader SHALL execute the Module's
   contributed code with subprocess-level isolation using the existing SandboxManager.
5. WHERE a Module has Trust Level `system`, THE Module_Loader SHALL permit the Module to run without
   sandbox isolation using the existing SandboxManager host (`none`) backend.
6. WHEN the Permission_Broker requires Operator approval for an elevated permission, THE
   Module_Platform SHALL keep the Module disabled until the Operator either approves or denies the
   request.
7. WHEN the Operator approves a pending elevated-permission request, THE Permission_Broker SHALL
   grant the requested permission to the Module and THE Module_Platform SHALL allow the Module to be
   enabled.
8. IF the Operator denies a pending elevated-permission request, THEN THE Permission_Broker SHALL
   withhold the requested permission and THE Module_Platform SHALL keep the Module disabled and
   report the denied permission.

### Requirement 6: Registration and Hot-load of the Capability Bundle

**User Story:** As an operator, I want a validated module to become usable immediately, so that I do
not have to restart AetherRavyn to gain new capabilities.

#### Acceptance Criteria

1. WHEN a Module passes validation, dependency, secret, and permission checks, THE Module_Loader
   SHALL register each item in the Module's Capability Bundle with its corresponding subsystem:
   tools with the tool layer and SystemKernel, agents with the SwarmManager, skills with the
   Module_Registry, event sources and detectors with the Event_Bridge, and reactions with the
   StandingOrderStore.
2. WHEN a Module is registered, THE Module_Loader SHALL hot-load the Capability Bundle into the
   running process without requiring a restart, completing within 5 seconds of the start of
   registration.
3. WHEN a tool or agent from a Module is registered, THE Module_Loader SHALL make that tool or agent
   available to the orchestrator so it can be invoked as a Bidirectional Action.
4. WHEN a Module registers successfully, THE Module_Platform SHALL set the Module state to enabled if
   `enabled_by_default` is true, and to disabled otherwise.
5. IF registering any item in a Module's Capability Bundle fails during hot-load, THEN THE
   Module_Loader SHALL deregister every item already registered for that Module from its subsystem,
   leave the running system in the state it held before registration began, set the Module state to
   disabled, and report the failed item and the failure reason.
6. WHEN an Operator requests registration of an already-registered `module_id`, THE Module_Loader
   SHALL hot-unload the existing registration before registering the new version.
7. IF registration of the new version fails after the existing registration has been hot-unloaded,
   THEN THE Module_Loader SHALL re-register the previously hot-unloaded version, restore its prior
   Module state, and report the registration failure.

### Requirement 7: Event Source and Anomaly Detector Integration

**User Story:** As a module author building surveillance, I want my module to register a camera
event source and an anomaly detector that raises prioritized events, so that AetherRavyn reacts to
what my sensor observes.

#### Acceptance Criteria

1. WHERE a Module provides an Event Source, THE Event_Bridge SHALL register the Event Source so that
   events it emits enter the ambient pipeline, reusing the existing `app/sensors/` plumbing
   (camera_bridge, mqtt_listener, webhook_server) and SentinelBridge.
2. IF registration of a Module's Event Source fails, THEN THE Event_Bridge SHALL isolate the failure
   to that Event Source, leave all previously registered Event Sources operational, and report the
   failure with an indication identifying the Event Source and the cause.
3. WHEN an Event Source emits an event, THE Event_Bridge SHALL deliver the event to every Anomaly
   Detector that the same Module registered for that Event Source.
4. WHEN an Anomaly Detector raises an event, THE Event_Bridge SHALL submit the event to the
   OutputRouter with the priority declared by the detector, where the priority is exactly one of
   CRITICAL, HIGH, NORMAL, LOW, or DIGEST.
5. IF an Anomaly Detector raises an event whose declared priority is missing or is not one of
   CRITICAL, HIGH, NORMAL, LOW, or DIGEST, THEN THE Event_Bridge SHALL submit the event to the
   OutputRouter with priority NORMAL and report the substitution with an indication identifying the
   detector and the invalid priority value.
6. WHEN an Anomaly Detector raises an event with priority CRITICAL, THE OutputRouter SHALL deliver
   the event to every configured Operator platform, including while the Operator is in a
   do-not-disturb state.
7. THE Module_Platform SHALL allow a single Module to express the home-protection example as one
   module: a camera Event Source, an anomaly Anomaly Detector, a surveillance Tool, and a Proactive
   Reaction that both alerts the Operator and captures a camera snapshot.

### Requirement 8: Proactive Reactions and Bidirectional Action

**User Story:** As a module author, I want my module to define standing reactions and expose tools,
so that AetherRavyn can act automatically on events and I can also trigger the module's abilities.

#### Acceptance Criteria

1. WHERE a Module provides a Proactive Reaction, THE Module_Loader SHALL register the reaction with
   the StandingOrderStore, recording the reaction's condition and its defined response.
2. WHEN an event matches the condition of a registered Proactive Reaction belonging to an enabled
   Module, THE Module_Platform SHALL submit the reaction's defined response to the OutputRouter with
   the priority declared by the reaction, where the priority is one of CRITICAL, HIGH, NORMAL, LOW,
   or DIGEST.
3. WHEN a Proactive Reaction's defined response invokes one or more of the Module's Tools, THE
   Module_Platform SHALL execute each invoked Tool subject to the Permission_Broker decision for the
   Module that owns the Tool.
4. WHEN the orchestrator selects a Tool contributed by an enabled Module and the Permission_Broker
   returns an allow decision for that Module, THE Module_Platform SHALL execute the selected Tool.
5. IF the Permission_Broker decision for a selected Module Tool requires Operator confirmation, THEN
   THE Module_Platform SHALL withhold execution of the Tool until the Operator responds, and SHALL
   execute the Tool only after the Operator approves the request.
6. IF the Permission_Broker denies execution of a Module Tool, THEN THE Module_Platform SHALL block
   the execution, leave the system state unchanged, and report the permission identifiers that the
   decision reported as missing.

### Requirement 9: Health Check and Failure Isolation

**User Story:** As an operator, I want a faulty module to be contained, so that a single bad module
cannot crash AetherRavyn.

#### Acceptance Criteria

1. WHEN a Module is registered, THE Health_Monitor SHALL run a health check covering manifest format
   validity, dependency status, and required-secret presence, reusing the existing health-report
   mechanism, and SHALL record the result as the Module's latest health status.
2. IF a Module's registration health check reports a failing manifest-format, dependency, or
   required-secret check, THEN THE Health_Monitor SHALL set the Module's latest health status to
   unhealthy and report the failing check without revealing any secret value.
3. IF a Module's contributed code raises an unhandled error during execution, THEN THE
   Module_Platform SHALL catch the error so that it does not propagate to the core process, SHALL
   keep the core process running, and SHALL record one consecutive execution failure against that
   Module.
4. WHEN a Module's contributed code completes execution without raising an error, THE Health_Monitor
   SHALL reset that Module's consecutive execution failure count to zero.
5. WHEN a Module's consecutive execution failure count reaches the configured threshold, THE
   Health_Monitor SHALL auto-disable the Module.
6. WHEN the Health_Monitor auto-disables a Module, THE Health_Monitor SHALL notify the Operator
   through the OutputRouter at HIGH priority, identifying the auto-disabled Module.
7. THE Health_Monitor SHALL expose a configurable consecutive-failure threshold that is an integer
   of at least 1, with a default value of 3 failures.
8. WHILE a Module is auto-disabled, THE Module_Platform SHALL exclude the Module's Capability Bundle
   from orchestrator tool selection, agent selection, event ingestion, and reactions.

### Requirement 10: Enable, Disable, Hot-unload, and Uninstall

**User Story:** As an operator, I want to turn modules on and off and remove them at runtime, so that
I can manage capabilities without downtime.

#### Acceptance Criteria

1. WHEN an Operator disables an enabled Module, THE Module_Loader SHALL hot-unload the Module's
   Capability Bundle from the running process, set the Module state to disabled, and complete the
   disable transition within 5 seconds on the development reference machine.
2. WHEN an Operator disables a Module that is already disabled, THE Module_Loader SHALL leave the
   Module state disabled and report that no state change occurred.
3. WHEN an Operator enables a disabled Module and all validation, dependency, secret, and permission
   checks pass, THE Module_Loader SHALL hot-load the Module's Capability Bundle into the running
   process and set the Module state to enabled.
4. IF any validation, dependency, secret, or permission check fails while an Operator enables a
   disabled Module, THEN THE Module_Loader SHALL withhold hot-load, leave the Module state disabled,
   report the failed check, and leave the running system unchanged.
5. WHEN an Operator uninstalls a Module, THE Module_Loader SHALL hot-unload the Capability Bundle if
   the Module is enabled, remove the Module from the Module_Registry and the SystemKernel capability
   graph, and delete the Module's files from its module directory.
6. IF deletion of a Module's files from its module directory fails during uninstall, THEN THE
   Module_Loader SHALL complete removal of the Module from the Module_Registry and the SystemKernel
   capability graph, report the file-removal failure indicating the affected path, and leave the
   Module deregistered.
7. WHEN a Module is hot-unloaded, THE Module_Loader SHALL deregister every item in the Module's
   Capability Bundle — its Tools and Agents from the tool layer, SystemKernel, and SwarmManager, its
   Skills from the Module_Registry, and its Event Sources, Anomaly Detectors, and Proactive Reactions
   from the Event_Bridge and StandingOrderStore — so that no further tool invocations, events, or
   reactions are produced by the Module.

### Requirement 11: Module Authoring Experience

**User Story:** As a module author, I want a scaffold command and a clear directory layout, so that I
can create and drop in a working module quickly.

#### Acceptance Criteria

1. WHEN an Operator runs the Module scaffold command with a Module name of 1 to 64 characters and a
   Module category of either `tool` or `agent`, THE Module_CLI SHALL create a Module directory
   containing a `module.yaml`, a `SKILL.md`, and one placeholder implementation file, placing the
   placeholder file under `app/tools/` when the category is `tool` and under `app/agents/` when the
   category is `agent`.
2. THE Module_CLI SHALL generate a scaffolded `module.yaml` that passes the Module Manifest
   validation defined in Requirement 3 without further edits, with all required manifest fields
   (`schema_version`, `module_id`, `display_name`, `version`, `category`) populated with valid
   values.
3. IF the scaffold command is invoked with an empty Module name, a name longer than 64 characters,
   or a name that resolves to a Module directory that already exists in the target location, THEN
   THE Module_CLI SHALL reject the request, create no files, leave the filesystem unchanged, and
   return an error indication describing the invalid or conflicting name.
4. WHEN an Operator drops a self-contained Module directory into a configured module root, THE
   Module_Platform SHALL install the Module from that local directory without requiring a network
   connection.
5. WHERE a Module marketplace source is configured, THE Module_CLI SHALL support installing a Module
   from the marketplace.
6. IF a marketplace install is requested while the configured marketplace source is unreachable,
   THEN THE Module_CLI SHALL abort the install, make no changes to the configured module roots, and
   return an error indication that the marketplace source is unavailable.

### Requirement 12: Discoverability and Management

**User Story:** As an operator, I want to list, inspect, and manage modules from the CLI and
dashboard, so that I always know what capabilities are active.

#### Acceptance Criteria

1. WHEN an Operator requests the Module list, THE Module_CLI SHALL display every discovered Module,
   ordered by `module_id`, with its `module_id`, `display_name`, `version`, Trust Level, and enabled
   or disabled state.
2. IF an Operator requests the Module list and no Modules have been discovered, THEN THE Module_CLI
   SHALL display a message indicating that no Modules are available.
3. WHEN an Operator inspects a Module by `module_id`, THE Module_CLI SHALL display the Module's
   Capability Bundle, `required_permissions`, `required_secrets`, dependency status, and the latest
   health-check result, and WHERE no health check has run for the Module, THE Module_CLI SHALL
   indicate that no health-check result is available.
4. IF an Operator inspects a Module whose `module_id` is not among the discovered Modules, THEN THE
   Module_CLI SHALL report an error indicating the Module was not found and SHALL leave the running
   system unchanged.
5. WHEN an Operator opens the Module management view in the Dashboard, THE Dashboard SHALL display
   the list of Modules and each Module's enabled or disabled state.
6. WHEN an Operator enables or disables a Module from the Dashboard, THE Module_Platform SHALL apply
   the same enable or disable behavior defined for the Module_CLI.
7. IF an enable or disable action initiated from the Dashboard fails, THEN THE Module_Platform SHALL
   retain the Module's prior enabled or disabled state and report the failure to the Operator.

### Requirement 13: Security and Audit Trail

**User Story:** As an operator, I want every module action recorded and elevated permissions gated,
so that I retain accountability over what modules do.

#### Acceptance Criteria

1. WHEN a Module is installed, enabled, disabled, or uninstalled, THE Module_Platform SHALL record
   an audit event through the existing ActionLogger that identifies the Module by `module_id`, the
   lifecycle action performed, the Operator who initiated the action, and whether the action
   succeeded or failed.
2. WHEN a Module Tool execution completes, THE Module_Platform SHALL record an audit event through
   the existing ActionLogger that identifies the Module by `module_id`, the Tool, and whether the
   execution succeeded or failed.
3. THE Module_Platform SHALL exclude secret values from all audit events and logs, recording only
   the secret key name wherever a Module's secret must be referenced.
4. WHEN a Module requests a permission that exceeds the default grant for its Trust Level and
   therefore requires Operator approval, THE Module_Platform SHALL record an audit event through the
   existing ActionLogger that captures the approval request and the requested permission identifier.
5. WHEN the Operator approves or denies an elevated-permission request, THE Module_Platform SHALL
   record an audit event through the existing ActionLogger that captures the Operator's identity,
   the decision outcome, and the affected `module_id`.

### Requirement 14: Backward Compatibility, Performance, and Observability

**User Story:** As a maintainer, I want existing skills, tools, and agents to keep working and module
loading to be fast and observable, so that adopting the platform does not regress the system.

#### Acceptance Criteria

1. THE Module_Platform SHALL continue to discover and load existing skills that use the current
   `module.yaml` and `SKILL.md` format through the existing `SkillRegistry` without requiring any
   change to those skills.
2. THE Module_Platform SHALL continue to register existing tools and agents through the existing
   SystemKernel and SwarmManager interfaces without requiring any change to those tools and agents.
3. WHEN an Operator hot-loads a single Module on the development reference machine, THE Module_Loader
   SHALL complete registration — measured from the start of registration to the point the Module's
   Capability Bundle is available — within 5 seconds.
4. IF a single Module's hot-load does not complete within 5 seconds on the development reference
   machine, THEN THE Module_Loader SHALL abort the hot-load, leave the running system in the state it
   held before registration began, set the Module state to disabled, and report a hot-load timeout
   identifying the Module.
5. WHEN any Module lifecycle transition occurs (discovery, validation, registration, enable, disable,
   uninstall, auto-disable), THE Module_Platform SHALL emit a structured log entry using
   `logging.getLogger(__name__)` that includes the Module `module_id`, the transition type, and the
   transition outcome.
6. THE Module_Platform SHALL exclude secret values from every Module lifecycle log entry.
7. IF a Module lifecycle transition fails, THEN THE Module_Platform SHALL emit the structured log
   entry for that transition at error level, including the failure reason.
8. WHEN the count of enabled or disabled Modules is requested, THE Module_Platform SHALL return the
   current count of enabled Modules and the current count of disabled Modules.

### Requirement 15: Optional UI Surface

**User Story:** As a module author, I want my module to optionally contribute a dashboard panel, so
that it can present its own status and controls.

#### Acceptance Criteria

1. WHERE a Module declares a UI Surface in its `provides` section, WHILE the Module is enabled, WHEN
   an Operator loads the Dashboard, THE Dashboard SHALL render the declared panel for the Module.
2. IF a Module's UI Surface raises an error or does not complete rendering within 5 seconds, THEN
   THE Dashboard SHALL omit that Module's panel, continue rendering all remaining Dashboard content
   unaffected, and display an indication on the Dashboard identifying the failed Module panel.
3. WHERE a Module does not declare a UI Surface, THE Module_Platform SHALL register the Module's
   remaining Capability Bundle without a UI panel.
4. WHEN a Module that declares a UI Surface is disabled or hot-unloaded, THE Dashboard SHALL remove
   that Module's panel from the Dashboard while continuing to render all remaining Dashboard content.
