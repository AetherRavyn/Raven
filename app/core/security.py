import logging
import re
import os
import json
from typing import List, Tuple

from app.settings.config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential resolution (A4 — SecretVault integration)
# ---------------------------------------------------------------------------


class CredentialsResolver:
    """Look up sensitive credentials from the vault, then env, then default.

    This is the migration target for code that used to read
    ``os.environ["OPENAI_API_KEY"]`` directly.  When a vault is
    configured the encrypted value wins; otherwise the call
    transparently falls back to the environment so the legacy path
    keeps working.
    """

    def __init__(self, vault: "object | None" = None) -> None:
        self._vault = vault

    def get(
        self, name: str, *, env_var: str | None = None, default: str | None = None
    ) -> str | None:
        """Return the credential, preferring the vault.

        ``name`` is the vault entry name.  ``env_var`` is the legacy
        environment variable to fall back to.  If both are missing,
        ``default`` is returned.
        """
        if self._vault is not None:
            try:
                v = self._vault.get(name)  # type: ignore[attr-defined]
                if v:
                    return v
            except Exception as exc:  # noqa: BLE001
                logger.debug("vault lookup for %s failed: %s", name, exc)
        if env_var:
            env_v = os.environ.get(env_var, "").strip()
            if env_v:
                return env_v
        return default

    def get_required(self, name: str, *, env_var: str | None = None) -> str:
        v = self.get(name, env_var=env_var)
        if not v:
            raise KeyError(f"credential {name!r} not in vault or {env_var!r}")
        return v


# Mapping of (vault entry name, env-var name) for known credentials.
# Add new entries here as integrations come online.
KNOWN_CREDENTIALS: list[tuple[str, str]] = [
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("xai", "XAI_API_KEY"),
    ("opencode_zen", "OPENCODE_ZEN_API_KEY"),
    ("virustotal", "VIRUSTOTAL_API_KEY"),
    ("telegram_bot", "TELEGRAM_BOT_TOKEN"),
    ("discord_bot", "DISCORD_BOT_TOKEN"),
    ("slack_bot", "SLACK_BOT_TOKEN"),
    ("slack_app", "SLACK_APP_TOKEN"),
    ("deepgram", "DEEPGRAM_API_KEY"),
    ("home_assistant", "HOME_ASSISTANT_TOKEN"),
    ("notion", "NOTION_API_KEY"),
    ("openweathermap", "OPENWEATHERMAP_API_KEY"),
]


_DEFAULT_RESOLVER: CredentialsResolver | None = None


def get_credentials_resolver() -> CredentialsResolver:
    """Return a process-wide resolver.

    On first use, this lazily constructs a :class:`SecretVault` if
    ``RAVEN_VAULT_ENABLED`` is set.  When the vault is not enabled,
    the resolver falls back to env vars only.
    """
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is not None:
        return _DEFAULT_RESOLVER
    vault = None
    if os.environ.get("RAVEN_VAULT_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from app.core.vault import SecretVault

            vault = SecretVault()
        except Exception as exc:  # noqa: BLE001
            logger.debug("vault unavailable, falling back to env: %s", exc)
    _DEFAULT_RESOLVER = CredentialsResolver(vault=vault)
    return _DEFAULT_RESOLVER


# ── Rotation hooks (P5.7) ────────────────────────────────────────────
#
# A credential is "rotated" when its underlying value changes —
# usually because a secret manager (Vault, AWS SM, etc.) replaced
# it, or an operator restarted the service with new env vars.
#
# Without an explicit rotation hook, ``CredentialsResolver.get`` will
# happily return the *old* value for the lifetime of the process.
# Tools that hold a credential across a long run (e.g. an LLM
# provider client with a long-lived session) would silently keep
# using the stale key — possibly causing 401s that look like outages.
#
# The fix: every call to :func:`resolve_credential` registers the
# (name, env_var) pair in :data:`_ROTATION_REGISTRY`. An external
# rotation source (admin CLI, vault webhook, SIGHUP handler) calls
# :func:`rotate_credential` to record a rotation event. Tools can
# then opt-in to a freshness check via :func:`is_credential_stale`
# and re-fetch on stale.


import time as _time
from typing import Any, Dict, Optional

_ROTATION_REGISTRY: Dict[str, Dict[str, Any]] = {}
# {credential_key: {"last_fetched": float, "last_rotated": float,
#                   "fetch_count": int, "name": str, "env_var": Optional[str]}}


def _cred_key(name: str, env_var: str | None) -> str:
    """Canonical key for a credential lookup."""
    return f"{name}::{env_var or ''}"


def resolve_credential(
    name: str, *, env_var: str | None = None, default: str | None = None
) -> str | None:
    """Convenience: look up a credential via the global resolver.

    Use this in new code; legacy code that reads ``Config.X`` directly
    continues to work.

    This call is recorded in the rotation registry. Operators can
    call :func:`rotate_credential` to mark a credential as rotated
    (forcing a re-read on the next call), or
    :func:`is_credential_stale` to check freshness.
    """
    key = _cred_key(name, env_var)
    value = get_credentials_resolver().get(name, env_var=env_var, default=default)
    _record_fetch(key, name, env_var)
    return value


def _record_fetch(key: str, name: str, env_var: str | None) -> None:
    """Update the registry with a fresh fetch timestamp."""
    prev = _ROTATION_REGISTRY.get(key, {})
    _ROTATION_REGISTRY[key] = {
        "name": name,
        "env_var": env_var,
        "last_fetched": _time.time(),
        "last_rotated": prev.get("last_rotated", 0.0),
        "fetch_count": prev.get("fetch_count", 0) + 1,
    }


def _record_rotate(key: str, name: str, env_var: str | None) -> None:
    """Mark a credential as rotated (without recording a fetch)."""
    prev = _ROTATION_REGISTRY.get(key, {})
    _ROTATION_REGISTRY[key] = {
        "name": name,
        "env_var": env_var,
        "last_rotated": _time.time(),
        "last_fetched": prev.get("last_fetched", 0.0),
        "fetch_count": prev.get("fetch_count", 0),
    }


def rotate_credential(name: str, *, env_var: str | None = None) -> str:
    """Mark a credential as rotated.

    After this call:
    - the next :func:`resolve_credential` with the same ``name`` and
      ``env_var`` will re-read from the vault / env;
    - any cached downstream state (e.g. an LLM client) must be
      refreshed by its owner.

    The function returns the *new* value (re-read at call time) so
    the rotation source can sanity-check the new credential
    immediately.

    Important: this function does **not** record a fetch — so the
    credential is left "stale" until the caller actually does the
    refresh via :func:`resolve_credential`.
    """
    key = _cred_key(name, env_var)
    _record_rotate(key, name, env_var)
    # Force the global resolver to be rebuilt so the new vault / env
    # values are picked up on the next read.
    global _DEFAULT_RESOLVER
    _DEFAULT_RESOLVER = None
    new_value = get_credentials_resolver().get(name, env_var=env_var)
    logger.info(
        "credential rotated: name=%s env_var=%s has_new_value=%s",
        name, env_var, bool(new_value),
    )
    return new_value or ""


def is_credential_stale(name: str, *, env_var: str | None = None) -> bool:
    """Return True if the credential has been rotated since last read.

    A long-lived client should call this periodically; if True,
    drop any cached state and re-fetch via :func:`resolve_credential`.
    """
    key = _cred_key(name, env_var)
    entry = _ROTATION_REGISTRY.get(key)
    if not entry:
        return False  # never read; nothing is "stale"
    return entry.get("last_rotated", 0.0) > entry.get("last_fetched", 0.0)


def rotation_registry() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of the rotation registry (for diagnostics)."""
    return {
        k: dict(v) for k, v in _ROTATION_REGISTRY.items()
    }


def reset_rotation_registry() -> None:
    """Drop the rotation registry.  Tests use this between cases."""
    _ROTATION_REGISTRY.clear()


class SecurityGuard:
    """
    The central security and authorization module for RAVEN.
    Handles Prompt Injection detection, Role-Based Access Control (RBAC),
    and execution sanitization.
    """

    # Common jailbreak phrasing and system prompt override attempts
    JAILBREAK_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        r"(?i)disregard\s+(all\s+)?prior\s+directions",
        r"(?i)disregard\s+(all\s+)?previous\s+instructions",
        r"(?i)you\s+are\s+now\s+(?:a|an|the)",
        r"(?i)forget\s+(all\s+)?(?:your|the)\s+(?:rules|instructions|guidelines)",
        r"(?i)system\s*prompt\s*(?:override|injection|override)",
        r"(?i)bypass\s+(?:all\s+)?(?:restrictions|safety|rules|guidelines)",
        r"(?i)do\s+not\s+follow\s+(?:the\s+)?(?:rules|guidelines|instructions)",
        r"(?i)act\s+as\s+if\s+(?:you\s+)?(?:have\s+)?(?:no|zero)\s+(?:restrictions|rules)",
        r"(?i)\bpretend\s+(?:you\s+)?(?:are|have)\s+(?:no|zero)\s+(?:restrictions|rules)",
        r"(?i)jailbreak",
        r"(?i)DAN\s+mode",
        r"(?i)developer\s+mode\s+(?:enabled|activated)",
        r"(?i)\bdo\s+anything\s+now\b",
        r"(?i)simulated\s+environment.*(?:no\s+rules|no\s+restrictions)",
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
            logger.warning("No ADMIN_USER_IDS configured. All privileged actions will be blocked.")
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

        Phase 0.4 — reads through `policy_cache.get_approval_config()` which
        caches the JSON read for 30 s. This avoids the per-call disk hit
        and the race condition with simultaneous writes.
        """
        from app.core.policy_cache import get_approval_config

        cfg = get_approval_config()
        approval_level = cfg.get("approval_level", "Balanced")

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
            # Check for destructive commands even in autonomous mode
            if tool_name in ("system_execute", "bash_execute", "sandbox_exec"):
                from app.core.command_sanitizer import is_destructive_command
                cmd = args.get("command", "").strip()
                if cmd and is_destructive_command(cmd):
                    return (
                        True,
                        "High",
                        f"Destructive command requires override even in autonomous mode: {cmd[:60]}",
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

    # ------------------------------------------------------------------
    # Per-Channel Tool Permissions (Phase 3 Enhancement)
    # ------------------------------------------------------------------

    def get_channel_permissions(self, platform: str, channel_id: str) -> set[str] | None:
        """Return allowed tool names for a specific channel.

        Returns None if no restrictions are set (all tools allowed).
        Returns a set of tool names if an allowlist is configured.
        """
        config = self._load_channel_config()
        key = f"{platform}:{channel_id}"
        entry = config.get(key)
        if entry is None:
            return None  # No restrictions
        allowed = entry.get("allowed_tools")
        if allowed is None:
            return None
        return set(allowed)

    def set_channel_permissions(
        self,
        platform: str,
        channel_id: str,
        allowed_tools: list[str],
        label: str = "",
    ) -> None:
        """Set tool allowlist for a channel."""
        config = self._load_channel_config()
        key = f"{platform}:{channel_id}"
        config[key] = {
            "allowed_tools": allowed_tools,
            "label": label or key,
            "updated_at": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
        }
        self._save_channel_config(config)
        logger.info(
            "Set channel permissions for %s: %d tools allowed",
            key,
            len(allowed_tools),
        )

    def is_tool_allowed(
        self,
        tool_name: str,
        platform: str,
        channel_id: str,
        user_id: str,
    ) -> tuple[bool, str]:
        """Check if a tool is allowed in this context.

        Returns (allowed, reason).
        """
        # Admin always allowed
        if self.is_admin(user_id):
            return True, "Admin user"

        # Check channel-level permissions
        allowed_tools = self.get_channel_permissions(platform, channel_id)
        if allowed_tools is not None and tool_name not in allowed_tools:
            return False, f"Tool '{tool_name}' not in channel allowlist"

        return True, "Allowed"

    def check_dm_pairing(self, user_id: str, platform: str) -> tuple[bool, str]:
        """Check if a DM user is paired. Returns (is_paired, message).

        If DM pairing is disabled via env or dashboard, always returns True.
        """
        dm_enabled_env = os.getenv("DM_PAIRING_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        if not dm_enabled_env:
            return True, "DM pairing disabled via environment"
            
        try:
            from app.core.dm_pairing import get_dm_pairing_manager
            manager = get_dm_pairing_manager()
            if not manager.is_pairing_enabled():
                return True, "DM pairing disabled via dashboard"
        except Exception:
            pass

        if self.is_admin(user_id):
            return True, "Admin user"

        try:
            from app.core.dm_pairing import get_dm_pairing_manager

            manager = get_dm_pairing_manager()
            if manager.is_paired(user_id, platform):
                return True, "User is paired"

            code = manager.generate_pairing_code(user_id, platform)
            return False, (
                f"🔒 You need to pair before chatting. "
                f"Your pairing code is: **{code}**\n"
                f"Ask your admin to run: `ravyn approve-pairing {code}`"
            )
        except Exception as exc:
            logger.warning("DM pairing check failed: %s", exc)
            return True, "Pairing check failed — allowing access"

    # ------------------------------------------------------------------
    # Channel Config Helpers
    # ------------------------------------------------------------------

    def _load_channel_config(self) -> dict:
        """Load channel permissions config from JSON."""
        config_path = os.path.expanduser("~/.raven/channel_permissions.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception:  # nosec  # fallback to defaults
                pass
        return {}

    def _save_channel_config(self, config: dict) -> None:
        """Save channel permissions config to JSON."""
        config_path = os.path.expanduser("~/.raven/channel_permissions.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save channel config: %s", exc)


_GLOBAL_SECURITY_GUARD = SecurityGuard()


def get_security_guard() -> SecurityGuard:
    return _GLOBAL_SECURITY_GUARD
