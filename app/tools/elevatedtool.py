from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.security import get_security_guard
from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------


class ElevatedLevel(str, Enum):
    OFF = "off"
    ON = "on"  # alias for ask
    ASK = "ask"  # same behaviour as on
    FULL = "full"


# Normalise on/ask → ask internally so comparisons are clean
_ALIASES = {"on": ElevatedLevel.ASK}

VALID_LEVELS = {e.value for e in ElevatedLevel}

# Directive patterns:  /elevated <level>  |  /elev <level>
_DIRECTIVE_RE = re.compile(
    r"^\s*/(?:elevated|elev)(?::)?\s*([a-z]*)?\s*$",
    re.IGNORECASE,
)

# Per-session state:  session_key → ElevatedLevel
_SESSION_STATE: Dict[str, ElevatedLevel] = {}


# ---------------------------------------------------------------------------
# Allowlist matching helpers
# ---------------------------------------------------------------------------


def _match_sender(entry: str, sender: Dict[str, str]) -> bool:
    """
    Match a single allowlist entry against sender metadata.

    Prefixed entries:
        name:<v>      → SenderName
        username:<v>  → SenderUsername
        tag:<v>       → SenderTag
        id:<v>        → SenderId
        from:<v>      → From
        e164:<v>      → SenderE164

    Unprefixed entries match only immutable identity fields:
        SenderId, SenderE164, From
    """
    entry = entry.strip()
    prefixed_map = {
        "name": "SenderName",
        "username": "SenderUsername",
        "tag": "SenderTag",
        "id": "SenderId",
        "from": "From",
        "e164": "SenderE164",
    }

    if ":" in entry:
        prefix, _, value = entry.partition(":")
        field = prefixed_map.get(prefix.lower())
        if not field:
            return False
        return sender.get(field, "") == value

    # Unprefixed → immutable identity fields only
    return entry in (
        sender.get("SenderId", ""),
        sender.get("SenderE164", ""),
        sender.get("From", ""),
    )


def _sender_in_allowlist(
    allow_list: List[str],
    sender: Dict[str, str],
) -> bool:
    return any(_match_sender(e, sender) for e in allow_list)


# ---------------------------------------------------------------------------
# Core elevated state manager
# ---------------------------------------------------------------------------


class ElevatedManager:
    """
    Encapsulates all elevated-mode logic so it can be shared between the
    tool and any middleware that needs to resolve the effective level.
    """

    def __init__(
        self,
        *,
        global_enabled: bool = True,
        global_allow_from: Optional[Dict[str, List[str]]] = None,
        agent_enabled: Optional[bool] = None,
        agent_allow_from: Optional[Dict[str, List[str]]] = None,
        default_level: ElevatedLevel = ElevatedLevel.OFF,
        is_sandboxed: bool = True,
    ):
        self.global_enabled = global_enabled
        self.global_allow_from: Dict[str, List[str]] = global_allow_from or {}
        self.agent_enabled = agent_enabled  # None = no per-agent restriction
        self.agent_allow_from: Dict[str, List[str]] = agent_allow_from or {}
        self.default_level = default_level
        self.is_sandboxed = is_sandboxed

    # ---------------------------------------------------------------- gates

    def is_available(self, provider: str, sender: Dict[str, str]) -> bool:
        """All gates must pass for elevated to be available."""
        if not self.global_enabled:
            return False
        if self.agent_enabled is False:
            return False

        # RBAC Check via Security Guard
        guard = get_security_guard()
        user_id = sender.get("SenderId", "") or sender.get("id", "")
        if not guard.is_admin(user_id):
            logger.warning(f"Elevated mode blocked: User {user_id} is not an admin.")
            return False

        # Global allowlist check
        global_list = self._resolve_allowlist(
            provider,
            self.global_allow_from,
            use_discord_fallback=True,
        )
        if global_list is not None and not _sender_in_allowlist(global_list, sender):
            return False

        # Per-agent allowlist check (no discord fallback for per-agent)
        if self.agent_allow_from:
            agent_list = self._resolve_allowlist(
                provider,
                self.agent_allow_from,
                use_discord_fallback=False,
            )
            if agent_list is not None and not _sender_in_allowlist(agent_list, sender):
                return False

        return True

    def _resolve_allowlist(
        self,
        provider: str,
        allow_from: Dict[str, List[str]],
        *,
        use_discord_fallback: bool,
    ) -> Optional[List[str]]:
        """
        Return the effective allowlist for *provider*, or None if no list is
        configured (meaning all senders are allowed for that provider).
        """
        if provider in allow_from:
            return allow_from[provider]

        # Discord-specific fallback (global only)
        if provider == "discord" and use_discord_fallback:
            fallback = getattr(Config, "DISCORD_ALLOW_FROM", None)
            if fallback is not None:
                return fallback

        # If allow_from has entries for other providers but not this one,
        # we treat this provider as unrestricted (no list = open).
        return None if not allow_from else []

    # ---------------------------------------------------------------- resolve

    def resolve_level(
        self,
        session_key: str,
        inline_directive: Optional[str] = None,
    ) -> ElevatedLevel:
        """
        Resolution order:
        1. Inline directive on the message
        2. Session override
        3. Global default
        """
        if inline_directive:
            lvl = _normalise(inline_directive)
            if lvl:
                return lvl

        session_lvl = _SESSION_STATE.get(session_key)
        if session_lvl is not None:
            return session_lvl

        return self.default_level

    # ---------------------------------------------------------------- exec behaviour

    def exec_on_host(self, level: ElevatedLevel) -> bool:
        """Should exec run on the gateway host?"""
        if not self.is_sandboxed:
            return False  # already on host, no-op for location
        return level in (ElevatedLevel.ON, ElevatedLevel.ASK, ElevatedLevel.FULL)

    def auto_approve_exec(self, level: ElevatedLevel) -> bool:
        """Should exec approvals be skipped?"""
        return level == ElevatedLevel.FULL

    def security_full(self, level: ElevatedLevel) -> bool:
        """Does this level set exec.security=full?"""
        return level == ElevatedLevel.FULL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(raw: str) -> Optional[ElevatedLevel]:
    """Return a canonical ElevatedLevel or None if unrecognised."""
    v = raw.strip().lower()
    if v in _ALIASES:
        return _ALIASES[v]
    try:
        return ElevatedLevel(v)
    except ValueError:
        return None


def _parse_inline_directive(message: str) -> Optional[str]:
    """
    Extract the level argument from an inline /elevated directive, or
    return None if the message does not contain one.
    """
    m = _DIRECTIVE_RE.match(message)
    if m:
        return m.group(1) or ""  # "" means status query
    return None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class ElevatedModeTool(BaseTool):
    """
    Handle /elevated (and /elev) directives for elevated execution mode.

    Supports:
        /elevated on      — host exec, keep approvals  (alias for ask)
        /elevated ask     — host exec, keep approvals
        /elevated full    — host exec, auto-approve exec (security=full)
        /elevated off     — disable elevated mode
        /elevated         — query current level

    Constructor kwargs (all optional):
        global_enabled      bool
        global_allow_from   dict  e.g. {"discord": ["id:12345"], "whatsapp": ["+1..."]}
        agent_enabled       bool  (None = no per-agent restriction)
        agent_allow_from    dict
        default_level       str   "off"|"on"|"ask"|"full"
        is_sandboxed        bool  (default True)
    """

    def __init__(self, **cfg: Any):
        default_raw = cfg.get("default_level", "off")
        default_lvl = _normalise(str(default_raw)) or ElevatedLevel.OFF

        self.manager = ElevatedManager(
            global_enabled=bool(cfg.get("global_enabled", True)),
            global_allow_from=cfg.get("global_allow_from") or {},
            agent_enabled=cfg.get("agent_enabled"),
            agent_allow_from=cfg.get("agent_allow_from") or {},
            default_level=default_lvl,
            is_sandboxed=bool(cfg.get("is_sandboxed", True)),
        )

    # ---------------------------------------------------------- tool metadata

    def get_name(self) -> str:
        return "elevated_mode"

    def get_description(self) -> str:
        return (
            "Manage elevated execution mode via /elevated (or /elev) directives. "
            "Controls whether exec runs on the gateway host and whether approvals "
            "are required. Levels: on/ask (host exec, keep approvals), "
            "full (host exec, auto-approve, security=full), off (disabled)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="message",
                    type="string",
                    description=(
                        "The raw message containing the directive, e.g. '/elevated full'. "
                        "Used to detect inline directives and session-set commands."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="level",
                    type="string",
                    description=(
                        "Explicit level to set: 'on', 'ask', 'full', or 'off'. "
                        "If provided alongside 'message', this takes precedence."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="session_key",
                    type="string",
                    description="Unique key identifying the current session (e.g. channel+user ID).",
                    required=False,
                ),
                ToolParameter(
                    name="provider",
                    type="string",
                    description=(
                        "Messaging provider name for allowlist matching "
                        "(e.g. 'discord', 'whatsapp', 'slack')."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="sender",
                    type="object",
                    description=(
                        "Sender metadata dict used for allowlist checks. "
                        "Recognised keys: SenderId, SenderName, SenderUsername, "
                        "SenderTag, SenderE164, From."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="is_group",
                    type="boolean",
                    description=(
                        "True if this is a group chat. In group chats, directives are "
                        "only honoured when the agent is mentioned."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="agent_mentioned",
                    type="boolean",
                    description=(
                        "True if the agent was mentioned (required for directives in group chats)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "'set' (default) to apply a directive, "
                        "'status' to query the current level, "
                        "'resolve' to get the effective level for a message without changing state."
                    ),
                    required=False,
                ),
            ],
        )

    # ---------------------------------------------------------------- execute

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        message: str = kwargs.get("message", "").strip()
        explicit_level: Optional[str] = kwargs.get("level")
        session_key: str = kwargs.get("session_key", "default")
        provider: str = kwargs.get("provider", "")
        sender: Dict[str, str] = kwargs.get("sender") or {}
        is_group: bool = bool(kwargs.get("is_group", False))
        agent_mentioned: bool = bool(kwargs.get("agent_mentioned", True))
        action: str = kwargs.get("action", "set").lower()

        # --- group chat gate ---
        if is_group and not agent_mentioned:
            return {
                "success": True,
                "output": "Elevated directive ignored: agent not mentioned in group chat.",
                "ignored": True,
            }

        # --- status query ---
        if action == "status":
            current = self.manager.resolve_level(session_key)
            return {
                "success": True,
                "output": self._status_message(session_key, current),
                "level": current.value,
            }

        # --- determine the requested level ---
        raw_level: Optional[str] = None

        if explicit_level:
            raw_level = explicit_level

        elif message:
            inline = _parse_inline_directive(message)
            if inline is None:
                # Not a directive message — just resolve the effective level (no state change)
                effective = self.manager.resolve_level(session_key)
                return {
                    "success": True,
                    "output": f"No directive found. Current effective level: {effective.value}.",
                    "level": effective.value,
                    "changed": False,
                }
            if inline == "":
                # /elevated with no argument → status
                current = self.manager.resolve_level(session_key)
                return {
                    "success": True,
                    "output": self._status_message(session_key, current),
                    "level": current.value,
                }
            raw_level = inline

        else:
            return {
                "success": False,
                "output": "Error: provide 'message' with a directive or an explicit 'level'.",
            }

        # --- validate the level ---
        level = _normalise(raw_level)
        if level is None:
            hint = ", ".join(sorted(VALID_LEVELS))
            return {
                "success": False,
                "output": (
                    f"Unknown elevated level '{raw_level}'. Valid values: {hint}."
                ),
            }

        # --- availability check (only matters when turning on) ---
        if level != ElevatedLevel.OFF:
            if not self.manager.is_available(provider, sender):
                return {
                    "success": False,
                    "output": (
                        "Elevated mode is not available: either it is disabled in config "
                        "or you are not on the approved allowlist. "
                        "Check tools.elevated.enabled and tools.elevated.allowFrom."
                    ),
                    "available": False,
                }

        # --- resolve mode: apply to message only, no session change ---
        if action == "resolve":
            effective = self.manager.resolve_level(
                session_key, inline_directive=raw_level
            )
            return {
                "success": True,
                "output": f"Effective level for this message: {effective.value}.",
                "level": effective.value,
                "exec_on_host": self.manager.exec_on_host(effective),
                "auto_approve_exec": self.manager.auto_approve_exec(effective),
                "security_full": self.manager.security_full(effective),
                "changed": False,
            }

        # --- set session state ---
        if level == ElevatedLevel.OFF:
            _SESSION_STATE.pop(session_key, None)
            msg = "Elevated mode disabled."
        else:
            _SESSION_STATE[session_key] = level
            msg = self._confirmation_message(level)

        # Logging
        logger.info(
            "Elevated mode set to '%s' for session '%s' (provider=%s, sender=%s)",
            level.value,
            session_key,
            provider,
            sender,
        )

        return {
            "success": True,
            "output": msg,
            "level": level.value,
            "exec_on_host": self.manager.exec_on_host(level),
            "auto_approve_exec": self.manager.auto_approve_exec(level),
            "security_full": self.manager.security_full(level),
            "changed": True,
        }

    # ---------------------------------------------------------------- helpers

    def _confirmation_message(self, level: ElevatedLevel) -> str:
        if level in (ElevatedLevel.ON, ElevatedLevel.ASK):
            return (
                "Elevated mode set to ask. "
                "Exec will run on the gateway host; approval policy still applies."
            )
        if level == ElevatedLevel.FULL:
            return (
                "Elevated mode set to full. "
                "Exec will run on the gateway host with exec approvals skipped "
                "and security=full."
            )
        return "Elevated mode disabled."

    def _status_message(self, session_key: str, level: ElevatedLevel) -> str:
        parts = [f"elevated={level.value}"]
        if self.manager.exec_on_host(level):
            parts.append("exec=host")
        if self.manager.auto_approve_exec(level):
            parts.append("approvals=skipped")
        if self.manager.security_full(level):
            parts.append("security=full")
        return f"Current session status: {', '.join(parts)}."
