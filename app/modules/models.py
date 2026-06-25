"""Core data models for the Modular Extension Platform.

Defines the enums, dataclasses, and provides-type protocols shared across the
platform components (registry, loader, permission broker, health monitor, and
event bridge). Dataclasses use ``slots=True`` to match the style of the existing
``PolicyDecision`` and ``SandboxResult`` models. Absent optional manifest fields
default to empty lists and ``enabled_by_default`` defaults to ``False``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.core.output_router import Priority

if TYPE_CHECKING:
    # Defined in app.modules.manifest (created by task 2.1), which imports the
    # dependency/provides models from this module; referenced here only as a
    # forward annotation to avoid a runtime import cycle.
    from app.modules.manifest import (  # pyright: ignore[reportMissingImports]
        ModuleManifest,
    )

logger = logging.getLogger(__name__)

# A proactive reaction's defined response (e.g. {"invoke_tools": [...], "notify": True}).
ReactionResponse = dict[str, Any]
# A rendered dashboard UI surface payload.
PanelHtml = str


class ModuleState(str, Enum):
    """Lifecycle state of a module.

    ``DISCOVERED``, ``VALIDATED``, ``RESOLVED``, ``PERMITTED``, and ``REGISTERED``
    are transient pipeline phases; the remaining states are persisted in
    ``ModuleRecord.state``.
    """

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    RESOLVED = "resolved"
    AWAITING_APPROVAL = "awaiting_approval"
    PERMITTED = "permitted"
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    AUTO_DISABLED = "auto_disabled"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    UNINSTALLED = "uninstalled"


class ProvidesType(str, Enum):
    """The contribution type of a single capability-bundle entry."""

    TOOL = "tool"
    AGENT = "agent"
    SKILL = "skill"
    EVENT_SOURCE = "event_source"
    ANOMALY_DETECTOR = "anomaly_detector"
    PROACTIVE_REACTION = "proactive_reaction"
    UI_SURFACE = "ui_surface"


@dataclass(slots=True)
class DependencySpec:
    """A declared module dependency to be resolved before registration."""

    name: str
    status: str = "required"  # required | recommended | optional
    check: str | None = None  # shell command run by DependencyResolver (A4)
    required: bool = True


@dataclass(slots=True)
class ResolvedDependency:
    """The result of resolving a single declared dependency."""

    name: str
    required: bool
    status: str  # satisfied | unsatisfied | unknown
    message: str = ""


@dataclass(slots=True)
class Compatibility:
    """Compatibility constraints a module declares against the platform."""

    min_ravyn_version: str = "0.0.0"
    schema_version: str = "1.0"


@dataclass(slots=True)
class ProvidesEntry:
    """A single entry in a module's ``provides`` section."""

    type: ProvidesType
    name: str
    entrypoint: str | None = None  # "file.py:Symbol"
    listens_to: str | None = None  # anomaly_detector -> event_source name
    priority: str | None = None  # detector/reaction declared priority
    condition: str | None = None  # proactive_reaction
    response: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    """Structured outcome of validating a module manifest (no side effects)."""

    ok: bool
    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[tuple[str, str]] = field(
        default_factory=list
    )  # (field, value)
    reason: str = ""


@dataclass(slots=True)
class CapabilityBundle:
    """Resolved, instantiated contributions ready to register."""

    module_id: str
    tools: list[Any] = field(default_factory=list)  # BaseTool instances
    agents: list[Any] = field(default_factory=list)  # BaseAgent instances
    skills: list[str] = field(default_factory=list)  # skill names
    event_sources: list[Any] = field(default_factory=list)
    detectors: list[Any] = field(default_factory=list)
    reactions: list[Any] = field(default_factory=list)
    ui_surfaces: list[Any] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when the bundle contributes nothing."""
        return not (
            self.tools
            or self.agents
            or self.skills
            or self.event_sources
            or self.detectors
            or self.reactions
            or self.ui_surfaces
        )

    def item_ids(self) -> list[str]:
        """Stable identifiers for every contribution.

        Used by the registration ledger and the property tests to assert that
        hot-unload exactly reverses hot-load.
        """
        ids: list[str] = []
        ids.extend(f"tool:{_item_name(tool)}" for tool in self.tools)
        ids.extend(f"agent:{_item_name(agent)}" for agent in self.agents)
        ids.extend(f"skill:{skill}" for skill in self.skills)
        ids.extend(f"event_source:{_item_name(src)}" for src in self.event_sources)
        ids.extend(f"anomaly_detector:{_item_name(det)}" for det in self.detectors)
        ids.extend(f"proactive_reaction:{_item_name(rxn)}" for rxn in self.reactions)
        ids.extend(f"ui_surface:{_item_name(panel)}" for panel in self.ui_surfaces)
        return ids


def _item_name(item: Any) -> str:
    """Best-effort stable name for a bundle contribution."""
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


@dataclass(slots=True)
class PermissionRequest:
    """A single permission a module requests at its trust level."""

    module_id: str
    permission: str
    trust_level: str
    granted: bool = False
    pending: bool = False  # awaiting operator approval (Req 5.2/5.6)
    decided_by: str | None = None  # operator id once approved/denied


@dataclass(slots=True)
class BrokerDecision:
    """The Permission_Broker's verdict for a module's requested permissions."""

    granted: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)  # require operator approval
    denied: list[str] = field(default_factory=list)

    @property
    def needs_approval(self) -> bool:
        """True when one or more permissions await operator approval."""
        return bool(self.pending)


@dataclass(slots=True)
class HealthStatus:
    """The latest health-check result recorded for a module."""

    module_id: str
    state: str  # healthy | degraded | unhealthy | unknown
    checks: list[dict[str, Any]] = field(default_factory=list)
    consecutive_failures: int = 0
    summary: str = ""
    has_run: bool = False  # False => "no health-check result available" (Req 12.3)


@dataclass(slots=True)
class ModuleEvent:
    """An event emitted by a module event source into the ambient pipeline."""

    module_id: str
    source_name: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass(slots=True)
class RaisedEvent:
    """An event raised by an anomaly detector for prioritized delivery."""

    detector_name: str
    message: str
    priority: str  # declared priority (validated by Event_Bridge)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UndoEntry:
    """A single reversible step recorded in the registration ledger."""

    subsystem: str  # "tool" | "agent" | "skill" | "source" | ...
    item_id: str
    undo: Callable[[], Awaitable[None]] | Callable[[], None]


@dataclass(slots=True)
class LifecycleResult:
    """The outcome of a module lifecycle transition."""

    module_id: str
    transition: str  # discovery|validation|register|enable|disable|uninstall
    ok: bool
    state: ModuleState
    detail: str = ""
    failed_item: str | None = None
    timed_out: bool = False


@dataclass(slots=True)
class ScaffoldResult:
    """The outcome of a ``ravyn modules scaffold`` invocation (Req 11.1-11.3).

    ``ok`` is ``True`` only when the module directory and all of its files were
    created atomically. ``created_paths`` lists every path written on success and
    is empty on failure (a rejected or colliding name leaves the filesystem
    unchanged). ``detail`` is a human-readable summary of the outcome or the
    reason the request was rejected.
    """

    ok: bool
    created_paths: list[str] = field(default_factory=list)
    detail: str = ""
    module_id: str = ""


@dataclass(slots=True)
class SecretCheck:
    """Presence-only result of checking a module's required secrets.

    Never holds secret values; only key names are recorded.
    """

    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)

    @property
    def all_present(self) -> bool:
        """True when no required secret key is absent."""
        return not self.absent


# ``ModuleManifest`` is defined in ``app.modules.manifest`` (which imports the
# dependency/provides models from this module), so it is referenced via a
# forward annotation to avoid a runtime import cycle.
@dataclass(slots=True)
class ModuleRecord:
    """The platform's authoritative typed record for a discovered module."""

    manifest: ModuleManifest
    state: ModuleState = ModuleState.DISCOVERED
    trust_level: str = "workspace"
    sandbox_backend: str = "subprocess"
    granted_permissions: list[str] = field(default_factory=list)
    pending_permissions: list[str] = field(default_factory=list)
    resolved_dependencies: list[ResolvedDependency] = field(default_factory=list)
    secret_presence: dict[str, bool] = field(default_factory=dict)
    health: HealthStatus | None = None
    bundle: CapabilityBundle | None = None

    @property
    def module_id(self) -> str:
        """The module's stable identifier from its manifest."""
        return self.manifest.module_id

    @property
    def is_active(self) -> bool:
        """True only while the module is enabled."""
        return self.state is ModuleState.ENABLED


@runtime_checkable
class EventSource(Protocol):
    """A module-provided sensor or input adapter that emits events."""

    name: str

    async def start(self, emit: Callable[[ModuleEvent], Awaitable[None]]) -> None:
        """Begin producing events, delivering each through ``emit``."""
        ...

    async def stop(self) -> None:
        """Stop producing events and release any resources."""
        ...


@runtime_checkable
class AnomalyDetector(Protocol):
    """A module-provided detector that raises prioritized events."""

    name: str
    listens_to: str
    default_priority: Priority

    async def inspect(self, event: ModuleEvent) -> RaisedEvent | None:
        """Inspect an event and optionally raise a prioritized event."""
        ...


@runtime_checkable
class ProactiveReaction(Protocol):
    """A module-provided standing reaction that acts back through the module."""

    name: str
    condition: str

    async def respond(self, event: ModuleEvent) -> ReactionResponse:
        """Produce the response to perform when ``condition`` matches an event."""
        ...
