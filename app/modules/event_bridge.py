"""Event_Bridge — route module event sources, detectors, and reactions.

The :class:`EventBridge` generalizes the existing ``SentinelBridge`` so a module
can contribute event sources, anomaly detectors, and proactive reactions and have
them participate in the ambient pipeline. This module implements the
*registration* surface (task 8.1):

* ``register_source`` / ``deregister_source`` — start/stop a module event source,
  wrapping its execution in :meth:`HealthMonitor.guard` so a faulty source is
  isolated and never reaches the core process; a failure in one source leaves the
  others operational (Req 7.1, 7.2, 10.7).
* ``register_detector`` / ``deregister_detector`` — subscribe a detector to the
  event source it declares via ``listens_to`` (Req 7.3, 10.7).
* ``register_reaction`` / ``deregister_reaction`` — persist a reaction's condition
  and defined response into the :class:`StandingOrderStore` (Req 8.1, 10.7).

The event fan-out (``on_event``) and the detector/reaction priority mapping
(``normalize_priority``) live alongside the registration surface in this class
(task 8.2); the in-memory registries below are the source of truth those methods
consume, so the source's ``emit`` callback is wired through :meth:`_emit`, which
dispatches to ``on_event``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from app.core.output_router import Priority
from app.runtime.event_outbox import (
    CHANNEL_OUTPUT_ROUTER,
    CHANNEL_SENTINEL_BRIDGE,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.core.output_router import OutputRouter
    from app.core.sentinel_bridge import SentinelBridge
    from app.core.standing_orders import StandingOrderStore
    from app.modules.health import HealthMonitor
    from app.modules.models import (
        AnomalyDetector,
        EventSource,
        ModuleEvent,
        ProactiveReaction,
        RaisedEvent,
        ReactionResponse,
    )

    # Broker-gated tool executor injected by the Module_Platform (the loader).
    # Given a module id, a tool reference named by a reaction's response, and the
    # full response, it evaluates the owning module's Permission_Broker decision
    # and executes the tool only on an allow verdict (Req 8.3). Event_Bridge owns
    # neither the broker nor the tool registry, so this seam keeps the fan-out
    # surface decoupled from permission evaluation (mirrors the on_event seam).
    ToolGate = Callable[[str, Any, ReactionResponse], Awaitable[None]]

logger = logging.getLogger(__name__)

# ── A5: SentinelBridge severity ↔ OutputRouter Priority mapping ─────────
# SentinelBridge grades events on a LOW/MEDIUM/HIGH/CRITICAL severity scale
# (``app.core.sentinel_bridge.SEVERITY_LEVELS``) whereas OutputRouter routes on
# its ``Priority`` IntEnum (CRITICAL/HIGH/NORMAL/LOW/DIGEST). Event_Bridge owns
# the translation between the two scales so module-emitted events can be both
# logged to the Sentinel history and routed by priority (assumption A5).
_SEVERITY_TO_PRIORITY: dict[str, Priority] = {
    "CRITICAL": Priority.CRITICAL,
    "HIGH": Priority.HIGH,
    "MEDIUM": Priority.NORMAL,
    "LOW": Priority.LOW,
}
_PRIORITY_TO_SEVERITY: dict[Priority, str] = {
    Priority.CRITICAL: "CRITICAL",
    Priority.HIGH: "HIGH",
    Priority.NORMAL: "MEDIUM",
    Priority.LOW: "LOW",
    Priority.DIGEST: "LOW",
}


class EventBridge:
    """Routes module event sources, detectors, and reactions into the pipeline.

    Registration is per-module so that hot-unload can remove exactly the items a
    module contributed (Req 10.7). Each source runs under
    :meth:`HealthMonitor.guard`, isolating a faulty source from the core process
    and from the other registered sources (Req 7.1, 7.2).
    """

    def __init__(
        self,
        sentinel: SentinelBridge,
        router: OutputRouter,
        standing_orders: StandingOrderStore,
        health: HealthMonitor,
        *,
        durable: bool = True,
        event_outbox: Any | None = None,
    ) -> None:
        self._sentinel = sentinel
        self._router = router
        self._standing_orders = standing_orders
        self._health = health
        # ``durable=True`` (the default) routes external-sink
        # delivery (OutputRouter + SentinelBridge) through the
        # durable :class:`app.runtime.event_outbox.EventOutbox`
        # so an event survives a process restart.  Set
        # ``durable=False`` for the legacy synchronous-only
        # shape (used by the in-package lifecycle tests).
        self._durable = durable
        self._event_outbox = event_outbox
        if self._durable and self._event_outbox is not None:
            # Wire the two per-channel senders on the outbox
            # using this bridge's live router + sentinel.  Done
            # once at construction so the bridge never touches
            # the outbox wiring again.
            self._event_outbox.register_bridge_senders(
                router=self._router, sentinel=self._sentinel,
            )
        # module_id -> {source_name: EventSource}
        self._sources: dict[str, dict[str, EventSource]] = {}
        # module_id -> {source_name: running start() task}
        self._source_tasks: dict[str, dict[str, asyncio.Task[Any]]] = {}
        # module_id -> {detector_name: AnomalyDetector}
        self._detectors: dict[str, dict[str, AnomalyDetector]] = {}
        # module_id -> {reaction_name: ProactiveReaction}
        self._reactions: dict[str, dict[str, ProactiveReaction]] = {}
        # Optional broker-gated tool executor wired by the Module_Platform so a
        # reaction's response can invoke the owning module's tools subject to its
        # Permission_Broker decision (Req 8.3). ``None`` until set; absent it, a
        # reaction's declared tools are skipped (the notification still routes).
        self._tool_gate: ToolGate | None = None

    def set_tool_gate(self, gate: ToolGate | None) -> None:
        """Wire the broker-gated tool executor used by reaction fan-out (Req 8.3).

        The Module_Platform injects a callable that, given ``(module_id, tool,
        response)``, evaluates the owning module's Permission_Broker decision and
        runs the tool only on an allow verdict. Event_Bridge owns neither the
        broker nor the tool registry, so this seam keeps the fan-out decoupled
        from permission evaluation.
        """
        self._tool_gate = gate

    # ── Event sources (Req 7.1, 7.2) ───────────────────────────────────

    def register_source(self, module_id: str, source: EventSource) -> None:
        """Start a module event source and connect its ``emit`` callback.

        The source's ``start`` coroutine runs under :meth:`HealthMonitor.guard`,
        so an unhandled error is caught and counted instead of propagating to the
        core. A failure registering or starting one source is isolated and leaves
        every previously registered source operational (Req 7.1, 7.2).
        """
        try:
            source_name = source.name
            sources = self._sources.setdefault(module_id, {})
            if source_name in sources:
                logger.warning(
                    "Event source %s already registered for module %s; replacing",
                    source_name,
                    module_id,
                )
                self.deregister_source(module_id, source_name)
                sources = self._sources.setdefault(module_id, {})
            sources[source_name] = source

            async def emit(event: ModuleEvent) -> None:
                await self._emit(module_id, source_name, event)

            task = self._start_source(module_id, source_name, source.start(emit))
            if task is not None:
                self._source_tasks.setdefault(module_id, {})[source_name] = task
            logger.info(
                "Registered event source %s for module %s", source_name, module_id
            )
        except Exception:
            logger.exception(
                "Failed to register event source for module %s; failure isolated",
                module_id,
            )

    def deregister_source(self, module_id: str, source_name: str) -> None:
        """Stop and remove a module event source (Req 10.7).

        Idempotent: deregistering an absent source is a no-op. The source's
        ``stop`` coroutine runs under :meth:`HealthMonitor.guard` for isolation.
        """
        sources = self._sources.get(module_id, {})
        source = sources.pop(source_name, None)
        if not sources:
            self._sources.pop(module_id, None)

        tasks = self._source_tasks.get(module_id, {})
        task = tasks.pop(source_name, None)
        if not tasks:
            self._source_tasks.pop(module_id, None)
        if task is not None and not task.done():
            task.cancel()

        if source is None:
            logger.debug(
                "No event source %s for module %s to deregister",
                source_name,
                module_id,
            )
            return
        self._schedule_stop(module_id, source)
        logger.info(
            "Deregistered event source %s for module %s", source_name, module_id
        )

    # ── Anomaly detectors (Req 7.3) ────────────────────────────────────

    def register_detector(self, module_id: str, detector: AnomalyDetector) -> None:
        """Subscribe a detector to the event source it declares via ``listens_to``.

        The detector is recorded per-module so :meth:`on_event` (task 8.2) can fan
        an event out only to the detectors that declared the emitting source
        (Req 7.3). A failed registration is isolated and does not raise.
        """
        try:
            name = detector.name
            listens_to = detector.listens_to
            if not listens_to:
                logger.warning(
                    "Detector %s for module %s declares no listens_to source",
                    name,
                    module_id,
                )
            self._detectors.setdefault(module_id, {})[name] = detector
            logger.info(
                "Registered anomaly detector %s for module %s (listens_to=%s)",
                name,
                module_id,
                listens_to,
            )
        except Exception:
            logger.exception(
                "Failed to register anomaly detector for module %s; failure isolated",
                module_id,
            )

    def deregister_detector(self, module_id: str, detector_name: str) -> None:
        """Remove a module anomaly detector (Req 10.7).

        Idempotent: deregistering an absent detector is a no-op.
        """
        detectors = self._detectors.get(module_id, {})
        if detectors.pop(detector_name, None) is None:
            logger.debug(
                "No anomaly detector %s for module %s to deregister",
                detector_name,
                module_id,
            )
            return
        if not detectors:
            self._detectors.pop(module_id, None)
        logger.info(
            "Deregistered anomaly detector %s for module %s", detector_name, module_id
        )

    # ── Proactive reactions (Req 8.1) ──────────────────────────────────

    def register_reaction(self, module_id: str, reaction: ProactiveReaction) -> None:
        """Persist a reaction's condition and defined response (Req 8.1).

        The reaction is recorded both in the :class:`StandingOrderStore` (so it
        survives as a persistent standing order) and in the in-memory registry
        (so :meth:`on_event` can fire it). A failed registration is isolated.
        """
        try:
            name = reaction.name
            condition = reaction.condition
            response = getattr(reaction, "response", None) or {}
            self._persist_reaction(module_id, name, condition, response)
            self._reactions.setdefault(module_id, {})[name] = reaction
            logger.info(
                "Registered proactive reaction %s for module %s", name, module_id
            )
        except Exception:
            logger.exception(
                "Failed to register proactive reaction for module %s; failure isolated",
                module_id,
            )

    def deregister_reaction(self, module_id: str, reaction_name: str) -> None:
        """Remove a module proactive reaction from memory and the store (Req 10.7).

        Idempotent: deregistering an absent reaction is a no-op.
        """
        reactions = self._reactions.get(module_id, {})
        reactions.pop(reaction_name, None)
        if not reactions:
            self._reactions.pop(module_id, None)
        title = self._reaction_title(module_id, reaction_name)
        removed = self._standing_orders.deregister_reaction(title)
        if removed:
            logger.info(
                "Deregistered proactive reaction %s for module %s",
                reaction_name,
                module_id,
            )
        else:
            logger.debug(
                "No persisted proactive reaction %s for module %s to deregister",
                reaction_name,
                module_id,
            )

    # ── Event fan-out and priority mapping (Req 7.3-7.6, 8.2, 8.3) ─────

    async def on_event(
        self, module_id: str, source_name: str, event: ModuleEvent
    ) -> None:
        """Fan a source-emitted event out to a module's detectors and reactions.

        Delivery is scoped to the emitting module: the event reaches only the
        detectors that module registered which declared this source via
        ``listens_to`` (Req 7.3). Each detector runs under
        :meth:`HealthMonitor.guard` so a faulty detector is isolated from core;
        a detector that raises a :class:`RaisedEvent` has it submitted to
        ``OutputRouter`` at the detector's declared priority — substituted with
        ``NORMAL`` when missing or invalid (Req 7.4, 7.5). A ``CRITICAL`` event
        reaches every operator platform even during do-not-disturb, which
        ``OutputRouter`` handles natively (Req 7.6).

        After the detectors, every reaction the module registered is offered the
        event; a reaction that returns a truthy response is fired — its response
        is routed at the reaction's declared priority and any tools it names are
        executed through the broker-gated tool seam (Req 8.2, 8.3).
        """
        for detector in self._detectors_for(module_id, source_name):
            raised = await self._health.guard(module_id, detector.inspect(event))
            if raised is None:
                continue
            await self._submit_raised(module_id, source_name, detector, raised)

        for reaction in list(self._reactions.get(module_id, {}).values()):
            await self._fire_reaction(module_id, reaction, event)

    @staticmethod
    def normalize_priority(value: Any) -> tuple[Priority, bool]:
        """Map a declared priority to an ``OutputRouter`` ``Priority`` (Req 7.5).

        Returns ``(priority, substituted)``. A declared priority is valid only
        when it is one of ``CRITICAL``, ``HIGH``, ``NORMAL``, ``LOW``, or
        ``DIGEST`` — accepted as a ``Priority`` member, its case-insensitive
        name, or its integer value. A missing (``None``) or otherwise invalid
        value resolves to ``(Priority.NORMAL, True)`` so the caller can report
        the substitution; a valid value resolves to ``(priority, False)``.
        """
        if isinstance(value, Priority):
            return value, False
        if isinstance(value, bool):
            # bool is an int subclass; never a valid declared priority.
            return Priority.NORMAL, True
        if isinstance(value, int):
            try:
                return Priority(value), False
            except ValueError:
                return Priority.NORMAL, True
        if isinstance(value, str):
            member = Priority.__members__.get(value.strip().upper())
            if member is not None:
                return member, False
        return Priority.NORMAL, True

    @staticmethod
    def severity_to_priority(severity: str) -> Priority:
        """Map a ``SentinelBridge`` severity to an ``OutputRouter`` ``Priority`` (A5).

        Unknown severities fall back to ``NORMAL``.
        """
        if not isinstance(severity, str):
            return Priority.NORMAL
        return _SEVERITY_TO_PRIORITY.get(severity.strip().upper(), Priority.NORMAL)

    @staticmethod
    def priority_to_severity(priority: Priority) -> str:
        """Map an ``OutputRouter`` ``Priority`` to a ``SentinelBridge`` severity (A5)."""
        return _PRIORITY_TO_SEVERITY.get(priority, "MEDIUM")

    # ── Internal helpers ───────────────────────────────────────────────

    async def _emit(self, module_id: str, source_name: str, event: ModuleEvent) -> None:
        """Deliver a source-emitted event to the fan-out handler.

        Resolving :meth:`on_event` dynamically keeps the registration surface
        decoupled from the delivery surface; the source's ``emit`` callback is
        wired here at registration time.
        """
        handler = getattr(self, "on_event", None)
        if handler is None:
            logger.debug(
                "EventBridge has no on_event handler; dropping event from %s/%s",
                module_id,
                source_name,
            )
            return
        await handler(module_id, source_name, event)

    def _detectors_for(self, module_id: str, source_name: str) -> list[AnomalyDetector]:
        """Return the module's detectors that declared ``source_name``.

        Delivery is scoped so an event reaches only the detectors that the
        emitting module registered against the emitting source (Req 7.3).
        """
        detectors = self._detectors.get(module_id, {}).values()
        return [d for d in detectors if d.listens_to == source_name]

    async def _submit_raised(
        self,
        module_id: str,
        source_name: str,
        detector: AnomalyDetector,
        raised: RaisedEvent,
    ) -> None:
        """Submit a detector's raised event to ``OutputRouter`` at its priority.

        The declared priority is normalized; a missing or invalid value is
        substituted with ``NORMAL`` and the substitution is reported, identifying
        the detector and the offending value (Req 7.4, 7.5). The event is also
        recorded to the Sentinel history for parity with the existing pipeline,
        translating the priority back to a severity via the A5 mapping.

        When ``self._durable`` is true (the default), the OutputRouter delivery
        is wrapped in :class:`app.runtime.event_outbox.EventOutbox` so the event
        survives a process restart; the live ``router.route(...)`` still fires
        after a successful drain so in-process ``RecordingRouter`` assertions
        keep passing.  ``_record_history`` follows the same pattern for the
        SentinelBridge channel.
        """
        priority, substituted = self.normalize_priority(raised.priority)
        if substituted:
            logger.warning(
                "Detector %s (module %s) declared invalid priority %r; "
                "substituting NORMAL",
                detector.name,
                module_id,
                raised.priority,
            )
        await self._record_history(module_id, source_name, raised, priority)
        try:
            if self._durable:
                # Durable path: enqueue + drain. The outbox sender
                # is the single delivery point — it forwards the
                # event to the live router exactly once. We do
                # NOT call ``self._router.route(...)`` again after
                # the drain: doing so would double-fire on
                # success (once via the sender, once via the
                # bridge) and defeat the at-least-once guarantee.
                await self._enqueue_and_drain_sink(
                    sink=CHANNEL_OUTPUT_ROUTER,
                    module_id=module_id,
                    source_name=source_name,
                    event=raised,
                    target=detector.name,
                    payload={
                        "message": raised.message,
                        "source": f"module:{module_id}:{detector.name}",
                        "priority": priority.name,
                    },
                )
            else:
                # Synchronous-only path (tests that need the
                # exact pre-outbox contract; opt-out via
                # ``EventBridge(durable=False, ...)``).
                self._router.route(
                    raised.message,
                    source=f"module:{module_id}:{detector.name}",
                    explicit_priority=priority,
                )
        except Exception:  # pragma: no cover - delivery must never reach core
            logger.exception(
                "Failed to route raised event from detector %s (module %s)",
                detector.name,
                module_id,
            )

    async def _fire_reaction(
        self, module_id: str, reaction: ProactiveReaction, event: ModuleEvent
    ) -> None:
        """Offer an event to a reaction and fire it when it matches (Req 8.2, 8.3).

        ``reaction.respond`` runs under :meth:`HealthMonitor.guard` for isolation;
        a falsy response means the event did not match and nothing fires. A
        matching response is routed to ``OutputRouter`` at the priority the
        response declares (substituted with ``NORMAL`` when invalid), and each
        tool the response names is executed through the broker-gated tool seam.
        """
        response = await self._health.guard(module_id, reaction.respond(event))
        if not response:
            return

        priority = self._reaction_priority(module_id, reaction, response)
        if response.get("notify", True):
            message = self._reaction_message(reaction, response)
            try:
                self._router.route(
                    message,
                    source=f"module:{module_id}:{reaction.name}",
                    explicit_priority=priority,
                )
            except Exception:  # pragma: no cover - delivery must never reach core
                logger.exception(
                    "Failed to route response for reaction %s (module %s)",
                    reaction.name,
                    module_id,
                )

        for tool in response.get("invoke_tools") or []:
            await self._invoke_tool(module_id, tool, response)

    def _reaction_priority(
        self, module_id: str, reaction: ProactiveReaction, response: ReactionResponse
    ) -> Priority:
        """Resolve the priority a reaction's response is routed at (Req 8.2).

        An absent priority defaults to ``NORMAL`` silently; a present but invalid
        priority is substituted with ``NORMAL`` and the substitution is reported.
        """
        declared = response.get("priority")
        if declared is None:
            return Priority.NORMAL
        priority, substituted = self.normalize_priority(declared)
        if substituted:
            logger.warning(
                "Reaction %s (module %s) declared invalid priority %r; "
                "substituting NORMAL",
                reaction.name,
                module_id,
                declared,
            )
        return priority

    @staticmethod
    def _reaction_message(
        reaction: ProactiveReaction, response: ReactionResponse
    ) -> str:
        """Best-effort notification text for a fired reaction."""
        for key in ("message", "notify_text", "text"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        return f"Proactive reaction {reaction.name} fired"

    async def _invoke_tool(
        self, module_id: str, tool: Any, response: ReactionResponse
    ) -> None:
        """Execute one reaction-named tool through the broker-gated seam (Req 8.3).

        When no tool gate is wired the invocation is skipped with a warning — the
        reaction's notification has already been routed, but a module tool must
        never run outside the owning module's Permission_Broker decision. The
        gate itself runs under :meth:`HealthMonitor.guard` for isolation.
        """
        gate = self._tool_gate
        if gate is None:
            logger.warning(
                "No broker-gated tool executor wired; skipping tool %r for module %s",
                tool,
                module_id,
            )
            return
        await self._health.guard(module_id, gate(module_id, tool, response))

    async def _record_history(
        self,
        module_id: str,
        source_name: str,
        raised: RaisedEvent,
        priority: Priority,
    ) -> None:
        """Record a raised event into the Sentinel history (best-effort).

        Mirrors the existing ``SentinelBridge`` pipeline so module-raised events
        appear in the same event log/digest, translating the resolved priority
        back to a severity via the A5 mapping. Any failure is isolated so it
        never reaches core or blocks routing.

        When ``self._durable`` is true (the default) the
        :class:`SentinelBridge` delivery is routed through the
        :class:`app.runtime.event_outbox.EventOutbox` for the same
        at-least-once guarantee the OutputRouter channel gets. The outbox
        sender is the single delivery point; the bridge does NOT call
        ``self._sentinel.inject_event(...)`` again after the drain.
        """
        event_type = raised.detector_name or "module_event"
        severity = self.priority_to_severity(priority)
        try:
            if self._durable:
                # Durable path: enqueue + drain. The outbox sender
                # is the single delivery point for the sentinel
                # channel. ``event_type`` is part of the payload so
                # the sender can rehydrate the full
                # ``SentinelBridge.inject_event(...)`` call (the
                # production signature requires it positionally).
                await self._enqueue_and_drain_sink(
                    sink=CHANNEL_SENTINEL_BRIDGE,
                    module_id=module_id,
                    source_name=source_name,
                    event=raised,
                    target=source_name,
                    payload={
                        "event_type": event_type,
                        "message": raised.message,
                        "source": f"module:{module_id}:{source_name}",
                        "severity": severity,
                        "metadata": dict(raised.payload),
                    },
                )
            else:
                # Synchronous-only path (opt-out for tests).
                self._sentinel.inject_event(
                    event_type=event_type,
                    message=raised.message,
                    severity=severity,
                    source=f"module:{module_id}:{source_name}",
                    metadata=dict(raised.payload),
                )
        except Exception:  # pragma: no cover - history logging is best-effort
            logger.debug(
                "Failed to record raised event from module %s into Sentinel history",
                module_id,
                exc_info=True,
            )

    async def _enqueue_and_drain_sink(
        self,
        *,
        sink: str,
        module_id: str,
        source_name: str,
        event: RaisedEvent,
        target: str,
        payload: dict[str, Any],
    ) -> None:
        """Enqueue an event-sink delivery and drain the outbox inline.

        The drain is awaited (so a slow ``drain_once`` blocks the
        bridge's sink call, just like the original synchronous
        ``router.route`` did), but the entry is **persisted before
        the sender is awaited** — the at-least-once guarantee the
        gap analysis names.

        A failed drain is **not** raised; the bridge's
        never-propagate-router-exception guard wraps the call so
        a stuck outbox never breaks the in-bridge fan-out.  The
        entry remains ``pending`` for a later retry.
        """
        from app.runtime.event_outbox import get_event_outbox

        ob = self._event_outbox or get_event_outbox()
        # Lazily wire the per-channel senders on first use so
        # bridge construction without a passed-in outbox (the
        # common test path) still works.
        if not ob.senders_registered:
            ob.register_bridge_senders(
                router=self._router, sentinel=self._sentinel,
            )
        event_id = (
            getattr(event, "event_id", None)
            or getattr(event, "id", None)
            or f"{module_id}:{source_name}:{getattr(event, 'message', '')[:32]}"
        )
        await ob.enqueue_event(
            module_id=module_id,
            source_name=source_name,
            event_id=str(event_id),
            sink=sink,
            target=target,
            payload=payload,
        )
        await ob.drain_once()

    def _start_source(
        self, module_id: str, source_name: str, start_coro: Any
    ) -> asyncio.Task[Any] | None:
        """Schedule a source's ``start`` coroutine under the health guard.

        Returns the created task, or ``None`` when there is no running event loop
        to schedule on (in which case the coroutine is closed to avoid a dangling
        warning). Wrapping in :meth:`HealthMonitor.guard` isolates failures.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop; cannot start event source %s for module %s",
                source_name,
                module_id,
            )
            start_coro.close()
            return None
        return loop.create_task(self._health.guard(module_id, start_coro))

    def _schedule_stop(self, module_id: str, source: EventSource) -> None:
        """Schedule a source's ``stop`` coroutine under the health guard."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "No running event loop to stop event source for module %s", module_id
            )
            return
        loop.create_task(self._health.guard(module_id, source.stop()))

    def _persist_reaction(
        self,
        module_id: str,
        name: str,
        condition: str,
        response: dict[str, Any],
    ) -> None:
        """Append a reaction as a standing order recording condition + response.

        The persisted line uses the same ``- [on] <title> | <rule>`` shape that
        :meth:`StandingOrderStore.render` emits and that
        :meth:`StandingOrderStore.deregister_reaction` matches on, so a later
        hot-unload removes exactly this entry by title.
        """
        title = self._reaction_title(module_id, name)
        # Remove any stale entry for the same title before re-persisting.
        self._standing_orders.deregister_reaction(title)
        rule = json.dumps(
            {"condition": condition, "response": response}, sort_keys=True
        )
        line = f"- [on] {title} | {rule}"
        raw = self._standing_orders.load_raw()
        if raw.strip():
            content = raw.rstrip("\n") + "\n" + line + "\n"
        else:
            content = "# Standing Orders\n\n" + line + "\n"
        self._standing_orders.save_raw(content)

    @staticmethod
    def _reaction_title(module_id: str, reaction_name: str) -> str:
        """Build the standing-order title a reaction is persisted under."""
        return f"module:{module_id}:{reaction_name}"
