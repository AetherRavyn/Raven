"""Signal abstraction — the reactive substrate for v2 routines.

Producers (calendar watcher, internet watcher, autonomy worker, anomaly
checks) emit :class:`Signal` objects.  The :class:`SignalRouter` fans them
out to any number of subscribers: botsignal delivery, the
anticipation engine, the audit log, etc.

This sits below :class:`app.core.models.SignalPayload`, which is the
delivery-layer representation.  A signal knows *what* happened and
*who* it concerns; a payload knows *how* to render it for a user.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)


class SignalKind(str, Enum):
    """Producer-side category of a reactive event.

    Stable string values so they survive JSON round-trips and
    can be referenced in log filters / metrics labels.
    """

    CALENDAR = "calendar"
    INTERNET = "internet"
    AUTONOMY = "autonomy"
    ANOMALY = "anomaly"
    FOLLOW_UP = "follow_up"
    SYSTEM = "system"
    MEMORY = "memory"
    CONTINUITY = "continuity"


class SignalSeverity(str, Enum):
    """Urgency / impact level.

    Used by subscribers to decide whether to page the user
    immediately, queue for the next briefing, or just record.
    """

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class Signal:
    """A typed reactive event produced by a v2 routine.

    Attributes:
        id: Globally-unique signal id (``sig_`` + 12-char uuid).
        kind: Category of event (see :class:`SignalKind`).
        severity: Urgency level.
        source: Identifier of the producer — e.g.
            ``"calendar_watcher"``, ``"internet_watcher"``,
            ``"autonomy_worker"``.
        user_id: Owning user.  Empty string for global signals.
        title: Short, human-readable label suitable for a list
            view or notification.
        body: Optional longer text (already-formatted markdown).
        payload: Arbitrary producer-specific data; must be
            JSON-serialisable.  Used by subscribers that want
            structured access (e.g. calendar event ids).
        created_at: UTC timestamp of when the signal was created.
        dedupe_key: Optional caller-supplied key.  The router
            drops signals whose ``dedupe_key`` matches a recent
            signal of the same kind for the same user within
            ``dedupe_window``.  Lets producers like the calendar
            watcher prevent duplicate alerts.
    """

    id: str
    kind: SignalKind
    severity: SignalSeverity
    source: str
    user_id: str
    title: str
    body: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dedupe_key: str | None = None

    @classmethod
    def make(
        cls,
        kind: SignalKind | str,
        source: str,
        user_id: str,
        title: str,
        *,
        severity: SignalSeverity | str = SignalSeverity.INFO,
        body: str | None = None,
        payload: Mapping[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> Signal:
        """Convenience constructor.

        Generates the id automatically.  Accepts either enum
        instances or their string values for ``kind`` /
        ``severity`` so producers can use string literals
        without importing the enum.
        """
        if isinstance(kind, str):
            kind = SignalKind(kind)
        if isinstance(severity, str):
            severity = SignalSeverity(severity)
        return cls(
            id=f"sig_{uuid.uuid4().hex[:12]}",
            kind=kind,
            severity=severity,
            source=source,
            user_id=user_id,
            title=title,
            body=body,
            payload=dict(payload or {}),
            dedupe_key=dedupe_key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "source": self.source,
            "user_id": self.user_id,
            "title": self.title,
            "body": self.body,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
            "dedupe_key": self.dedupe_key,
        }

    def __repr__(self) -> str:
        return (
            f"Signal(kind={self.kind.value}, source={self.source!r}, "
            f"user={self.user_id!r}, severity={self.severity.value})"
        )


# Type aliases ----------------------------------------------------------

SignalHandler = Callable[[Signal], Awaitable[None]]
"""Async handler invoked by the router for each delivered signal."""

SignalPredicate = Callable[[Signal], bool]
"""Filter applied before delivery.  ``True`` = deliver, ``False`` = drop."""


@dataclass(slots=True)
class _Queue:
    """Per-user FIFO queue with a hard cap.

    Older signals are dropped on overflow.  The deque itself
    is bounded via ``maxlen``, so memory is bounded by
    ``maxlen * size_of(Signal)``.
    """

    user_id: str
    items: deque[Signal] = field(default_factory=deque)
    maxlen: int = 100

    def push(self, signal: Signal) -> None:
        if self.maxlen > 0 and len(self.items) >= self.maxlen:
            dropped = self.items.popleft()
            logger.debug(
                "SignalQueue[%s]: dropped oldest signal %s (queue full)",
                self.user_id,
                dropped.id,
            )
        self.items.append(signal)

    def drain(self) -> list[Signal]:
        out = list(self.items)
        self.items.clear()
        return out

    def peek(self, n: int = 10) -> list[Signal]:
        return list(self.items)[-n:]


class SignalRouter:
    """Fans out :class:`Signal` objects to subscribers.

    Subscribers register an async ``SignalHandler``.  When the
    router receives a signal (via :meth:`publish`), it applies
    the optional per-subscriber predicate, then invokes the
    handler.  A per-user :class:`_Queue` always receives a copy
    of the signal so consumers can poll or replay.

    The router is thread-safe; handlers themselves run
    sequentially per ``publish`` call (one bad handler cannot
    block the others — exceptions are caught and logged).
    """

    def __init__(self, queue_maxlen: int = 100) -> None:
        self._handlers: list[tuple[SignalHandler, SignalPredicate | None, str]] = []
        self._queues: dict[str, _Queue] = {}
        self._lock = threading.Lock()
        self._queue_maxlen = queue_maxlen

    # -- subscription ----------------------------------------------------

    def subscribe(
        self,
        handler: SignalHandler,
        *,
        name: str | None = None,
        predicate: SignalPredicate | None = None,
    ) -> Callable[[], None]:
        """Register a handler.

        Returns a callable that unsubscribes the handler when
        invoked — useful for scoped subscriptions in tests.
        """
        handler_name = name or getattr(handler, "__name__", "anonymous")
        with self._lock:
            self._handlers.append((handler, predicate, handler_name))

        def unsubscribe() -> None:
            self.unsubscribe_handler(handler)

        return unsubscribe

    def unsubscribe_handler(self, handler: SignalHandler) -> None:
        with self._lock:
            self._handlers = [
                (h, p, n) for (h, p, n) in self._handlers if h is not handler
            ]

    @property
    def handler_count(self) -> int:
        with self._lock:
            return len(self._handlers)

    # -- queue access ----------------------------------------------------

    def _queue_for(self, user_id: str) -> _Queue:
        with self._lock:
            q = self._queues.get(user_id)
            if q is None:
                q = _Queue(user_id=user_id, maxlen=self._queue_maxlen)
                self._queues[user_id] = q
            return q

    def push(self, signal: Signal) -> None:
        """Add ``signal`` to the per-user queue without invoking handlers."""
        self._queue_for(signal.user_id).push(signal)

    def drain(self, user_id: str) -> list[Signal]:
        return self._queue_for(user_id).drain()

    def peek(self, user_id: str, n: int = 10) -> list[Signal]:
        return self._queue_for(user_id).peek(n)

    def queue_size(self, user_id: str) -> int:
        with self._lock:
            return len(self._queues.get(user_id, _Queue(user_id=user_id)).items)

    # -- publish ---------------------------------------------------------

    async def publish(self, signal: Signal) -> int:
        """Deliver ``signal`` to the queue and all matching handlers.

        Returns the number of handlers the signal was delivered to.
        Per-handler errors are caught and logged so a single
        broken subscriber doesn't kill the fan-out.
        """
        self.push(signal)
        return await self._dispatch(signal)

    async def publish_many(self, signals: Sequence[Signal]) -> dict[str, int]:
        """Publish a batch of signals.

        Returns a mapping ``signal_id -> handler_count`` so
        callers (and tests) can see the per-signal fan-out.
        """
        out: dict[str, int] = {}
        for s in signals:
            out[s.id] = await self.publish(s)
        return out

    async def _dispatch(self, signal: Signal) -> int:
        with self._lock:
            handlers = list(self._handlers)
        delivered = 0
        for handler, predicate, name in handlers:
            if predicate is not None and not predicate(signal):
                continue
            try:
                await handler(signal)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "SignalRouter: handler %r raised for %s: %s",
                    name,
                    signal.id,
                    exc,
                )
                continue
            delivered += 1
        return delivered

    # -- introspection ---------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Snapshot of router state — useful for ``/metrics`` and tests."""
        with self._lock:
            return {
                "handlers": len(self._handlers),
                "users_with_queues": len(self._queues),
                "total_queued": sum(len(q.items) for q in self._queues.values()),
            }


# -- dedupe helper -------------------------------------------------------


@dataclass(slots=True)
class DedupeCache:
    """Tracks recent ``(user_id, kind, dedupe_key)`` triples.

    Used by watchers to suppress duplicate alerts.  Bounded
    to ``maxlen`` entries to keep memory predictable.  This
    is intentionally separate from the SignalRouter — dedupe
    is a producer concern (don't emit the same signal twice),
    not a router concern (don't deliver the same signal twice).
    """

    ttl_seconds: float = 600.0
    maxlen: int = 1024
    _entries: dict[tuple[str, str, str | None], float] = field(default_factory=dict)
    _order: deque[tuple[str, str, str | None]] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check_and_record(
        self,
        user_id: str,
        kind: SignalKind,
        dedupe_key: str | None,
        now: float | None = None,
    ) -> bool:
        """Return ``True`` if ``dedupe_key`` is fresh; record it either way.

        A "fresh" key (i.e. ``True``) means the caller should
        *not* emit a duplicate signal.  ``False`` means it's
        safe to emit, and the key has been recorded for future
        lookups.
        """
        import time

        if not dedupe_key:
            return False
        ts = time.time() if now is None else now
        k = (user_id, kind.value, dedupe_key)
        with self._lock:
            self._evict_expired(ts)
            if k in self._entries:
                return True
            self._entries[k] = ts + self.ttl_seconds
            self._order.append(k)
            if len(self._order) > self.maxlen:
                old = self._order.popleft()
                self._entries.pop(old, None)
        return False

    def _evict_expired(self, now: float) -> None:
        while self._order and self._entries.get(self._order[0], 0) <= now:
            old = self._order.popleft()
            self._entries.pop(old, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._order.clear()


# -- module-level singleton (mirrors the Scheduler pattern) --------------

_router: SignalRouter | None = None
_router_lock = threading.Lock()


def get_default_signal_router() -> SignalRouter:
    """Return the process-wide :class:`SignalRouter`.

    Lazy-initialised on first access.  Mirrors the
    ``get_default_scheduler`` / ``get_privacy_manager`` pattern
    so consumers can grab a ready-to-use router without
    worrying about wiring.
    """
    global _router
    with _router_lock:
        if _router is None:
            _router = SignalRouter()
        return _router


def set_default_signal_router(router: SignalRouter | None) -> None:
    """Set or clear the process-wide router (mainly for tests)."""
    global _router
    with _router_lock:
        _router = router


def reset_default_signal_router() -> None:
    set_default_signal_router(None)


# -- producer contract ---------------------------------------------------


async def generate_signals(
    *producers: Callable[[], Awaitable[Iterable[Signal]]],
) -> list[Signal]:
    """Run a sequence of async producers and aggregate their signals.

    Producers that raise are caught and logged (so a single
    broken source doesn't take down the whole pipeline).  This
    is the contract every v2 watcher implements at its public
    boundary — the scheduler calls the routine, the routine
    returns :class:`Signal` objects, and the boot layer
    publishes them through the router.
    """
    out: list[Signal] = []
    for producer in producers:
        try:
            signals = await producer()
        except Exception as exc:  # noqa: BLE001
            logger.exception("generate_signals: producer %r failed: %s", producer, exc)
            continue
        out.extend(signals)
    return out
