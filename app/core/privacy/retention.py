"""Retention policy + purge scheduler.

A record the runtime wants to keep around has a
:class:`PurgeRecord` in the manager.  The manager walks
its records on every :meth:`purge_due` call and removes
the ones whose ``retention_until`` has passed.  The
actual deletion is delegated to a ``purger`` callable
that the runtime injects — the manager doesn't know how
to delete from the underlying store, only when.

A typical setup:

  * Default TTL: 90 days for everything
  * Override per :class:`DataClass` (e.g. credentials = 30
    days, conversation = 365 days)
  * On ``consent.revoke`` the runtime calls
    :meth:`mark_for_purge` to schedule the record for
    immediate deletion

The manager is in-memory; the runtime persists purge
records via the same HelixDB snapshot pattern as
continuity.  That keeps the architecture uniform.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.privacy.consent import ConsentStore, DataClass

logger = logging.getLogger(__name__)


# A purger is a callable that takes a record_id and a
# data class and deletes the underlying record.  The
# runtime injects the actual delete-from-HelixDB logic.
Purger = Callable[[str, DataClass], None]


@dataclass(slots=True)
class PurgeRecord:
    """A single record scheduled for retention-based deletion."""

    record_id: str
    data_class: DataClass
    user_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retention_until: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_due(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        if self.retention_until is None:
            return False
        return moment >= self.retention_until

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "data_class": self.data_class.value,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "retention_until": (self.retention_until.isoformat() if self.retention_until else None),
            "metadata": dict(self.metadata),
        }


# -------------------------------------------------------------------
# policy
# -------------------------------------------------------------------


@dataclass(slots=True)
class RetentionPolicy:
    """TTL configuration."""

    # Default retention period.  Used when the data class
    # isn't in ``by_class`` and the record didn't supply
    # a custom retention_until.
    default_ttl: timedelta = field(default_factory=lambda: timedelta(days=90))
    # Per-class overrides.  Anything not listed uses default_ttl.
    by_class: dict[DataClass, timedelta] = field(default_factory=dict)
    # Classes that should NEVER be auto-purged (e.g. credentials
    # that the runtime still needs at boot).
    exempt: set[DataClass] = field(default_factory=set)

    def ttl_for(self, data_class: DataClass) -> timedelta:
        return self.by_class.get(data_class, self.default_ttl)

    def compute_until(
        self,
        data_class: DataClass,
        *,
        created_at: datetime | None = None,
    ) -> datetime | None:
        if data_class in self.exempt:
            return None
        moment = created_at or datetime.now(timezone.utc)
        return moment + self.ttl_for(data_class)


# -------------------------------------------------------------------
# manager
# -------------------------------------------------------------------


class RetentionManager:
    """Track purge records and run scheduled deletions."""

    def __init__(
        self,
        *,
        policy: RetentionPolicy | None = None,
        purger: Purger | None = None,
        consent_store: ConsentStore | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._policy = policy or RetentionPolicy()
        self._purger = purger
        self._consent_store = consent_store
        self._records: dict[str, PurgeRecord] = {}

    # ---- configuration ----

    def set_purger(self, purger: Purger) -> None:
        self._purger = purger

    def set_policy(self, policy: RetentionPolicy) -> None:
        with self._lock:
            self._policy = policy

    # ---- records ----

    def mark_for_purge(
        self,
        record_id: str,
        data_class: DataClass,
        user_id: str,
        *,
        retention_until: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PurgeRecord:
        """Schedule a record for deletion.

        If ``retention_until`` is None, the manager uses the
        policy's TTL for the data class.
        """
        if retention_until is None:
            retention_until = self._policy.compute_until(data_class)
        record = PurgeRecord(
            record_id=record_id,
            data_class=data_class,
            user_id=user_id,
            retention_until=retention_until,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[record_id] = record
        logger.info(
            "retention.mark record=%s class=%s user=%s until=%s",
            record_id,
            data_class.value,
            user_id,
            retention_until.isoformat() if retention_until else "never",
        )
        return record

    def cancel(self, record_id: str) -> bool:
        with self._lock:
            return self._records.pop(record_id, None) is not None

    def get(self, record_id: str) -> PurgeRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def list_due(self, *, now: datetime | None = None) -> list[PurgeRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.is_due(now=now)]

    def list_for_user(self, user_id: str) -> list[PurgeRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.user_id == user_id]

    def list_for_class(self, data_class: DataClass) -> list[PurgeRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.data_class == data_class]

    def clear_user(self, user_id: str) -> int:
        with self._lock:
            to_drop = [k for k, r in self._records.items() if r.user_id == user_id]
            for k in to_drop:
                del self._records[k]
            return len(to_drop)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    # ---- purge execution ----

    def purge_due(self, *, now: datetime | None = None) -> list[str]:
        """Run a purge pass.  Returns the list of purged record ids."""
        if self._purger is None:
            raise RuntimeError("no purger configured — call set_purger() first")
        with self._lock:
            due = [r for r in self._records.values() if r.is_due(now=now)]
        purged: list[str] = []
        for record in due:
            try:
                self._purger(record.record_id, record.data_class)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "purger raised for record=%s: %s",
                    record.record_id,
                    exc,
                )
                continue
            with self._lock:
                self._records.pop(record.record_id, None)
            purged.append(record.record_id)
            logger.info(
                "retention.purged record=%s class=%s user=%s",
                record.record_id,
                record.data_class.value,
                record.user_id,
            )
        return purged

    def purge_user(
        self,
        user_id: str,
        *,
        reason: str = "user-request",
    ) -> list[str]:
        """Force-purge every record for a user.  GDPR-style delete."""
        if self._purger is None:
            raise RuntimeError("no purger configured — call set_purger() first")
        with self._lock:
            owned = [r for r in self._records.values() if r.user_id == user_id]
        purged: list[str] = []
        for record in owned:
            try:
                self._purger(record.record_id, record.data_class)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "purger raised for record=%s: %s",
                    record.record_id,
                    exc,
                )
                continue
            with self._lock:
                self._records.pop(record.record_id, None)
            purged.append(record.record_id)
        if self._consent_store is not None:
            self._consent_store.clear_user(user_id)
        logger.info(
            "retention.purge_user user=%s count=%d reason=%s",
            user_id,
            len(purged),
            reason,
        )
        return purged

    # ---- diagnostics ----

    def explain(self) -> dict[str, Any]:
        with self._lock:
            by_class: dict[str, int] = {}
            for r in self._records.values():
                by_class[r.data_class.value] = by_class.get(r.data_class.value, 0) + 1
            return {
                "total": len(self._records),
                "by_class": by_class,
                "default_ttl_days": self._policy.default_ttl.days,
                "exempt": sorted(c.value for c in self._policy.exempt),
            }
