"""Module_Loader and RegistrationLedger for the Modular Extension Platform.

The ``ModuleLoader`` orchestrates the full module lifecycle (validate -> resolve
-> permit -> register/hot-load -> enable/disable -> hot-unload -> uninstall) and
is the only component that mutates subsystem state. Every mutation it performs is
mirrored into a :class:`RegistrationLedger` so it can be reversed atomically.

This module implements :class:`RegistrationLedger` (assumption A2) and the
``ModuleLoader`` lifecycle: ``_hot_load`` and its paired ``_undo_*`` helpers
(task 9.2), the ``register`` pipeline (task 9.3), and ``_hot_unload`` /
``enable`` / ``disable`` / ``reregister`` / ``uninstall`` (task 9.4).

Assumption A2: the existing subsystems (``SystemKernel``, ``SwarmManager``,
``StandingOrderStore``) expose only register/parse methods and no deregistration
introspection, so the per-module ledger -- not subsystem state -- is the
authoritative source of truth for rollback (Req 6.5, 10.7).
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.audit import AuditEvent
from app.modules.dependencies import DependencyResolver
from app.modules.manifest import validate_manifest
from app.modules.models import (
    CapabilityBundle,
    LifecycleResult,
    ModuleState,
    ProvidesType,
    UndoEntry,
)

if TYPE_CHECKING:
    from app.agents.base import BaseAgent
    from app.core.agency import SwarmManager
    from app.core.audit import ActionLogger
    from app.core.kernel import SystemKernel
    from app.core.sandbox_manager import SandboxManager
    from app.core.standing_orders import StandingOrderStore
    from app.modules.event_bridge import EventBridge
    from app.modules.health import HealthMonitor
    from app.modules.models import ModuleRecord, ProvidesEntry
    from app.modules.permissions import PermissionBroker
    from app.modules.registry import ModuleRegistry
    from app.modules.secrets import SecretResolver
    from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Fallback running platform version used for manifest compatibility checks when
# the installed package metadata cannot be read (matches pyproject ``version``).
_FALLBACK_RUNNING_VERSION = "0.1.0"


def _running_version() -> str:
    """Return the running AetherRavyn version for manifest compatibility checks.

    Reads the installed package version, falling back to the pinned project
    version when the metadata is unavailable (e.g. running from a source tree
    that was never installed).
    """
    try:
        from importlib.metadata import version

        return version("raven")
    except Exception:  # noqa: BLE001 - metadata is best-effort; fall back to pinned
        return _FALLBACK_RUNNING_VERSION


class BundleBuildError(Exception):
    """Raised when a ``provides`` entry cannot be loaded into a CapabilityBundle.

    Carries the bundle ``item_id`` of the offending entry so the registration
    pipeline can report the failed item (Req 6.5).
    """

    def __init__(self, item_id: str | None, message: str) -> None:
        super().__init__(message)
        self.item_id = item_id


class RegistrationLedger:
    """Per-module ordered undo log.

    Each :class:`~app.modules.models.UndoEntry` pairs a subsystem with the
    inverse action needed to remove a just-registered capability-bundle item.
    The ledger is the authoritative source of truth for rollback (assumption
    A2): hot-unload and failed-registration rollback replay it rather than
    introspecting subsystem state.

    Entries are appended in registration order via :meth:`push` and replayed in
    last-in-first-out order by :meth:`rollback`, so the most recently registered
    item is reversed first.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: list[UndoEntry] = []

    def push(self, undo: UndoEntry) -> None:
        """Append an undo entry recording how to reverse a registration step."""
        self._entries.append(undo)

    def entries(self) -> list[UndoEntry]:
        """Return the recorded undo entries in registration (push) order."""
        return list(self._entries)

    async def rollback(self) -> list[str]:
        """Replay every undo entry in LIFO order, collecting non-fatal errors.

        Each entry's ``undo`` callable may be synchronous or asynchronous: a
        coroutine result is awaited, a plain callable is invoked directly. An
        error raised by any single undo is caught and logged so it does not
        abort the remaining rollback steps -- partial failure must never leave
        more items reversed than necessary.

        Returns the item ids that were reversed, in the LIFO order they were
        reversed (most recently registered first).
        """
        reversed_ids: list[str] = []
        for entry in reversed(self._entries):
            try:
                result = entry.undo()
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - non-fatal; collect and continue
                logger.exception(
                    "Rollback undo failed for %s item %r; continuing",
                    entry.subsystem,
                    entry.item_id,
                )
            reversed_ids.append(entry.item_id)
        self._entries.clear()
        return reversed_ids


class ModuleLoader:
    """Orchestrates the module lifecycle and is the sole mutator of subsystem state.

    Every subsystem mutation the loader performs is mirrored into a
    :class:`RegistrationLedger` so it can be reversed atomically. :meth:`_hot_load`
    and its paired ``_undo_*`` helpers register each :class:`CapabilityBundle` item
    with its owning subsystem and record the inverse action immediately after each
    success (Req 6.1, 6.3); :meth:`register` runs the full validate -> resolve ->
    permit -> build -> hot-load pipeline with atomic rollback (Req 6.5);
    :meth:`_hot_unload` replays a module's ledger to deregister everything it
    contributed (Req 10.7); and :meth:`enable`, :meth:`disable`,
    :meth:`reregister`, and :meth:`uninstall` drive the remaining lifecycle
    transitions (Req 6.6, 6.7, 10.1-10.6).

    The ``dashboard`` dependency is optional: the dashboard surface is built later
    (task 12) and wired in at bootstrap (task 13.1). When it is absent, UI-surface
    registration is skipped with a warning and its undo is a safe no-op, keeping
    hot-load and hot-unload symmetric over the bundle's items.
    """

    def __init__(
        self,
        registry: ModuleRegistry,
        broker: PermissionBroker,
        dependency_resolver: DependencyResolver,
        secret_resolver: SecretResolver,
        event_bridge: EventBridge,
        health_monitor: HealthMonitor,
        kernel: SystemKernel,
        swarm: SwarmManager,
        standing_orders: StandingOrderStore,
        tool_runtime: Any,  # AgentRuntime tool layer (register/deregister tool)
        audit: ActionLogger,
        sandbox: SandboxManager,
        dashboard: Any = None,  # dashboard panel registry (task 12), wired at bootstrap
        hot_load_timeout_s: float = 5.0,  # Req 6.2 / 14.3
    ) -> None:
        self._registry = registry
        self._broker = broker
        self._dependency_resolver = dependency_resolver
        self._secret_resolver = secret_resolver
        self._event_bridge = event_bridge
        self._health_monitor = health_monitor
        self._kernel = kernel
        self._swarm = swarm
        self._standing_orders = standing_orders
        self._tool_runtime = tool_runtime
        self._audit = audit
        self._sandbox = sandbox
        self._dashboard = dashboard
        self._hot_load_timeout_s = hot_load_timeout_s
        # Per-module registration ledger retained after a successful hot-load so a
        # later hot-unload (task 9.4) can replay it in reverse (Req 10.7, A2).
        self._ledgers: dict[str, RegistrationLedger] = {}

    # ── Hot-load dispatch (Req 6.1, 6.3) ───────────────────────────────

    async def _hot_load(
        self,
        record: ModuleRecord,
        bundle: CapabilityBundle,
        ledger: RegistrationLedger,
    ) -> None:
        """Register every bundle item with its subsystem, recording each undo.

        Items are registered in a fixed order (tools, agents, skills, event
        sources, detectors, reactions, UI surfaces). An :class:`UndoEntry` is
        pushed onto ``ledger`` immediately **after** each successful registration,
        so a failure partway through can be reversed by replaying exactly the
        steps that succeeded (Req 6.5). The undo of each item is the paired
        ``_undo_*`` helper, which calls the A2 deregistration helpers.

        Per the dispatch table (design): tools register with the tool layer and
        the kernel; agents with the swarm and the kernel; skills with the
        Module_Registry; event sources, detectors, and reactions with the
        Event_Bridge (reactions persist into the StandingOrderStore); and UI
        surfaces with the dashboard.
        """
        module_id = record.module_id

        for tool in bundle.tools:
            self._tool_runtime.register_tool(tool)
            self._kernel.register_tool(tool)
            name = tool.get_name()
            ledger.push(UndoEntry("tool", name, lambda t=tool: self._undo_tool(t)))

        for agent in bundle.agents:
            self._swarm.register_agent(agent)
            self._kernel.register_agent(agent.name, f"Module agent from {module_id}")
            ledger.push(
                UndoEntry("agent", agent.name, lambda a=agent: self._undo_agent(a))
            )

        for skill_name in bundle.skills:
            self._registry.add_skill(record)
            ledger.push(
                UndoEntry(
                    "skill",
                    skill_name,
                    lambda mid=module_id: self._undo_skill(mid),
                )
            )

        for source in bundle.event_sources:
            self._event_bridge.register_source(module_id, source)
            ledger.push(
                UndoEntry(
                    "event_source",
                    source.name,
                    lambda mid=module_id, n=source.name: self._undo_source(mid, n),
                )
            )

        for detector in bundle.detectors:
            self._event_bridge.register_detector(module_id, detector)
            ledger.push(
                UndoEntry(
                    "anomaly_detector",
                    detector.name,
                    lambda mid=module_id, n=detector.name: self._undo_detector(mid, n),
                )
            )

        for reaction in bundle.reactions:
            self._event_bridge.register_reaction(module_id, reaction)
            ledger.push(
                UndoEntry(
                    "proactive_reaction",
                    reaction.name,
                    lambda mid=module_id, n=reaction.name: self._undo_reaction(mid, n),
                )
            )

        for panel in bundle.ui_surfaces:
            panel_name = self._register_panel(module_id, panel)
            ledger.push(
                UndoEntry(
                    "ui_surface",
                    panel_name,
                    lambda mid=module_id, n=panel_name: self._undo_ui_surface(mid, n),
                )
            )

    def _register_panel(self, module_id: str, panel: Any) -> str:
        """Register a UI surface with the dashboard, returning its panel name.

        When no dashboard is wired (it is built later, task 12), registration is
        skipped with a warning; the paired undo is then a safe no-op, so the
        ledger stays symmetric with the bundle's items.
        """
        panel_name = _item_name(panel)
        if self._dashboard is None:
            logger.warning(
                "No dashboard wired; UI surface %s for module %s not registered",
                panel_name,
                module_id,
            )
            return panel_name
        self._dashboard.register_panel(module_id, panel)
        return panel_name

    # ── Paired undo helpers (call the A2 deregistration helpers) ────────

    def _undo_tool(self, tool: BaseTool) -> None:
        """Reverse a tool registration: drop it from the tool layer and kernel."""
        name = tool.get_name()
        self._tool_runtime.deregister_tool(name)
        self._kernel.deregister(name)

    def _undo_agent(self, agent: BaseAgent) -> None:
        """Reverse an agent registration: drop it from the swarm and kernel."""
        self._swarm.deregister_agent(agent.name)
        self._kernel.deregister(agent.name)

    def _undo_skill(self, module_id: str) -> None:
        """Reverse a skill contribution via the Module_Registry (idempotent)."""
        self._registry.remove_skill(module_id)

    def _undo_source(self, module_id: str, source_name: str) -> None:
        """Reverse an event-source registration via the Event_Bridge."""
        self._event_bridge.deregister_source(module_id, source_name)

    def _undo_detector(self, module_id: str, detector_name: str) -> None:
        """Reverse an anomaly-detector registration via the Event_Bridge."""
        self._event_bridge.deregister_detector(module_id, detector_name)

    def _undo_reaction(self, module_id: str, reaction_name: str) -> None:
        """Reverse a proactive-reaction registration via the Event_Bridge.

        The Event_Bridge also removes the persisted standing order.
        """
        self._event_bridge.deregister_reaction(module_id, reaction_name)

    def _undo_ui_surface(self, module_id: str, panel_name: str) -> None:
        """Reverse a UI-surface registration via the dashboard (no-op if absent)."""
        if self._dashboard is None:
            return
        self._dashboard.deregister_panel(module_id, panel_name)

    # ── Registration pipeline (Req 4.2, 4.5, 5.6, 6.1-6.5, 14.3, 14.4) ──

    async def register(self, record: ModuleRecord, operator: str) -> LifecycleResult:
        """Run the full registration pipeline for a module, atomically.

        The pipeline runs in order: validate the manifest, resolve declared
        dependencies, check required-secret presence, broker the module's
        permissions, build the :class:`CapabilityBundle`, and hot-load it into the
        running process inside an :func:`asyncio.timeout` bound by
        ``hot_load_timeout_s`` (Req 6.1, 6.2, 14.3).

        Each pre-hot-load gate short-circuits to its own terminal state when it
        fails, leaving the running system untouched: a manifest that fails
        validation is ``REJECTED`` (Req 3); an unmet required dependency or an
        absent required secret leaves the module ``BLOCKED`` (Req 4.2, 4.5); a
        permission requiring operator approval leaves it ``AWAITING_APPROVAL`` and
        disabled until the operator decides (Req 5.6).

        If building the bundle or hot-loading any item fails -- or the hot-load
        exceeds the 5-second bound -- the loader rolls back the registration
        ledger (reversing exactly the items already registered), sets the module
        ``DISABLED``, and returns a :class:`LifecycleResult` reporting the failed
        item or the timeout (Req 6.5, 14.4). On success the module is
        ``REGISTERED`` and then set ``ENABLED`` iff ``enabled_by_default``,
        otherwise ``DISABLED`` (Req 6.4).
        """
        module_id = record.module_id
        logger.info("Registering module %s (operator=%s)", module_id, operator)

        # 1. Validate the manifest against the running platform version (Req 3).
        validation = validate_manifest(record.manifest, _running_version())
        if not validation.ok:
            failed = self._first_invalid_field(validation)
            return self._fail_check(
                record,
                ModuleState.REJECTED,
                failed_item=failed,
                detail=validation.reason or "manifest validation failed",
                operator=operator,
            )

        # 2. Resolve dependencies; a required dep not satisfied blocks (Req 4.1, 4.2).
        resolved = await self._dependency_resolver.resolve(record.manifest.dependencies)
        record.resolved_dependencies = resolved
        unmet = DependencyResolver.unmet_required(resolved)
        if unmet:
            detail = "; ".join(f"{dep.name} ({dep.status})" for dep in unmet)
            return self._fail_check(
                record,
                ModuleState.BLOCKED,
                failed_item=unmet[0].name,
                detail=f"unmet required dependencies: {detail}",
                operator=operator,
            )

        # 3. Check required-secret presence; an absent required secret blocks (Req 4.4, 4.5).
        secret_check = self._secret_resolver.check_presence(
            record.manifest.required_secrets
        )
        record.secret_presence = {key: True for key in secret_check.present}
        record.secret_presence.update({key: False for key in secret_check.absent})
        if not secret_check.all_present:
            return self._fail_check(
                record,
                ModuleState.BLOCKED,
                failed_item=secret_check.absent[0],
                detail="absent required secrets: " + ", ".join(secret_check.absent),
                operator=operator,
            )

        # 4. Broker permissions; an elevated request awaits operator approval (Req 5.1, 5.2, 5.6).
        decision = self._broker.evaluate_module(record)
        record.granted_permissions = list(decision.granted)
        record.pending_permissions = list(decision.pending)
        if decision.needs_approval:
            record.state = ModuleState.AWAITING_APPROVAL
            detail = "awaiting operator approval for: " + ", ".join(decision.pending)
            self._log_transition(record, ok=False, detail=detail, operator=operator)
            return LifecycleResult(
                module_id,
                "register",
                ok=False,
                state=record.state,
                detail=detail,
            )

        # 5. Build the capability bundle from the module's provides entries.
        try:
            bundle = self._build_bundle(record)
        except Exception as exc:  # noqa: BLE001 - reported as a registration failure
            logger.exception("Failed to build capability bundle for %s", module_id)
            record.state = ModuleState.DISABLED
            detail = f"failed to build capability bundle: {exc}"
            self._log_transition(record, ok=False, detail=detail, operator=operator)
            return LifecycleResult(
                module_id,
                "register",
                ok=False,
                state=record.state,
                failed_item=getattr(exc, "item_id", None),
                detail=detail,
            )
        record.bundle = bundle

        # 6. Hot-load atomically within the 5s bound, rolling back on any failure (Req 6.2, 6.5, 14.3, 14.4).
        ledger = RegistrationLedger()
        try:
            async with asyncio.timeout(self._hot_load_timeout_s):
                await self._hot_load(record, bundle, ledger)
        except TimeoutError:
            await ledger.rollback()
            record.state = ModuleState.DISABLED
            detail = f"hot-load exceeded {self._hot_load_timeout_s:g}s"
            logger.warning("Hot-load for module %s timed out; rolled back", module_id)
            self._log_transition(
                record, ok=False, detail=detail, timed_out=True, operator=operator
            )
            return LifecycleResult(
                module_id,
                "register",
                ok=False,
                state=record.state,
                timed_out=True,
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - any failure triggers rollback
            reversed_ids = await ledger.rollback()
            record.state = ModuleState.DISABLED
            detail = f"hot-load failed: {exc}"
            logger.exception(
                "Hot-load failed for module %s; rolled back %d item(s)",
                module_id,
                len(reversed_ids),
            )
            self._log_transition(record, ok=False, detail=detail, operator=operator)
            return LifecycleResult(
                module_id,
                "register",
                ok=False,
                state=record.state,
                failed_item=getattr(exc, "item_id", None),
                detail=detail,
            )

        # 7. Success: enabled iff enabled_by_default, disabled otherwise (Req 6.4).
        self._ledgers[module_id] = ledger
        if record.manifest.enabled_by_default:
            record.state = ModuleState.ENABLED
            detail = "registered and enabled"
        else:
            record.state = ModuleState.DISABLED
            detail = "registered (disabled; not enabled_by_default)"
        self._log_transition(record, ok=True, detail=detail, operator=operator)
        return LifecycleResult(
            module_id,
            "register",
            ok=True,
            state=record.state,
            detail=detail,
        )

    # ── Hot-unload, enable, disable, re-register, uninstall (Req 10) ────

    async def _hot_unload(self, module_id: str) -> list[str]:
        """Reverse a module's hot-load by replaying its ledger in LIFO order.

        Looks up the module's retained :class:`RegistrationLedger` and runs
        :meth:`RegistrationLedger.rollback`, deregistering every item the module
        contributed -- tools/agents from the tool layer, ``SystemKernel``, and
        ``SwarmManager``; skills from the ``ModuleRegistry``; and event sources,
        detectors, and reactions from the ``Event_Bridge``/``StandingOrderStore``
        -- so the module produces no further tool invocations, events, or
        reactions (Req 10.7). The ledger is cleared afterwards (popped before
        replay), so a module with nothing registered hot-unloads as a no-op.

        Returns the item ids reversed, in the LIFO order they were reversed.
        """
        ledger = self._ledgers.pop(module_id, None)
        if ledger is None:
            logger.debug(
                "No registration ledger for module %s; hot-unload is a no-op", module_id
            )
            return []
        return await ledger.rollback()

    async def enable(self, module_id: str, operator: str) -> LifecycleResult:
        """Re-run all checks, hot-load the bundle, and set the module enabled.

        Enabling re-runs the full registration pipeline -- manifest validation,
        dependency resolution, required-secret presence, permission brokering,
        bundle build, and a 5-second-bounded hot-load -- so a module is only
        enabled when every check passes (Req 10.3). If any check fails the
        pipeline withholds the hot-load, rolls back anything partially registered,
        leaves the running system unchanged, and reports the failed check; the
        module stays disabled (Req 10.4). On success the state is forced to
        ``ENABLED`` regardless of ``enabled_by_default`` (the operator asked for
        it explicitly). Enabling an already-enabled module is a no-op.
        """
        record = self._registry.get(module_id)
        if record is None:
            return self._not_found(module_id, "enable", ModuleState.DISABLED)

        if record.state is ModuleState.ENABLED:
            detail = "already enabled; no state change"
            self._log_transition(
                record, ok=True, detail=detail, transition="enable", operator=operator
            )
            return LifecycleResult(
                module_id, "enable", ok=True, state=record.state, detail=detail
            )

        # Re-run the registration pipeline (checks + atomic, bounded hot-load).
        result = await self.register(record, operator)
        if not result.ok:
            self._log_transition(
                record,
                ok=False,
                detail=result.detail,
                transition="enable",
                operator=operator,
                timed_out=result.timed_out,
            )
            return LifecycleResult(
                module_id,
                "enable",
                ok=False,
                state=record.state,
                failed_item=result.failed_item,
                timed_out=result.timed_out,
                detail=result.detail,
            )

        record.state = ModuleState.ENABLED
        detail = "enabled"
        self._log_transition(
            record, ok=True, detail=detail, transition="enable", operator=operator
        )
        return LifecycleResult(
            module_id, "enable", ok=True, state=record.state, detail=detail
        )

    async def disable(self, module_id: str, operator: str) -> LifecycleResult:
        """Hot-unload the module's bundle and set it disabled, bounded at 5s.

        Disabling an enabled module hot-unloads its Capability Bundle from the
        running process and sets the state to ``DISABLED``, completing within the
        5-second bound (Req 10.1). Disabling a module that is already disabled is
        an idempotent no-op: the state stays disabled and the result reports that
        no state change occurred (Req 10.2).
        """
        record = self._registry.get(module_id)
        if record is None:
            return self._not_found(module_id, "disable", ModuleState.DISABLED)

        if record.state is not ModuleState.ENABLED:
            detail = "already disabled; no state change"
            self._log_transition(
                record, ok=True, detail=detail, transition="disable", operator=operator
            )
            return LifecycleResult(
                module_id, "disable", ok=True, state=record.state, detail=detail
            )

        try:
            async with asyncio.timeout(self._hot_load_timeout_s):
                await self._hot_unload(module_id)
        except TimeoutError:
            detail = f"disable exceeded {self._hot_load_timeout_s:g}s"
            self._log_transition(
                record,
                ok=False,
                detail=detail,
                transition="disable",
                operator=operator,
                timed_out=True,
            )
            return LifecycleResult(
                module_id,
                "disable",
                ok=False,
                state=record.state,
                timed_out=True,
                detail=detail,
            )

        record.state = ModuleState.DISABLED
        detail = "disabled"
        self._log_transition(
            record, ok=True, detail=detail, transition="disable", operator=operator
        )
        return LifecycleResult(
            module_id, "disable", ok=True, state=record.state, detail=detail
        )

    async def reregister(self, record: ModuleRecord, operator: str) -> LifecycleResult:
        """Register a new version of an already-registered module, atomically.

        When ``module_id`` is not currently registered this is a plain
        :meth:`register`. When a version is already registered, its existing
        registration is hot-unloaded **first** (Req 6.6) and the new version is
        then registered. If the new version fails to register, the previously
        hot-unloaded version is re-registered from its retained bundle and its
        prior state restored, leaving the system equivalent to before the attempt
        (Req 6.7).

        Re-register handling lives here rather than in :meth:`register`: a plain
        ``register`` assumes the module is not yet hot-loaded, so the
        already-registered case is handled by this thin wrapper that brackets a
        single ``register`` call with unload-first / restore-on-failure, keeping
        the core pipeline untouched.
        """
        module_id = record.module_id
        if module_id not in self._ledgers:
            return await self.register(record, operator)

        previous = self._registry.get(module_id)
        prev_state = previous.state if previous is not None else None
        prev_bundle = previous.bundle if previous is not None else None

        logger.info(
            "Re-registering module %s; hot-unloading existing version first", module_id
        )
        await self._hot_unload(module_id)  # Req 6.6

        result = await self.register(record, operator)
        if result.ok:
            return result

        # Req 6.7: the new version failed -- restore the previous version.
        restored = await self._restore_previous(previous, prev_bundle, prev_state)
        detail = result.detail + (
            "; restored previous version"
            if restored
            else "; no previous version to restore"
        )
        state = previous.state if (restored and previous is not None) else record.state
        return LifecycleResult(
            module_id,
            "register",
            ok=False,
            state=state,
            failed_item=result.failed_item,
            timed_out=result.timed_out,
            detail=detail,
        )

    async def _restore_previous(
        self,
        record: ModuleRecord | None,
        bundle: CapabilityBundle | None,
        prev_state: ModuleState | None,
    ) -> bool:
        """Re-register a previously hot-unloaded version after a failed re-register.

        Hot-loads the retained ``bundle`` into a fresh ledger and restores the
        module's prior state (Req 6.7). Best-effort: if the restore itself fails
        it is rolled back and reported, returning ``False`` so the caller can note
        that the previous version could not be restored.
        """
        if record is None or bundle is None:
            return False
        ledger = RegistrationLedger()
        try:
            await self._hot_load(record, bundle, ledger)
        except Exception:  # noqa: BLE001 - restore is best-effort
            await ledger.rollback()
            logger.exception(
                "Failed to restore previous version of module %s after a failed "
                "re-registration",
                record.module_id,
            )
            return False
        self._ledgers[record.module_id] = ledger
        if prev_state is not None:
            record.state = prev_state
        logger.info(
            "Restored previous version of module %s after a failed re-registration",
            record.module_id,
        )
        return True

    async def uninstall(self, module_id: str, operator: str) -> LifecycleResult:
        """Hot-unload, deregister, and delete a module's files (Req 10.5, 10.6).

        Uninstall hot-unloads the Capability Bundle if it is registered, removes
        the module from the ``Module_Registry`` and the ``SystemKernel``
        capability graph, and deletes the module's files from its module
        directory (Req 10.5). Deregistration always completes: if deleting the
        files fails, the module stays deregistered (state ``UNINSTALLED``), the
        file-removal failure is reported with the affected path, and the
        transition is reported as failed (Req 10.6).
        """
        record = self._registry.get(module_id)
        if record is None:
            return self._not_found(module_id, "uninstall", ModuleState.UNINSTALLED)

        # 1. Hot-unload the bundle (no-op when nothing is registered) (Req 10.5).
        await self._hot_unload(module_id)

        # 2. Remove from the registry and the capability graph (Req 10.5).
        self._registry.remove_skill(module_id)
        self._registry.remove_from_graph(module_id)

        # 3. Delete the module's files; deregistration completes regardless (Req 10.6).
        module_dir = self._module_dir(record)
        file_error: str | None = None
        try:
            if module_dir.exists():
                shutil.rmtree(module_dir)
        except OSError as exc:
            file_error = f"failed to delete module files at {module_dir}: {exc}"
            logger.error(
                "Uninstall of module %s left files in place at %s: %s",
                module_id,
                module_dir,
                exc,
            )

        record.state = ModuleState.UNINSTALLED
        ok = file_error is None
        detail = "uninstalled" if ok else file_error
        self._log_transition(
            record, ok=ok, detail=detail, transition="uninstall", operator=operator
        )
        return LifecycleResult(
            module_id,
            "uninstall",
            ok=ok,
            state=record.state,
            failed_item=str(module_dir) if file_error else None,
            detail=detail,
        )

    def _not_found(
        self, module_id: str, transition: str, state: ModuleState
    ) -> LifecycleResult:
        """Build a failing result for a lifecycle action on an unknown module.

        Emits an error-level structured log (Req 14.7); no audit event is
        recorded because there is no module record to attribute the action to.
        """
        detail = f"module {module_id!r} not found in registry"
        logger.error(
            "Cannot %s module %s: not found in registry", transition, module_id
        )
        return LifecycleResult(
            module_id, transition, ok=False, state=state, detail=detail
        )

    def _fail_check(
        self,
        record: ModuleRecord,
        state: ModuleState,
        *,
        failed_item: str | None,
        detail: str,
        operator: str | None = None,
    ) -> LifecycleResult:
        """Set a terminal pre-hot-load state and build the failing LifecycleResult.

        Used by the validation, dependency, and secret gates: no subsystem state
        was mutated, so there is nothing to roll back -- the running system is
        already in its pre-registration form (Req 4.2, 4.5).
        """
        record.state = state
        self._log_transition(record, ok=False, detail=detail, operator=operator)
        return LifecycleResult(
            record.module_id,
            "register",
            ok=False,
            state=state,
            failed_item=failed_item,
            detail=detail,
        )

    @staticmethod
    def _first_invalid_field(validation: Any) -> str:
        """Best-effort failed-item name for a validation failure."""
        if validation.missing_fields:
            return validation.missing_fields[0]
        if validation.invalid_fields:
            return validation.invalid_fields[0][0]
        return "manifest"

    def _log_transition(
        self,
        record: ModuleRecord,
        *,
        ok: bool,
        detail: str,
        transition: str = "register",
        operator: str | None = None,
        timed_out: bool = False,
    ) -> None:
        """Emit exactly one structured log + audit per lifecycle transition.

        Every transition (register/install, enable, disable, uninstall) emits a
        single structured log entry via ``logging.getLogger(__name__)`` carrying
        the ``module_id``, transition type, and outcome (Req 14.5); a failed
        transition logs at error level with the failure reason (Req 14.7).
        Install/enable/disable/uninstall additionally record an ``AuditEvent``
        through :class:`ActionLogger`, identifying the module, the action, the
        operator who initiated it, and the success flag (Req 13.1). Only secret
        *key names* are ever referenced -- no secret value reaches a log or audit
        entry (Req 13.2, 14.6).

        Auditing is best-effort: a failure recording the event must never abort
        the lifecycle transition or its rollback.
        """
        logger.log(
            logging.INFO if ok else logging.ERROR,
            "Module %s %s -> %s (ok=%s%s): %s",
            record.module_id,
            transition,
            record.state.value,
            ok,
            ", timed_out" if timed_out else "",
            detail,
        )
        try:
            self._audit.record(
                AuditEvent(
                    kind="module_lifecycle",
                    # ``actor`` is a required positional on
                    # :class:`AuditEvent`; the operator is the
                    # only identity the loader knows about for
                    # this transition (the system has no user
                    # context at module-lifecycle time).
                    actor=operator or "system",
                    action=transition,
                    success=ok,
                    detail=f"Module {record.module_id} -> {record.state.value}: {detail}",
                    metadata={
                        "module_id": record.module_id,
                        "state": record.state.value,
                        "operator": operator,
                        "timed_out": timed_out,
                    },
                )
            )
        except Exception:  # pragma: no cover - auditing must never break the pipeline
            logger.debug(
                "Failed to audit %s transition for %s",
                transition,
                record.module_id,
                exc_info=True,
            )

    # ── Capability-bundle construction (Req 6.1) ───────────────────────

    def _build_bundle(self, record: ModuleRecord) -> CapabilityBundle:
        """Build a :class:`CapabilityBundle` from a module's ``provides`` entries.

        Each non-skill entry's ``entrypoint`` (``"file.py:Symbol"`` relative to the
        module directory) is loaded and instantiated into its matching bundle slot;
        skills carry no entrypoint and contribute their name (the module itself is
        surfaced through the Module_Registry). A failure loading any entry raises
        :class:`BundleBuildError`, aborting registration before any subsystem is
        touched.
        """
        bundle = CapabilityBundle(module_id=record.module_id)
        module_dir = self._module_dir(record)
        for entry in record.manifest.provides:
            self._add_entry(bundle, record, entry, module_dir)
        return bundle

    def _add_entry(
        self,
        bundle: CapabilityBundle,
        record: ModuleRecord,
        entry: ProvidesEntry,
        module_dir: Path,
    ) -> None:
        """Load one provides entry and append it to the matching bundle slot."""
        if entry.type is ProvidesType.SKILL:
            bundle.skills.append(entry.name or record.module_id)
            return

        instance = self._load_entrypoint(record.module_id, entry, module_dir)
        if entry.type is ProvidesType.TOOL:
            bundle.tools.append(instance)
        elif entry.type is ProvidesType.AGENT:
            bundle.agents.append(instance)
        elif entry.type is ProvidesType.EVENT_SOURCE:
            bundle.event_sources.append(instance)
        elif entry.type is ProvidesType.ANOMALY_DETECTOR:
            bundle.detectors.append(instance)
        elif entry.type is ProvidesType.PROACTIVE_REACTION:
            bundle.reactions.append(instance)
        elif entry.type is ProvidesType.UI_SURFACE:
            bundle.ui_surfaces.append(instance)

    def _module_dir(self, record: ModuleRecord) -> Path:
        """Resolve the directory a module's contributed code is loaded from.

        The manifest path is resolved against the registry's project root when it
        is relative, mirroring how the Module_Registry reads the on-disk manifest.
        """
        manifest_path = Path(record.manifest.manifest_path)
        if not manifest_path.is_absolute():
            root = getattr(
                getattr(self._registry, "_skill_registry", None), "project_root", None
            )
            if root is not None:
                manifest_path = Path(root) / manifest_path
        return manifest_path.parent

    def _load_entrypoint(
        self, module_id: str, entry: ProvidesEntry, module_dir: Path
    ) -> Any:
        """Load and instantiate a ``"file.py:Symbol"`` entrypoint for a provides entry.

        The symbol is imported from the module directory and instantiated with no
        arguments (the provides-type protocols are no-arg constructors); a plain
        non-callable symbol is used as-is. Any problem -- a missing/malformed
        entrypoint, a missing file or symbol, or an error while importing or
        instantiating -- raises :class:`BundleBuildError` tagged with the entry's
        item id so the failure can be reported (Req 6.5).
        """
        item_id = f"{entry.type.value}:{entry.name}"
        if not entry.entrypoint or ":" not in entry.entrypoint:
            raise BundleBuildError(
                item_id,
                f"provides entry {entry.name!r} ({entry.type.value}) declares no "
                "valid entrypoint",
            )
        file_part, symbol_name = entry.entrypoint.split(":", 1)
        module_path = (module_dir / file_part).resolve()
        if not module_path.is_file():
            raise BundleBuildError(item_id, f"entrypoint file not found: {module_path}")

        try:
            py_module = self._import_module_file(module_id, module_path)
        except Exception as exc:  # noqa: BLE001 - surfaced as a build failure
            raise BundleBuildError(
                item_id, f"failed to import {module_path.name}: {exc}"
            ) from exc

        symbol = getattr(py_module, symbol_name, None)
        if symbol is None:
            raise BundleBuildError(
                item_id,
                f"entrypoint symbol {symbol_name!r} not found in {module_path.name}",
            )

        try:
            return symbol() if (inspect.isclass(symbol) or callable(symbol)) else symbol
        except Exception as exc:  # noqa: BLE001 - surfaced as a build failure
            raise BundleBuildError(
                item_id, f"failed to instantiate {symbol_name!r}: {exc}"
            ) from exc

    @staticmethod
    def _import_module_file(module_id: str, module_path: Path) -> Any:
        """Import a module file by path under a unique, collision-safe module name."""
        safe_id = re.sub(r"\W+", "_", module_id)
        mod_name = f"ravyn_module_{safe_id}_{module_path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, str(module_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot create import spec for {module_path}")
        py_module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = py_module
        spec.loader.exec_module(py_module)
        return py_module


def _item_name(item: Any) -> str:
    """Best-effort stable name for a bundle contribution.

    Mirrors the naming used by :meth:`CapabilityBundle.item_ids` so a UI surface
    is reversed under the same identifier it was registered with.
    """
    name = getattr(item, "name", None)
    if isinstance(name, str) and name:
        return name
    get_name = getattr(item, "get_name", None)
    if callable(get_name):
        try:
            value = get_name()
        except Exception:  # pragma: no cover - defensive, never reaches core
            logger.debug("get_name() failed for bundle item %r", item, exc_info=True)
        else:
            if isinstance(value, str) and value:
                return value
    return repr(item)
