"""Dashboard panel registry and timeout-guarded rendering.

The :class:`Dashboard` is the platform's UI-surface registry. Modules that
declare a ``ui_surface`` in their ``provides`` section contribute a panel object
implementing ``async def render_panel() -> PanelHtml``; the loader registers it
per ``module_id`` on hot-load and deregisters it on hot-unload (task 9.2). This
component owns the registry and the render path that turns the currently enabled
modules' panels into rendered HTML.

Rendering is fault-isolated (Req 15.1, 15.2): every panel is rendered inside its
own :func:`asyncio.timeout` bound, so a panel that raises or exceeds the bound is
omitted from the output and recorded as a :class:`PanelFailure` (a failure
indicator the dashboard surface can display) while every other panel still
renders. One failing or slow panel can never block the rest.

Modules that declare no UI surface simply contribute no panel; the registry
cleanly supports modules with zero panels, so the rest of their capability
bundle registers normally (Req 15.3). Deregistration is idempotent so a
hot-unload rollback that removes an absent panel is a safe no-op (Req 15.4).

The FastAPI/WebSocket wiring that exposes this render output (reusing
``app/api/ui.py`` and the ``broadcast_event`` hook in ``app/web/server.py``) is
task 12.2 and lives outside this module.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.modules.models import PanelHtml

if TYPE_CHECKING:
    from app.modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)

# Default per-panel render bound (Req 15.2); mirrors the loader's hot-load bound.
_DEFAULT_RENDER_TIMEOUT_S = 5.0


@runtime_checkable
class UISurface(Protocol):
    """A module-provided dashboard panel.

    Mirrors the contribution protocols in :mod:`app.modules.models`: a panel is
    identified by ``name`` and rendered asynchronously into a :data:`PanelHtml`
    payload.
    """

    name: str

    async def render_panel(self) -> PanelHtml:
        """Render this panel's current HTML payload."""
        ...


@dataclass(slots=True)
class RenderedPanel:
    """A panel that rendered successfully within the render bound."""

    module_id: str
    panel_name: str
    html: PanelHtml


@dataclass(slots=True)
class PanelFailure:
    """A panel that was omitted because it errored or exceeded the render bound.

    ``reason`` is ``"timeout"`` when the panel exceeded the render bound and
    ``"error"`` when ``render_panel`` raised; ``detail`` carries a short
    human-readable explanation for the dashboard's failure indicator (Req 15.2).
    """

    module_id: str
    panel_name: str
    reason: str  # "timeout" | "error"
    detail: str = ""


@dataclass(slots=True)
class DashboardRender:
    """The outcome of rendering every enabled module's panel.

    ``panels`` holds the panels that rendered successfully (in deterministic
    ``module_id`` then ``panel_name`` order); ``failures`` flags the panels that
    were omitted so the dashboard can show a failure indicator for each (Req
    15.2).
    """

    panels: list[RenderedPanel] = field(default_factory=list)
    failures: list[PanelFailure] = field(default_factory=list)


def _panel_name(panel: Any) -> str:
    """Best-effort stable name for a panel.

    Mirrors the loader's ``_item_name`` so a panel is registered, rendered, and
    deregistered under the same identifier the loader passes to
    :meth:`Dashboard.deregister_panel`.
    """
    name = getattr(panel, "name", None)
    if isinstance(name, str) and name:
        return name
    get_name = getattr(panel, "get_name", None)
    if callable(get_name):
        try:
            value = get_name()
        except Exception:  # pragma: no cover - defensive, never reaches core
            logger.debug("get_name() failed for panel %r", panel, exc_info=True)
        else:
            if isinstance(value, str) and value:
                return value
    return repr(panel)


class Dashboard:
    """Per-module UI-surface registry with timeout-guarded panel rendering.

    The loader calls :meth:`register_panel` on hot-load and
    :meth:`deregister_panel` on hot-unload (matching those call signatures).
    :meth:`render` renders the panels of the currently enabled modules, isolating
    every panel inside its own :func:`asyncio.timeout` bound so a failed or slow
    panel is omitted and flagged while the rest render (Req 15.1, 15.2).

    The ``registry`` dependency is optional. When supplied, only panels whose
    owning module is currently enabled are rendered (Req 15.1); when absent,
    every registered panel is rendered (panels are only present while their
    module is hot-loaded, so the two agree in normal operation).
    """

    def __init__(
        self,
        registry: ModuleRegistry | None = None,
        render_timeout_s: float = _DEFAULT_RENDER_TIMEOUT_S,
    ) -> None:
        self._registry = registry
        self._render_timeout_s = render_timeout_s
        # module_id -> {panel_name: panel}. A module with no UI surface simply
        # never appears here (Req 15.3).
        self._panels: dict[str, dict[str, UISurface]] = {}

    # ── Registry management (Req 15.3, 15.4) ───────────────────────────

    def register_panel(self, module_id: str, panel: Any) -> str:
        """Register ``panel`` for ``module_id`` and return its panel name.

        Idempotent per ``(module_id, panel_name)``: re-registering replaces the
        existing panel rather than duplicating it.
        """
        panel_name = _panel_name(panel)
        self._panels.setdefault(module_id, {})[panel_name] = panel
        logger.debug("Registered panel %s for module %s", panel_name, module_id)
        return panel_name

    def deregister_panel(self, module_id: str, panel_name: str) -> None:
        """Remove a module's panel from the registry; idempotent (Req 15.4).

        Removing a panel that is not registered -- or a module with no panels --
        is a no-op, so a hot-unload rollback that reverses an unregistered panel
        is safe.
        """
        panels = self._panels.get(module_id)
        if not panels or panel_name not in panels:
            return
        del panels[panel_name]
        if not panels:
            del self._panels[module_id]
        logger.debug("Deregistered panel %s for module %s", panel_name, module_id)

    def panel_names(self, module_id: str) -> list[str]:
        """Return the registered panel names for ``module_id`` (sorted)."""
        return sorted(self._panels.get(module_id, {}))

    # ── Rendering (Req 15.1, 15.2) ─────────────────────────────────────

    async def render(self) -> DashboardRender:
        """Render every enabled module's panel, omitting and flagging failures.

        Each panel is rendered concurrently inside its own
        :func:`asyncio.timeout` bound: a panel that raises or exceeds the bound is
        omitted from ``panels`` and recorded in ``failures`` (Req 15.2), while
        every other panel still renders -- one failing or slow panel never blocks
        the rest (Req 15.1). Panels are returned in deterministic ``module_id``
        then ``panel_name`` order.
        """
        targets = self._enabled_panels()
        if not targets:
            return DashboardRender()

        results = await asyncio.gather(
            *(self._render_one(mid, name, panel) for mid, name, panel in targets)
        )
        rendered = DashboardRender()
        for result in results:
            if isinstance(result, RenderedPanel):
                rendered.panels.append(result)
            else:
                rendered.failures.append(result)
        return rendered

    async def _render_one(
        self, module_id: str, panel_name: str, panel: UISurface
    ) -> RenderedPanel | PanelFailure:
        """Render one panel within the bound, converting any fault to a failure."""
        try:
            async with asyncio.timeout(self._render_timeout_s):
                html = await panel.render_panel()
        except TimeoutError:
            logger.warning(
                "Panel %s for module %s exceeded %gs render bound; omitting",
                panel_name,
                module_id,
                self._render_timeout_s,
            )
            return PanelFailure(
                module_id,
                panel_name,
                "timeout",
                f"render exceeded {self._render_timeout_s:g}s",
            )
        except Exception as exc:  # noqa: BLE001 - isolate the panel; render the rest
            logger.exception(
                "Panel %s for module %s failed to render; omitting",
                panel_name,
                module_id,
            )
            return PanelFailure(module_id, panel_name, "error", str(exc))

        if not isinstance(html, str):
            logger.warning(
                "Panel %s for module %s returned non-HTML payload %r; omitting",
                panel_name,
                module_id,
                type(html).__name__,
            )
            return PanelFailure(
                module_id, panel_name, "error", "render_panel did not return panel HTML"
            )
        return RenderedPanel(module_id, panel_name, html)

    def _enabled_panels(self) -> list[tuple[str, str, UISurface]]:
        """Collect ``(module_id, panel_name, panel)`` for every enabled panel.

        Ordered by ``module_id`` then ``panel_name`` so render output is stable.
        """
        targets: list[tuple[str, str, UISurface]] = []
        for module_id in sorted(self._panels):
            if not self._is_enabled(module_id):
                continue
            module_panels = self._panels[module_id]
            for panel_name in sorted(module_panels):
                targets.append((module_id, panel_name, module_panels[panel_name]))
        return targets

    def _is_enabled(self, module_id: str) -> bool:
        """Return whether ``module_id`` should have its panel rendered (Req 15.1).

        With no registry wired, every registered panel renders; otherwise only
        panels whose owning module record is currently enabled render.
        """
        if self._registry is None:
            return True
        record = self._registry.get(module_id)
        return record is not None and record.is_active
