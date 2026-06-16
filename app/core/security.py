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
    ("killo", "KILLO_API_KEY"),
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
    ``SARAS_VAULT_ENABLED`` is set.  When the vault is not enabled,
    the resolver falls back to env vars only.
    """
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is not None:
        return _DEFAULT_RESOLVER
    vault = None
    if os.environ.get("SARAS_VAULT_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from app.core.vault import SecretVault

            vault = SecretVault()
        except Exception as exc:  # noqa: BLE001
            logger.debug("vault unavailable, falling back to env: %s", exc)
    _DEFAULT_RESOLVER = CredentialsResolver(vault=vault)
    return _DEFAULT_RESOLVER


def resolve_credential(
    name: str, *, env_var: str | None = None, default: str | None = None
) -> str | None:
    """Convenience: look up a credential via the global resolver.

    Use this in new code; legacy code that reads ``Config.X`` directly
    continues to work.
    """
    return get_credentials_resolver().get(name, env_var=env_var, default=default)


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
        """
        config_path = os.path.expanduser("~/.saras/user_config.json")
        approval_level = "Balanced"

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    approval_level = cfg.get("approval_level", approval_level)
            except Exception:  # nosec  # fallback to defaults on bad config
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

        If DM pairing is disabled, always returns True.
        """
        dm_enabled = os.getenv("DM_PAIRING_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        if not dm_enabled:
            return True, "DM pairing disabled"

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
        config_path = os.path.expanduser("~/.saras/channel_permissions.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception:  # nosec  # fallback to defaults
                pass
        return {}

    def _save_channel_config(self, config: dict) -> None:
        """Save channel permissions config to JSON."""
        config_path = os.path.expanduser("~/.saras/channel_permissions.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save channel config: %s", exc)


_GLOBAL_SECURITY_GUARD = SecurityGuard()


def get_security_guard() -> SecurityGuard:
    return _GLOBAL_SECURITY_GUARD
