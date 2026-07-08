---
title: "04 - Tools Ecosystem"
---

# 04 - Tools Ecosystem

## How RAVEN Uses Tools

RAVEN is not just a chatbot -- it can act on the world. When you ask it to search the
web, check the weather, run some code, or turn on a light, the LLM decides which tool
to call, executes it, reads the result, and crafts a natural response.

This document covers every tool RAVEN has, how tool calling works internally, and how
to add your own tools through the plugin system.

---

## Tool Calling Architecture

The LLM (Mistral 7B Instruct AWQ via vLLM) supports a structured function-calling
format. The system prompt lists available tools with their parameters. When the LLM
decides a tool is needed, it emits a JSON tool call instead of (or alongside) a text
response. The brain intercepts this, executes the tool, feeds the result back, and the
LLM generates a final human-readable response.

```
User: "What's the weather in Bangalore?"
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                        RAVEN BRAIN                               │
│                                                                  │
│  1. Build context:                                               │
│     [system prompt + memories + tool descriptions + user msg]    │
│                                                                  │
│  2. LLM generates:                                               │
│     {"tool_call": "get_weather", "args": {"location":            │
│      "Bangalore"}}                                               │
│                                                                  │
│  3. Tool executor runs get_weather("Bangalore")                  │
│     Result: {"temp": 26, "condition": "Partly cloudy",           │
│              "humidity": 65, "wind_kph": 12}                     │
│                                                                  │
│  4. Result fed back to LLM as a tool-result message              │
│                                                                  │
│  5. LLM generates final response:                                │
│     "It's 26 degrees in Bangalore right now, partly cloudy.      │
│      Humidity's at 65%. Pretty nice out."                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
Response sent back to user on Telegram / Discord / wherever
```

### The Tool Calling Loop

```python
class RavenBrain:
    async def _think_and_respond(self, message: IncomingMessage) -> OutgoingMessage:
        """Core thinking loop with tool calling support."""

        # Build the initial messages for the LLM
        messages = await self._build_context(message)

        # Tool calling loop -- LLM may call multiple tools in sequence
        max_tool_rounds = 5
        for round_num in range(max_tool_rounds):
            # Call the LLM
            llm_response = await self.llm.chat_completion(
                messages=messages,
                tools=self.tool_registry.get_tool_schemas(),
                temperature=0.7,
                max_tokens=1024,
            )

            # Check if the LLM wants to call a tool
            if llm_response.tool_calls:
                for tool_call in llm_response.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)

                    # Execute the tool
                    result = await self.tool_executor.execute(
                        tool_name, tool_args, user_id=message.user_id
                    )

                    # Format and truncate the result
                    formatted_result = self.tool_formatter.format(
                        tool_name, result
                    )

                    # Append tool call and result to the conversation
                    messages.append({
                        "role": "assistant",
                        "tool_calls": [tool_call.model_dump()],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": formatted_result,
                    })

                # Continue the loop -- LLM may want to call another tool
                continue

            else:
                # LLM produced a text response -- we're done
                return OutgoingMessage(
                    text=llm_response.content,
                    reply_to=message.reply_context,
                )

        # Safety: if we hit max rounds, return what we have
        return OutgoingMessage(
            text=llm_response.content or "I got a bit lost in my tools there. "
                 "Can you rephrase?",
            reply_to=message.reply_context,
        )
```

### LLM Tool Format

The tool definitions are passed to vLLM in OpenAI-compatible format. The system prompt
also includes a natural-language description of each tool so the LLM knows when to
use them.

```python
# Example tool schema passed to vLLM
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for current information. "
                           "Use when the user asks about recent events, "
                           "facts you're unsure about, or anything that "
                           "requires up-to-date information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    # ... more tools
]
```

---

## Base Tool Interface and Registry

Every tool in RAVEN implements a common abstract interface. Tools are discovered and
registered at startup through a registry pattern.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import logging

logger = logging.getLogger(__name__)

# Type alias: Database refers to an asyncpg.Pool connection pool.
# Used by ToolExecutor, MemoryManager, and individual tools via bind().
Database = Any  # asyncpg.Pool at runtime


@dataclass
class ToolParameter:
    """Describes a single parameter for a tool."""
    name: str
    type: str                          # "string", "integer", "number", "boolean"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None      # Allowed values


@dataclass
class ToolResult:
    """Standardized result from any tool execution."""
    success: bool
    data: Any = None                   # The actual result data
    error: str | None = None           # Error message if failed
    execution_time_ms: float = 0.0


class BaseTool(ABC):
    """Abstract base class for all RAVEN tools.

    Every tool must define its name, description, parameters, and an
    execute method. The registry auto-discovers tools by scanning for
    subclasses.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name used in function calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM system prompt."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """List of parameters this tool accepts."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given arguments.

        Returns a ToolResult with success/failure and data.
        Must handle its own timeouts and errors gracefully.
        """
        ...

    def get_schema(self) -> dict:
        """Generate OpenAI-compatible function schema for vLLM."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                prop["default"] = param.default
            if param.enum:
                prop["enum"] = param.enum

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }
```

### Tool Registry

```python
import importlib
import pkgutil
from pathlib import Path


class ToolRegistry:
    """Discovers, registers, and manages all available tools.

    Built-in tools are loaded from raven/tools/.
    Plugin tools are loaded from the plugins/ directory.
    """

    def __init__(self, config: dict):
        self.config = config
        self._tools: dict[str, BaseTool] = {}

    async def initialize(self):
        """Discover and register all tools."""
        # Load built-in tools
        self._discover_builtin_tools()

        # Load plugin tools
        self._discover_plugin_tools()

        enabled = [name for name, tool in self._tools.items()]
        logger.info(f"Registered {len(enabled)} tools: {enabled}")

    def _discover_builtin_tools(self):
        """Import all tool classes from raven/tools/ package."""
        import raven.tools as tools_package

        for importer, modname, ispkg in pkgutil.iter_modules(
            tools_package.__path__
        ):
            module = importlib.import_module(f"raven.tools.{modname}")

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr is not BaseTool):
                    tool_instance = attr(self.config)
                    if self._is_enabled(tool_instance.name):
                        self._tools[tool_instance.name] = tool_instance

    def _discover_plugin_tools(self):
        """Load custom tools from the plugins/ directory."""
        plugins_dir = Path("plugins")
        if not plugins_dir.exists():
            return

        for py_file in plugins_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            spec = importlib.util.spec_from_file_location(
                py_file.stem, py_file
            )
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"Failed to load plugin {py_file.name}: {e}")
                continue

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr is not BaseTool):
                    tool_instance = attr(self.config)
                    self._tools[tool_instance.name] = tool_instance
                    logger.info(f"Loaded plugin tool: {tool_instance.name}")

    def _is_enabled(self, tool_name: str) -> bool:
        """Check if a tool is enabled in config.yaml."""
        tools_config = self.config.get("tools", {})
        tool_conf = tools_config.get(tool_name, {})
        return tool_conf.get("enabled", True)

    def get(self, tool_name: str) -> BaseTool | None:
        return self._tools.get(tool_name)

    def get_tool_schemas(self) -> list[dict]:
        """Get all tool schemas for the LLM."""
        return [tool.get_schema() for tool in self._tools.values()]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
```

### Tool Executor

```python
import asyncio
import time


class ToolExecutor:
    """Executes tools with timeout handling and audit logging."""

    def __init__(self, registry: ToolRegistry, db: Database):
        self.registry = registry
        self.db = db

    async def execute(self, tool_name: str, args: dict,
                      user_id: str) -> ToolResult:
        """Execute a tool by name with the given arguments.

        Applies a timeout, catches errors, and logs the execution.
        """
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}"
            )

        # Inject runtime context for tools that need it (e.g. reminders, notes).
        # Tools declare _context as an optional parameter to receive this.
        args["_context"] = {"user_id": user_id}

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                tool.execute(**args),
                timeout=30.0  # Default 30s timeout per tool
            )
        except asyncio.TimeoutError:
            result = ToolResult(
                success=False,
                error=f"Tool '{tool_name}' timed out after 30 seconds"
            )
        except Exception as e:
            logger.exception(f"Tool '{tool_name}' failed: {e}")
            result = ToolResult(
                success=False,
                error=f"Tool error: {str(e)}"
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        result.execution_time_ms = elapsed_ms

        # Audit log
        await self.db.execute(
            """INSERT INTO audit_log (user_id, action_type, details)
               VALUES ($1, 'tool_call', $2)""",
            user_id,
            json.dumps({
                "tool": tool_name,
                "args": args,
                "success": result.success,
                "time_ms": round(elapsed_ms, 1),
                "error": result.error,
            }),
        )

        return result
```

---

## Built-in Tools

### web_search -- Internet Search via SearXNG

SearXNG is a self-hosted metasearch engine that aggregates results from Google, Bing,
DuckDuckGo, and others without tracking. RAVEN queries it over a local HTTP API.

```python
import httpx


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the internet for current information. Use when the user "
        "asks about recent events, facts you are unsure about, or anything "
        "requiring up-to-date data."
    )
    parameters = [
        ToolParameter("query", "string", "The search query"),
        ToolParameter("num_results", "integer", "Number of results (1-10)",
                      required=False, default=5),
    ]

    def __init__(self, config: dict):
        self.searxng_url = config.get("tools", {}).get(
            "web_search", {}
        ).get("url", "http://localhost:8888")

    async def execute(self, query: str, num_results: int = 5) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.searxng_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "categories": "general",
                        "engines": "google,duckduckgo,brave",
                        "language": "en",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get("results", [])[:num_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")[:300],
                })

            return ToolResult(success=True, data=results)

        except httpx.TimeoutException:
            return ToolResult(success=False, error="Search timed out")
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error=f"Search engine returned {e.response.status_code}"
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")
```

### run_code -- Sandboxed Python Execution

Runs user-provided Python code in a sandboxed subprocess with strict resource limits.
This is not a full Jupyter kernel -- it is intentionally constrained for safety.
See `06-safety-moderation.md` for the `CodeSandbox` class which provides the
underlying static analysis and Docker-based isolation; `RunCodeTool` delegates to it
at runtime.

```python
import asyncio
import resource
import tempfile
import os


class RunCodeTool(BaseTool):
    name = "run_code"
    description = (
        "Execute Python code and return the output. Use for calculations, "
        "data processing, generating text, or any task that benefits from "
        "running actual code. The code runs in a sandbox with no network "
        "access and limited resources."
    )
    parameters = [
        ToolParameter("code", "string", "Python code to execute"),
        ToolParameter("language", "string", "Programming language",
                      required=False, default="python",
                      enum=["python"]),
    ]

    def __init__(self, config: dict):
        code_config = config.get("tools", {}).get("code_execution", {})
        self.timeout = code_config.get("timeout_seconds", 30)
        self.max_output_bytes = 10_000

    async def execute(self, code: str, language: str = "python") -> ToolResult:
        if language != "python":
            return ToolResult(
                success=False,
                error=f"Language '{language}' not supported. Only Python."
            )

        # Write code to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-u", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._sandbox_env(),
                preexec_fn=self._set_resource_limits,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    error=f"Code execution timed out after {self.timeout}s"
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")[
                :self.max_output_bytes
            ]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[
                :self.max_output_bytes
            ]

            if proc.returncode == 0:
                return ToolResult(
                    success=True,
                    data={"stdout": stdout, "stderr": stderr}
                )
            else:
                return ToolResult(
                    success=False,
                    data={"stdout": stdout, "stderr": stderr},
                    error=f"Code exited with status {proc.returncode}"
                )

        finally:
            os.unlink(script_path)

    def _sandbox_env(self) -> dict:
        """Minimal environment for sandboxed execution."""
        return {
            "PATH": "/usr/bin:/usr/local/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
            # No network-related env vars, no API keys
        }

    def _set_resource_limits(self):
        """Set resource limits for the child process (Linux only)."""
        # Max 256 MB memory
        resource.setrlimit(
            resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)
        )
        # Max 100 MB file writes
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024)
        )
        # Max 50 child processes (prevent fork bombs)
        resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
        # Max 30 seconds CPU time
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
```

### read_url -- Web Page Content Extraction

Fetches a URL and extracts the readable content using trafilatura, stripping ads,
navigation, and boilerplate. Useful for reading articles, documentation, or any page
the user links.

```python
import httpx
import trafilatura


class ReadUrlTool(BaseTool):
    name = "read_url"
    description = (
        "Fetch and read the content of a web page. Extracts the main "
        "article text, stripping ads and navigation. Use when the user "
        "shares a link or you need to read a specific page."
    )
    parameters = [
        ToolParameter("url", "string", "The URL to read"),
    ]

    def __init__(self, config: dict):
        self.max_content_length = 4000  # Characters to return to LLM

    async def execute(self, url: str) -> ToolResult:
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; RAVEN/1.0)"
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            # Extract readable content
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
                output_format="txt",
            )

            if not extracted:
                return ToolResult(
                    success=False,
                    error="Could not extract readable content from that page"
                )

            # Truncate to fit in LLM context
            if len(extracted) > self.max_content_length:
                extracted = (
                    extracted[:self.max_content_length]
                    + "\n\n[Content truncated -- page was too long]"
                )

            return ToolResult(
                success=True,
                data={"url": url, "content": extracted}
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=f"Timed out fetching {url}"
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error=f"HTTP {e.response.status_code} fetching {url}"
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Read failed: {e}")
```

### get_weather -- Open-Meteo API

Open-Meteo is a free weather API that requires no API key. RAVEN uses geocoding to
resolve location names to coordinates, then fetches the forecast.

```python
import httpx


class GetWeatherTool(BaseTool):
    name = "get_weather"
    description = (
        "Get current weather and forecast for a location. Provides "
        "temperature, conditions, humidity, wind, and a brief forecast."
    )
    parameters = [
        ToolParameter("location", "string",
                      "City name or location (e.g. 'Bangalore', 'New York')"),
    ]

    async def execute(self, location: str) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: Geocode the location name to coordinates
                geo_resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en"},
                )
                geo_data = geo_resp.json()

                if not geo_data.get("results"):
                    return ToolResult(
                        success=False,
                        error=f"Could not find location: {location}"
                    )

                place = geo_data["results"][0]
                lat, lon = place["latitude"], place["longitude"]
                resolved_name = place.get("name", location)

                # Step 2: Fetch current weather + daily forecast
                weather_resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,"
                                   "apparent_temperature,weather_code,"
                                   "wind_speed_10m",
                        "daily": "temperature_2m_max,temperature_2m_min,"
                                 "precipitation_probability_max,"
                                 "weather_code",
                        "forecast_days": 3,
                        "timezone": "auto",
                    },
                )
                weather = weather_resp.json()

            current = weather.get("current", {})
            daily = weather.get("daily", {})

            return ToolResult(
                success=True,
                data={
                    "location": resolved_name,
                    "current": {
                        "temp_c": current.get("temperature_2m"),
                        "feels_like_c": current.get("apparent_temperature"),
                        "humidity_pct": current.get("relative_humidity_2m"),
                        "wind_kph": current.get("wind_speed_10m"),
                        "condition": self._weather_code_to_text(
                            current.get("weather_code", 0)
                        ),
                    },
                    "forecast": [
                        {
                            "date": daily["time"][i],
                            "high_c": daily["temperature_2m_max"][i],
                            "low_c": daily["temperature_2m_min"][i],
                            "rain_chance_pct": daily[
                                "precipitation_probability_max"
                            ][i],
                            "condition": self._weather_code_to_text(
                                daily["weather_code"][i]
                            ),
                        }
                        for i in range(len(daily.get("time", [])))
                    ],
                },
            )

        except httpx.TimeoutException:
            return ToolResult(success=False, error="Weather API timed out")
        except Exception as e:
            return ToolResult(success=False, error=f"Weather failed: {e}")

    @staticmethod
    def _weather_code_to_text(code: int) -> str:
        """Convert WMO weather codes to human-readable text."""
        codes = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy",
            3: "Overcast", 45: "Foggy", 48: "Rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
            95: "Thunderstorm", 96: "Thunderstorm with hail",
        }
        return codes.get(code, f"Code {code}")
```

### set_reminder / set_alarm -- APScheduler Integration

Reminders and alarms use APScheduler to schedule future callbacks. When a reminder
fires, RAVEN sends a message to the user on whichever platform the reminder was set
from.

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
import uuid


class SetReminderTool(BaseTool):
    name = "set_reminder"
    description = (
        "Set a reminder that will notify the user at a specific time. "
        "The reminder message is sent to the same platform the user is "
        "currently on."
    )
    parameters = [
        ToolParameter("message", "string",
                      "What to remind the user about"),
        ToolParameter("time", "string",
                      "When to remind, e.g. 'in 30 minutes', "
                      "'at 5pm', 'tomorrow at 9am'"),
    ]

    def __init__(self, config: dict):
        self.scheduler: AsyncIOScheduler | None = None
        self.db: Database | None = None
        self.brain: RavenBrain | None = None  # Set after init

    def bind(self, scheduler: AsyncIOScheduler, db: Database,
             brain: 'RavenBrain'):
        """Bind runtime dependencies after initialization."""
        self.scheduler = scheduler
        self.db = db
        self.brain = brain

    async def execute(self, message: str, time: str,
                      _context: dict | None = None) -> ToolResult:
        try:
            trigger_time = self._parse_time(time)
        except ValueError as e:
            return ToolResult(success=False, error=f"Cannot parse time: {e}")

        if trigger_time <= datetime.now(timezone.utc):
            return ToolResult(
                success=False,
                error="That time is in the past"
            )

        task_id = str(uuid.uuid4())
        user_id = _context.get("user_id") if _context else None
        reply_context = _context.get("reply_context") if _context else None

        # Store in database
        await self.db.execute(
            """INSERT INTO scheduled_tasks
               (id, user_id, task_type, description, trigger_time,
                target_platform, target_context, is_active)
               VALUES ($1, $2, 'reminder', $3, $4, $5, $6, true)""",
            task_id, user_id, message, trigger_time,
            reply_context.platform if reply_context else None,
            json.dumps(self._serialize_reply_context(reply_context)),
        )

        # Schedule with APScheduler
        self.scheduler.add_job(
            self._fire_reminder,
            trigger=DateTrigger(run_date=trigger_time),
            args=[task_id, user_id, message, reply_context],
            id=task_id,
            replace_existing=True,
        )

        return ToolResult(
            success=True,
            data={
                "task_id": task_id,
                "message": message,
                "trigger_time": trigger_time.isoformat(),
            },
        )

    async def _fire_reminder(self, task_id: str, user_id: str,
                              message: str, reply_context: ReplyContext):
        """Called by APScheduler when the reminder fires."""
        response = OutgoingMessage(
            text=f"Reminder: {message}",
            reply_to=reply_context,
        )
        await self.brain.send_proactive_message(user_id, response)

        # Mark as completed
        await self.db.execute(
            "UPDATE scheduled_tasks SET is_active = false WHERE id = $1",
            task_id,
        )

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """Parse natural language time expressions."""
        lower = time_str.lower().strip()
        now = datetime.now()

        # Handle relative times: "in 30 minutes", "in 2 hours"
        if lower.startswith("in "):
            parts = lower[3:].split()
            if len(parts) >= 2:
                amount = int(parts[0])
                unit = parts[1].rstrip("s")  # "minutes" -> "minute"
                if unit == "minute":
                    return now + timedelta(minutes=amount)
                elif unit == "hour":
                    return now + timedelta(hours=amount)
                elif unit == "day":
                    return now + timedelta(days=amount)

        # Fall back to dateutil parser for "at 5pm", "tomorrow 9am", etc.
        result = dateparser.parse(time_str, fuzzy=True)
        if result is None:
            raise ValueError(f"Could not parse time expression: '{time_str}'")
        return result

    def _serialize_reply_context(self, ctx: ReplyContext) -> dict | None:
        if not ctx:
            return None
        return {
            "platform": ctx.platform,
            "chat_id": ctx.chat_id,
            "guild_id": ctx.guild_id,
            "voice_channel_id": ctx.voice_channel_id,
        }


class SetAlarmTool(BaseTool):
    """Nearly identical to SetReminderTool but with a different name and
    description so the LLM knows when to use each one."""

    name = "set_alarm"
    description = (
        "Set an alarm for a specific time. Unlike reminders, alarms "
        "trigger a louder notification or sound."
    )
    parameters = [
        ToolParameter("time", "string",
                      "When the alarm should go off, e.g. '6:30am', "
                      "'tomorrow 7am'"),
    ]

    def __init__(self, config: dict):
        self.scheduler: AsyncIOScheduler | None = None
        self.db: Database | None = None
        self.brain: RavenBrain | None = None

    def bind(self, scheduler, db, brain):
        self.scheduler = scheduler
        self.db = db
        self.brain = brain

    async def execute(self, time: str,
                      _context: dict | None = None) -> ToolResult:
        try:
            trigger_time = SetReminderTool._parse_time(time)
        except ValueError as e:
            return ToolResult(success=False, error=f"Cannot parse time: {e}")

        task_id = str(uuid.uuid4())
        user_id = _context.get("user_id") if _context else None
        reply_context = _context.get("reply_context") if _context else None

        # Schedule the alarm
        self.scheduler.add_job(
            self._fire_alarm,
            trigger=DateTrigger(run_date=trigger_time),
            args=[task_id, user_id, reply_context],
            id=task_id,
        )

        return ToolResult(
            success=True,
            data={
                "task_id": task_id,
                "alarm_time": trigger_time.isoformat(),
            },
        )

    async def _fire_alarm(self, task_id, user_id, reply_context):
        """Fire the alarm -- send notification and optionally play a sound."""
        response = OutgoingMessage(
            text="ALARM! Time to wake up.",
            reply_to=reply_context,
        )
        await self.brain.send_proactive_message(user_id, response)

        # If local speakers are available, play an alarm sound
        if hasattr(self.brain, "voice_io") and self.brain.voice_io:
            await self.brain.voice_io.play_alarm_sound()
```

### smart_home -- Home Assistant REST API

Controls smart home devices through Home Assistant's REST API. Supports lights,
switches, thermostats, locks, and any entity HA exposes.

```python
import httpx


class SmartHomeTool(BaseTool):
    name = "smart_home"
    description = (
        "Control smart home devices: turn lights on/off, set thermostat "
        "temperature, lock/unlock doors, toggle switches. The user may "
        "say things like 'turn on the bedroom lights' or 'set AC to 22'."
    )
    parameters = [
        ToolParameter("device", "string",
                      "Device name or entity_id, e.g. 'bedroom lights', "
                      "'living room AC'"),
        ToolParameter("action", "string",
                      "Action to perform",
                      enum=["turn_on", "turn_off", "toggle", "set",
                            "lock", "unlock", "open", "close"]),
        ToolParameter("params", "string",
                      "Additional parameters as JSON, e.g. "
                      "'{\"brightness\": 80}' or '{\"temperature\": 22}'",
                      required=False, default="{}"),
    ]

    def __init__(self, config: dict):
        ha_config = config.get("smart_home", {})
        self.ha_url = ha_config.get("ha_url", "http://homeassistant.local:8123")
        self.ha_token = ha_config.get("ha_token", "")
        self._entity_cache: dict[str, str] = {}  # name -> entity_id

    async def execute(self, device: str, action: str,
                      params: str = "{}") -> ToolResult:
        try:
            parsed_params = json.loads(params) if isinstance(params, str) else params
        except json.JSONDecodeError:
            parsed_params = {}

        # Resolve device name to HA entity_id
        entity_id = await self._resolve_entity(device)
        if not entity_id:
            return ToolResult(
                success=False,
                error=f"Could not find device: {device}"
            )

        # Map our action names to HA service calls
        service_map = {
            "turn_on": ("homeassistant", "turn_on"),
            "turn_off": ("homeassistant", "turn_off"),
            "toggle": ("homeassistant", "toggle"),
            "set": self._infer_set_service(entity_id, parsed_params),
            "lock": ("lock", "lock"),
            "unlock": ("lock", "unlock"),
            "open": ("cover", "open_cover"),
            "close": ("cover", "close_cover"),
        }

        domain, service = service_map.get(action, ("homeassistant", action))

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.ha_url}/api/services/{domain}/{service}",
                    headers={
                        "Authorization": f"Bearer {self.ha_token}",
                        "Content-Type": "application/json",
                    },
                    json={"entity_id": entity_id, **parsed_params},
                )
                resp.raise_for_status()

            return ToolResult(
                success=True,
                data={
                    "device": device,
                    "entity_id": entity_id,
                    "action": action,
                    "status": "executed",
                },
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error="Home Assistant is not responding"
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error=f"Home Assistant error: {e.response.status_code}"
            )

    async def _resolve_entity(self, device_name: str) -> str | None:
        """Resolve a friendly device name to a HA entity_id.

        Searches the HA entity registry by friendly name.
        """
        if device_name in self._entity_cache:
            return self._entity_cache[device_name]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.ha_url}/api/states",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                )
                states = resp.json()

            name_lower = device_name.lower()
            for entity in states:
                friendly = entity.get("attributes", {}).get(
                    "friendly_name", ""
                ).lower()
                eid = entity["entity_id"]

                if name_lower == friendly or name_lower in friendly:
                    self._entity_cache[device_name] = eid
                    return eid

            return None

        except Exception:
            return None

    def _infer_set_service(self, entity_id: str,
                            params: dict) -> tuple[str, str]:
        """Infer the correct HA service for a 'set' action."""
        domain = entity_id.split(".")[0]
        if domain == "climate":
            return ("climate", "set_temperature")
        elif domain == "light":
            return ("light", "turn_on")  # brightness/color via params
        elif domain == "fan":
            return ("fan", "set_percentage")
        return ("homeassistant", "turn_on")
```

### read_sensor -- Query PostgreSQL Sensor Data

Reads the latest value from a sensor or queries historical data. The sensor_readings
table is populated by the MQTT listener (covered in doc 05).

```python
class ReadSensorTool(BaseTool):
    name = "read_sensor"
    description = (
        "Read the current or recent value from an IoT sensor. "
        "Available sensors include temperature, humidity, motion, "
        "and door sensors in various locations."
    )
    parameters = [
        ToolParameter("sensor_id", "string",
                      "Sensor identifier or description, e.g. "
                      "'bedroom temperature', 'front door'"),
        ToolParameter("history_minutes", "integer",
                      "If set, return readings from the last N minutes",
                      required=False, default=0),
    ]

    def __init__(self, config: dict):
        self.db: Database | None = None

    def bind(self, db: Database):
        self.db = db

    async def execute(self, sensor_id: str,
                      history_minutes: int = 0) -> ToolResult:
        try:
            if history_minutes > 0:
                rows = await self.db.fetch(
                    """SELECT sensor_type, value, unit, location, timestamp
                       FROM sensor_readings
                       WHERE (device_id ILIKE $1 OR location ILIKE $1
                              OR sensor_type ILIKE $1)
                         AND timestamp > NOW() - $2 * INTERVAL '1 minute'
                       ORDER BY timestamp DESC
                       LIMIT 50""",
                    f"%{sensor_id}%",
                    history_minutes,
                )

                if not rows:
                    return ToolResult(
                        success=False,
                        error=f"No readings found for '{sensor_id}'"
                    )

                return ToolResult(
                    success=True,
                    data={
                        "sensor": sensor_id,
                        "readings": [
                            {
                                "type": r["sensor_type"],
                                "value": r["value"],
                                "unit": r["unit"],
                                "location": r["location"],
                                "time": r["timestamp"].isoformat(),
                            }
                            for r in rows
                        ],
                    },
                )
            else:
                # Latest reading only
                row = await self.db.fetchrow(
                    """SELECT sensor_type, value, unit, location, timestamp
                       FROM sensor_readings
                       WHERE device_id ILIKE $1 OR location ILIKE $1
                             OR sensor_type ILIKE $1
                       ORDER BY timestamp DESC
                       LIMIT 1""",
                    f"%{sensor_id}%",
                )

                if not row:
                    return ToolResult(
                        success=False,
                        error=f"No sensor found matching '{sensor_id}'"
                    )

                return ToolResult(
                    success=True,
                    data={
                        "type": row["sensor_type"],
                        "value": row["value"],
                        "unit": row["unit"],
                        "location": row["location"],
                        "timestamp": row["timestamp"].isoformat(),
                    },
                )

        except Exception as e:
            return ToolResult(success=False, error=f"Sensor read failed: {e}")
```

### take_photo -- RTSP Camera Snapshot

Captures a single frame from an RTSP camera using ffmpeg. The camera URL is looked
up from config by camera name.

```python
import asyncio
import os
import time


class TakePhotoTool(BaseTool):
    name = "take_photo"
    description = (
        "Take a photo from a connected camera. Returns the image path. "
        "Use when the user asks to check a camera or see what's happening "
        "somewhere."
    )
    parameters = [
        ToolParameter("camera_id", "string",
                      "Camera name, e.g. 'front door', 'backyard', 'garage'"),
    ]

    def __init__(self, config: dict):
        self.cameras = config.get("cameras", {})
        # cameras:
        #   front_door:
        #     url: "rtsp://192.168.1.50:554/stream"
        #   backyard:
        #     url: "rtsp://192.168.1.51:554/stream"

    async def execute(self, camera_id: str) -> ToolResult:
        # Resolve camera name to RTSP URL
        camera_key = camera_id.lower().replace(" ", "_")
        camera_config = self.cameras.get(camera_key)

        if not camera_config:
            available = ", ".join(self.cameras.keys())
            return ToolResult(
                success=False,
                error=f"Unknown camera '{camera_id}'. "
                      f"Available: {available}"
            )

        rtsp_url = camera_config["url"]
        output_path = f"/tmp/raven_camera_{camera_key}_{int(time.time())}.jpg"

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-rtsp_transport", "tcp",
                "-i", rtsp_url,
                "-frames:v", "1",
                "-q:v", "2",
                "-y", output_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)

            if not os.path.exists(output_path):
                return ToolResult(
                    success=False,
                    error=f"Failed to capture image from {camera_id}"
                )

            return ToolResult(
                success=True,
                data={
                    "camera": camera_id,
                    "image_path": output_path,
                },
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Camera '{camera_id}' did not respond in time"
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Camera error: {e}")
```

### play_music -- mpv + yt-dlp

Plays music on connected speakers using mpv as the player and yt-dlp for resolving
YouTube and other streaming URLs.

```python
import asyncio
import shutil


class PlayMusicTool(BaseTool):
    name = "play_music"
    description = (
        "Play music or audio. Accepts a search query (searches YouTube), "
        "a direct URL, or a song name. Plays through the server's speakers."
    )
    parameters = [
        ToolParameter("query", "string",
                      "Song name, artist, YouTube URL, or search query"),
        ToolParameter("action", "string",
                      "Control playback",
                      required=False, default="play",
                      enum=["play", "pause", "stop", "next", "volume_up",
                            "volume_down"]),
    ]

    def __init__(self, config: dict):
        self._mpv_proc: asyncio.subprocess.Process | None = None

    async def execute(self, query: str,
                      action: str = "play") -> ToolResult:
        if action == "stop":
            return await self._stop()
        if action == "pause":
            return await self._send_mpv_command("cycle pause")

        if action != "play":
            return ToolResult(
                success=False,
                error=f"Action '{action}' not yet implemented"
            )

        # Stop any currently playing audio
        await self._stop()

        # Resolve the query to a playable URL via yt-dlp
        if not query.startswith("http"):
            # Search YouTube
            query = f"ytsearch1:{query}"

        if not shutil.which("yt-dlp") or not shutil.which("mpv"):
            return ToolResult(
                success=False,
                error="yt-dlp or mpv not installed on this system"
            )

        try:
            # Get the audio URL via yt-dlp
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--get-url", "--get-title",
                "-f", "bestaudio", "--no-playlist",
                query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=15.0
            )

            lines = stdout.decode().strip().split("\n")
            if len(lines) < 2:
                return ToolResult(
                    success=False,
                    error=f"Could not find: {query}"
                )

            title = lines[0]
            audio_url = lines[1]

            # Play via mpv (non-blocking, runs in background)
            self._mpv_proc = await asyncio.create_subprocess_exec(
                "mpv", "--no-video", "--really-quiet",
                audio_url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            return ToolResult(
                success=True,
                data={"title": title, "status": "playing"},
            )

        except asyncio.TimeoutError:
            return ToolResult(success=False, error="Search timed out")
        except Exception as e:
            return ToolResult(success=False, error=f"Music error: {e}")

    async def _stop(self) -> ToolResult:
        if self._mpv_proc and self._mpv_proc.returncode is None:
            self._mpv_proc.terminate()
            await self._mpv_proc.wait()
            self._mpv_proc = None
        return ToolResult(success=True, data={"status": "stopped"})

    async def _send_mpv_command(self, cmd: str) -> ToolResult:
        # In production, use mpv's IPC socket for commands
        return ToolResult(success=True, data={"command": cmd})
```

### calculate -- Safe Math Evaluation

Evaluates math expressions safely using a restricted AST evaluator and sympy for
symbolic math. No `eval()` or `exec()` -- only whitelisted operations.

```python
import ast
import operator
import math


class CalculateTool(BaseTool):
    name = "calculate"
    description = (
        "Evaluate a mathematical expression. Supports arithmetic, "
        "trigonometry, logarithms, exponents, and symbolic algebra. "
        "Use for any calculation the user needs."
    )
    parameters = [
        ToolParameter("expression", "string",
                      "Math expression, e.g. '2**10', 'sqrt(144)', "
                      "'sin(pi/4)', 'integrate(x**2, x)'"),
    ]

    # Whitelisted operators for the AST evaluator
    SAFE_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    SAFE_FUNCTIONS = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "log2": math.log2,
        "ceil": math.ceil,
        "floor": math.floor,
        "factorial": math.factorial,
        "pi": math.pi,
        "e": math.e,
    }

    async def execute(self, expression: str) -> ToolResult:
        # Try simple AST evaluation first (fast, safe)
        try:
            result = self._safe_eval(expression)
            return ToolResult(
                success=True,
                data={"expression": expression, "result": result}
            )
        except (ValueError, TypeError, KeyError):
            pass

        # Fall back to sympy for symbolic math
        try:
            import sympy
            result = sympy.sympify(expression)
            evaluated = float(result.evalf()) if result.is_number else str(result)
            return ToolResult(
                success=True,
                data={"expression": expression, "result": evaluated}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Cannot evaluate: {expression}. Error: {e}"
            )

    def _safe_eval(self, expr: str) -> float | int:
        """Evaluate a math expression using a restricted AST walker."""
        import re
        # Replace common math names with values (word boundaries prevent
        # mangling digits or other words containing "e" or "pi")
        expr = re.sub(r'\bpi\b', str(math.pi), expr)
        expr = re.sub(r'\be\b', str(math.e), expr)

        tree = ast.parse(expr, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant: {node.value}")

        elif isinstance(node, ast.BinOp):
            op = self.SAFE_OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported operator: {type(node.op)}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return op(left, right)

        elif isinstance(node, ast.UnaryOp):
            op = self.SAFE_OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported unary op: {type(node.op)}")
            return op(self._eval_node(node.operand))

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func = self.SAFE_FUNCTIONS.get(node.func.id)
                if not func:
                    raise ValueError(f"Unknown function: {node.func.id}")
                args = [self._eval_node(arg) for arg in node.args]
                return func(*args)

        raise ValueError(f"Unsupported expression node: {type(node)}")
```

### get_news -- Hacker News API + RSS

Fetches top stories from Hacker News and optionally from configured RSS feeds.

```python
import httpx
import feedparser


class GetNewsTool(BaseTool):
    name = "get_news"
    description = (
        "Get the latest news headlines. Can fetch from Hacker News or "
        "from configured RSS feeds. Use when the user asks for news."
    )
    parameters = [
        ToolParameter("topic", "string",
                      "News topic or source. Use 'hackernews' for HN, "
                      "or a general topic like 'tech', 'world'",
                      required=False, default="hackernews"),
        ToolParameter("count", "integer",
                      "Number of headlines to return",
                      required=False, default=5),
    ]

    def __init__(self, config: dict):
        news_config = config.get("tools", {}).get("news", {})
        self.rss_feeds = news_config.get("rss_feeds", {})
        # rss_feeds:
        #   tech: "https://feeds.arstechnica.com/arstechnica/technology-lab"
        #   world: "https://feeds.bbci.co.uk/news/world/rss.xml"

    async def execute(self, topic: str = "hackernews",
                      count: int = 5) -> ToolResult:
        if topic.lower() in ("hackernews", "hn", "hacker news"):
            return await self._fetch_hackernews(count)
        elif topic.lower() in self.rss_feeds:
            return await self._fetch_rss(self.rss_feeds[topic.lower()], count)
        else:
            # Try HN search for the topic
            return await self._search_hackernews(topic, count)

    async def _fetch_hackernews(self, count: int) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get top story IDs
                resp = await client.get(
                    "https://hacker-news.firebaseio.com/v0/topstories.json"
                )
                story_ids = resp.json()[:count]

                # Fetch each story's details
                stories = []
                for sid in story_ids:
                    sr = await client.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"
                    )
                    item = sr.json()
                    stories.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "score": item.get("score", 0),
                        "comments": item.get("descendants", 0),
                    })

            return ToolResult(success=True, data=stories)

        except Exception as e:
            return ToolResult(success=False, error=f"HN fetch failed: {e}")

    async def _fetch_rss(self, feed_url: str, count: int) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(feed_url)
                feed = feedparser.parse(resp.text)

            entries = []
            for entry in feed.entries[:count]:
                entries.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:200],
                })

            return ToolResult(success=True, data=entries)

        except Exception as e:
            return ToolResult(success=False, error=f"RSS fetch failed: {e}")

    async def _search_hackernews(self, query: str,
                                  count: int) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": query, "hitsPerPage": count},
                )
                data = resp.json()

            results = [
                {
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "points": hit.get("points", 0),
                }
                for hit in data.get("hits", [])
            ]

            return ToolResult(success=True, data=results)

        except Exception as e:
            return ToolResult(success=False, error=f"HN search failed: {e}")
```

### wikipedia -- Wikipedia API

Fetches a summary and first section from Wikipedia for factual lookups.

```python
import httpx


class WikipediaTool(BaseTool):
    name = "wikipedia"
    description = (
        "Look up a topic on Wikipedia. Returns a summary and the first "
        "section of the article. Use for factual questions, definitions, "
        "historical events, or explaining concepts."
    )
    parameters = [
        ToolParameter("query", "string",
                      "The topic to look up on Wikipedia"),
    ]

    async def execute(self, query: str) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Use the Wikipedia REST API for summary
                resp = await client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/"
                    f"{query.replace(' ', '_')}",
                    headers={"User-Agent": "RAVEN/1.0"},
                )

                if resp.status_code == 404:
                    # Try search instead
                    return await self._search_wikipedia(client, query)

                resp.raise_for_status()
                data = resp.json()

            return ToolResult(
                success=True,
                data={
                    "title": data.get("title", ""),
                    "summary": data.get("extract", ""),
                    "url": data.get("content_urls", {}).get(
                        "desktop", {}
                    ).get("page", ""),
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Wikipedia error: {e}")

    async def _search_wikipedia(self, client: httpx.AsyncClient,
                                 query: str) -> ToolResult:
        """Fall back to search if the exact title wasn't found."""
        resp = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "RAVEN/1.0"},
        )
        data = resp.json()
        results = data.get("query", {}).get("search", [])

        if not results:
            return ToolResult(
                success=False,
                error=f"No Wikipedia article found for '{query}'"
            )

        # Fetch the top result
        title = results[0]["title"]
        summary_resp = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/"
            f"{title.replace(' ', '_')}",
            headers={"User-Agent": "RAVEN/1.0"},
        )
        summary_data = summary_resp.json()

        return ToolResult(
            success=True,
            data={
                "title": summary_data.get("title", ""),
                "summary": summary_data.get("extract", ""),
                "url": summary_data.get("content_urls", {}).get(
                    "desktop", {}
                ).get("page", ""),
            },
        )
```

### create_note / list_notes -- PostgreSQL Notes

Simple note-taking backed by the PostgreSQL database. Notes belong to a user and can
be listed, searched, and retrieved.

```python
import uuid
from datetime import datetime, timezone


class CreateNoteTool(BaseTool):
    name = "create_note"
    description = (
        "Save a note for the user. Use when they ask to remember "
        "something, save a list, or jot something down."
    )
    parameters = [
        ToolParameter("title", "string", "Short title for the note"),
        ToolParameter("content", "string", "The note content"),
    ]

    def __init__(self, config: dict):
        self.db: Database | None = None

    def bind(self, db: Database):
        self.db = db

    async def execute(self, title: str, content: str,
                      _context: dict | None = None) -> ToolResult:
        user_id = _context.get("user_id") if _context else None
        note_id = str(uuid.uuid4())

        try:
            await self.db.execute(
                """INSERT INTO notes (id, user_id, title, content, created_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                note_id, user_id, title, content, datetime.now(timezone.utc),
            )

            return ToolResult(
                success=True,
                data={"note_id": note_id, "title": title},
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to save note: {e}")


class ListNotesTool(BaseTool):
    name = "list_notes"
    description = (
        "List the user's saved notes. Returns titles and creation dates."
    )
    parameters = [
        ToolParameter("search", "string",
                      "Optional search term to filter notes",
                      required=False, default=""),
    ]

    def __init__(self, config: dict):
        self.db: Database | None = None

    def bind(self, db: Database):
        self.db = db

    async def execute(self, search: str = "",
                      _context: dict | None = None) -> ToolResult:
        user_id = _context.get("user_id") if _context else None

        try:
            if search:
                rows = await self.db.fetch(
                    """SELECT id, title, content, created_at
                       FROM notes
                       WHERE user_id = $1
                         AND (title ILIKE $2 OR content ILIKE $2)
                       ORDER BY created_at DESC
                       LIMIT 20""",
                    user_id, f"%{search}%",
                )
            else:
                rows = await self.db.fetch(
                    """SELECT id, title, content, created_at
                       FROM notes
                       WHERE user_id = $1
                       ORDER BY created_at DESC
                       LIMIT 20""",
                    user_id,
                )

            notes = [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "preview": r["content"][:100],
                    "created": r["created_at"].isoformat(),
                }
                for r in rows
            ]

            return ToolResult(success=True, data=notes)

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to list notes: {e}"
            )
```

The notes table schema (added to the database alongside the tables in doc 01):

```sql
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notes_user ON notes(user_id, created_at DESC);
```

---

## Multi-Step Tool Chains

The LLM can call multiple tools in sequence within a single user request. The tool
calling loop (shown earlier) runs up to 5 rounds, allowing the LLM to chain tools
together based on intermediate results.

```
User: "Find me a good article about async Python and summarize it"

┌─────────────────────────────────────────────────────────────────────┐
│  Round 1: LLM decides to search                                     │
│  Tool call: web_search(query="best async Python tutorial 2026")      │
│  Result: [{title: "Async Python Deep Dive", url: "https://..."},     │
│           {title: "Python asyncio Guide", url: "https://..."}, ...]  │
├─────────────────────────────────────────────────────────────────────┤
│  Round 2: LLM picks the best result and reads it                     │
│  Tool call: read_url(url="https://example.com/async-python-guide")   │
│  Result: {content: "Async Python has evolved significantly...         │
│           (4000 chars of article text)"}                              │
├─────────────────────────────────────────────────────────────────────┤
│  Round 3: LLM has enough context -- generates final response         │
│  No tool call. Text response:                                        │
│  "Found a solid article on async Python. Here's the gist:            │
│   1. Use asyncio.TaskGroup (Python 3.11+) instead of gather...       │
│   2. Structured concurrency is the future...                         │
│   3. Common pitfalls to avoid...                                     │
│   Full article: https://example.com/async-python-guide"              │
└─────────────────────────────────────────────────────────────────────┘
```

### More Chain Examples

| User Request | Tool Chain |
|---|---|
| "What's the weather and should I carry an umbrella?" | get_weather -> (LLM reasons about rain chance) |
| "Search HN for Rust articles and save the best one" | get_news(topic="rust") -> read_url -> create_note |
| "Run this code and explain the error" | run_code -> (LLM reads stderr, explains) |
| "Remind me about the meeting I saw on HN" | get_news -> (LLM finds the item) -> set_reminder |
| "Is anyone at the front door?" | take_photo -> (VLM describes image) -> (LLM responds) |

The LLM learns when to chain tools from the system prompt and from the patterns in its
instruction tuning. The max of 5 rounds prevents infinite loops while allowing complex
multi-step workflows.

---

## Tool Result Formatting

Raw tool results often contain more data than the LLM needs. The formatter truncates,
summarizes, and structures results before they enter the LLM context window.

```python
import json


class ToolResultFormatter:
    """Format and truncate tool results for LLM consumption.

    The LLM context window is finite (8192 tokens). Tool results must be
    concise -- just enough information for the LLM to craft a response.
    """

    MAX_RESULT_CHARS = 3000  # Per tool result
    MAX_LIST_ITEMS = 10       # For list-type results

    def format(self, tool_name: str, result: ToolResult) -> str:
        """Format a ToolResult into a string for the LLM."""
        if not result.success:
            return f"Tool '{tool_name}' failed: {result.error}"

        data = result.data

        # Tool-specific formatting
        formatter = getattr(self, f"_format_{tool_name}", None)
        if formatter:
            return formatter(data)

        # Default: JSON dump with truncation
        return self._default_format(data)

    def _format_web_search(self, data: list[dict]) -> str:
        lines = ["Search results:"]
        for i, item in enumerate(data[:self.MAX_LIST_ITEMS], 1):
            lines.append(
                f"{i}. {item['title']}\n"
                f"   {item['url']}\n"
                f"   {item['snippet'][:150]}"
            )
        return "\n".join(lines)

    def _format_get_weather(self, data: dict) -> str:
        c = data["current"]
        lines = [
            f"Weather in {data['location']}:",
            f"  Now: {c['temp_c']}C (feels like {c['feels_like_c']}C), "
            f"{c['condition']}",
            f"  Humidity: {c['humidity_pct']}%, Wind: {c['wind_kph']} km/h",
        ]
        for day in data.get("forecast", []):
            lines.append(
                f"  {day['date']}: {day['high_c']}C/{day['low_c']}C, "
                f"{day['condition']}, {day['rain_chance_pct']}% rain"
            )
        return "\n".join(lines)

    def _format_read_url(self, data: dict) -> str:
        content = data.get("content", "")
        if len(content) > self.MAX_RESULT_CHARS:
            content = content[:self.MAX_RESULT_CHARS] + "\n[truncated]"
        return f"Content from {data['url']}:\n{content}"

    def _format_run_code(self, data: dict) -> str:
        parts = []
        if data.get("stdout"):
            stdout = data["stdout"][:2000]
            parts.append(f"stdout:\n{stdout}")
        if data.get("stderr"):
            stderr = data["stderr"][:1000]
            parts.append(f"stderr:\n{stderr}")
        return "\n".join(parts) if parts else "(no output)"

    def _format_get_news(self, data: list[dict]) -> str:
        lines = ["Headlines:"]
        for i, item in enumerate(data[:self.MAX_LIST_ITEMS], 1):
            title = item.get("title", "Untitled")
            score = item.get("score") or item.get("points", "")
            score_str = f" ({score} pts)" if score else ""
            lines.append(f"{i}. {title}{score_str}")
            if item.get("url"):
                lines.append(f"   {item['url']}")
        return "\n".join(lines)

    def _default_format(self, data) -> str:
        """Generic formatter for any tool result."""
        text = json.dumps(data, indent=2, default=str)
        if len(text) > self.MAX_RESULT_CHARS:
            text = text[:self.MAX_RESULT_CHARS] + "\n... [truncated]"
        return text
```

### Context Budget

The formatting step is critical for keeping tool results within the LLM's context
window. Here is how the context budget is allocated:

```
Total context window: 8192 tokens (~6000 usable)

┌────────────────────────────────────────────────────────┐
│  System prompt + personality + tool descriptions       │  ~1500 tokens
│  Conversation history (last 10-20 messages)            │  ~2000 tokens
│  Retrieved memories (top 5)                            │  ~500 tokens
│  Current user message                                  │  ~100 tokens
│  ──────────────────────────────────────────────────     │
│  Remaining for tool results + LLM response:            │  ~1900 tokens
│                                                        │
│  Each tool result: max ~800 tokens after formatting    │
│  LLM response generation: ~500 tokens reserved         │
│  Leaves room for 1-2 tool results per round            │
└────────────────────────────────────────────────────────┘
```

If tool results exceed the budget, the formatter aggressively truncates. The LLM can
always call `read_url` or re-query with narrower parameters if it needs more detail.

---

## Plugin System

Users can extend RAVEN with custom tools by dropping a Python file in the `plugins/`
directory. The tool registry auto-discovers these at startup.

### Writing a Plugin

A plugin is a single Python file that defines a class inheriting from `BaseTool`:

```python
# plugins/stock_price.py
#
# Custom tool: get stock prices from Yahoo Finance.
# Drop this file in the plugins/ directory and restart RAVEN.

from raven.tools.base import BaseTool, ToolParameter, ToolResult
import httpx


class StockPriceTool(BaseTool):
    name = "stock_price"
    description = (
        "Get the current stock price for a given ticker symbol. "
        "Use when the user asks about stock prices or market data."
    )
    parameters = [
        ToolParameter("ticker", "string",
                      "Stock ticker symbol, e.g. 'AAPL', 'GOOGL', 'TSLA'"),
    ]

    def __init__(self, config: dict):
        pass  # No config needed for this tool

    async def execute(self, ticker: str) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                    params={"interval": "1d", "range": "1d"},
                    headers={"User-Agent": "RAVEN/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("previousClose", 0)
            change_pct = ((price - prev_close) / prev_close * 100
                          if prev_close else 0)

            return ToolResult(
                success=True,
                data={
                    "ticker": ticker.upper(),
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "currency": meta.get("currency", "USD"),
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Could not fetch price for {ticker}: {e}"
            )
```

### Plugin Directory Structure

```
plugins/
  stock_price.py          # Each file = one tool
  unit_converter.py
  translate.py
  my_custom_api.py
  _helpers.py             # Files starting with _ are ignored
  __init__.py             # Not required
```

### Plugin Lifecycle

```
Startup:
  1. ToolRegistry scans plugins/ for .py files
  2. Each file is imported dynamically via importlib
  3. Classes inheriting BaseTool are instantiated with config
  4. Tool schemas are added to the LLM's tool list
  5. Tool shows up in system prompt automatically

Runtime:
  - Plugin tools are called exactly like built-in tools
  - Same timeout, error handling, and audit logging applies
  - Plugin exceptions are caught and logged, never crash the bot

Hot reload (future):
  - Watch plugins/ for file changes with watchdog
  - Re-import modified plugins without restarting the bot
```

---

## Error Handling Per Tool

Every tool handles its own errors gracefully. The ToolExecutor adds a second layer
of protection with timeouts and catch-all exception handling. The LLM receives
error information and can communicate the failure naturally to the user.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Error Handling Layers                            │
│                                                                        │
│  Layer 1: Inside the tool                                              │
│     - httpx.TimeoutException  ->  "Search timed out"                   │
│     - httpx.HTTPStatusError   ->  "API returned 503"                   │
│     - json.JSONDecodeError    ->  "Invalid response from API"          │
│     - FileNotFoundError       ->  "Camera not available"               │
│     - subprocess.TimeoutExpired -> "Code execution timed out"          │
│     - Any other exception     ->  "Tool error: {message}"             │
│                                                                        │
│  Layer 2: ToolExecutor                                                 │
│     - asyncio.wait_for(timeout=30s) wraps every tool call              │
│     - Catches any exception the tool didn't handle                     │
│     - Logs to audit_log table                                          │
│     - Returns ToolResult(success=False, error=...)                     │
│                                                                        │
│  Layer 3: RavenBrain                                                   │
│     - Receives the error as a tool result                              │
│     - LLM generates a natural error message for the user               │
│     - e.g. "I tried to search but the search engine is down.          │
│             Want me to check Wikipedia instead?"                       │
│                                                                        │
│  Layer 4: ToolExecutionError exception (fallback)                      │
│     - If brain._think_and_respond itself fails                         │
│     - Caught by handle_message's outer try/except                      │
│     - Returns a generic "something went wrong" message                 │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Per-Tool Timeout Configuration

Different tools have different expected latencies. Timeouts can be configured in
`config.yaml`:

```yaml
tools:
  web_search:
    enabled: true
    timeout_seconds: 15
  run_code:
    enabled: true
    timeout_seconds: 30
  read_url:
    enabled: true
    timeout_seconds: 20
  get_weather:
    enabled: true
    timeout_seconds: 10
  smart_home:
    enabled: true
    timeout_seconds: 10
  take_photo:
    enabled: true
    timeout_seconds: 10
  play_music:
    enabled: true
    timeout_seconds: 20
```

### Graceful Degradation

When a tool fails, RAVEN does not crash or give a raw error dump. The LLM receives
the error and crafts a helpful response:

```
Tool failure: web_search timed out
LLM response: "My search engine seems to be down right now. I can try
               checking Wikipedia if you want, or you could try again
               in a minute."

Tool failure: smart_home 503
LLM response: "I can't reach Home Assistant at the moment -- it might
               be restarting. Want me to try again in a few seconds?"

Tool failure: take_photo camera timeout
LLM response: "The front door camera isn't responding. Could be offline
               or the network is slow. I'll keep trying."
```

---

## Tool Summary

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Tool              │ Backend           │ Needs API Key │ Timeout (s)     │
├──────────────────────────────────────────────────────────────────────────┤
│  web_search        │ SearXNG (local)   │ No            │ 15              │
│  run_code          │ async subprocess  │ No            │ 30              │
│  read_url          │ httpx+trafilatura │ No            │ 20              │
│  get_weather       │ Open-Meteo        │ No            │ 10              │
│  set_reminder      │ APScheduler + PG  │ No            │ 5               │
│  set_alarm         │ APScheduler + PG  │ No            │ 5               │
│  smart_home        │ Home Assistant    │ HA token      │ 10              │
│  read_sensor       │ PostgreSQL        │ No            │ 5               │
│  take_photo        │ ffmpeg + RTSP     │ No            │ 10              │
│  play_music        │ mpv + yt-dlp      │ No            │ 20              │
│  calculate         │ ast + sympy       │ No            │ 5               │
│  get_news          │ HN API + RSS      │ No            │ 10              │
│  wikipedia         │ Wikipedia API     │ No            │ 10              │
│  create_note       │ PostgreSQL        │ No            │ 5               │
│  list_notes        │ PostgreSQL        │ No            │ 5               │
│  (plugins)         │ User-defined      │ Varies        │ 30 (default)    │
└──────────────────────────────────────────────────────────────────────────┘

Design decisions:
  - Every tool is async. No blocking calls.
  - No tool requires a paid API key by default. SearXNG, Open-Meteo,
    Wikipedia, and Hacker News are all free and self-hosted or public.
  - Home Assistant requires a long-lived access token, but HA itself
    is self-hosted.
  - The plugin system lets you add paid APIs (OpenAI, Stripe, Twilio)
    if you want them -- RAVEN just doesn't depend on them.
```
