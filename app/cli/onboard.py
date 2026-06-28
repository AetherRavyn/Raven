"""Onboarding Wizard — ``raven onboard`` guided first-time setup.

Walks the user through API key configuration, channel setup, voice pipeline,
and identity customization. Inspired by Hermes/OpenClaw onboarding flows.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_RESET = "\033[0m"
_CHECK = f"{_GREEN}✓{_RESET}"
_CROSS = f"{_RED}✗{_RESET}"
_ARROW = f"{_CYAN}→{_RESET}"


def _banner() -> str:
    return f"""{_CYAN}{_BOLD}
    ╔══════════════════════════════════════════╗
    ║      🦅  Raven  Setup Wizard              ║
    ║   "Let's configure your agent."          ║
    ╚══════════════════════════════════════════╝
{_RESET}"""


def _prompt(question: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass

            answer = getpass.getpass(f"  {_ARROW} {question}{suffix}: ")
        else:
            answer = input(f"  {_ARROW} {question}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _confirm(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = _prompt(f"{question} {suffix}")
    if not answer:
        return default
    return answer.lower() in ("y", "yes", "1", "true")


def _section(title: str) -> None:
    print(f"\n{_BOLD}{_MAGENTA}━━━ {title} ━━━{_RESET}\n")


def _success(msg: str) -> None:
    print(f"  {_CHECK} {msg}")


def _skip(msg: str) -> None:
    print(f"  {_DIM}↷ {msg}{_RESET}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠ {msg}{_RESET}")


def _parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    return result


def _write_env_updates(env_file: Path, existing: dict[str, str], updates: dict[str, str]) -> None:
    lines: list[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f'{key}="{updates[key]}"')
                updated_keys.add(key)
                continue
        new_lines.append(line)
    remaining = {k: v for k, v in updates.items() if k not in updated_keys}
    if remaining:
        new_lines.append("\n# Added by raven onboard")
        for key, value in remaining.items():
            new_lines.append(f'{key}="{value}"')
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def run_onboarding(env_path: str | None = None) -> None:
    """Run the full onboarding wizard."""
    project_root = Path(__file__).resolve().parents[2]
    env_file = Path(env_path) if env_path else project_root / ".env"

    print(_banner())

    existing = _parse_env_file(env_file) if env_file.exists() else {}
    if existing:
        _success(f"Found existing .env ({len(existing)} keys)")
    else:
        _warn("No .env file found — creating from scratch.")

    updates: dict[str, str] = {}

    # Step 1: LLM Providers
    _section("Step 1: LLM Providers")
    providers = [
        ("GEMINI_API_KEY", "Gemini", "https://aistudio.google.com/apikey"),
        ("OPENAI_API_KEY", "OpenAI", "https://platform.openai.com/api-keys"),
        ("ANTHROPIC_API_KEY", "Anthropic", "https://console.anthropic.com"),
        ("GROQ_API_KEY", "Groq", "https://console.groq.com"),
        ("OPENROUTER_API_KEY", "OpenRouter", "https://openrouter.ai/keys"),
        ("XAI_API_KEY", "xAI/Grok", "https://console.x.ai"),
    ]
    for key, label, url in providers:
        if existing.get(key):
            _success(f"{label}: configured")
        elif _confirm(f"Configure {label}?"):
            val = _prompt(f"{label} key ({url})", secret=True)
            if val:
                updates[key] = val
                _success(f"{label}: set")
            else:
                _skip(f"{label}: skipped")
        else:
            _skip(f"{label}: skipped")

    # Step 2: Channels
    _section("Step 2: Messaging Channels")
    channels = [
        ("TELEGRAM_BOT_TOKEN", "Telegram Bot"),
        ("DISCORD_BOT_TOKEN", "Discord Bot"),
        ("SLACK_BOT_TOKEN", "Slack Bot"),
    ]
    for key, label in channels:
        if existing.get(key):
            _success(f"{label}: configured")
        elif _confirm(f"Configure {label}?", default=False):
            val = _prompt(f"{label} token", secret=True)
            if val:
                updates[key] = val
                _success(f"{label}: set")
        else:
            _skip(f"{label}: skipped")

    # Step 3: Location & Identity
    _section("Step 3: Identity")
    loc = _prompt("Your city (for weather)", default=existing.get("DEFAULT_LOCATION", ""))
    if loc:
        updates["DEFAULT_LOCATION"] = loc

    # Step 4: Voice
    _section("Step 4: Voice Pipeline")
    if _confirm("Enable voice (wake word + STT + TTS)?", default=False):
        updates["ENABLE_LOCAL_VOICE"] = "true"
        _success("Voice: enabled")
    else:
        _skip("Voice: disabled")

    # Save
    _section("Saving Configuration")
    if updates:
        _write_env_updates(env_file, existing, updates)
        _success(f"Wrote {len(updates)} settings to {env_file}")
    else:
        _skip("No changes to write")

    _section("Setup Complete! 🎉")
    print(f"  Run {_BOLD}raven doctor{_RESET} to verify everything works")
    print(f"  Run {_BOLD}raven chat{_RESET} to start chatting\n")
