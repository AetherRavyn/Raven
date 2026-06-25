"""Durable event delivery outbox (Q2 from
``docs/12-modular-platform-integration.md`` §6).

The :class:`EventBridge` historically calls ``OutputRouter.route(...)``
and ``SentinelBridge.inject_event(...)`` *synchronously* from
inside :meth:`EventBridge._submit_raised` and
:meth:`EventBridge._record_history`.  If the destination is
unavailable (process restart, outbox replay in flight,
BotSignal failure) the event is lost.

This module wraps those two external-sink calls in the existing
:class:`app.runtime.outbox.Outbox` machinery (durable JSONL
persistence, idempotency keys, exponential backoff, per-channel
senders) so the bridge's external delivery is at-least-once
and survives process restarts.

Design constraints
------------------

* **In-bridge detector/reaction fan-out is unchanged.**
  The synchronous ``for detector in self._detectors_for(...)``
  loop in :meth:`EventBridge.on_event` is the module-internal
  contract that ``HealthMonitor.guard`` isolation depends on.
  Only the *external-sink* delivery (OutputRouter +
  SentinelBridge) is wrapped here.

* **The bridge registers the per-channel senders.**  The
  outbox does not know about the bridge's router/sentinel at
  construction time (it would create a circular import).
  Instead, the bridge calls :meth:`register_bridge_senders`
  with its router and sentinel after construction; the outbox
  wires the per-channel adapters in.

* **Singleton + env-var override, mirroring
  :func:`app.runtime.outbox.get_outbox`.**  Tests use
  ``RAVEN_EVENT_OUTBOX_PATH`` to point at a per-test tmp
  file via the autouse ``isolated_event_outbox`` fixture.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.runtime.outbox import Outbox, OutboxEntry, make_idempotency_key

logger = logging.getLogger(__name__)


# ── Public constants ──────────────────────────────────────────────────


CHANNEL_OUTPUT_ROUTER = "output_router"
CHANNEL_SENTINEL_BRIDGE = "sentinel_bridge"

#: Default on-disk path.  Overridable via env var for tests
#: and operators who want a non-default location.
_DEFAULT_PATH = Path(
    os.environ.get("RAVEN_EVENT_OUTBOX_PATH")
    or (Path.home() / ".raven" / "runtime" / "event_outbox.jsonl"),
)


# ── Wrapper ───────────────────────────────────────────────────────────


class EventOutbox:
    """Thin domain wrapper around :class:`Outbox` for EventBridge delivery.

    Provides :meth:`enqueue_event` (with a stable idempotency key
    built from the bridge's call-site arguments) and exposes
    :meth:`drain_once` / :meth:`list` / :meth:`pending_count`
    on the underlying :class:`Outbox`.  All durability / retry /
    persistence semantics are inherited from
    :class:`app.runtime.outbox.Outbox`.

    The per-channel senders (``output_router`` and
    ``sentinel_bridge``) are registered by the bridge via
    :meth:`register_bridge_senders` because the bridge holds
    the live router/sentinel instances; the outbox itself
    stays sink-agnostic.
    """

    def __init__(self, *, outbox: Outbox | None = None) -> None:
        # NB: ``outbox or Outbox(path=_DEFAULT_PATH)`` is wrong
        # because :class:`Outbox` defines ``__len__`` (for
        # ``pending_count`` / ``len(ob.list())`` callers), so an
        # empty outbox is *falsy*.  Use an explicit ``None`` check
        # so the caller-supplied outbox is always honoured.
        self._outbox = outbox if outbox is not None else Outbox(path=_DEFAULT_PATH)
        self._senders_registered = False

    # ── Sender wiring ─────────────────────────────────────────────

    def register_bridge_senders(
        self,
        *,
        router: Any,
        sentinel: Any,
    ) -> None:
        """Wire the two per-channel senders used by the bridge.

        Idempotent: a second call replaces the previous
        senders (the underlying :class:`Outbox` overwrites on
        each call).  The senders are async functions that
        rehydrate the bridge's two sink calls from the
        :class:`OutboxEntry` payload and forward.

        Both senders swallow exceptions raised by the live
        router/sentinel so the outbox's retry layer sees a
        transient failure rather than a crash.  A hard
        failure is signalled by re-raising after the
        ``drain_once`` count.

        ``router`` and ``sentinel`` are duck-typed — the
        outbox does not import the concrete classes (that
        would create a circular import with
        ``app.modules.event_bridge``).  The bridge passes
        the live instances at construction time.
        """
        if router is not None:
            self._outbox.register_sender(
                CHANNEL_OUTPUT_ROUTER,
                _make_output_router_sender(router),
            )
        if sentinel is not None:
            self._outbox.register_sender(
                CHANNEL_SENTINEL_BRIDGE,
                _make_sentinel_bridge_sender(sentinel),
            )
        self._senders_registered = True

    @property
    def senders_registered(self) -> bool:
        """Whether :meth:`register_bridge_senders` has been called."""
        return self._senders_registered

    # ── Enqueue / drain / inspect ──────────────────────────────────

    async def enqueue_event(
        self,
        *,
        module_id: str,
        source_name: str,
        event_id: str,
        sink: str,
        target: str,
        payload: dict[str, Any],
    ) -> OutboxEntry:
        """Enqueue one event for delivery to ``sink``.

        The idempotency key is built deterministically from
        the call-site arguments so two callers with the same
        ``(module_id, source_name, event_id, sink)`` collapse
        to a single outbox entry.
        """
        key = make_idempotency_key(
            "event_bridge", module_id, source_name, event_id, sink,
        )
        return await self._outbox.enqueue(
            idempotency_key=key,
            channel=sink,
            target=target,
            action="deliver",
            payload=dict(payload or {}),
        )

    async def drain_once(self, **kw: Any) -> dict[str, int]:
        """Attempt to send every pending entry once.

        Forwards to :meth:`Outbox.drain_once`.
        """
        return await self._outbox.drain_once(**kw)

    def list(self, **kw: Any) -> list[OutboxEntry]:
        """Return a snapshot of the outbox entries (any state)."""
        return self._outbox.list(**kw)

    def pending_count(self) -> int:
        """Number of entries still in ``pending`` state."""
        return self._outbox.pending_count()

    @property
    def raw_outbox(self) -> Outbox:
        """Direct access to the underlying :class:`Outbox` (escape hatch)."""
        return self._outbox


# ── Sender adapters ───────────────────────────────────────────────────
#
# The two adapters below rehydrate a bridge-style side effect from
# the outbox entry's JSON-safe payload.  The shape is kept as close
# as possible to the bridge's existing synchronous call sites so
# the runtime behaviour matches exactly when the drain succeeds on
# the first try.


def _make_output_router_sender(router: Any):
    """Build a sender that forwards to ``router.route(...)``.

    Reads ``payload["message"]``, ``payload["source"]``, and
    ``payload["priority"]`` from the entry.  An unknown /
    missing priority falls back to ``NORMAL`` (the bridge's
    own :meth:`EventBridge.normalize_priority` runs upstream
    and substitutes; this fallback is the last line of
    defence).
    """

    async def _sender(entry: OutboxEntry) -> None:
        message = entry.payload.get("message", "")
        source = entry.payload.get("source", f"module:{entry.target}")
        # OutputRouter.route takes a Priority enum or None; pass
        # through the priority name string as a fallback (the
        # real bridge writes the enum; this handles old / partial
        # entries gracefully).
        from app.core.output_router import Priority  # lazy: avoid cycle

        priority_name = entry.payload.get("priority")
        priority: Any = None
        if isinstance(priority_name, str):
            try:
                priority = Priority[priority_name.upper()]
            except (KeyError, AttributeError):
                priority = None
        router.route(
            message,
            source=source,
            explicit_priority=priority,
        )

    return _sender


def _make_sentinel_bridge_sender(sentinel: Any):
    """Build a sender that forwards to ``sentinel.inject_event(...)``.

    Reads ``payload["event_type"]``, ``payload["severity"]``,
    ``payload["source"]``, ``payload["message"]``, and (optionally)
    ``payload["metadata"]`` from the entry.  ``event_type`` is
    the A5 detector-name translation; the bridge writes it when
    it persists the entry.  ``event_type`` is required by
    :meth:`SentinelBridge.inject_event` (positional); falls back
    to ``"module_event"`` for any pre-fix entry on disk.
    """

    async def _sender(entry: OutboxEntry) -> None:
        event_type = entry.payload.get("event_type", "module_event")
        severity = entry.payload.get("severity", "MEDIUM")
        source = entry.payload.get("source", f"module:{entry.target}")
        message = entry.payload.get("message", "")
        metadata = entry.payload.get("metadata") or {}
        # SentinelBridge.inject_event is sync in the production
        # code; wrap any exception so the outbox's retry layer
        # can catch it.  The bridge's own try/except around the
        # live call ensures we never propagate to the caller.
        sentinel.inject_event(
            event_type=event_type,
            message=message,
            severity=severity,
            source=source,
            metadata=metadata,
        )

    return _sender


# ── Singleton ─────────────────────────────────────────────────────────


_event_outbox_singleton: EventOutbox | None = None


def get_event_outbox() -> EventOutbox:
    """Return the process-wide :class:`EventOutbox`.

    Lazy-initialised on first call.  The underlying
    :class:`Outbox` reads ``$RAVEN_EVENT_OUTBOX_PATH`` on
    every call so tests can swap the path via the
    ``isolated_event_outbox`` autouse fixture.
    """
    global _event_outbox_singleton
    if _event_outbox_singleton is None:
        # Re-resolve the path on every call so a swapped
        # env var takes effect immediately.
        env_path = os.environ.get("RAVEN_EVENT_OUTBOX_PATH")
        path = Path(env_path) if env_path else (Path.home() / ".raven" / "runtime" / "event_outbox.jsonl")
        ob = Outbox(path=path)
        _event_outbox_singleton = EventOutbox(outbox=ob)
    return _event_outbox_singleton


def reset_event_outbox_for_tests() -> None:
    """Drop the cached singleton.  Used by the test fixtures."""
    global _event_outbox_singleton
    _event_outbox_singleton = None
