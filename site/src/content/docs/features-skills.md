---
title: "Skills System & Procedural Memory"
---

# Skills System & Procedural Memory

RAVEN does not just have static tools; it has the ability to learn and crystallize new workflows into reusable Skills. This represents a leap from declarative memory (knowing facts) to procedural memory (knowing how to do something). The skills system comprises eight layers: SkillCrystallizer, SkillRegistry, SkillHub, SkillMarketplace, LearningStore, IntelligentRetriever, ConsolidationEngine, and the Modular Platform.

## 1. Complete Skill Lifecycle

The skill lifecycle follows a continuous loop:

```
Creation → Crystallization → Registration → Discovery → Execution → Refinement → (loop)
```

**Phase 1 — Creation**: An agent successfully completes a complex multi-step task involving 3+ tool calls. The execution trace is captured in `self._last_tool_traces` and passed to `_learn_from_turn()`.

**Phase 2 — Crystallization**: The `SkillCrystallizer` (`app/core/skill_crystallizer.py`) runs on a schedule (every 200 turns via TaskScheduler). It:
1. Queries the learning store for high-confidence execution traces
2. Reviews the successful execution path and intermediate tool calls
3. Identifies the core workflow pattern independent of specific parameters
4. Abstracts hardcoded variables into typed parameters
5. Generates a confidence score based on execution history

**Phase 3 — Registration**: The new skill is written as a structured YAML/Python definition to the skill store. The `SkillHub` registers it for future use. The skill record includes:
- `module_id`: Unique identifier (`skill.{name}`)
- `display_name`: Human-readable name
- `version`: Semantic version (default `0.1.0`)
- `category`: Skill type
- `description`: What the skill does
- `parameters`: Typed input parameters (with defaults, enums, descriptions)
- `body`: The workflow steps or code
- `success_rate`: Historical success percentage
- `usage_count`: How many times invoked
- `metadata`: Tags, capabilities, maintainers, dependencies

**Phase 4 — Discovery**: The `SkillRegistry` discovers all installed skills by scanning directories for manifests (`SKILL.md`, `module.yaml`, `manifest.json`). It validates health, checks dependencies, and builds an onboarding queue for incomplete skills.

**Phase 5 — Execution**: When a user query matches a skill's intent (via the `IntelligentRetriever` or `SkillInvoker`), the skill is injected into the active agent's system prompt as a matched skill block. The agent may then execute the skill's workflow steps through the normal tool-calling mechanism.

**Phase 6 — Refinement**: Each skill execution is tracked for success/failure. The `SkillCurator` (`app/core/skill_curator.py`) periodically evaluates skill quality, removes low-performing skills (success_rate < 0.3), promotes frequently used ones, and the ConsolidationEngine merges redundant skills.

### Crystallization Algorithm (Pseudocode)

```
function crystallize_all(min_confidence=0.6):
    traces = learning_store.query(type="successful_execution", min_confidence=min_confidence)
    skills = []
    for trace in traces:
        if trace.tool_count < 3: continue  # Skip simple tasks
        if already_crystallized(trace): continue  # Skip duplicates
        
        # Extract core pattern
        steps = analyze_trace(trace.tool_calls)
        # Abstract parameters
        params = extract_parameters(trace.inputs, trace.outputs)
        # Generate name and description
        name = generate_skill_name(steps)
        description = generate_description(steps)
        # Write skill definition
        skill = write_skill_yaml(name, description, params, steps)
        # Register in skill hub
        register_skill(skill)
        skills.append(skill.name)
    return skills
```

## 2. SkillCrystallizer (`app/core/skill_crystallizer.py`)

The SkillCrystallizer transforms successful execution traces into reusable skills.

### Trace Analysis

Each successful trace is analyzed for:
- **Tool sequence**: The ordered list of tools called (e.g., `[web_search, web_fetch, file_write]`)
- **Parameter patterns**: Which arguments were passed to each tool (e.g., `query`, `url`, `filepath`)
- **Output dependencies**: How the output of one tool feeds into the next
- **Conditional branches**: Decision points in the workflow
- **Error recovery**: How failures were handled

### Parameter Extraction

The crystallizer extracts parameters by analyzing:
1. Input values that differ between invocations (candidates for parameters)
2. Constant values that always appear (hardcoded into the skill)
3. Output fields that depend on parameters (documented in the skill)

Extracted parameters include:
- Name, type (string, integer, boolean, enum, filepath, URL)
- Description (auto-generated from usage)
- Default value (most common value from traces)
- Required/optional (based on whether the value was always present)
- Validation rules (regex patterns, min/max, allowed values)

### Crystallization Configuration

```python
class SkillCrystallizer:
    def __init__(self):
        self.min_confidence = 0.6       # Minimum confidence to crystallize
        self.min_tool_calls = 3         # Minimum tool calls for a skill
        self.max_skills_per_run = 10    # Cap per crystallization run
        self.parameter_detection = "auto"  # auto, manual, hybrid
```

## 3. SkillRegistry (`app/core/skill_registry.py`)

The `SkillRegistry` (719 lines) discovers and manages installed skills via manifest files.

### Manifest Discovery

The registry scans configured root directories for manifest files in priority order:

| File | Priority | Description |
|---|---|---|
| `module.yaml` | 0 (highest) | Canonical YAML manifest with all fields |
| `module.yml` | 0 | Alternative YAML extension |
| `manifest.json` | 1 | JSON format manifest |
| `SKILL.md` | 2 (lowest) | Markdown with YAML frontmatter |

Default root directories (relative to project root):
- `skills/` — user-installed skills
- `plugins/` — code-based plugins
- `agent_reach/skill/` — agent-created skills

### SKILL.md + module.yaml Manifest Format

**SKILL.md** (frontmatter + markdown body):
```yaml
---
module_id: skill.weather_report
display_name: Weather Report Generator
version: 1.0.0
category: skill
description: Fetches weather data and generates a formatted report
tags: [weather, report, automation]
capabilities: [weather, reporting]
parameters:
  - name: location
    type: string
    description: City or ZIP code
    required: true
  - name: days
    type: integer
    description: Forecast days (1-7)
    default: 3
    validation:
      min: 1
      max: 7
maintainers: [user@example.com]
stability: stable
---

## Steps

1. Call weather API for the specified location
2. Format the response as a structured report
3. Include temperature, humidity, wind, and precipitation
4. Add a human-readable summary at the top
```

**module.yaml** (canonical format):
```yaml
schema_version: "1.0"
module_id: skill.server_health
display_name: Server Health Monitor
version: 0.1.0
category: skill
description: Check system health and report anomalies
entrypoint: health.py:get_tools
tags: [system, monitoring, health]
capabilities: [system_stats, monitoring]
dependencies:
  - name: psutil
    status: available
    required: true
  - name: ping3
    status: available
    required: false
trust_level: workspace
enabled_by_default: true
```

### Health Reporting

Each discovered skill gets a health report with the following checks:
- `manifest_parse`: Can the manifest be parsed? (critical)
- `identity_fields`: Is display_name present? (critical)
- `canonical_fields`: Are schema_version, module_id, version present? (error if canonical)
- `version_format`: Is version semver-compatible? (warning)
- `category`: Is category in the standard set? (warning)
- `module_id`: Is ID properly normalized? (warning)
- `manifest_kind`: Is a canonical manifest used? (warning)
- `capabilities`: Are capabilities declared? (warning)

Health states: `healthy`, `degraded`, `unhealthy`

### Skill Query Matching

The `match_skills()` method (`app/core/skill_registry.py:645`) implements lightweight token-overlap matching:

```python
def match_skills(self, query: str, min_confidence: float = 0.0) -> list[dict]:
    query_tokens = [tok for tok in query.lower().split() if tok]
    for record in self.discover():
        if record.get("health_state") != "healthy": continue
        body = (record.get("body") or "").strip()
        if not body: continue
        haystack = " ".join(str(record.get(f) or "") for f in 
            ("display_name", "description", "body")).lower()
        matched = sum(1 for tok in query_tokens if tok in haystack)
        if matched == 0: continue
        confidence = matched / len(query_tokens)
        # ... add to results sorted by confidence
```

Capped at 25 candidates. Skills without a body are skipped.

## 4. SkillHub (`app/tools/skill_hub.py`)

The `SkillHubTool` provides the agent-callable interface for skill execution:
- `list_skills`: Returns available skills with descriptions
- `get_skill_info`: Returns detailed skill metadata
- `execute_skill`: Runs a skill's workflow steps
- `search_skills`: Semantic search across skill descriptions

## 5. SkillMarketplace (`app/core/skill_marketplace.py`)

Community skill sharing platform:
- **Import**: Download skills from community repositories (GitHub, local filesystem)
- **Export**: Pack crystallized skills with metadata for sharing
- **Version Management**: Track skill versions; support upgrades and downgrades
- **Dependency Resolution**: Automatically install skill dependencies
- **Trust Levels**: `workspace` (local), `community` (verified), `external` (unverified)

## 6. LearningStore Schema (`app/core/learning_db.py`)

Unified SQLite + FTS5 store for all learning signals (536 lines):

```sql
CREATE TABLE IF NOT EXISTS learnings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    type             TEXT    NOT NULL,        -- correction, fact, pattern, feedback, skill, swarm_result
    topic            TEXT    NOT NULL DEFAULT '',  -- categorization key
    content          TEXT    NOT NULL,        -- the learning content
    confidence       REAL    NOT NULL DEFAULT 0.5, -- 0.0 to 1.0
    metadata         TEXT    NOT NULL DEFAULT '{}', -- JSON blob
    source           TEXT    NOT NULL DEFAULT '',   -- origin identifier
    turn_created     INTEGER NOT NULL DEFAULT 0,
    turn_last_used   INTEGER NOT NULL DEFAULT 0,
    use_count        INTEGER NOT NULL DEFAULT 0,
    helpfulness_score REAL  NOT NULL DEFAULT 0.0,
    feedback_count   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
    topic, content, metadata,
    content='learnings',
    content_rowid='id',
    tokenize='porter unicode61'
);
```

### Learning Types

| Type | Description | Confidence Threshold | Retention |
|---|---|---|---|
| `correction` | User corrections mapped to interaction traces | 0.7 | 90 days |
| `fact` | Extracted facts from conversations | 0.5 | 180 days |
| `pattern` | Recurring behavior patterns | 0.6 | 90 days |
| `feedback` | Explicit and implicit preference signals | 0.8 | 30 days |
| `skill` | Crystallized skill definitions | 0.6 | Indefinite |
| `swarm_result` | Cross-agent learning results | 0.4 | 60 days |
| `exploration` | Curiosity-driven research findings | 0.3 | 30 days |

### CRUD Operations

```python
store = get_learning_store()

# Add
store.add(type_="fact", content="User prefers dark mode", topic="preferences",
          confidence=0.8, source="conversation")

# Search (FTS5)
results = store.search("dark mode preferences", limit=5, min_confidence=0.4)

# Record usage (updates turn_last_used, use_count)
store.record_use(item_id=42)

# Update confidence
store.update_confidence(item_id=42, confidence=0.9)

# Prune low-confidence items
result = store.prune(min_confidence=0.3)  # Returns {low_confidence: N, excess: M}

# Vacuum (reclaim space)
reclaimed = store.vacuum()

# Aggregate stats
stats = store.aggregate()  # Count by type, avg confidence, etc.
```

## 7. IntelligentRetriever

When the `MessageOrchestrator` receives a new prompt:

1. **Semantic Search**: The `IntelligentRetriever` performs FTS5 full-text search against the `LearningStore`
2. **Ranking**: Results are ranked by a combination of:
   - FTS5 relevance score (BM25)
   - Confidence score
   - Recency (turn_last_used)
   - Usage count
3. **Injection**: If a crystallized skill matches the prompt intent above the confidence threshold, the skill's text is injected into the active agent's system prompt as a `[Matched Skills]` block
4. **Fallback**: When no skill matches above threshold, falls back to general LLM reasoning
5. **Recording**: Skill invocations are recorded back to the `LearningTracker` for refinement

```python
# From runtime.py — skill injection in system prompt
invoker = get_skill_invoker()
matched_block = invoker.get_matched_skills_text(request.text)
if matched_block:
    system_content += "\n\n--- [Matched Skills] ---\n" + matched_block
```

## 8. ConsolidationEngine

The `ConsolidationEngine` (`app/core/consolidation.py`) is a background process that runs every 300 turns:

### Deduplication

- Detects semantically similar learning entries using FTS5 similarity
- Merges duplicate corrections, facts, and patterns
- Retains the highest confidence version
- Updates use counts and feedback scores on the surviving entry

### Pruning

- Removes items with confidence < 0.3 (low-confidence noise)
- Removes items unused for 90+ days (stale knowledge)
- Caps per-type maximums (e.g., max 1000 facts, 500 patterns)
- Reports pruning metrics to the event system

### Promotion

- Frequently used items (use_count > 10) get confidence boost (+0.1)
- Items with high helpfulness_score (> 0.8) are promoted to skills
- Promoted items are flagged and sent to SkillCrystallizer

### Contradiction Detection

- Identifies items with conflicting content on the same topic
- Flags contradictions for user resolution
- Reports contradictions in the learning health report

```python
# Consolidation result format
{
    "merges": 3,           # Duplicate merges performed
    "deletions": 12,       # Items pruned
    "promotions": [        # Items promoted to skills
        {"id": 42, "type": "pattern", "content": "..."}
    ],
    "contradictions": [    # Conflicting items found
        {"topic": "preferred_temperature", "items": [15, 23]}
    ]
}
```

## 9. Modular Platform (`app/modules/`)

The modular extension platform auto-discovers community modules:

### module.yaml Format

```yaml
schema_version: "1.0"
module_id: plugin.slack_integration
display_name: Slack Connector Plugin
version: 1.2.0
category: plugin
description: Extended Slack integration with custom commands
entrypoint: slack_plugin.py:get_tools
dependencies:
  - name: slack_sdk
    status: required
  - name: app.connectors.slack
    status: required
capabilities: [messaging, commands]
tags: [slack, communication]
stability: stable
trust_level: external
```

### Bootstrapping

On startup, `bootstrap_modular_platform()` in `app/core/bootstrapper.py`:
1. Scans `app/modules/` for module directories
2. Reads each `module.yaml` manifest
3. Validates dependencies and trust level
4. Calls the specified entrypoint function to register tools
5. Registers any new routines or schedules
6. Reports bootstrap success/failure for each module

### Hot-Plugging

Modules can be loaded at runtime without code changes:
```python
# From skill_registry.py load_plugin_tools
spec = importlib.util.spec_from_file_location(module_name, str(module_path))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
plugin_tools = getattr(module, func_name)()
```

Tools are registered into the runtime's tool dictionary and available for the next ReAct turn. Deregistration reverses the process:
```python
# From runtime.py
def deregister_tool(self, name: str) -> bool:
    return self.tools.pop(name, None) is not None
```

## 10. Configuration

```ini
# Skill crystallizer
SKILL_MIN_CONFIDENCE=0.6
SKILL_MIN_TOOL_CALLS=3
SKILL_MAX_PER_RUN=10
SKILL_CRYSTALLIZATION_INTERVAL_TURNS=200

# Learning store
LEARNING_DB_PATH=workspace/memory/learning.db
LEARNING_DEFAULT_CONFIDENCE=0.5
LEARNING_PRUNE_CONFIDENCE=0.3
LEARNING_PRUNE_UNUSED_DAYS=90

# Consolidation
CONSOLIDATION_INTERVAL_TURNS=300
CONSOLIDATION_MAX_FACTS=1000
CONSOLIDATION_MAX_PATTERNS=500
CONSOLIDATION_PROMOTION_THRESHOLD=0.8

# Skill registry
SKILL_ROOTS=skills,plugins,agent_reach/skill
SKILL_MAX_CANDIDATES=25
SKILL_MATCH_MIN_CONFIDENCE=0.0
```
