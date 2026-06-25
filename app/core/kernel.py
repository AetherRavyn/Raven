from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ModuleManifest:
    """Standardized metadata block for any RAVEN component (Tool, Sensor, Agent)."""

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
    Central registry and capability graph for RAVEN.
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

    def deregister(self, name: str) -> bool:
        """Remove a registered tool/agent by name.

        Returns ``True`` if a manifest was removed, ``False`` if
        nothing was registered under ``name``.  Mirrors the
        inverse of :meth:`register_tool` and :meth:`register_agent`
        so the loader's ``_undo_tool`` / ``_undo_agent`` rollback
        step can clean the kernel after a module hot-unload.

        The capability graph entry for the name is also removed
        so :meth:`get_capability_graph` does not advertise a
        no-longer-registered tool/agent.
        """
        removed = self.modules.pop(name, None)
        if removed is None:
            return False
        # Strip the matching entry from whichever capability-graph
        # bucket the manifest was filed under.  The graph is a
        # simple list-of-dicts keyed by ``name``.
        kind = removed.kind
        bucket_key = {
            "tool": "tools",
            "agent": "agents",
            "sensor": "sensors",
        }.get(kind)
        if bucket_key is not None:
            self._capability_graph[bucket_key] = [
                entry
                for entry in self._capability_graph[bucket_key]
                if entry.get("name") != name
            ]
        logger.info("Kernel deregistered %s: %s", kind, name)
        return True

    # Alias for API consistency
    deregister_tool = deregister
    deregister_agent = deregister

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
        """Returns the full map of what RAVEN is currently allowed to do."""
        return self._capability_graph

    def get_module(self, name: str) -> ModuleManifest | None:
        return self.modules.get(name)


# Global kernel instance
_KERNEL = SystemKernel()


def get_kernel() -> SystemKernel:
    return _KERNEL
