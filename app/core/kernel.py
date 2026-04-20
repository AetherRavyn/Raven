from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ModuleManifest:
    """Standardized metadata block for any SARAS component (Tool, Sensor, Agent)."""

    def __init__(
        self,
        name: str,
        kind: str,
        description: str,
        version: str = "1.0",
        capabilities: Dict[str, Any] | None = None,
    ):
        self.name = name
        self.kind = kind  # e.g., 'tool', 'agent', 'sensor'
        self.description = description
        self.version = version
        self.capabilities = capabilities or {}


class SystemKernel:
    """
    Central registry and capability graph for SARAS.
    All modules must register here to declare their intent, compute cost, and risk level.
    """

    def __init__(self):
        self.modules: Dict[str, ModuleManifest] = {}
        self._capability_graph: Dict[str, Any] = {
            "tools": [],
            "agents": [],
            "sensors": [],
        }

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool and map its capability footprint."""
        name = tool.get_name()
        caps = tool.get_capabilities()

        manifest = ModuleManifest(
            name=name,
            kind="tool",
            description=tool.get_description(),
            capabilities={
                "permissions": caps.required_permissions,
                "risk_level": caps.risk_level,
                "cost_tier": caps.cost_tier,
                "confirmation": caps.confirmation_policy,
                "readonly": caps.readonly,
            },
        )
        self.modules[name] = manifest
        self._update_graph("tools", manifest)
        logger.info(f"Kernel registered tool: {name} [Risk: {caps.risk_level}]")

    def register_agent(
        self, agent_name: str, description: str, risk_level: str = "low"
    ) -> None:
        """Register a swarm agent."""
        manifest = ModuleManifest(
            name=agent_name,
            kind="agent",
            description=description,
            capabilities={"risk_level": risk_level},
        )
        self.modules[agent_name] = manifest
        self._update_graph("agents", manifest)
        logger.info(f"Kernel registered agent: {agent_name}")

    def _update_graph(self, category: str, manifest: ModuleManifest) -> None:
        """Updates the live capability graph for routing."""
        self._capability_graph[category].append(
            {
                "name": manifest.name,
                "risk": manifest.capabilities.get("risk_level", "unknown"),
                "readonly": manifest.capabilities.get("readonly", True),
            }
        )

    def get_capability_graph(self) -> Dict[str, Any]:
        """Returns the full map of what SARAS is currently allowed to do."""
        return self._capability_graph

    def get_module(self, name: str) -> ModuleManifest | None:
        return self.modules.get(name)


# Global kernel instance
_KERNEL = SystemKernel()


def get_kernel() -> SystemKernel:
    return _KERNEL
