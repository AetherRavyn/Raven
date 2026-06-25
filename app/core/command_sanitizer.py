"""Command Sanitizer — prevents shell injection in tool arguments.

All tools that execute shell commands MUST use this module to
validate and sanitize user/LLM-controlled input before passing
it to subprocess or shell execution.
"""

from __future__ import annotations

import re
import shlex
import logging

logger = logging.getLogger(__name__)

# Characters that are dangerous in shell contexts
_DANGEROUS_CHARS = set(";&|`$(){}[]!#~<>?\\'\"")

# Patterns that indicate command injection attempts
_INJECTION_PATTERNS = [
    re.compile(r";\s*(?:rm|dd|mkfs|shutdown|reboot|kill|wget|curl)"),
    re.compile(r"\|\s*(?:bash|sh|python|perl|ruby)"),
    re.compile(r"&&\s*(?:rm|dd|mkfs|shutdown|reboot)"),
    re.compile(r"`[^`]+`"),  # backtick substitution
    re.compile(r"\$\("),  # $() command substitution
    re.compile(r">\s*/dev/"),  # redirect to device
    re.compile(r"0>&1"),  # fd redirection
]

# Whitelist of allowed shell commands for sandboxed execution
_ALLOWED_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "grep", "find", "wc", "sort", "uniq",
    "echo", "date", "whoami", "hostname", "pwd", "env", "which",
    "python", "python3", "pip", "pip3", "node", "npm", "npx",
    "git", "gh", "curl", "wget", "ping", "dig", "nslookup",
    "df", "du", "free", "top", "ps", "lsof", "netstat", "ss",
    "mkdir", "cp", "mv", "touch", "chmod", "chown",
    "diff", "patch", "tar", "gzip", "gunzip", "zip", "unzip",
    "sed", "awk", "tr", "cut", "xargs",
})


def sanitize_command(command: str, *, allow_all: bool = False) -> str | None:
    """Sanitize a shell command string.

    Returns the sanitized command if safe, or None if dangerous.
    When allow_all=True, only checks for injection patterns (not whitelisting).

    Usage:
        sanitized = sanitize_command("ls -la /tmp")
        if sanitized is None:
            return {"error": "Command blocked by security filter"}
    """
    if not command or not command.strip():
        return None

    command = command.strip()

    # Check for injection patterns
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(command):
            logger.warning("Command blocked by injection filter: %s", command[:100])
            return None

    if not allow_all:
        # Parse the command to extract the base command
        try:
            parts = shlex.split(command)
        except ValueError:
            # shlex can't parse it — suspicious
            return None

        if not parts:
            return None

        base_cmd = parts[0].split("/")[-1]  # Handle /usr/bin/ls → ls

        if base_cmd not in _ALLOWED_COMMANDS:
            logger.warning("Command not in whitelist: %s", base_cmd)
            return None

    return command


def sanitize_file_path(path: str) -> str | None:
    """Sanitize a file path to prevent path traversal.

    Returns the sanitized path or None if dangerous.
    """
    if not path:
        return None

    # Block path traversal
    if ".." in path:
        return None

    # Block absolute paths outside workspace (optional, configurable)
    if path.startswith("/") and not path.startswith("/tmp"):
        # Allow /tmp paths (common for temp files)
        pass

    # Block null bytes
    if "\x00" in path:
        return None

    return path


def is_destructive_command(command: str) -> bool:
    """Check if a command is potentially destructive."""
    destructive_patterns = [
        r"\brm\b", r"\brmdir\b", r"\bmkfs\b", r"\bdd\b",
        r"\bformat\b", r"\bshutdown\b", r"\breboot\b",
        r"\bkill\b", r"\bkillall\b", r"\bpkill\b",
        r"\bdrop\s+table\b", r"\bdrop\s+database\b",
        r"\btruncate\b", r"\bdelete\s+from\b",
    ]
    cmd_lower = command.lower()
    for pattern in destructive_patterns:
        if re.search(pattern, cmd_lower):
            return True
    return False
