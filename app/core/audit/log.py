"""Append-only audit log with a query API.

Storage strategy
----------------
- **Primary**: JSONL file (one event per line, append-only).  Easy to
  ``grep``/``awk``/``jq`` from the shell, durable across restarts,
  and trivially rotatable.
- **Secondary**: in-memory list for fast queries.  Rebuilt from the
  JSONL on first access or every ``N`` events (configurable).
- **Optional**: HelixDB graph nodes for cross-host queries.  We
  write-through but never block on a Helix outage.

The log never raises on a write.  A Helix failure is logged and
swallowed; the JSONL copy is the source of truth.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.audit.types import AuditEvent, _enum_value

logger = logging.getLogger(__name__)


DEFAULT_PATH = Path("workspace/audit.log")
HELIX_KV_PREFIX = "audit:"


class AuditLog:
    """Append-only, queryable audit log.

    Thread-/asyncio-safe.  All writes are serialized through a single
    lock; reads are lock-free and work from the in-memory mirror.
    """

    def __init__(
        self,
        *,
        jsonl_path: Path | str = DEFAULT_PATH,
        # How many events to keep in memory before the next append
        # triggers a full reload.  0 = reload on every event (slow
        # but always correct).  Default is fine for any realistic
        # single-host load.
        reload_every: int = 1000,
        # Optional HelixDB client for durable cross-host storage.
        helix_client: Any | None = None,
    ) -> None:
        self._path = Path(jsonl_path)
        self._reload_every = max(0, reload_every)
        self._helix = helix_client
        self._events: list[AuditEvent] = []
        self._lock = threading.RLock()
        self._since_reload: int = 0
        self._loaded = False
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, event: AuditEvent) -> str:
        """Append an event.  Returns the event id.

        Never raises.  Persistence failures (disk full, permission
        denied, Helix down) are logged and swallowed — the caller
        should be able to continue working.
        """
        try:
            with self._lock:
                self._events.append(event)
                self._since_reload += 1
                self._append_line(event)
                if self._reload_every and self._since_reload >= self._reload_every:
                    self._loaded = False
                    self._since_reload = 0
        except Exception as e:  # noqa: BLE001
            logger.error("audit write failed: %s", e)
        # Best-effort Helix write (outside the lock to avoid blocking).
        if self._helix is not None:
            try:
                key = f"{HELIX_KV_PREFIX}{event.timestamp.isoformat()}:{event.id}"
                # The helix client's kv_put may be sync or async.  We
                # call the sync variant if present; if it's async the
                # caller is expected to schedule a background flush.
                put = getattr(self._helix, "kv_put", None)
                if callable(put):
                    put(key, event.to_dict())
            except Exception as e:  # noqa: BLE001
                logger.debug("helix audit write failed (non-fatal): %s", e)
        return event.id

    def _append_line(self, event: AuditEvent) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), default=str))
            f.write("\n")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._events = []
            if not self._path.exists():
                self._loaded = True
                return
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            self._events.append(AuditEvent.from_dict(d))
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.warning(
                                "audit line parse failed: %s: %s",
                                e,
                                line[:100],
                            )
            except OSError as e:
                logger.error("audit read failed: %s", e)
            self._loaded = True
            self._since_reload = 0

    def get(self, event_id: str) -> AuditEvent | None:
        self._ensure_loaded()
        with self._lock:
            for e in self._events:
                if e.id == event_id:
                    return e
        return None

    def query(
        self,
        *,
        kind: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        target: str | None = None,
        success: bool | None = None,
        risk_level: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        # If set, return newest first (default) or oldest first.
        newest_first: bool = True,
    ) -> list[AuditEvent]:
        self._ensure_loaded()
        with self._lock:
            events = list(self._events)
        # Filter
        out: list[AuditEvent] = []
        for e in events:
            if kind is not None and _enum_value(e.kind) != kind:
                continue
            if actor is not None and e.actor != actor:
                continue
            if action is not None and e.action != action:
                continue
            if target is not None and e.target != target:
                continue
            if success is not None and e.success != success:
                continue
            if risk_level is not None and _enum_value(e.risk_level) != risk_level:
                continue
            if since is not None and e.timestamp < since:
                continue
            if until is not None and e.timestamp > until:
                continue
            if search:
                haystack = " ".join(
                    [
                        e.actor,
                        e.action,
                        e.target or "",
                        e.detail or "",
                        json.dumps(e.context, default=str),
                        json.dumps(e.metadata, default=str),
                    ]
                ).lower()
                if search.lower() not in haystack:
                    continue
            out.append(e)
        out.sort(key=lambda e: e.timestamp, reverse=newest_first)
        return out[offset : offset + limit]

    def count(
        self,
        *,
        kind: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        risk_level: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        success: bool | None = None,
    ) -> int:
        return len(
            self.query(
                kind=kind,
                actor=actor,
                action=action,
                risk_level=risk_level,
                since=since,
                until=until,
                success=success,
                limit=10_000_000,
            )
        )

    # ------------------------------------------------------------------
    # Replay + maintenance
    # ------------------------------------------------------------------

    def replay(self, event_id: str) -> dict[str, Any] | None:
        """Return a dict of inputs needed to re-run the recorded action.

        The dict has ``action``, ``args`` (from ``metadata``), and
        ``context``.  The caller is responsible for actually invoking
        the action — the audit log never re-executes anything.
        """
        e = self.get(event_id)
        if e is None:
            return None
        return {
            "event_id": e.id,
            "kind": _enum_value(e.kind),
            "action": e.action,
            "target": e.target,
            "args": dict(e.metadata),
            "context": dict(e.context),
            "timestamp": e.timestamp.isoformat(),
        }

    def all(self) -> list[AuditEvent]:
        self._ensure_loaded()
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Drop the in-memory cache and the JSONL file.  Use with care."""
        with self._lock:
            self._events = []
            self._loaded = True
            if self._path.exists():
                self._path.unlink()

    def rotate(self) -> Path:
        """Move the JSONL to ``<name>.<utc-timestamp>.log`` and start fresh."""
        with self._lock:
            if not self._path.exists():
                return self._path
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = self._path.with_name(f"{self._path.stem}.{ts}{self._path.suffix}")
            self._path.rename(target)
            self._events = []
            self._loaded = True
            return target

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            count = len(self._events)
            oldest = self._events[0].timestamp if self._events else None
            newest = self._events[-1].timestamp if self._events else None
            by_kind: dict[str, int] = {}
            by_risk: dict[str, int] = {}
            failures = 0
            for e in self._events:
                k = _enum_value(e.kind)
                by_kind[k] = by_kind.get(k, 0) + 1
                r = _enum_value(e.risk_level)
                by_risk[r] = by_risk.get(r, 0) + 1
                if not e.success:
                    failures += 1
        return {
            "path": str(self._path),
            "event_count": count,
            "oldest": oldest.isoformat() if oldest else None,
            "newest": newest.isoformat() if newest else None,
            "by_kind": by_kind,
            "by_risk_level": by_risk,
            "failures": failures,
            "size_bytes": self._path.stat().st_size if self._path.exists() else 0,
        }


# -- process singleton --------------------------------------------------------


_DEFAULT_LOG: AuditLog | None = None
_DEFAULT_LOCK = threading.RLock()


def get_audit_log() -> AuditLog:
    """Return the process-singleton :class:`AuditLog`.

    Constructed lazily on first call.  Tests that need a
    fresh instance should call :func:`reset_default_audit_log`
    between cases.
    """
    global _DEFAULT_LOG
    with _DEFAULT_LOCK:
        if _DEFAULT_LOG is None:
            _DEFAULT_LOG = AuditLog()
        return _DEFAULT_LOG


def set_default_audit_log(log: AuditLog | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_LOG
    with _DEFAULT_LOCK:
        _DEFAULT_LOG = log


def reset_default_audit_log() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_LOG
    with _DEFAULT_LOCK:
        _DEFAULT_LOG = None


__all__ = [
    "AuditLog",
    "DEFAULT_PATH",
    "HELIX_KV_PREFIX",
    "get_audit_log",
    "reset_default_audit_log",
    "set_default_audit_log",
]
