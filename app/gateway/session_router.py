"""Session Router — Route channels to isolated agent sessions.

Different channels or chat groups can be routed to different agent personas.
For example, a Telegram work group gets the "DeveloperAgent" persona while
a personal Discord channel gets "PersonalAssistantAgent".
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RoutingRule:
    """A rule mapping a channel to an agent and session."""

    platform: str
    channel_id: str
    agent_name: str = ""          # Empty = use default agent
    session_prefix: str = ""      # Custom session prefix
    label: str = ""               # Human-readable label
    priority: int = 0             # Higher = checked first
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SessionRouter:
    """Routes channels/accounts to isolated agent sessions.

    Config is stored in ``workspace/config/routing.json``.

    Usage:
        router = SessionRouter()
        session_id = router.get_session("telegram", "group_123", "user_456")
        agent_name = router.get_agent("telegram", "group_123")
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            from app.settings.config import Config
            config_path = Path(Config.MEMORY_ROOT) / "config" / "routing.json"

        self._config_path = Path(config_path)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._rules: dict[str, RoutingRule] = {}
        self._load()

    # ── Public API ──────────────────────────────────────────────────

    def get_session(
        self, platform: str, channel_id: str, user_id: str
    ) -> str:
        """Return a session_id for this context.

        Sessions are scoped to (platform, channel, user) by default.
        Custom routing rules can override the session prefix.
        """
        rule = self._find_rule(platform, channel_id)
        if rule and rule.session_prefix:
            return f"{rule.session_prefix}:{user_id}"

        return f"{platform}:{channel_id}:{user_id}"

    def get_agent(self, platform: str, channel_id: str) -> str:
        """Return which agent handles this channel.

        Returns empty string if no specific routing is configured
        (meaning the default orchestrator routing applies).
        """
        rule = self._find_rule(platform, channel_id)
        if rule:
            return rule.agent_name
        return ""

    def set_routing(
        self,
        platform: str,
        channel_id: str,
        agent_name: str = "",
        session_prefix: str = "",
        label: str = "",
    ) -> RoutingRule:
        """Configure routing for a channel."""
        key = self._make_key(platform, channel_id)
        rule = RoutingRule(
            platform=platform,
            channel_id=channel_id,
            agent_name=agent_name,
            session_prefix=session_prefix or f"{platform}_{channel_id}",
            label=label or key,
        )
        self._rules[key] = rule
        self._save()
        logger.info("Set routing: %s → agent=%s", key, agent_name or "(default)")
        return rule

    def remove_routing(self, platform: str, channel_id: str) -> bool:
        """Remove routing for a channel."""
        key = self._make_key(platform, channel_id)
        if key in self._rules:
            del self._rules[key]
            self._save()
            return True
        return False

    def list_rules(self) -> list[RoutingRule]:
        """Return all configured routing rules."""
        return sorted(self._rules.values(), key=lambda r: -r.priority)

    def get_channels_for_agent(self, agent_name: str) -> list[RoutingRule]:
        """Return all channels routed to a specific agent."""
        return [r for r in self._rules.values() if r.agent_name == agent_name]

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _make_key(platform: str, channel_id: str) -> str:
        return f"{platform}:{channel_id}"

    def _find_rule(self, platform: str, channel_id: str) -> RoutingRule | None:
        key = self._make_key(platform, channel_id)
        return self._rules.get(key)

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            for key, entry in data.items():
                self._rules[key] = RoutingRule(**entry)
        except Exception as exc:
            logger.warning("Failed to load routing config: %s", exc)

    def _save(self) -> None:
        try:
            data = {key: asdict(rule) for key, rule in self._rules.items()}
            self._config_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save routing config: %s", exc)


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_ROUTER: SessionRouter | None = None


def get_session_router() -> SessionRouter:
    """Get or create the global SessionRouter."""
    global _GLOBAL_ROUTER
    if _GLOBAL_ROUTER is None:
        _GLOBAL_ROUTER = SessionRouter()
    return _GLOBAL_ROUTER
