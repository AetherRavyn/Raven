import logging
import re
import os
import json
from typing import List, Tuple

from app.settings.config import Config

logger = logging.getLogger(__name__)


class SecurityGuard:
    """
    The central security and authorization module for SARAS.
    Handles Prompt Injection detection, Role-Based Access Control (RBAC),
    and execution sanitization.
    """

    # Common jailbreak phrasing and system prompt override attempts
    JAILBREAK_PATTERNS = [
        r"(?i)\bignore all previous instructions\b",
        r"(?i)\byou are now\b",
        r"(?i)\bsystem prompt\b",
        r"(?i)\bdisregard previous\b",
        r"(?i)\bbypass restrictions\b",
        r"(?i)\bdo not follow the rules\b",
        r"(?i)\bsimulate a scenario where\b",
    ]

    # Highly destructive bash commands that should never be run automatically
    DANGEROUS_COMMANDS = [
        r"\brm\s+-rf\s+/\b",
        r"\brm\s+-rf\s+\*\b",
        r"\bmkfs\b",
        r"\bdd\s+if=.*of=/dev/sda\b",
        r">\s*/dev/sda\b",
        r"\b:\(\)\{\s*:\s*\|\s*:&\s*\};\s*:\b",  # Fork bomb
    ]

    def __init__(self):
        self.admin_users = Config.ADMIN_USER_IDS

        # Compile regexes for speed
        self._compiled_jailbreaks = [re.compile(p) for p in self.JAILBREAK_PATTERNS]
        self._compiled_dangerous_cmds = [re.compile(p) for p in self.DANGEROUS_COMMANDS]

    def is_admin(self, user_id: str) -> bool:
        """Check if a user ID is explicitly allowed to perform privileged actions."""
        if not self.admin_users:
            logger.warning(
                "No ADMIN_USER_IDS configured. All privileged actions will be blocked."
            )
            return False
        return str(user_id) in self.admin_users

    def analyze_prompt(self, text: str) -> Tuple[bool, str]:
        """
        Analyze incoming user text for prompt injection and jailbreak attempts.
        Returns (is_safe, reason).
        """
        for pattern in self._compiled_jailbreaks:
            if pattern.search(text):
                logger.warning(f"Prompt injection detected: matched {pattern.pattern}")
                return False, "Prompt injection or jailbreak attempt detected."
        return True, "Safe"

    def analyze_command(self, command: str) -> Tuple[bool, str]:
        """
        Analyze a shell command for catastrophic self-destruction patterns.
        Returns (is_safe, reason).
        """
        for pattern in self._compiled_dangerous_cmds:
            if pattern.search(command):
                logger.warning(f"Dangerous command blocked: matched {pattern.pattern}")
                return (
                    False,
                    "Catastrophically dangerous shell command detected and blocked.",
                )
        return True, "Safe"

    def requires_approval(self, tool_name: str, args: dict) -> Tuple[bool, str, str]:
        """
        Check if a tool execution requires explicit operator approval based on config.
        Returns: (needs_approval, risk_level, reason)
        """
        config_path = os.path.expanduser("~/.saras/user_config.json")
        approval_level = "Balanced"

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    approval_level = cfg.get("approval_level", approval_level)
            except Exception:
                pass

        high_risk_tools = {
            "system_execute",
            "git_ops",
            "file_operations",
            "agency_delegation",
            "virustotal_scanner",
            "sql_query",
            "bash_execute",
        }
        medium_risk_tools = {
            "messaging",
            "spotify_ops",
            "twitter_ops",
            "gmail_ops",
            "calendar_ops",
        }

        if approval_level.startswith("Autonomous"):
            # Only ask for strictly destructive actions even in autonomous
            if tool_name in ("system_execute", "bash_execute") and args.get(
                "command", ""
            ).startswith("rm "):
                return (
                    True,
                    "High",
                    "Destructive system command requires override even in autonomous mode.",
                )
            return False, "Low", "Autonomous mode enabled"

        if approval_level.startswith("Strict"):
            return (
                True,
                "High",
                "Strict approval policy requires manual authorization for all tools.",
            )

        # Balanced Mode (Default)
        if tool_name in high_risk_tools:
            # Exempt safe reads within high-risk tools
            if tool_name == "file_operations" and args.get("operation") in (
                "read",
                "info",
                "list",
            ):
                return False, "Low", "Safe read operation"
            if tool_name == "git_ops" and args.get("operation") in (
                "status",
                "log",
                "diff",
                "branch",
            ):
                return False, "Low", "Safe read operation"
            if (
                tool_name == "sql_query"
                and "select" in args.get("query", "").lower()
                and "drop" not in args.get("query", "").lower()
            ):
                return False, "Low", "Safe SELECT query"

            return (
                True,
                "High",
                f"{tool_name} is considered high risk in Balanced mode.",
            )

        if tool_name in medium_risk_tools:
            return True, "Medium", f"{tool_name} has external side effects."

        return False, "Low", "Safe operation"


_GLOBAL_SECURITY_GUARD = SecurityGuard()


def get_security_guard() -> SecurityGuard:
    return _GLOBAL_SECURITY_GUARD
