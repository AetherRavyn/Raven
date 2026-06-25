"""Plugin System — extensible tool/hook/context engine system.

Allows users to add custom tools, hooks, and context engines
without modifying core Raven code.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PluginBase:
    """Base class for all Raven plugins."""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"

    def get_tools(self) -> list[Any]:
        return []

    def get_hooks(self) -> dict[str, list[Callable]]:
        return {}

    def get_context_providers(self) -> list[Callable]:
        return []


class PluginManager:
    """Discovers, loads, and manages plugins."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._plugins_dir = Path(self._workspace) / "plugins"
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, PluginBase] = {}
        self._hooks: dict[str, list[Callable]] = {}

    def discover_plugins(self) -> list[dict[str, Any]]:
        """Discover available plugins."""
        plugins = []
        for plugin_dir in self._plugins_dir.iterdir():
            if plugin_dir.is_dir():
                manifest = plugin_dir / "plugin.json"
                if manifest.exists():
                    try:
                        meta = json.loads(manifest.read_text(encoding="utf-8"))
                        meta["path"] = str(plugin_dir)
                        meta["loaded"] = plugin_dir.name in self._loaded
                        plugins.append(meta)
                    except Exception:
                        pass
        return plugins

    def load_plugin(self, name: str) -> dict[str, Any]:
        """Load a plugin by name."""
        plugin_dir = self._plugins_dir / name
        if not plugin_dir.exists():
            return {"error": f"Plugin '{name}' not found"}

        manifest_file = plugin_dir / "plugin.json"
        if not manifest_file.exists():
            return {"error": f"No plugin.json found in {plugin_dir}"}

        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            module_name = manifest.get("module", f"plugins.{name}.main")

            # Add plugin dir to path
            import sys
            plugin_path = str(plugin_dir)
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)

            module = importlib.import_module(module_name)

            # Instantiate plugin class
            plugin_class = getattr(module, manifest.get("class", "Plugin"), None)
            if plugin_class:
                plugin_instance = plugin_class()
                self._loaded[name] = plugin_instance

                # Register tools
                for tool in plugin_instance.get_tools():
                    logger.info("Plugin '%s' registered tool: %s", name, getattr(tool, 'get_name', lambda: 'unknown')())

                # Register hooks
                for hook_name, handlers in plugin_instance.get_hooks().items():
                    self._hooks.setdefault(hook_name, []).extend(handlers)

                return {"success": True, "name": name, "tools": len(plugin_instance.get_tools())}

            return {"error": f"No plugin class found in {module_name}"}

        except Exception as e:
            return {"error": str(e)[:500]}

    def run_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Run all registered hooks for a given hook point."""
        results = []
        for handler in self._hooks.get(hook_name, []):
            try:
                result = handler(*args, **kwargs)
                results.append(result)
            except Exception as e:
                logger.debug("Hook '%s' error: %s", hook_name, e)
        return results

    def get_loaded_plugins(self) -> list[str]:
        return list(self._loaded.keys())


# Singleton
_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager
