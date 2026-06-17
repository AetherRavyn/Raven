"""Phase F1 — Trust & Explainability: Audit Viewer.

A query layer over the existing :class:`AuditLog` that supports
rich filtering, timeline grouping, turn replay, and summary
stats.  The viewer does NOT store events — it delegates to the
audit log singleton.

Typical usage::

    viewer = AuditViewer()
    events = viewer.query(AuditFilter(tool_name="calendar.delete"))
    summary = viewer.summary(AuditFilter(user_id="u1"))
    timeline = viewer.timeline(AuditFilter(since=...))
    replay = viewer.replay(turn_id="turn_42")
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.audit.log import AuditLog, get_audit_log
from app.core.audit.types import AuditEvent, AuditKind, RiskLevel


@dataclass(slots=True)
class AuditFilter:
    """Composable filter for :class:`AuditViewer` queries.

    All fields are optional.  ``None`` means "don't filter on
    this dimension".  ``since`` and ``until`` are inclusive.
    """

    kind: AuditKind | str | None = None
    actor: str | None = None
    tool_name: str | None = None
    user_id: str | None = None
    risk_level: RiskLevel | str | None = None
    turn_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    success_only: bool | None = None
    failed_only: bool | None = None
    metadata_contains: dict[str, Any] | None = None
    limit: int | None = None

    def matches(self, event: AuditEvent) -> bool:
        """Return True if ``event`` matches every populated field."""
        if self.kind is not None and event.kind != self.kind:
            return False
        if self.actor is not None and event.actor != self.actor:
            return False
        if self.tool_name is not None:
            target = event.target or ""
            if self.tool_name not in (event.action, target):
                return False
        if self.user_id is not None:
            user = event.context.get("user_id") if event.context else None
            if user != self.user_id:
                return False
        if self.risk_level is not None and event.risk_level != self.risk_level:
            return False
        if self.turn_id is not None:
            turn = event.metadata.get("turn_id") if event.metadata else None
            if turn != self.turn_id:
                return False
        if self.since is not None and event.timestamp < self.since:
            return False
        if self.until is not None and event.timestamp > self.until:
            return False
        if self.success_only is not None:
            if self.success_only and not event.success:
                return False
            if not self.success_only and event.success:
                return False
        if self.failed_only is not None:
            if self.failed_only and event.success:
                return False
            if not self.failed_only and not event.success:
                return False
        if self.metadata_contains:
            for k, v in self.metadata_contains.items():
                if not event.metadata or event.metadata.get(k) != v:
                    return False
        return True


@dataclass(slots=True)
class AuditSummary:
    """Aggregate stats for a filtered view."""

    total: int = 0
    successful: int = 0
    failed: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    by_risk: dict[str, int] = field(default_factory=dict)
    by_actor: dict[str, int] = field(default_factory=dict)
    by_tool: dict[str, int] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "by_kind": dict(self.by_kind),
            "by_risk": dict(self.by_risk),
            "by_actor": dict(self.by_actor),
            "by_tool": dict(self.by_tool),
            "total_cost_usd": self.total_cost_usd,
            "total_duration_ms": self.total_duration_ms,
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "last_at": self.last_at.isoformat() if self.last_at else None,
        }


@dataclass(slots=True)
class TimelineBucket:
    """A time-bucketed slice of events."""

    start: datetime
    end: datetime
    events: list[AuditEvent] = field(default_factory=list)
    bucket_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def count(self) -> int:
        return len(self.events)

    def add(self, event: AuditEvent) -> None:
        self.events.append(event)


class AuditViewer:
    """Query layer over an :class:`AuditLog`.

    Construct with an explicit log for tests; the default uses
    the process singleton from :func:`app.core.audit.log.get_audit_log`.
    """

    def __init__(self, *, log: AuditLog | None = None) -> None:
        self._lock = threading.RLock()
        self._log = log or get_audit_log()

    # -- single-criterion shortcuts --------------------------------------

    def recent(self, n: int = 50) -> list[AuditEvent]:
        """Return the ``n`` most recent events, newest first."""
        with self._lock:
            all_events = self._log.all()
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:n]

    def get(self, event_id: str) -> AuditEvent | None:
        """Look up an event by its :attr:`AuditEvent.id`."""
        with self._lock:
            for e in self._log.all():
                if e.id == event_id:
                    return e
            return None

    # -- filtered queries ------------------------------------------------

    def query(self, filter: AuditFilter | None = None) -> list[AuditEvent]:
        """Return events matching ``filter``, newest first."""
        flt = filter or AuditFilter()
        with self._lock:
            events = [e for e in self._log.all() if flt.matches(e)]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        if flt.limit is not None:
            events = events[: flt.limit]
        return events

    def count(self, filter: AuditFilter | None = None) -> int:
        """Count events matching ``filter``."""
        flt = filter or AuditFilter()
        with self._lock:
            return sum(1 for e in self._log.all() if flt.matches(e))

    def summary(self, filter: AuditFilter | None = None) -> AuditSummary:
        """Compute aggregate stats for the filtered events."""
        events = self.query(filter)
        s = AuditSummary(total=len(events))
        kinds: Counter[str] = Counter()
        risks: Counter[str] = Counter()
        actors: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        for e in events:
            if e.success:
                s.successful += 1
            else:
                s.failed += 1
            kinds[str(e.kind)] += 1
            risks[str(e.risk_level)] += 1
            actors[e.actor] += 1
            tools[e.action] += 1
            s.total_cost_usd += e.cost_usd
            s.total_duration_ms += e.duration_ms
        s.by_kind = dict(kinds)
        s.by_risk = dict(risks)
        s.by_actor = dict(actors)
        s.by_tool = dict(tools)
        if events:
            s.first_at = min(e.timestamp for e in events)
            s.last_at = max(e.timestamp for e in events)
        return s

    # -- timeline grouping -----------------------------------------------

    def timeline(
        self,
        filter: AuditFilter | None = None,
        *,
        bucket: str = "hour",
    ) -> list[TimelineBucket]:
        """Group events into time buckets.

        ``bucket`` is one of ``"minute"``, ``"hour"``, ``"day"``.
        Returns buckets in chronological order, oldest first.
        Empty buckets are NOT included.
        """
        bucket_seconds = {
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }.get(bucket)
        if bucket_seconds is None:
            raise ValueError(f"unknown bucket size: {bucket!r}")
        events = self.query(filter)
        if not events:
            return []
        # Reverse so we walk oldest → newest.
        events.sort(key=lambda e: e.timestamp)
        buckets: dict[int, TimelineBucket] = {}
        for e in events:
            ts = e.timestamp
            epoch = int(ts.timestamp())
            key = epoch - (epoch % bucket_seconds)
            if key not in buckets:
                start = datetime.fromtimestamp(key, tz=timezone.utc)
                end = datetime.fromtimestamp(key + bucket_seconds, tz=timezone.utc)
                buckets[key] = TimelineBucket(start=start, end=end)
            buckets[key].add(e)
        return [buckets[k] for k in sorted(buckets)]

    # -- turn replay -----------------------------------------------------

    def replay(self, turn_id: str) -> list[AuditEvent]:
        """Return every event that belongs to a given turn, oldest first."""
        flt = AuditFilter(turn_id=turn_id)
        events = self.query(flt)
        events.sort(key=lambda e: e.timestamp)
        return events

    # -- time-window shortcuts -------------------------------------------

    def last_hour(self, *, user_id: str | None = None) -> list[AuditEvent]:
        """Return events from the last 60 minutes."""
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        return self.query(AuditFilter(since=since, user_id=user_id))

    def last_day(self, *, user_id: str | None = None) -> list[AuditEvent]:
        """Return events from the last 24 hours."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return self.query(AuditFilter(since=since, user_id=user_id))

    # -- export ----------------------------------------------------------

    def to_dicts(
        self,
        events: Iterable[AuditEvent] | None = None,
        *,
        filter: AuditFilter | None = None,
    ) -> list[dict[str, Any]]:
        """Serialize events (or a filtered view) to dicts."""
        if events is None:
            events = self.query(filter)
        return [e.to_dict() for e in events]


# -- module-level singleton helpers ------------------------------------------


_DEFAULT_VIEWER: AuditViewer | None = None
_LOCK = threading.RLock()


def get_default_audit_viewer() -> AuditViewer:
    """Return the process-singleton :class:`AuditViewer`."""
    global _DEFAULT_VIEWER
    with _LOCK:
        if _DEFAULT_VIEWER is None:
            _DEFAULT_VIEWER = AuditViewer()
        return _DEFAULT_VIEWER


def set_default_audit_viewer(viewer: AuditViewer | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_VIEWER
    with _LOCK:
        _DEFAULT_VIEWER = viewer


def reset_default_audit_viewer() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_VIEWER
    with _LOCK:
        _DEFAULT_VIEWER = None


__all__ = [
    "AuditFilter",
    "AuditSummary",
    "AuditViewer",
    "TimelineBucket",
    "get_default_audit_viewer",
    "reset_default_audit_viewer",
    "set_default_audit_viewer",
]
