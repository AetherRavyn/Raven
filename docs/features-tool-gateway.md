# Tool Gateway

RAVEN's capability to act upon the world is defined by its massive Tool Gateway in `app/tools/`. The framework natively ships with **100+ tools** containing **over 110 tool classes** categorized by domain, all of which agents can invoke dynamically at runtime.

---

## 1. Architecture Overview

The tool system follows a layered architecture:

```
Layer 0: BaseTool ABC           (app/tools/base.py)
Layer 1: Optional ResilientWrapper   (app/tools/resilient.py)
Layer 2: Concrete Tool Impl     (app/tools/*.py)
Layer 3: Tool Discovery         (app/core/skill_registry.py, skill_hub)
Layer 4: Tool Router / Executor (orchestrator at runtime)
Layer 5: Resilience Decorators  (app/tools/resilience.py)
```

### 1.1 BaseTool ABC (`app/tools/base.py`)

Every tool is a subclass of `BaseTool` and must implement four abstract methods:

```
class BaseTool(ABC):
    group: str = "ungrouped"

    @abstractmethod
    def get_name(self) -> str
    @abstractmethod
    def get_description(self) -> str
    @abstractmethod
    def get_schema(self) -> ToolSchema
    @abstractmethod
    async def execute(**kwargs) -> dict[str, Any]
```

Supporting dataclasses:

| Class | Fields | Purpose |
|---|---|---|
| `ToolParameter` | `name, type, description, required, enum, default` | Defines a single parameter in OpenAI function-calling format |
| `ToolSchema` | `name, description, parameters: list[ToolParameter]` | Complete tool schema for LLM function calling |
| `ToolCapability` | `required_permissions, risk_level, cost_tier, confirmation_policy, readonly` | Security and risk metadata |

### 1.2 BaseResilientTool (`app/tools/resilient.py`)

An optional upgrade wrapper that adds automatic resilience to any tool:

| Feature | Mechanism |
|---|---|
| Timeout watchdog | `asyncio.wait_for` with configurable `timeout_s` |
| Circuit breaker | Opens after 3 consecutive timeouts, recovers after 10 min |
| Rate limiting | Sliding-window gate, configurable `rate_limit_per_min` |
| Result caching | By SHA-256 parameter hash with configurable TTL |
| Dry-run support | Returns the call that *would* be made without side effects |
| Audit outbox | Every call recorded before/after via envelope bridge |
| Retry on failure | Configurable via `retryable` flag (uses the resilience decorators) |

Tools opt in by subclassing `BaseResilientTool` instead of `BaseTool`.

### 1.3 ToolResult Convention

Every tool returns a `dict[str, Any]` with this shape:

```python
{
    "success": bool,       # Required — true/false
    "error": str | None,   # Human-readable error on failure
    ...                    # Domain-specific fields
}
```

Helper functions in `app/tools/__init__.py`:

```python
def tool_success(data=None, action=None, **kwargs) -> dict
def tool_error(msg, hint=None, action=None) -> dict
def deps_error(package, pip_install=None, action=None) -> dict
```

---

## 2. Tool Execution Lifecycle

```
LLM generates tool call JSON
        │
        ▼
┌─────────────────────────────────────┐
│ 1. Schema Validation                │
│    Orchestrator parses JSON params  │
│    against ToolSchema.parameters    │
│    Rejects on missing required      │
│    params or invalid enum values    │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 2. Security & Capability Check      │
│    a) required_permissions check    │
│    b) Risk level assessment         │
│    c) Confirmation policy:          │
│       - NEVER      → proceed        │
│       - ON_HIGH    → prompt if HIGH │
│       - ALWAYS     → prompt user    │
│    d) User approval gate            │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 3. Resilience Layer Wrappers        │
│    a) @with_retry (exponential      │
│       backoff, max_attempts=3)      │
│    b) @with_timeout (30s default)   │
│    c) @with_fallback (if configured)│
│    d) Circuit breaker check         │
│    e) Rate limiter check            │
│    f) Cache lookup                  │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 4. asyncio Execution                │
│    await tool.execute(**params)     │
│    in an async task with timeout    │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 5. Self-Correction (on failure)     │
│    SelfCorrector tries strategies:  │
│    a) relax_params                  │
│    b) simplify_query                │
│    c) add_timeout (halve limits)    │
│    d) switch_provider (log only)    │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│ 6. Output Normalization             │
│    Result formatted as Observation  │
│    Fed back to LLM context          │
└─────────────────────────────────────┘
        │
        ▼
LLM continues with tool output in context
```

### ASCII Flow Diagram

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ LLM Call │────>│ Tool Router  │────>│ Security     │
│  JSON    │     │ Parse/Verify │     │ Check        │
└──────────┘     └──────────────┘     └──────┬───────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ Resilience Layer │
                                    │ retry/timeout/   │
                                    │ fallback/circuit │
                                    │ breaker/cache    │
                                    └──────┬───────────┘
                                           │
                                           ▼
                                    ┌──────────────────┐
                                    │ asyncio.execute  │
                                    │ (with watchdog)  │
                                    └──────┬───────────┘
                                           │
                              ┌────────────┴────────────┐
                              │                         │
                              ▼                         ▼
                     ┌──────────────┐          ┌──────────────┐
                     │ Success      │          │ Failure      │
                     │ → cache hit  │          │ → Self-      │
                     │ → audit log  │          │   Corrector  │
                     │ → return     │          │ → retry/     │
                     │   result     │          │   fallback   │
                     └──────────────┘          └──────────────┘
```

---

## 3. Resilience Layer (`app/tools/resilience.py`)

### 3.1 Decorators

#### `@with_retry`

```python
@with_retry(
    max_attempts: int = 3,
    backoff_base: float = 1.5,
    retry_on: tuple = (Exception,),
    skip_on: tuple = (KeyboardInterrupt, SystemExit, asyncio.CancelledError),
)
```

Applies exponential backoff: delays are `backoff_base ** (attempt - 1)` seconds. After all attempts exhausted, re-raises the last exception. Never retries `KeyboardInterrupt`, `SystemExit`, or `CancelledError`.

#### `@with_timeout`

```python
@with_timeout(seconds: float = 30.0)
```

Wraps the tool in `asyncio.wait_for`. On timeout, raises `TimeoutError` with the tool name and configured timeout duration.

#### `@with_fallback`

```python
@with_fallback(fallback_fn: Callable)
```

If the primary tool raises any `Exception`, the fallback async callable is invoked with the same kwargs.

### 3.2 Error Standardization

```python
standardize_error(
    tool_name: str,
    error: Exception,
    context: str = "",
    recoverable: bool = True,
) -> dict
```

Returns a consistent error dict with fields: `success`, `error`, `error_type`, `tool`, `context`, `recoverable`, `suggestion`.

Error-type-aware suggestions:
| Error Pattern | Suggestion |
|---|---|
| timeout/timed out | "The service is slow. Try again in a moment." |
| connection/connect | "Cannot reach the service. Check network connectivity." |
| 401/403/unauthorized | "Authentication failed. Check API keys or credentials." |
| 404/not found | "The requested resource was not found." |
| rate/limit/429 | "Rate limited. Wait a moment before retrying." |
| permission/denied | "Permission denied. Check access rights." |
| FileNotFoundError/OSError | "File system error. Check paths and permissions." |
| JSONDecodeError | "Received invalid response data." |

### 3.3 Circuit Breaker

```python
class ToolCircuitBreaker(
    failure_threshold: int = 5,
    cooldown_seconds: float = 60.0,
)
```

States: `CLOSED` (normal) → `OPEN` (blocking) → `HALF_OPEN` (test after cooldown). Tracks failure count, records success/failure, and provides `allow_request()`, `record_success()`, `record_failure()`, `to_dict()`.

### 3.4 Self-Correction

```python
class SelfCorrector:
    def add_strategy(self, name: str, modifier: Callable) -> None
    async def correct(self, tool_fn, tool_name, kwargs, error) -> Any | None
```

Default strategies:

| Strategy | Trigger | Action |
|---|---|---|
| `relax_params` | "invalid", "required", "missing" in error | Remove None-valued optional kwargs |
| `simplify_query` | "no results", "empty", "not found" | Truncate query to first 3 words |
| `add_timeout` | "timeout", "timed out" | Halve `limit`, `max_results`, `top_k`, `max_chars` |
| `switch_provider` | "rate", "429", "overloaded" | Log suggestion to switch provider |

Strategies are tried in order until one succeeds. If none succeed, the original error is returned.

---

## 4. Tool Security Tiers

### 4.1 Risk Levels

| Level | Description | Examples | Confirmation Policy |
|---|---|---|---|
| `LOW` | Read-only, no side effects, no external calls | `weathertool`, `wolframtool`, `translation` | `NEVER` |
| `MEDIUM` | External API calls, moderate resource usage | `browsertool`, `websearch`, `webfetch` | `ON_HIGH_RISK` |
| `HIGH` | System mutation, shell execution, dangerous ops | `shelltool`, `elevatedtool`, `dockertool` | `ALWAYS` |

### 4.2 Permission Requirements

Each tool declares `required_permissions` in its `ToolCapability`:

| Permission | Tools |
|---|---|
| `browser:control` | `browsertool` |
| `shell.exec` | `shelltool`, `sandbox`, `exectool` |
| `filesystem.write` | `filetool` (mutating ops) |
| `system.control` | `elevatedtool`, `desktoptool`, `computeruse` |
| `network.diagnostics` | `network` |
| `calendar:read` | `calendar`, `google_calendar`, `outlook_calendar` |
| `calendar:write` | `calendar`, `google_calendar` (create events) |
| `mail:send` | `mail` |
| `camera.access` | `camerasnapshottool`, `videostreamtool` |
| `docker.control` | `dockertool`, `docker_exec_tool` |

### 4.3 Confirmation Policies

| Policy | Behavior |
|---|---|
| `NEVER` | Execute without asking |
| `ON_HIGH_RISK` | Ask for confirmation only when risk_level=HIGH |
| `ALWAYS` | Always ask for confirmation before executing |

### 4.4 SSRF Protection

The `NetworkTool` has built-in SSRF protection: it rejects targets that resolve to private/loopback addresses (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1`).

The `filetool` has path traversal protection: operations are restricted to a configurable `base_directory` and paths are validated with `resolve()` plus `relative_to()` checks.

The `shelltool` has a security guard integration: commands are analyzed before execution and rejected if flagged dangerous.

---

## 5. Complete Tool Inventory (100+ Tool Files)

### 5.1 Web & Network (12 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 1 | `websearch.py` | `WebOperationTool` | LOW | Web search via configured search engine |
| 2 | `webfetch.py` | `WebFetchOperationTool` | LOW | HTTP fetch with markdown conversion |
| 3 | `browsertool.py` | `BrowserOperationTool` | MEDIUM | 22+ Playwright browser ops: navigate, click, type, screenshot, extract, scroll, tab mgmt, cookies, JS |
| 4 | `urltool.py` | `URLMetadataTool`, `SSLMonitorTool` | LOW | URL metadata extraction, link validation, SSL monitoring |
| 5 | `youtube.py` | `YouTubeTool` | LOW | YouTube video search, metadata, transcript |
| 6 | `twittertool.py` | `TwitterTool` | LOW | Twitter/X timeline reading, trending, hashtag search |
| 7 | `reddittool.py` | `RedditTool` | LOW | Reddit content monitoring, hot posts, comments |
| 8 | `rssreadertool.py` | `RSSReaderTool` | LOW | RSS/Atom feed polling, parsing, summarization |
| 9 | `session_search.py` | `SessionSearchTool` | LOW | Session-based persistent search across tools |
| 10 | `searxngtool.py` | `SearXNGTool` | LOW | Self-hosted SearXNG search engine integration |
| 11 | `internetinteltool.py` | `InternetIntelTool` | LOW | Internet intelligence: WHOIS, DNS, IP reputation |
| 12 | `network.py` | `NetworkTool` | MEDIUM | Network diagnostics: ping, DNS, ports, traceroute, SSRF-safe |

### 5.2 Development (10 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 13 | `gittool.py` | `GitOperationTool` | MEDIUM | Git: clone, pull, commit, push, branch, diff, log, status, stash, tag, cherry-pick |
| 14 | `dockertool.py` | `DockerTool` | HIGH | Docker lifecycle: run, stop, exec, logs, ps, images, build |
| 15 | `docker_exec_tool.py` | `DockerExecTool` | HIGH | Execute commands inside running Docker containers |
| 16 | `shelltool.py` | `ShellTool` | HIGH | Shell execution via SandboxManager (Docker/subprocess), security guard, resource limits |
| 17 | `exectool.py` | `ExecTool` | HIGH | Generic command execution with timeout and output cap |
| 18 | `sandbox.py` | `SandboxExecTool` | HIGH | Restricted subprocess execution with forced Docker sandbox |
| 19 | `acptool.py` | `AcpTool` | LOW | Agent Communication Protocol tool |
| 20 | `desktoptool.py` | `DesktopControlTool` | MEDIUM | Desktop automation: window list/focus/launch, clipboard, volume, workspaces |
| 21 | `computeruse.py` | `ComputerUseTool` | HIGH | Full computer control: screenshot, click, type, key, mouse_move via pyautogui |
| 22 | `pathchtool.py` | `ApplyPatchTool` | MEDIUM | AST-based code patching and modification |

### 5.3 File & Document (9 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 23 | `filetool.py` | `AdvancedFileOperationTool` | MEDIUM | 50+ file ops: read/write/search/glob, archive, hash, CSV, batch, symlink, base64 |
| 24 | `document_parser.py` | `PDFReaderTool`, `DocxReaderTool`, `ExcelReaderTool` | LOW | PDF, DOCX, XLSX parsing and text extraction |
| 25 | `document_generator.py` | `PDFGeneratorTool`, `DocxGeneratorTool`, `ExcelGeneratorTool`, `CSVGeneratorTool`, `HTMLGeneratorTool` | MEDIUM | PDF, DOCX, Excel, CSV, HTML generation from data |
| 26 | `writetool.py` | `WriteTodosTool` | LOW | Structured todo list writing with validation |
| 27 | `deliverfiletool.py` | `DeliverFileTool` | MEDIUM | File delivery to platforms (email, upload, etc.) |
| 28 | `obsidian.py` | `ObsidianOperationTool` | MEDIUM | Obsidian vault integration: read/write notes, search, graph |
| 29 | `session_search.py` | `SessionSearchTool` | LOW | File content search with session persistence |
| 30 | `kgtool.py` | `KnowledgeGraphTool` | LOW | Knowledge graph file operations and triple store queries |
| 31 | `drivetool.py` | `DriveTool` | MEDIUM | Google Drive file listing, download, upload |

### 5.4 Productivity & Calendar (8 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 32 | `calendar.py` | (has `CalendarTool`) | MEDIUM | Unified Google Calendar + CalDAV interface |
| 33 | `google_calendar.py` | `GoogleCalendarTool` | MEDIUM | Google Calendar-specific CRUD operations |
| 34 | `outlook_calendar.py` | `OutlookCalendarTool` | MEDIUM | Outlook/CalDAV calendar operations |
| 35 | `mail.py` | `MailTool` | MEDIUM | SMTP send + Gmail API read inbox/search |
| 36 | `email_drafter.py` | `EmailDrafterTool` | LOW | AI-powered email drafting based on context |
| 37 | `meeting_notes.py` | `MeetingNotesTool` | LOW | Meeting notes generation and summarization |
| 38 | `remindertool.py` | `ReminderTool` | LOW | Reminder creation, listing, marking done |
| 39 | `pomodorotool.py` | `PomodoroTool` | LOW | Pomodoro timer: start, stop, status, sessions |

### 5.5 Database & Data (6 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 40 | `database_connector.py` | `DatabaseConnector` | MEDIUM | SQLite/MySQL/PostgreSQL read-only queries, schema, tables |
| 41 | `dbschedulertool.py` | `DatabaseQueryTool`, `SchedulerTool` | MEDIUM | DB-backed scheduling and query execution |
| 42 | `data_visualization.py` | `ChartGeneratorTool`, `TableVisualizerTool` | LOW | Chart/graph generation (matplotlib), table rendering |
| 43 | `financetools.py` | `StockQuoteTool`, `CryptoAlertTool`, `DNSLookupTool`, `HaveIBeenPwnedTool`, `URLVirusScanTool`, `CronManagerTool` | LOW | Financial data, security lookups, cron management |
| 44 | `cryptopricetool.py` | `CryptoPriceTool` | LOW | Cryptocurrency price tracking for multiple coins |
| 45 | `finance/__init__.py` | `FinanceOperationTool` | LOW | Yahoo Finance: quotes, overviews, statements, sectors, commodities |

### 5.6 Smart Home & IoT (5 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 46 | `smarthometool.py` | `SmartHomeTool` | MEDIUM | Home Assistant entity query and control (lights, switches, services) |
| 47 | `sensorreadtool.py` | `SensorReadTool` | LOW | Direct sensor/binary_sensor values from Home Assistant |
| 48 | `camerasnapshottool.py` | `CameraSnapshotTool` | MEDIUM | Camera snapshot capture from HA camera entities |
| 49 | `airqualitytool.py` | `AirQualityTool` | LOW | Air quality monitoring data |
| 50 | `weathertool.py` | `WeatherTool` | LOW | Current weather + 5-day forecast via OpenWeatherMap |

### 5.7 AI & ML (9 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 51 | `imagegentool.py` | `ImageGenerationTool` | MEDIUM | Image generation via xAI Aurora API |
| 52 | `xaiimagetool.py` | `XAIImageUnderstandTool` | MEDIUM | xAI Grok Vision image analysis and understanding |
| 53 | `localmltool.py` | `LocalMLTool` | LOW | Local ML model inference (ONNX, transformers) |
| 54 | `videostreamtool.py` | `VideoStreamTool` | MEDIUM | Video stream analysis, motion detection, WebSocket streaming |
| 55 | `translation.py` | `TranslationTool` | LOW | Multi-language translation (Google Translate or LibreTranslate) |
| 56 | `wolframtool.py` | `WolframAlphaTool` | LOW | Wolfram Alpha computational knowledge and answers |
| 57 | `jupypertool.py` | `JupyterTool` | MEDIUM | Jupyter notebook: create, execute cells, read outputs |
| 58 | `learning_system.py` | `LearningSystemTool` | LOW | RAVEN learning system tools for RLHF and preference capture |
| 59 | `free_apis.py` | `FreeInformationAPIs` | LOW | 15+ free public APIs: Wikipedia, DuckDuckGo, CoinGecko, etc. |

### 5.8 Knowledge & Memory (5 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 60 | `memorytool.py` | `MemoryTool` | LOW | Agent memory CRUD: store, recall, search, forget |
| 61 | `kgtool.py` | `KnowledgeGraphTool` | LOW | Knowledge graph triple store: add, query, delete triples |
| 62 | `contexttool.py` | `ContextTool` | LOW | Context management: store/retrieve conversation context |
| 63 | `batchtool.py` | `BatchTool` | MEDIUM | Batch processing of multiple queued tool calls |
| 64 | `rollbacktool.py` | `RollbackTool` | MEDIUM | Operation rollback: undo recent mutating tool actions |

### 5.9 MCP & Integration (5 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 65 | `mcptool.py` | `MCPManagementTool` | MEDIUM | MCP server connection management: list, connect, disconnect, register |
| 66 | `agencytool.py` | `AgencyDelegationTool` | MEDIUM | Agent-to-agent communication and delegation |
| 67 | `workflowtool.py` | `WorkflowTool` | MEDIUM | Multi-step workflow execution with state management |
| 68 | `skill_hub.py` | `SkillHubTool` | LOW | Skill registry browsing, discovery, and loading |
| 69 | `skill_manage.py` | `SkillManagementTool` | MEDIUM | Skill CRUD: create, update, delete, enable, disable |

### 5.10 Communication (4 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 70 | `messagingtool.py` | `PlatformMessagingTool` | MEDIUM | Cross-platform message sending (API-based) |
| 71 | `mail.py` | `MailTool` | MEDIUM | Email send/read/search via SMTP + Gmail API |
| 72 | `twittertool.py` | `TwitterTool` | LOW | Twitter/X timeline reading and posting |
| 73 | `reddittool.py` | `RedditTool` | LOW | Reddit monitoring and posting via PRAW |

### 5.11 Security & System (9 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 74 | `virustool.py` | `VirusTotalTool` | LOW | VirusTotal file hash and URL scanning |
| 75 | `systemstatstool.py` | `SystemStatsTool` | LOW | CPU, memory, disk, network, process monitoring |
| 76 | `network.py` | `NetworkTool` | MEDIUM | Network diagnostics, SSRF-safe, port scanning |
| 77 | `elevatedtool.py` | `ElevatedModeTool` | HIGH | Privileged operation management with sudo elevation |
| 78 | `totpgentool.py` | `TOTPGeneratorTool` | MEDIUM | TOTP 2FA code generation (RFC 6238), secret management |
| 79 | `monitoring_tool.py` | `MonitoringTool` | LOW | System monitoring: CPU, memory, disk, processes |
| 80 | `memorytool.py` | `MemoryTool` | LOW | Memory analysis and management |
| 81 | `health_tracker.py` | `HealthTrackerTool` | LOW | Health metric tracking and visualization |
| 82 | `governancetool.py` | `GovernanceTool` | MEDIUM | Agent governance: rules, policies, compliance checks |

### 5.12 Transportation & Travel (3 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 83 | `commutetool.py` | `CommuteTool` | LOW | Route calculation, travel time, directions via OSRM |
| 84 | `trip_planner.py` | `TripPlannerTool` | LOW | Trip planning with multi-stop routing |
| 85 | `maps_geocoding.py` | `MapsGeocodingTool` | LOW | Geocoding, reverse geocoding, map data |

### 5.13 Shopping & Commerce (3 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 86 | `shopping_tool.py` | `ShoppingTool` | LOW | Shopping list management and price comparison |
| 87 | `financetools.py` | `StockQuoteTool`, `CryptoAlertTool` | LOW | Stock/crypto transaction tracking |
| 88 | `finance/__init__.py` | `FinanceOperationTool` | LOW | Market overview, sector ETFs, commodities |

### 5.14 Toolkit Subdirectory (6 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 89 | `toolkit/github.py` | `GitHubTool` | MEDIUM | Full GitHub API: repos, branches, PRs, issues, actions, gists, releases, search |
| 90 | `toolkit/supabasetool.py` | `SupabaseTool` | MEDIUM | Supabase CRUD, storage, RPC, auth operations |
| 91 | `toolkit/google/docs.py` | (Docs tool) | MEDIUM | Google Docs read/write |
| 92 | `toolkit/google/gmailtool.py` | (Gmail tool) | MEDIUM | Gmail send/search/manage |
| 93 | `toolkit/google/googlecalendar.py` | (Calendar tool) | MEDIUM | Google Calendar operations |
| 94 | `toolkit/google/sheet.py` | (Sheets tool) | MEDIUM | Google Sheets read/write |
| 95 | `toolkit/notes/notion.py` | NotionTool | MEDIUM | Notion API: pages, databases, search |

### 5.15 Miscellaneous (3 files)

| # | File | Class(es) | Risk | Description |
|---|---|---|---|---|
| 96 | `airtabletool.py` | `AirtableTool` | MEDIUM | Airtable bases, tables, records CRUD |
| 97 | `lineartool.py` | `LinearTool` | MEDIUM | Linear issue tracking: issues, projects, teams |
| 98 | `ocrtool.py` | `OcrTool` | LOW | OCR text extraction from images via Tesseract |
| 99 | `academic_research.py` | `ArxivSearchTool`, `SemanticScholarTool` | LOW | Academic paper search on arXiv and Semantic Scholar |
| 100 | `mobiletool.py` | `MobileDeviceTool` | MEDIUM | Mobile device management: ADB, notifications |
| 101 | `autonomytool.py` | `AutonomyTool` | MEDIUM | Autonomous agent mode configuration |
| 102 | `screenreadertool.py` | `ScreenReaderTool` | LOW | Screen content reading and OCR |
| 103 | `music/spotify.py` | `SpotifyOperationTool` | MEDIUM | Spotify playback control, playlists, search |
| 104 | `news/hackernews.py` | `HackerNewsTool` | LOW | Hacker News top stories, comments, search |
| 105 | `home_protection/home_protection.py` | `HomeProtectionTool` | MEDIUM | Home security monitoring and alerts |
| 106 | `cli_demo_module/cli_demo_module.py` | `CliDemoModuleTool` | LOW | CLI demonstration and interaction |
| 107 | `edgetool.py` | `EdgeDeviceTool` | MEDIUM | Edge device management, task dispatch, result checking |
| 108 | `todolisttool.py` | `TodoListTool` | LOW | Todoist task management: create, complete, list, update |

---

## 6. Performance Characteristics

### 6.1 Typical Execution Times

| Category | P50 | P95 | P99 | Notes |
|---|---|---|---|---|
| Read-only data lookup (weather, crypto, translation) | 200-500ms | 2s | 5s | External API latency |
| File operations (read/write local) | 1-10ms | 50ms | 200ms | Local filesystem |
| Web search/fetch | 500ms-2s | 5s | 15s | Network + pagination |
| Browser automation (click/navigate) | 1-3s | 8s | 20s | Playwright + page load |
| Shell command execution | varies | 30s | 60s | Depends on command |
| Image generation (Aurora) | 3-8s | 15s | 30s | Model inference |
| Document parsing (PDF/DOCX) | 100ms-1s | 3s | 10s | File size dependent |
| Git operations | 100ms-2s | 5s | 15s | Repo size dependent |
| Docker operations | 500ms-5s | 15s | 30s | Image pull dominates |
| Database queries | 10-100ms | 1s | 5s | Query complexity dependent |

### 6.2 Timeout Configuration

| Tool | Default Timeout | Notes |
|---|---|---|
| All tools (BaseResilientTool) | 30s | Configurable via `metadata.timeout_s` |
| `webfetch` | 30s | Large pages may need more |
| `browsertool` | 15s per op | Configurable via `timeout_ms` param |
| `shelltool` | 60s | Configurable via `timeout` param |
| `dockertool` | 120s | Image pulls can be slow |
| `imagegentool` | 60s | Model generation latency |

### 6.3 Retry Behavior

Default retry: 3 attempts with exponential backoff (1.5x base):
- Attempt 1: immediate
- Attempt 2: after 1.5s
- Attempt 3: after 2.25s

Total worst-case retry time before failure: ~3.75s + tool execution time.

---

## 7. Configuration Options

### 7.1 Per-Tool Configuration

Tools read configuration from `app/settings/config.py` (the `Config` class):

```python
# Common tool config keys
Config.OPENWEATHERMAP_API_KEY    # weathertool
Config.DEFAULT_LOCATION          # weathertool fallback
Config.GITHUB_TOKEN              # toolkit/github.py
Config.TWITTER_BEARER_TOKEN      # twittertool
Config.REDDIT_CLIENT_ID          # reddittool
Config.REDDIT_CLIENT_SECRET      # reddittool
Config.HOME_ASSISTANT_URL        # smarthometool, sensorreadtool
Config.HOME_ASSISTANT_TOKEN      # smarthometool, sensorreadtool
Config.SMTP_SERVER               # mail
Config.SMTP_USERNAME             # mail
Config.GMAIL_CREDENTIALS_FILE    # mail (Gmail API)
Config.CALENDAR_PROVIDER         # calendar (google/outlook)
Config.OPENAI_API_KEY            # various LLM-dependent tools
Config.XAI_API_KEY               # imagegentool, xaiimagetool
Config.SEARXNG_BASE_URL          # searxngtool
Config.ALLOW_HOST_SHELL_EXECUTION # sandbox.py
Config.TODOIST_API_TOKEN         # todolisttool
Config.NOTION_API_KEY            # toolkit/notes/notion.py
Config.LINEAR_API_KEY            # lineartool
Config.AIRTABLE_API_KEY          # airtabletool
Config.SUPABASE_URL              # toolkit/supabasetool.py
Config.SUPABASE_KEY              # toolkit/supabasetool.py
```

### 7.2 Tool Registration

Tools are auto-discovered by the skill registry. To register a new tool, ensure it's importable from `app/tools/` and extends `BaseTool`. The `group` class attribute controls categorization:

```python
group = "ungrouped"  # default
group = "development"
group = "automation"
group = "communication"
group = "system"
group = "agent"
```

---

## 8. How to Add a New Tool

### Step 1: Create the file in `app/tools/`

```python
# app/tools/exampletool.py  (illustrative snippet — not a shipped file)
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.base import (
    BaseTool,
    ToolCapability,
    ToolParameter,
    ToolSchema,
)
from app.tools.resilience import with_retry, with_timeout, standardize_error
from app.settings.config import Config

logger = logging.getLogger(__name__)

_API_URL = "https://api.example.com/v1"


class ExampleTool(BaseTool):
    """Fetch data from Example API."""

    group = "ungrouped"

    def get_name(self) -> str:
        return "example_query"

    def get_description(self) -> str:
        return (
            "Query the Example API for resource data. "
            "Supports listing resources, getting details, and searching."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform: list, get, search",
                    required=True,
                    enum=["list", "get", "search"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for search action)",
                    required=False,
                ),
                ToolParameter(
                    name="resource_id",
                    type="string",
                    description="Resource ID (for get action)",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results (default 10)",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=[],
            risk_level="low",
            cost_tier="low",
            confirmation_policy="none",
            readonly=True,
        )

    @with_retry(max_attempts=3, backoff_base=2.0)
    @with_timeout(seconds=15)
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "list")
        api_key = Config.EXAMPLE_API_KEY

        if not api_key:
            return {"success": False, "error": "EXAMPLE_API_KEY not configured"}

        headers = {"Authorization": f"Bearer {api_key}"}
        params = {}

        try:
            if action == "list":
                url = f"{_API_URL}/resources"
                params["limit"] = kwargs.get("limit", 10)

            elif action == "get":
                resource_id = kwargs.get("resource_id")
                if not resource_id:
                    return {"success": False, "error": "resource_id required"}
                url = f"{_API_URL}/resources/{resource_id}"

            elif action == "search":
                query = kwargs.get("query")
                if not query:
                    return {"success": False, "error": "query required"}
                url = f"{_API_URL}/search"
                params["q"] = query
                params["limit"] = kwargs.get("limit", 10)

            else:
                return {"success": False, "error": f"Unknown action: {action}"}

            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, params=params, timeout=10)

            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"API error {resp.status_code}: {resp.text[:200]}",
                }

            data = resp.json()
            return {"success": True, "action": action, "data": data}

        except httpx.TimeoutException:
            return standardize_error(
                tool_name=self.get_name(),
                error=TimeoutError("Example API timed out"),
                context=f"action={action}",
            )
        except Exception as exc:
            logger.exception("ExampleTool failed")
            return standardize_error(
                tool_name=self.get_name(),
                error=exc,
                context=f"action={action}",
            )
```

### Step 2: Register in Config (if API keys needed)

Add to `app/settings/config.py`:

```python
EXAMPLE_API_KEY: str = os.getenv("EXAMPLE_API_KEY", "")
```

### Step 3: Write tests

```python
# tests/tools/test_exampletool.py  (illustrative snippet — not a shipped file)
from __future__ import annotations

import pytest

from app.tools.exampletool import ExampleTool  # illustrative only — file not shipped


@pytest.fixture
def tool():
    return ExampleTool()


@pytest.mark.asyncio
async def test_get_name(tool):
    assert tool.get_name() == "example_query"


@pytest.mark.asyncio
async def test_get_schema_has_required_params(tool):
    schema = tool.get_schema()
    assert schema.name == "example_query"
    assert len(schema.parameters) >= 1
    action_param = [p for p in schema.parameters if p.name == "action"]
    assert len(action_param) == 1
    assert action_param[0].required is True
    assert "list" in action_param[0].enum


@pytest.mark.asyncio
async def test_execute_missing_action(tool):
    result = await tool.execute()
    assert result["success"] is False


@pytest.mark.asyncio
async def test_execute_unknown_action(tool):
    result = await tool.execute(action="invalid")
    assert result["success"] is False
    assert "unknown" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_get_capabilities_defaults(tool):
    caps = tool.get_capabilities()
    assert caps.risk_level == "low"
    assert caps.readonly is True
```

### Step 4: Using BaseResilientTool (for built-in resilience)

Alternatively, extend `BaseResilientTool` for automatic timeout, circuit breaker, rate limiting, caching, and audit:

```python
from app.tools.resilient import BaseResilientTool, ToolMetadata

class ExampleResilientTool(BaseResilientTool):
    metadata = ToolMetadata(
        risk_level="low",
        timeout_s=15.0,
        retryable=True,
        cacheable=True,
        cache_ttl_s=60.0,
        side_effect=False,
        rate_limit_per_min=30,
        dry_run_supported=True,
    )

    async def _do_run(self, **kwargs) -> dict:
        # Your implementation here
        pass
```

---

## 9. Test Patterns for Tools

### 9.1 Unit Test Template

```python
import pytest
from app.tools.base import ToolSchema, ToolCapability

class TestMyTool:
    """Test suite for a tool — covers schema, execution, and edge cases."""

    # ── Schema Tests ──────────────────────────────────
    def test_name(self, tool):
        assert tool.get_name() == "expected_name"

    def test_description_is_not_empty(self, tool):
        assert len(tool.get_description()) > 10

    def test_schema_has_parameters(self, tool):
        schema = tool.get_schema()
        assert isinstance(schema, ToolSchema)
        assert len(schema.parameters) > 0

    def test_schema_required_params(self, tool):
        schema = tool.get_schema()
        required = [p for p in schema.parameters if p.required]
        assert len(required) >= 1

    def test_schema_enums_are_valid(self, tool):
        schema = tool.get_schema()
        for p in schema.parameters:
            if p.enum:
                assert all(isinstance(v, str) for v in p.enum)

    # ── Capability Tests ──────────────────────────────
    def test_capabilities_valid_level(self, tool):
        caps = tool.get_capabilities()
        assert caps.risk_level in ("low", "medium", "high")

    def test_readonly_tools_no_side_effects(self, tool):
        caps = tool.get_capabilities()
        if caps.readonly:
            assert caps.risk_level != "high"

    # ── Execution Tests ───────────────────────────────
    @pytest.mark.asyncio
    async def test_execute_success(self, tool):
        result = await tool.execute(...)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_missing_required(self, tool):
        result = await tool.execute()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_invalid_enum(self, tool):
        result = await tool.execute(action="nonexistent")
        assert "success" in result and not result.get("success", True)

    @pytest.mark.asyncio
    async def test_execute_no_crash_on_empty(self, tool):
        result = await tool.execute(action="", ...)
        assert isinstance(result, dict)

    # ── Error Handling Tests ──────────────────────────
    @pytest.mark.asyncio
    async def test_error_has_human_readable_message(self, tool):
        result = await tool.execute(action="invalid")
        if not result["success"]:
            assert isinstance(result.get("error"), str)
            assert len(result["error"]) > 0

    @pytest.mark.asyncio
    async def test_error_never_exception(self, tool):
        # Tools must catch all exceptions and return dict
        result = await tool.execute(action="trigger_error")
        assert isinstance(result, dict)
```

### 9.2 Mocking External Dependencies

```python
@pytest.mark.asyncio
async def test_webfetch_mocked(monkeypatch):
    async def mock_get(*args, **kwargs):
        return MockResponse(200, "<html><body>Hello</body></html>")

    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
    from app.tools.webfetch import WebFetchOperationTool
    tool = WebFetchOperationTool()
    result = await tool.execute(url="https://example.com")
    assert result["success"] is True
```

### 9.3 Resilience Layer Tests

```python
from app.tools.resilience import (
    with_retry,
    with_timeout,
    with_fallback,
    standardize_error,
    ToolCircuitBreaker,
)

def test_standardize_error_always_has_suggestion():
    err = standardize_error("test_tool", TimeoutError("timed out"))
    assert err["suggestion"]
    assert err["success"] is False
    assert err["tool"] == "test_tool"

def test_circuit_breaker_opens_after_threshold():
    cb = ToolCircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    assert cb.allow_request() is True
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.allow_request() is False
```

---

## 10. Tool Discovery & Registration

Tools are discovered through two mechanisms:

### 10.1 Auto-Discovery

The `SkillRegistry` in `app/core/skill_registry.py` scans `app/tools/` directories and subdirectories for modules containing classes that extend `BaseTool`. This happens at startup.

### 10.2 MCP Integration

The `MCPManagementTool` (`mcptool.py`) allows agents to dynamically:
- List available/public MCP servers
- Connect to custom MCP servers at runtime
- Register custom servers with command/args
- Browse tools by server
- Disconnect servers

Connected MCP servers expose additional tools beyond the 100+ built-in tools.

### 10.3 Manual Registration

Tools can also be manually registered in the orchestration layer:

```python
from app.tools.weathertool import WeatherTool
from app.tools.websearch import WebOperationTool

registry = get_tool_registry()
registry.register(WeatherTool())
registry.register(WebOperationTool())
```

---

## 11. Tool Group Categories

The `group` class attribute on each tool controls categorization for agent routing:

| Group | Example Tools |
|---|---|
| `ungrouped` | Default for most tools |
| `development` | `ShellTool`, `GitOperationTool`, `DockerTool` |
| `automation` | `BrowserOperationTool`, `DesktopControlTool` |
| `communication` | `MailTool`, `PlatformMessagingTool` |
| `system` | `SystemStatsTool`, `ComputerUseTool`, `ElevatedModeTool` |
| `agent` | `MCPManagementTool`, `AgencyDelegationTool` |

The agent supervisor uses these groups to match tools to agent capabilities.

---

## 12. Tool Output Size Limits

| Tool | Max Output | Truncation Strategy |
|---|---|---|
| `webfetch` | 15,000 chars | Truncated with `...[TRUNCATED]` |
| `browsertool` extract_text | 15,000 chars | Truncated with `...[TRUNCATED]` |
| `shelltool` | 8,000 bytes | Truncated with `...[output truncated]` |
| `gittool` | 8,000 chars | Configurable `MAX_OUTPUT_LENGTH` |
| `filetool` read | 10 MB | Rejection if file exceeds `max_file_size` |
| `mail` | 5,000 chars per email | Truncated subject/body |
| `kgtool` | 1,000 triples | Paginated results |

---

## 13. Dependency Management

Tools use a consistent pattern for optional dependencies:

```python
try:
    import playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
```

If a dependency is missing, the tool returns a clear installation hint:

```python
return {
    "success": False,
    "error": (
        "playwright not installed. "
        "Run: pip install playwright && playwright install chromium"
    )
}
```

The `deps_error()` helper provides a standard format:

```python
from app.tools import deps_error
return deps_error("pyotp", pip_install="pyotp", action="generate")
```

Dependencies by tool category:

| Category | Key Dependencies |
|---|---|
| Browser automation | `playwright` |
| Desktop control | `pyautogui`, `pillow`, `xdotool`, `wmctrl` |
| Document parsing | `PyMuPDF`, `python-docx`, `openpyxl` |
| Calendar | `google-api-python-client`, `google-auth-httplib2`, `caldav` |
| Mail | `httpx` (SMTP via stdlib) |
| Smart home | `httpx` (Home Assistant REST API) |
| Spotify | `spotipy` |
| Reddit | `praw` |
| YouTube | `yt-dlp`, `youtube-search-python` |
| Image gen | `httpx` (xAI API) |
| Local ML | `onnxruntime`, `transformers`, `torch` |
| Video stream | `opencv-python`, `numpy` |
| TOTP | `pyotp` |
| RSS | `feedparser` |
| GitHub | `requests` |
| Supabase | `supabase` |
| Notion | `notion-client` |
| Linear | `httpx` (Linear GraphQL API) |
| Airtable | `httpx` (Airtable REST API) |
| Sheets | `gspread`, `google-auth` |
| Music | `spotipy` |
| News | `httpx` (HackerNews Firebase API) |
| OSRM | `httpx` (free OSRM API) |
| Wolfram Alpha | `httpx` (Wolfram API) |
| Translation | `httpx` (Google Translate API) |
| Tesseract OCR | `pytesseract`, `pillow` |
| Finance | `yfinance`, `pandas`, `numpy` |
| Data viz | `matplotlib`, `seaborn` |

---

## 14. OpenAPI / Function Calling Compatibility

Each tool's `get_schema()` returns a `ToolSchema` that maps directly to OpenAI's function-calling format:

```json
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather or 5-day forecast for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["current", "forecast"],
                    "description": "current | forecast"
                },
                "location": {
                    "type": "string",
                    "description": "City name, e.g. 'London'"
                }
            },
            "required": ["action"]
        }
    }
}
```

This allows any LLM that supports function calling (OpenAI, Anthropic, Google, xAI, Ollama, etc.) to discover and invoke tools natively. The orchestrator translates between provider-specific formats.

---

## 15. Error Handling Patterns

Every tool must handle these error classes gracefully:

```python
# Network errors
httpx.TimeoutException → recoverable, retry
httpx.ConnectError → recoverable, retry
httpx.HTTPStatusError → non-recoverable (4xx) or recoverable (5xx)

# Auth errors
ValueError("API key not set") → non-recoverable, clear message

# Validation errors
Missing required param → non-recoverable, identify missing field
Invalid enum value → non-recoverable, list valid options

# Resource errors
FileNotFoundError → non-recoverable, check path
PermissionError → non-recoverable, check permissions

# Rate limiting
429 Too Many Requests → recoverable, suggest wait
```

The `standardize_error()` function in `resilience.py` generates a `suggestion` field that guides the LLM on how to recover autonomously. The `SelfCorrector` in the same module attempts automatic remediation when errors are recoverable.
