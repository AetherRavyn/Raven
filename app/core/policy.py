from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.settings.config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
    permissions_missing: list[str] = field(default_factory=list)


class PolicyEngine:
    def __init__(self) -> None:
        self.user_permissions = self._parse_permissions(Config.TOOL_USER_PERMISSIONS)
        self.agent_permissions = self._parse_permissions(Config.TOOL_AGENT_PERMISSIONS)

    @staticmethod
    def _parse_permissions(raw: str) -> set[str]:
        return {item.strip() for item in raw.split(",") if item.strip()}

    @staticmethod
    def _capability_get(tool: Any) -> Any:
        getter = getattr(tool, "get_capabilities", None)
        if callable(getter):
            try:
                return getter()
            except Exception as exc:
                logger.debug("Tool capability lookup failed: %s", exc)
        return None

    def evaluate(
        self, tool: Any, *, user_id: str | None = None, agent_name: str | None = None
    ) -> PolicyDecision:
        capability = self._capability_get(tool)
        if capability is None:
            return PolicyDecision(allowed=True)

        required = set(getattr(capability, "required_permissions", []) or [])
        risk_level = str(getattr(capability, "risk_level", "low")).lower()
        confirmation_policy = str(
            getattr(capability, "confirmation_policy", "none")
        ).lower()

        granted = set(self.user_permissions) | set(self.agent_permissions)
        missing = sorted(required - granted)
        if missing:
            return PolicyDecision(
                allowed=False,
                reason="Missing required permissions",
                permissions_missing=missing,
            )

        if confirmation_policy in {"always", "confirm"} or risk_level in {
            "high",
            "critical",
        }:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Confirmation required",
            )

        return PolicyDecision(allowed=True)


_GLOBAL_POLICY_ENGINE = PolicyEngine()


def get_policy_engine() -> PolicyEngine:
    return _GLOBAL_POLICY_ENGINE
