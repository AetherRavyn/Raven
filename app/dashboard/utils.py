"""Shared utilities for the SARAS Streamlit admin dashboard.

Provides:
- .env file read/write
- Agent discovery & introspection
- Memory file helpers
- Tool registry listing
- Platform connectivity checks
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # /home/.../SARAS
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
WORKSPACE_AGENTS = PROJECT_ROOT / "workspace" / "agents"
MEMORY_FILES = ["soul.md", "goals.md", "skill.md", "memory.md", "journal.md"]

# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------


def read_env_file(path: Path | None = None) -> Dict[str, str]:
    """Parse a .env file into an ordered dict (preserves blank lines as None keys)."""
    target = path or ENV_FILE
    if not target.exists():
        return {}
    result: Dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def read_env_raw(path: Path | None = None) -> str:
    """Return the raw .env file contents."""
    target = path or ENV_FILE
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def write_env_raw(content: str, path: Path | None = None) -> None:
    """Overwrite the .env file with new content. Creates a backup first."""
    target = path or ENV_FILE
    # Backup
    if target.exists():
        backup = target.with_suffix(".env.bak")
        shutil.copy2(target, backup)
    target.write_text(content, encoding="utf-8")


def update_env_value(key: str, value: str, path: Path | None = None) -> None:
    """Update a single key in the .env file (or append it)."""
    target = path or ENV_FILE
    raw = read_env_raw(target)
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(raw):
        raw = pattern.sub(new_line, raw)
    else:
        raw = raw.rstrip("\n") + f"\n{new_line}\n"
    write_env_raw(raw, target)


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------

# Agent class name -> module path mapping
_AGENT_MODULES = {
    "FinanceAgent": "app.agents.finance",
    "ResearcherAgent": "app.agents.researcher",
    "SecurityAgent": "app.agents.security",
    "ReviewerAgent": "app.agents.reviewer",
    "SysadminAgent": "app.agents.sysadmin",
    "DeveloperAgent": "app.agents.developer",
    "PersonalAssistantAgent": "app.agents.assistant",
    "NewsAgent": "app.agents.news",
    "HomeGuardianAgent": "app.agents.homeguardian",
    "HeraldAgent": "app.agents.communications",
    "PolymathAgent": "app.agents.scientist",
    "ConductorAgent": "app.agents.productivity",
    "ArchivistAgent": "app.agents.dataengineer",
    "ConscienceAgent": "app.agents.moral",
}


def get_agent_classes() -> Dict[str, type]:
    """Dynamically import and return all agent classes."""
    agents = {}
    for cls_name, mod_path in _AGENT_MODULES.items():
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            agents[cls_name] = cls
        except Exception as exc:
            logger.debug("Could not load %s: %s", cls_name, exc)
    return agents


def get_agent_instances() -> Dict[str, Any]:
    """Instantiate all discovered agent classes. Returns name->instance mapping.

    Some agents may fail to instantiate if their tool dependencies are missing.
    Those are silently skipped.
    """
    instances: Dict[str, Any] = {}
    for cls_name, cls in get_agent_classes().items():
        try:
            inst = cls()
            instances[inst.name] = inst
        except Exception as exc:
            logger.debug("Could not instantiate %s: %s", cls_name, exc)
    return instances


def get_agent_info(agent: Any) -> Dict[str, Any]:
    """Extract display-friendly information from a BaseAgent instance."""
    tool_names = []
    try:
        for t in agent.tools:
            tool_names.append(t.get_name())
    except Exception:
        pass

    return {
        "name": getattr(agent, "name", "Unknown"),
        "soul": getattr(agent, "soul", ""),
        "personality": getattr(agent, "personality", ""),
        "goals": getattr(agent, "goals", []),
        "perfectness": getattr(agent, "perfectness", 0.5),
        "heartbeat_interval": getattr(agent, "heartbeat_interval", 0),
        "provider_name": getattr(agent, "provider_name", "killo"),
        "model_name": getattr(agent, "model_name", ""),
        "tools": tool_names,
        "memory_dir": str(getattr(agent, "memory_dir", "")),
    }


# ---------------------------------------------------------------------------
# Memory file helpers
# ---------------------------------------------------------------------------


def list_agent_workspaces() -> List[str]:
    """Return list of agent workspace directory names."""
    if not WORKSPACE_AGENTS.exists():
        return []
    return sorted(d.name for d in WORKSPACE_AGENTS.iterdir() if d.is_dir())


def read_agent_memory_file(agent_dir_name: str, filename: str) -> str:
    """Read a specific memory file for an agent workspace."""
    p = WORKSPACE_AGENTS / agent_dir_name / filename
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def write_agent_memory_file(agent_dir_name: str, filename: str, content: str) -> None:
    """Write content to a specific memory file for an agent workspace."""
    d = WORKSPACE_AGENTS / agent_dir_name
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(content, encoding="utf-8")


def get_memory_stats() -> Dict[str, Any]:
    """Get aggregate stats about the agent memory system."""
    total_files = 0
    total_size = 0
    agent_count = 0
    for agent_dir in WORKSPACE_AGENTS.iterdir() if WORKSPACE_AGENTS.exists() else []:
        if not agent_dir.is_dir():
            continue
        agent_count += 1
        for f in agent_dir.iterdir():
            if f.is_file():
                total_files += 1
                total_size += f.stat().st_size
    return {
        "agent_workspaces": agent_count,
        "total_files": total_files,
        "total_size_kb": round(total_size / 1024, 1),
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# Maps tool class name -> module path for the full tool catalog
_TOOL_REGISTRY: Dict[str, str] = {
    "AdvancedFileOperationTool": "app.tools.filetool",
    "GitOperationTool": "app.tools.gittool",
    "KnowledgeGraphTool": "app.tools.kgtool",
    "NetworkTool": "app.tools.network",
    "BrowserOperationTool": "app.tools.browsertool",
    "VirusTotalTool": "app.tools.virustool",
    "WebOperationTool": "app.tools.websearch",
    "WebFetchOperationTool": "app.tools.webfetch",
    "XAIImageUnderstandTool": "app.tools.xaiimagetool",
    "FinanceOperationTool": "app.tools.finance",
    "WeatherTool": "app.tools.weathertool",
    "ReminderTool": "app.tools.remindertool",
    "SmartHomeTool": "app.tools.smarthometool",
    "SensorReadTool": "app.tools.sensorreadtool",
    "ImageGenerationTool": "app.tools.imagegentool",
    "CameraSnapshotTool": "app.tools.camerasnapshottool",
    "WolframAlphaTool": "app.tools.wolframtool",
    "SearXNGTool": "app.tools.searxngtool",
    "GoogleCalendarTool": "app.tools.toolkit.google.googlecalender",
    "SystemStatsTool": "app.tools.systemstatstool",
    "DockerTool": "app.tools.dockertool",
    "CryptoPriceTool": "app.tools.cryptopricetool",
    "RSSReaderTool": "app.tools.rssreadertool",
    "CommuteTool": "app.tools.commutetool",
    "PomodoroTool": "app.tools.pomodorotool",
    "TodoListTool": "app.tools.todolisttool",
    "TOTPGeneratorTool": "app.tools.totpgentool",
    "PlatformMessagingTool": "app.tools.messagingtool",
    "ObsidianOperationTool": "app.tools.obsidian",
    "SpotifyOperationTool": "app.tools.music.spotify",
    "NotionTool": "app.tools.toolkit.notes.notion",
    "AirQualityTool": "app.tools.airqualitytool",
    "MemoryTool": "app.tools.memorytool",
    "HackerNewsTool": "app.tools.news.hackernews",
    "ElevatedModeTool": "app.tools.elevatedtool",
    "ExecTool": "app.tools.exectool",
    "ApplyPatchTool": "app.tools.pathchtool",
    "WriteTodosTool": "app.tools.writetool",
    "GmailTool": "app.tools.toolkit.google.gmailtool",
    "GitHubTool": "app.tools.toolkit.github",
    "SupabaseTool": "app.tools.toolkit.supabasetool",
    "GoogleDocsTool": "app.tools.toolkit.google.docs",
    "GoogleSheetsTool": "app.tools.toolkit.google.sheet",
    "AgencyDelegationTool": "app.tools.agencytool",
}


def get_tool_info_list() -> List[Dict[str, str]]:
    """Return list of dicts with tool name, module path, and description (if loadable)."""
    result = []
    for cls_name, mod_path in sorted(_TOOL_REGISTRY.items()):
        info: Dict[str, str] = {
            "class": cls_name,
            "module": mod_path,
            "description": "",
            "status": "unknown",
        }
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            info["status"] = "loadable"
            # Try to get description without instantiating (some tools need args)
        except Exception as exc:
            info["status"] = f"error: {exc}"
        result.append(info)
    return result


# ---------------------------------------------------------------------------
# Platform connectivity checks
# ---------------------------------------------------------------------------

_PLATFORMS = {
    "Telegram": ("TELEGRAM_BOT_TOKEN",),
    "Discord": ("DISCORD_BOT_TOKEN",),
    "Slack": ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
    "WhatsApp": ("WHATSAPP_BRIDGE_URL",),
    "Web Dashboard": ("WEB_DASHBOARD_ENABLED",),
}


def get_platform_status() -> List[Dict[str, Any]]:
    """Check which platforms have their required env vars configured."""
    env = read_env_file()
    result = []
    for name, keys in _PLATFORMS.items():
        configured = all(
            env.get(k, "").strip()
            not in (
                "",
                "false",
                "your_telegram_bot_token_here",
                "your_discord_bot_token_here",
                "xoxb-...",
                "xapp-...",
            )
            for k in keys
        )
        result.append(
            {
                "platform": name,
                "configured": configured,
                "required_keys": list(keys),
            }
        )
    return result


def check_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open (service is running)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


# ---------------------------------------------------------------------------
# Env variable categorization (for the config page)
# ---------------------------------------------------------------------------

ENV_CATEGORIES: Dict[str, List[str]] = {
    "Core Platforms": [
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
        "DISCORD_CHANNEL_ID",
        "DISCORD_ENABLE_MESSAGE_CONTENT_INTENT",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "WHATSAPP_BRIDGE_URL",
    ],
    "AI Providers": [
        "XAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "KILLO_API_KEY",
        "KILLO_BASE_URL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
    ],
    "Google Services": [
        "GMAIL_CREDENTIALS_PATH",
        "GOOGLE_CALENDAR_CREDENTIALS_PATH",
        "GOOGLE_CALENDAR_TOKEN_PATH",
    ],
    "Productivity": [
        "OBSIDIAN_VAULT_PATH",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "NOTION_API_KEY",
    ],
    "Email (SMTP)": [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
    ],
    "Smart Home & Sensors": [
        "HOME_ASSISTANT_URL",
        "HOME_ASSISTANT_TOKEN",
        "MQTT_BROKER_URL",
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_TOPICS",
        "OPENWEATHERMAP_API_KEY",
        "DEFAULT_LOCATION",
    ],
    "Security & Research": [
        "VIRUSTOTAL_API_KEY",
        "WOLFRAM_ALPHA_APP_ID",
        "SEARXNG_URL",
    ],
    "Infrastructure": [
        "REDIS_URL",
        "DATABASE_URL",
        "MEMORY_BACKEND",
    ],
    "Voice": [
        "ENABLE_LOCAL_VOICE",
        "VOICE_STT_MODEL",
        "VOICE_TTS_VOICE",
        "VOICE_WAKE_WORD_THRESHOLD",
        "VOICE_REPLY_WITH_AUDIO",
        "DEEPGRAM_API_KEY",
        "API_KEY_SPEECHMATE",
    ],
    "Dashboards": [
        "WEB_DASHBOARD_ENABLED",
        "WEB_DASHBOARD_PORT",
        "WEB_DASHBOARD_HOST",
        "STREAMLIT_DASHBOARD_ENABLED",
        "STREAMLIT_DASHBOARD_PORT",
        "STREAMLIT_DASHBOARD_HOST",
    ],
    "Scheduling": [
        "MORNING_BRIEFING_USERS",
        "MORNING_BRIEFING_HOUR",
        "MORNING_BRIEFING_MINUTE",
    ],
    "Administration": [
        "ADMIN_USER_IDS",
    ],
}

# Sensitive keys that should be masked in the UI
SENSITIVE_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "XAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "KILLO_API_KEY",
    "VIRUSTOTAL_API_KEY",
    "DEEPGRAM_API_KEY",
    "API_KEY_SPEECHMATE",
    "HOME_ASSISTANT_TOKEN",
    "SMTP_PASS",
    "SPOTIFY_CLIENT_SECRET",
    "NOTION_API_KEY",
    "WOLFRAM_ALPHA_APP_ID",
    "MQTT_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
}
