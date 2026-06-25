"""Doctor — ``ravyn doctor`` system diagnostics.

Checks all services, API keys, channels, model connectivity, skills,
and system health. Reports issues with actionable fixes.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"
_CHECK = f"{_GREEN}✓{_RESET}"
_CROSS = f"{_RED}✗{_RESET}"
_WARN = f"{_YELLOW}⚠{_RESET}"


def _ok(msg: str) -> None:
    print(f"  {_CHECK} {msg}")


def _fail(msg: str) -> None:
    print(f"  {_CROSS} {msg}")


def _warn_msg(msg: str) -> None:
    print(f"  {_WARN} {msg}")


def _section(title: str) -> None:
    print(f"\n{_BOLD}{_CYAN}─── {title} ───{_RESET}")


def run_doctor() -> None:
    """Run full system diagnostics."""
    print(f"\n{_BOLD}🦅 AetherRavyn Doctor{_RESET}")
    print(f"{_DIM}Running diagnostics...{_RESET}")

    issues = 0
    warnings = 0

    # ── Python Environment ──────────────────────────────────────

    _section("Python Environment")
    version = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    if major >= 3 and minor >= 12:
        _ok(f"Python {version}")
    elif major >= 3 and minor >= 11:
        _warn_msg(f"Python {version} (3.12+ recommended)")
        warnings += 1
    else:
        _fail(f"Python {version} — requires 3.11+")
        issues += 1

    # Check venv
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        _ok(f"Virtual environment: {sys.prefix}")
    else:
        _warn_msg("Not running in a virtual environment")
        warnings += 1

    # ── Core Dependencies ───────────────────────────────────────

    _section("Core Dependencies")
    deps = [
        ("yaml", "pyyaml", True),
        ("sentence_transformers", "sentence-transformers", True),
        ("google.generativeai", "google-generativeai", False),
        ("openai", "openai", False),
        ("anthropic", "anthropic", False),
        ("mcp", "mcp", False),
        ("uvicorn", "uvicorn", False),
        ("fastapi", "fastapi", False),
        ("aiohttp", "aiohttp", True),
        ("apscheduler", "apscheduler", True),
    ]
    for module_name, package_name, required in deps:
        try:
            importlib.import_module(module_name)
            _ok(f"{package_name}")
        except ImportError:
            if required:
                _fail(f"{package_name} — MISSING (required)")
                issues += 1
            else:
                _warn_msg(f"{package_name} — not installed (optional)")
                warnings += 1

    # ── API Keys ────────────────────────────────────────────────

    _section("API Keys")

    keys = [
        ("GEMINI_API_KEY", "Gemini", True),
        ("OPENAI_API_KEY", "OpenAI", False),
        ("ANTHROPIC_API_KEY", "Anthropic", False),
        ("GROQ_API_KEY", "Groq", False),
        ("OPENROUTER_API_KEY", "OpenRouter", False),
        ("XAI_API_KEY", "xAI/Grok", False),
        ("VIRUSTOTAL_API_KEY", "VirusTotal", False),
        ("OPENWEATHERMAP_API_KEY", "OpenWeatherMap", False),
        ("WOLFRAM_ALPHA_APP_ID", "Wolfram Alpha", False),
    ]

    configured_providers = 0
    for key, label, recommended in keys:
        value = os.environ.get(key, "")
        if value:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            _ok(f"{label}: {masked}")
            if label in ("Gemini", "OpenAI", "Anthropic", "Groq", "OpenRouter", "xAI/Grok"):
                configured_providers += 1
        elif recommended:
            _warn_msg(f"{label}: not set (recommended)")
            warnings += 1
        else:
            print(f"  {_DIM}  {label}: not set{_RESET}")

    if configured_providers == 0:
        _fail("No LLM providers configured! Run: ravyn onboard")
        issues += 1

    # ── Messaging Channels ──────────────────────────────────────

    _section("Messaging Channels")
    channels = [
        ("TELEGRAM_BOT_TOKEN", "Telegram"),
        ("DISCORD_BOT_TOKEN", "Discord"),
        ("SLACK_BOT_TOKEN", "Slack"),
        ("WHATSAPP_BRIDGE_URL", "WhatsApp"),
    ]
    for key, label in channels:
        value = os.environ.get(key, "")
        if value:
            _ok(f"{label}: configured")
        else:
            print(f"  {_DIM}  {label}: not configured{_RESET}")

    # ── Identity Files ──────────────────────────────────────────

    _section("Identity Files")
    project_root = Path(__file__).resolve().parents[2]
    identity_files = [
        ("SOUL.md", True),
        ("MEMORY.md", True),
        ("AGENTS.md", True),
        ("Skills.md", False),
        ("Agent.md", False),
    ]
    for filename, required in identity_files:
        path = project_root / filename
        if path.exists():
            size = path.stat().st_size
            _ok(f"{filename} ({size:,} bytes)")
        elif required:
            _fail(f"{filename} — MISSING")
            issues += 1
        else:
            _warn_msg(f"{filename} — not found")
            warnings += 1

    # ── Skills ──────────────────────────────────────────────────

    _section("Skills System")
    skills_dir = project_root / "skills"
    if skills_dir.exists():
        bundled = list((skills_dir / "bundled").iterdir()) if (skills_dir / "bundled").exists() else []
        learned = list((skills_dir / "learned").iterdir()) if (skills_dir / "learned").exists() else []
        bundled_count = sum(1 for d in bundled if d.is_dir())
        learned_count = sum(1 for d in learned if d.is_dir())
        _ok(f"Bundled skills: {bundled_count}")
        _ok(f"Learned skills: {learned_count}")
    else:
        _warn_msg("Skills directory not found")
        warnings += 1

    # ── System Tools ────────────────────────────────────────────

    _section("System Tools")
    tools = [("docker", False), ("git", True), ("node", False), ("npm", False)]
    for tool_name, required in tools:
        if shutil.which(tool_name):
            _ok(f"{tool_name}: found")
        elif required:
            _fail(f"{tool_name}: NOT FOUND (required)")
            issues += 1
        else:
            print(f"  {_DIM}  {tool_name}: not found{_RESET}")

    # ── Disk Space ──────────────────────────────────────────────

    _section("Disk & Memory")
    try:
        statvfs = os.statvfs(str(project_root))
        free_gb = (statvfs.f_bavail * statvfs.f_frsize) / (1024**3)
        if free_gb > 5:
            _ok(f"Disk space: {free_gb:.1f} GB free")
        elif free_gb > 1:
            _warn_msg(f"Disk space: {free_gb:.1f} GB free (low)")
            warnings += 1
        else:
            _fail(f"Disk space: {free_gb:.1f} GB free (critical!)")
            issues += 1
    except Exception:
        _warn_msg("Could not check disk space")

    # ── Summary ─────────────────────────────────────────────────

    _section("Summary")
    if issues == 0 and warnings == 0:
        print(f"\n  {_GREEN}{_BOLD}All systems nominal! 🚀{_RESET}\n")
    elif issues == 0:
        print(f"\n  {_YELLOW}{_BOLD}{warnings} warning(s), no critical issues.{_RESET}\n")
    else:
        print(f"\n  {_RED}{_BOLD}{issues} issue(s), {warnings} warning(s).{_RESET}")
        print(f"  Run {_BOLD}ravyn onboard{_RESET} to fix configuration issues.\n")
