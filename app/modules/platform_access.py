"""Process-wide accessor for the wired Module_Platform components.

The dashboard and API surfaces (``app/api/ui.py`` and ``app/web/server.py``,
task 12.2) need read access to the :class:`~app.modules.registry.ModuleRegistry`
and lifecycle access to the :class:`~app.modules.loader.ModuleLoader`, but those
components are constructed and wired together at bootstrap (task 13.1). This
module provides a tiny indirection so the network surfaces can be defined now
without a hard dependency on the bootstrap wiring: bootstrap calls
:func:`set_module_platform` once the platform is assembled, and the surfaces read
it through :func:`get_module_platform`, degrading gracefully (an "unavailable"
response) while it is unset.

It also owns the *presentation* helpers shared by both surfaces so neither
duplicates the module-list shape or the enable/disable lifecycle call: the
controls reuse :meth:`ModuleLoader.enable`/:meth:`ModuleLoader.disable` directly
(no lifecycle logic is reimplemented here) and, because the loader leaves a
module's state unchanged on failure, a failed action naturally retains the prior
enabled/disabled state and surfaces the loader's failure detail to the operator
(Req 12.5, 12.6, 12.7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.modules.models import ModuleState

if TYPE_CHECKING:
    from app.modules.dashboard import Dashboard
    from app.modules.loader import ModuleLoader
    from app.modules.models import ModuleRecord
    from app.modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)

# The operator identity recorded for lifecycle actions initiated from the
# dashboard / web API, mirroring the CLI's operator argument convention.
_DASHBOARD_OPERATOR = "dashboard"


@dataclass(slots=True)
class ModulePlatform:
    """The wired Module_Platform components the UI/API surfaces consume.

    Holds the authoritative typed :class:`ModuleRegistry`, the lifecycle
    :class:`ModuleLoader`, and the UI-surface :class:`Dashboard`. Assembled and
    registered by the bootstrap wiring (task 13.1).
    """

    registry: ModuleRegistry
    loader: ModuleLoader
    dashboard: Dashboard


_platform: ModulePlatform | None = None


def set_module_platform(platform: ModulePlatform | None) -> None:
    """Register (or clear) the process-wide Module_Platform handle.

    Called once by the bootstrap wiring (task 13.1) after the registry, loader,
    and dashboard are assembled. Passing ``None`` clears it (used by tests).
    """
    global _platform
    _platform = platform


def get_module_platform() -> ModulePlatform | None:
    """Return the wired Module_Platform, or ``None`` if bootstrap has not run."""
    return _platform


def module_view_entry(record: ModuleRecord) -> dict[str, Any]:
    """Shape one module record for the management view (Req 12.5).

    Surfaces the module's ``module_id``, ``display_name``, ``version``,
    ``trust_level``, its lifecycle ``state``, and a convenience ``enabled`` flag
    so the surface can render an enabled/disabled control without re-deriving it.
    """
    manifest = record.manifest
    return {
        "module_id": record.module_id,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "trust_level": record.trust_level,
        "state": record.state.value,
        "enabled": record.state is ModuleState.ENABLED,
    }


def module_list_payload(platform: ModulePlatform | None) -> dict[str, Any]:
    """Build the module-list response body for the management view (Req 12.5).

    Returns every discovered module (ordered by ``module_id`` via the registry)
    with its enabled/disabled state. When the platform has not been wired yet the
    payload reports ``available=False`` with an empty list so the surface renders
    cleanly instead of erroring.
    """
    if platform is None:
        return {"available": False, "modules": [], "count": 0}
    modules = [module_view_entry(record) for record in platform.registry.all()]
    return {"available": True, "modules": modules, "count": len(modules)}


async def apply_module_state(
    platform: ModulePlatform | None,
    module_id: str,
    *,
    enabled: bool,
    operator: str = _DASHBOARD_OPERATOR,
) -> dict[str, Any]:
    """Enable or disable a module by reusing the loader, reporting the outcome.

    Delegates straight to :meth:`ModuleLoader.enable` or
    :meth:`ModuleLoader.disable` (Req 12.6) — no lifecycle logic is duplicated
    here. The loader runs all checks and, on any failure, leaves the module's
    state unchanged and rolls back partial registration; this helper captures the
    prior state, reflects the (unchanged-on-failure) current state, and surfaces
    the loader's failure ``detail`` to the operator (Req 12.7).

    Returns a JSON-serialisable result dict: ``success`` (whether the action
    applied), ``prior_state``, the refreshed ``module`` view entry, an ``error``
    message when it failed, and ``timed_out`` for a hot-load/unload timeout.
    """
    if platform is None:
        return {
            "success": False,
            "module_id": module_id,
            "available": False,
            "error": "Module platform is not available yet.",
            "module": None,
        }

    record = platform.registry.get(module_id)
    if record is None:
        logger.debug("Module action requested for unknown module %r", module_id)
        return {
            "success": False,
            "module_id": module_id,
            "available": True,
            "error": f"Module not found: {module_id!r}.",
            "module": None,
        }

    prior_state = record.state.value
    action = "enable" if enabled else "disable"
    if enabled:
        result = await platform.loader.enable(module_id, operator)
    else:
        result = await platform.loader.disable(module_id, operator)

    # The loader leaves the record's state unchanged on failure, so re-reading it
    # here yields the retained prior state for a failed action (Req 12.7).
    current = platform.registry.get(module_id)
    entry = module_view_entry(current) if current is not None else None
    error = None if result.ok else (result.detail or f"{action} failed")
    if not result.ok:
        logger.warning("Dashboard %s of module %s failed: %s", action, module_id, error)
    return {
        "success": result.ok,
        "module_id": module_id,
        "available": True,
        "action": action,
        "prior_state": prior_state,
        "state": current.state.value if current is not None else prior_state,
        "module": entry,
        "timed_out": result.timed_out,
        "error": error,
    }
