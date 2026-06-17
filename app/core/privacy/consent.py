"""Per-user consent ledger.

A user has many small consents: "the agent may store my
email", "the agent may remember my location", "the agent
may share anonymised usage with the team".  Each consent
is keyed by (user, data_class) and has a level (deny /
ask / allow / auto-purge), a granted_at timestamp, and an
optional expires_at.

The store is the source of truth.  The runtime consults it
on every read / write of a sensitive data class.  When a
consent expires or is revoked, the retention manager is
notified so the data is purged.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# data classes
# -------------------------------------------------------------------


class DataClass(str, Enum):
    """A class of personal data the agent may handle.

    The list is intentionally short — extensions go through
    new enum members, not free-form strings, so the consent
    ledger can build indexes and reports.
    """

    CONVERSATION = "conversation"
    LOCATION = "location"
    EMAIL = "email"
    CALENDAR = "calendar"
    CONTACTS = "contacts"
    HEALTH = "health"
    FINANCIAL = "financial"
    FILES = "files"
    CREDENTIALS = "credentials"
    ANALYTICS = "analytics"
    PROFILE = "profile"


class ConsentLevel(str, Enum):
    """What the user has agreed to for a data class."""

    DENY = "deny"  # explicit no
    ASK = "ask"  # ask every time
    ALLOW = "allow"  # default: store
    AUTO_PURGE = "auto_purge"  # store, but auto-purge after ttl


# -------------------------------------------------------------------
# record
# -------------------------------------------------------------------


@dataclass(slots=True)
class Consent:
    """A single (user, data_class) consent record."""

    user_id: str
    data_class: DataClass
    level: ConsentLevel
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    # Free-form metadata: source ("onboarding", "settings menu"),
    # audit ticket id, scope ("in-session-only" | "across-sessions"), ...
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_active(self) -> bool:
        if self.level == ConsentLevel.DENY:
            return False
        return not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "data_class": self.data_class.value,
            "level": self.level.value,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": dict(self.metadata),
        }


# -------------------------------------------------------------------
# store
# -------------------------------------------------------------------


class ConsentStore:
    """Thread-safe in-memory consent ledger.

    Indexes: ``(user_id, data_class) → Consent``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, DataClass], Consent] = {}

    # ---- CRUD ----

    def grant(
        self,
        user_id: str,
        data_class: DataClass,
        level: ConsentLevel,
        *,
        ttl: timedelta | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Consent:
        expires_at: datetime | None = None
        if ttl is not None:
            expires_at = datetime.now(timezone.utc) + ttl
        record = Consent(
            user_id=user_id,
            data_class=data_class,
            level=level,
            expires_at=expires_at,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[(user_id, data_class)] = record
        logger.info(
            "consent.grant user=%s class=%s level=%s ttl=%s",
            user_id,
            data_class.value,
            level.value,
            ttl,
        )
        return record

    def revoke(self, user_id: str, data_class: DataClass) -> bool:
        with self._lock:
            existing = self._records.get((user_id, data_class))
            if existing is None:
                return False
            existing.level = ConsentLevel.DENY
            existing.metadata["revoked_at"] = datetime.now(timezone.utc).isoformat()
            return True

    def remove(self, user_id: str, data_class: DataClass) -> bool:
        """Hard-delete a consent record.  Used by GDPR "forget me"."""
        with self._lock:
            return self._records.pop((user_id, data_class), None) is not None

    def check(
        self,
        user_id: str,
        data_class: DataClass,
    ) -> Consent | None:
        with self._lock:
            return self._records.get((user_id, data_class))

    def all_for_user(self, user_id: str) -> list[Consent]:
        with self._lock:
            return [r for (uid, _), r in self._records.items() if uid == user_id]

    def all_for_class(self, data_class: DataClass) -> list[Consent]:
        with self._lock:
            return [r for (_, cls), r in self._records.items() if cls == data_class]

    # ---- bulk operations ----

    def list_expired(self, *, now: datetime | None = None) -> list[Consent]:
        with self._lock:
            return [r for r in self._records.values() if r.is_expired]

    def clear_user(self, user_id: str) -> int:
        with self._lock:
            to_drop = [k for k in self._records if k[0] == user_id]
            for k in to_drop:
                del self._records[k]
            return len(to_drop)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    # ---- diagnostics ----

    def summary(self) -> dict[str, Any]:
        with self._lock:
            by_level: dict[str, int] = {}
            by_class: dict[str, int] = {}
            for r in self._records.values():
                by_level[r.level.value] = by_level.get(r.level.value, 0) + 1
                by_class[r.data_class.value] = by_class.get(r.data_class.value, 0) + 1
            return {
                "total": len(self._records),
                "by_level": by_level,
                "by_class": by_class,
            }
