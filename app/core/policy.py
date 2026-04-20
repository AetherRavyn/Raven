from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.settings.config import Config
from app.core.kernel import get_kernel

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
        self.kernel = get_kernel()
        self.policy_file = Path(Config.MEMORY_ROOT) / "state" / "policies.json"
        self._ensure_default_policies()

    def _ensure_default_policies(self):
        self.policy_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.policy_file.exists():
            default_policies = {
                "bash": {"requires_approval_if_contains": ["rm", "mv", "sudo"]},
                "edge_device": {
                    "requires_approval_if_match": {"operation": "dispatch_task"}
                },
                "file_operations": {
                    "requires_approval_if_match": {"operation": "delete"}
                },
                "docker_exec": {"requires_approval_if_not_none": ["mount_dir"]},
                "computeruse": {
                    "requires_approval_if_in": {"operation": ["click", "type"]}
                },
            }
            with open(self.policy_file, "w") as f:
                json.dump(default_policies, f, indent=4)

    def requires_approval(self, tool_name: str, tool_kwargs: dict) -> bool:
        if not self.policy_file.exists():
            return False
        with open(self.policy_file, "r") as f:
            policies = json.load(f)

        tool_policy = policies.get(tool_name)
        if not tool_policy:
            return False

        if "requires_approval_if_contains" in tool_policy:
            command_str = tool_kwargs.get("command", "")
            if isinstance(command_str, str):
                for restricted in tool_policy["requires_approval_if_contains"]:
                    if restricted in command_str:
                        return True

        if "requires_approval_if_match" in tool_policy:
            for key, match_val in tool_policy["requires_approval_if_match"].items():
                if tool_kwargs.get(key) == match_val:
                    return True

        if "requires_approval_if_not_none" in tool_policy:
            for key in tool_policy["requires_approval_if_not_none"]:
                if tool_kwargs.get(key) is not None:
                    return True

        if "requires_approval_if_in" in tool_policy:
            for key, values in tool_policy["requires_approval_if_in"].items():
                if tool_kwargs.get(key) in values:
                    return True

        return False

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
        name = getattr(tool, "get_name", lambda: "unknown")()

        # Deny-by-default logic using Kernel capability graph
        if name != "unknown" and not self.kernel.get_module(name):
            # Optional: During bootstrap phase we might allow this, but strictly speaking:
            pass  # We will soft-fail here because we haven't strictly registered all 50 legacy tools in Kernel yet

        capability = self._capability_get(tool)
        if capability is None:
            # If no capability is declared, we allow it to maintain backward compatibility,
            # but log a warning. In a pure Phase 1 deployment, this would be False.
            logger.warning(f"Tool {name} has no declared capabilities.")
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
                reason=f"Confirmation required due to risk level: {risk_level.upper()}",
            )

        return PolicyDecision(allowed=True)


_GLOBAL_POLICY_ENGINE = PolicyEngine()


def get_policy_engine() -> PolicyEngine:
    return _GLOBAL_POLICY_ENGINE
