"""Modular Extension Platform (Module_Platform).

Turns AetherRavyn from a fixed-capability agent into an extensible
platform by defining one unified module contract.  This package
wraps and reuses existing core subsystems rather than replacing
them.

The two main entry points for production wiring are:

  * :func:`bootstrap_modular_platform` — connects the
    :class:`ModuleLoader` to the running orchestrator's real
    collaborators (tool runtime, swarm, kernel, event bridge,
    audit, standing orders, health monitor, sandbox, etc.).
    Called from ``main.py`` at startup.

  * :func:`get_module_loader` — returns the lazily-initialised
    singleton so other subsystems (the CLI, tests, ambient
    loops) can interact with the loader without rebuilding
    the whole stack.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Module-level singleton (mirrors the pattern used by
# ``get_action_logger`` / ``get_botsignal`` / etc.).  ``None``
# until :func:`bootstrap_modular_platform` has wired the
# collaborators and instantiated the loader.
_module_loader_singleton: Any = None
_module_registry_singleton: Any = None
_bootstrapped_at: float | None = None


def get_module_loader() -> Any:
    """Return the process-wide ModuleLoader (or ``None`` if not bootstrapped).

    Test code that wants to exercise the modular platform can
    call :func:`bootstrap_modular_platform` with its own
    collaborators; production callers use ``main.py``'s
    startup wiring.
    """
    return _module_loader_singleton


def get_module_registry() -> Any:
    """Return the process-wide :class:`ModuleRegistry` (or ``None``)."""
    return _module_registry_singleton


def reset_for_tests() -> None:  # pragma: no cover - test seam only
    """Drop the cached singleton.  Used by the test fixtures so the
    bootstrap can be re-invoked with different collaborators."""
    global _module_loader_singleton, _module_registry_singleton, _bootstrapped_at
    _module_loader_singleton = None
    _module_registry_singleton = None
    _bootstrapped_at = None


def bootstrap_modular_platform(
    *,
    modules_root: str | os.PathLike[str] | None = None,
    orchestrator: Any | None = None,
    botsignal: Any | None = None,
    auto_load: bool = True,
    operator: str = "system",
) -> Any:
    """Wire the :class:`ModuleLoader` to the live orchestrator.

    Idempotent: calling it twice is a no-op for the second call
    unless :func:`reset_for_tests` was invoked in between.
    ``None`` is returned when ``modules_root`` is empty / unset
    so the caller can log a single line and continue.

    Parameters
    ----------
    modules_root:
        Directory containing module subdirectories.  When
        ``None`` (the default), the function reads
        ``Config.MODULES_ROOT`` / ``RAVEN_MODULES_ROOT``.  An
        empty value means the platform stays dormant — the
        caller sees ``None`` returned.
    orchestrator:
        The live :class:`MessageOrchestrator` whose tool
        runtime, swarm manager, and kernel the modular
        platform will register capabilities into.  When
        ``None``, the function builds its own minimal
        collaborators (useful for CLI / smoke tests).
    botsignal:
        The :class:`BotSignal` used to route module-raised
        notifications.  When ``None``, the function falls
        back to :func:`get_botsignal`.
    auto_load:
        When ``True`` (default), every discoverable module
        that passes trust gating is registered and enabled
        after bootstrap.  When ``False``, the loader is
        built and ready but modules are not loaded — the
        CLI can then ``raven modules register ...`` them
        explicitly.
    operator:
        The audit-log actor name for the auto-load step.

    Returns
    -------
    The bootstrapped :class:`ModuleLoader` instance, or
    ``None`` when the platform is dormant (``modules_root``
    is empty or non-existent).
    """
    global _module_loader_singleton, _module_registry_singleton, _bootstrapped_at

    if _module_loader_singleton is not None:
        return _module_loader_singleton

    # Resolve the modules root, honouring the Config default.
    from app.settings.config import Config

    if modules_root is None:
        modules_root = Config.MODULES_ROOT
    if not modules_root:
        logger.debug(
            "Modular platform dormant: RAVEN_MODULES_ROOT is not set",
        )
        return None
    root_path = Path(modules_root).expanduser().resolve()
    if not root_path.is_dir():
        logger.warning(
            "Modular platform root %s does not exist or is not a directory; "
            "platform stays dormant",
            root_path,
        )
        return None

    # Lazy imports keep ``import app.modules`` cheap — the heavy
    # collaborators (ActionLogger, OutputRouter, SentinelBridge,
    # ModuleLoader itself) are only built when bootstrap is asked
    # for, matching the rest of the core's lazy-init style.
    from app.core.audit import ActionLogger, get_action_logger
    from app.core.health import HealthMonitor, get_health_monitor
    from app.core.output_router import OutputRouter, get_output_router
    from app.core.policy import get_policy_engine
    from app.core.sentinel_bridge import SentinelBridge, get_sentinel_bridge
    from app.core.standing_orders import StandingOrderStore

    from app.modules import loader as loader_mod
    from app.modules import permissions as perms_mod
    from app.modules import registry as registry_mod
    from app.modules import secrets as secrets_mod
    from app.modules.dependencies import DependencyResolver
    from app.modules.event_bridge import EventBridge
    from app.modules.health import HealthMonitor as ModHealthMonitor

    # The platform-level ``SandboxManager`` lives in ``app.core``;
    # the modular platform wraps it (``Sandbox = ModuleSandbox``
    # from ``app.modules.sandbox`` if present, else the core one).
    try:
        from app.modules.sandbox import Sandbox as ModuleSandbox
    except ImportError:  # pragma: no cover - module-level fallback
        ModuleSandbox = None  # type: ignore[assignment]
    from app.core.sandbox_manager import SandboxManager as CoreSandboxManager

    # Build / reuse collaborators.  When the live orchestrator is
    # wired in we share its tool runtime, swarm, and kernel so
    # module-registered tools/agents show up in the user's chat
    # path with zero extra wiring.
    audit = get_action_logger() or ActionLogger(path=str(root_path / "audit.log"))
    router = get_output_router() or OutputRouter()
    sentinel = get_sentinel_bridge() or SentinelBridge()

    # Health monitor and StandingOrderStore need a workspace dir;
    # place them under the modules root so each install has its
    # own log and orders file (matches the modular platform's
    # isolation principle).
    standing_orders = StandingOrderStore(workspace_dir=str(root_path))
    # The core HealthMonitor and the modular-platform one have the
    # same signature — prefer the shared singleton so a module
    # crash lands in the same audit log as everything else.
    try:
        monitor = get_health_monitor()
        # The singleton's constructor signature differs; rebuild
        # with the shared router + audit so records route the same
        # way as the rest of RAVEN.
        if not isinstance(monitor, ModHealthMonitor):
            monitor = ModHealthMonitor(router, audit)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - lazy init never breaks bootstrap
        monitor = ModHealthMonitor(router, audit)  # type: ignore[arg-type]

    event_bridge = EventBridge(sentinel, router, standing_orders, monitor)

    # Tool runtime / swarm / kernel from the live orchestrator
    # when available; otherwise build minimal stand-ins.
    if orchestrator is not None:
        tool_runtime = getattr(orchestrator, "_agent_runtime", None)
        swarm = getattr(orchestrator, "_swarm_manager", None)
        kernel = getattr(orchestrator, "_kernel", None) or getattr(
            orchestrator, "_system_kernel", None
        )
    else:
        tool_runtime = None
        swarm = None
        kernel = None

    if tool_runtime is None:
        # Build a minimal FakeToolRuntime-shaped shim that satisfies
        # ModuleLoader's ``register_tool`` / ``deregister_tool`` API
        # without dragging in the full AgentRuntime (which requires
        # a configured workspace + LLM provider to construct).
        class _MinimalToolRuntime:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def register_tool(self, tool: Any) -> None:
                self.tools[tool.get_name()] = tool

            def deregister_tool(self, name: str) -> bool:
                return self.tools.pop(name, None) is not None

        tool_runtime = _MinimalToolRuntime()

    if swarm is None:
        from app.core.agency import SwarmManager

        swarm = SwarmManager(workspace_dir=str(root_path))

    if kernel is None:
        from app.core.kernel import SystemKernel

        kernel = SystemKernel()

    # Trust gating, secrets, broker, sandbox — the modular-platform
    # versions of these are what the loader is typed against.
    secret_resolver = secrets_mod.SecretResolver(
        vault=None,  # type: ignore[arg-type] - presence-only at bootstrap
    )
    sandbox = CoreSandboxManager(workspace_dir=str(root_path))
    dep_resolver = DependencyResolver(sandbox)
    broker = perms_mod.PermissionBroker(get_policy_engine(), audit)
    registry = registry_mod.ModuleRegistry(
        kernel=kernel, roots=[root_path],
    )

    loader = loader_mod.ModuleLoader(
        registry=registry,
        broker=broker,
        dependency_resolver=dep_resolver,
        secret_resolver=secret_resolver,
        event_bridge=event_bridge,
        health_monitor=monitor,
        kernel=kernel,
        swarm=swarm,
        standing_orders=standing_orders,
        tool_runtime=tool_runtime,
        audit=audit,
        sandbox=sandbox,
        dashboard=None,  # wired by a later task (UI surface tests)
    )

    _module_loader_singleton = loader
    _module_registry_singleton = registry
    import time as _time
    _bootstrapped_at = _time.time()

    logger.info(
        "Modular platform bootstrapped at %s (operator=%s, auto_load=%s)",
        root_path, operator, auto_load,
    )

    if auto_load:
        # Best-effort auto-load: failures are logged but never
        # abort the orchestrator (a faulty module must not block
        # the live system — it shows up in the audit log instead).
        _auto_load_discovered_modules(loader, operator=operator)

    return loader


async def bootstrap_modular_platform_async(
    *,
    modules_root: str | os.PathLike[str] | None = None,
    orchestrator: Any | None = None,
    botsignal: Any | None = None,
    auto_load: bool = True,
    operator: str = "system",
) -> Any:
    """Async wrapper around :func:`bootstrap_modular_platform`.

    Mirrors the loader's async API surface so ``main.py`` can
    ``await`` the bootstrap in a single line.  Currently the
    bootstrap itself is synchronous; the async signature is
    forward-compatible with a future lazy-discovery step.
    """
    return bootstrap_modular_platform(
        modules_root=modules_root,
        orchestrator=orchestrator,
        botsignal=botsignal,
        auto_load=auto_load,
        operator=operator,
    )


def _auto_load_discovered_modules(loader: Any, *, operator: str) -> None:
    """Discover + register every module under the configured root.

    Honours :attr:`Config.MODULES_AUTO_LOAD_COMMUNITY` for trust
    gating (Req 5.x): a module whose manifest declares
    ``trust_level: community`` is *not* auto-loaded by default
    and shows up in the audit log as ``awaiting approval``.

    Errors are isolated per the platform's "failure of one module
    must not stop the others" invariant (Req 6.5).
    """
    import asyncio

    from app.settings.config import Config

    async def _run() -> None:
        registry = _module_registry_singleton
        if registry is None:
            return
        records = await registry.discover()
        logger.info(
            "Modular platform discovered %d module record(s)", len(records),
        )
        for record in records:
            trust = (record.trust_level or "").lower()
            if trust == "community" and not Config.MODULES_AUTO_LOAD_COMMUNITY:
                logger.info(
                    "Skipping auto-load of community-trust module %s "
                    "(set RAVEN_MODULES_AUTO_LOAD_COMMUNITY=true to override)",
                    record.module_id,
                )
                continue
            try:
                result = await loader.register(record, operator=operator)
                if result.ok:
                    logger.info(
                        "Auto-loaded module %s -> %s",
                        record.module_id, result.state.value,
                    )
                else:
                    logger.warning(
                        "Auto-load of module %s failed: %s",
                        record.module_id, result.detail,
                    )
            except Exception:  # noqa: BLE001 - one module must not block the rest
                logger.exception(
                    "Auto-load of module %s raised; continuing",
                    record.module_id,
                )

    try:
        loop = asyncio.get_running_loop()
        # Inside an async context: schedule the work and let
        # the caller await the loader's first register() result.
        loop.create_task(_run())
        return
    except RuntimeError:
        # No running loop — bootstrap_modular_platform is being
        # called from a sync context (tests, CLI).  Run the work
        # in a fresh loop.  Python 3.10+ deprecated
        # ``asyncio.get_event_loop`` outside of a running loop,
        # so we build a new one explicitly.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()