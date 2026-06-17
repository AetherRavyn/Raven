"""Phase F2 — Privacy: Zones.

Per-:class:`DataClass` privacy policy: which data stays on
the local device, which gets synced to the cloud, and whether
it must be encrypted at rest.

Design
------

* A :class:`ZonePolicy` says: "data of class X is allowed in
  zones Y, must be encrypted, and has TTL Z days."
* A :class:`ZoneRegistry` stores the policies.  Sensible
  defaults are provided out of the box.
* A :class:`ZoneManager` is the public facade.

The :class:`Zone` enum is intentionally small — three values:

  * :attr:`Zone.LOCAL_ONLY` — never leave the device
  * :attr:`Zone.CLOUD_SYNC` — allowed in cloud storage
  * :attr:`Zone.BOTH` — same as CLOUD_SYNC but explicitly
    mirrored to both

This module is policy-only.  Enforcement (actually blocking
writes to a forbidden store) is done by the runtime + the
privacy check in :mod:`app.core.privacy.orchestrator`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from app.core.privacy.consent import DataClass


class Zone(str, Enum):
    """Where a piece of data is allowed to live."""

    LOCAL_ONLY = "local_only"
    CLOUD_SYNC = "cloud_sync"
    BOTH = "both"


@dataclass(slots=True, frozen=True)
class ZonePolicy:
    """Privacy policy for a single :class:`DataClass`."""

    data_class: DataClass
    zone: Zone = Zone.LOCAL_ONLY
    encryption_required: bool = True
    retention_days: int = 90
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalise DataClass to enum (accepts string for callers).
        if isinstance(self.data_class, str):
            object.__setattr__(self, "data_class", DataClass(self.data_class))
        if isinstance(self.zone, str):
            object.__setattr__(self, "zone", Zone(self.zone))

    def allows_cloud(self) -> bool:
        """Return True if this policy permits cloud storage."""
        return self.zone in (Zone.CLOUD_SYNC, Zone.BOTH)

    def allows_local(self) -> bool:
        """Return True if this policy permits local storage."""
        return self.zone in (Zone.LOCAL_ONLY, Zone.BOTH)


# -- default policy table -----------------------------------------------------


_DEFAULT_POLICIES: dict[DataClass, ZonePolicy] = {
    DataClass.CONVERSATION: ZonePolicy(
        data_class=DataClass.CONVERSATION,
        zone=Zone.BOTH,
        encryption_required=True,
        retention_days=365,
    ),
    DataClass.LOCATION: ZonePolicy(
        data_class=DataClass.LOCATION,
        zone=Zone.LOCAL_ONLY,
        encryption_required=True,
        retention_days=30,
    ),
    DataClass.EMAIL: ZonePolicy(
        data_class=DataClass.EMAIL,
        zone=Zone.CLOUD_SYNC,
        encryption_required=True,
        retention_days=365,
    ),
    DataClass.CALENDAR: ZonePolicy(
        data_class=DataClass.CALENDAR,
        zone=Zone.CLOUD_SYNC,
        encryption_required=False,
        retention_days=730,
    ),
    DataClass.CONTACTS: ZonePolicy(
        data_class=DataClass.CONTACTS,
        zone=Zone.CLOUD_SYNC,
        encryption_required=True,
        retention_days=1825,  # 5 years
    ),
    DataClass.HEALTH: ZonePolicy(
        data_class=DataClass.HEALTH,
        zone=Zone.LOCAL_ONLY,
        encryption_required=True,
        retention_days=1825,
    ),
    DataClass.FINANCIAL: ZonePolicy(
        data_class=DataClass.FINANCIAL,
        zone=Zone.LOCAL_ONLY,
        encryption_required=True,
        retention_days=2555,  # 7 years (regulatory)
    ),
    DataClass.FILES: ZonePolicy(
        data_class=DataClass.FILES,
        zone=Zone.BOTH,
        encryption_required=False,
        retention_days=365,
    ),
    DataClass.CREDENTIALS: ZonePolicy(
        data_class=DataClass.CREDENTIALS,
        zone=Zone.LOCAL_ONLY,
        encryption_required=True,
        retention_days=90,
    ),
    DataClass.ANALYTICS: ZonePolicy(
        data_class=DataClass.ANALYTICS,
        zone=Zone.CLOUD_SYNC,
        encryption_required=False,
        retention_days=90,
    ),
    DataClass.PROFILE: ZonePolicy(
        data_class=DataClass.PROFILE,
        zone=Zone.BOTH,
        encryption_required=True,
        retention_days=1825,
    ),
}


# -- registry + manager -------------------------------------------------------


class ZoneRegistry:
    """Thread-safe map of :class:`DataClass` → :class:`ZonePolicy`."""

    def __init__(self, *, defaults: dict[DataClass, ZonePolicy] | None = None) -> None:
        self._lock = threading.RLock()
        self._policies: dict[DataClass, ZonePolicy] = dict(defaults or _DEFAULT_POLICIES)

    def get(self, data_class: DataClass | str) -> ZonePolicy:
        """Return the policy for ``data_class``, falling back to a safe default."""
        if isinstance(data_class, str):
            data_class = DataClass(data_class)
        with self._lock:
            if data_class in self._policies:
                return self._policies[data_class]
        # Default: local-only, encrypted, 90-day TTL.
        return ZonePolicy(
            data_class=data_class, zone=Zone.LOCAL_ONLY, encryption_required=True, retention_days=90
        )

    def set(self, policy: ZonePolicy) -> None:
        """Install a custom policy for a data class."""
        with self._lock:
            self._policies[policy.data_class] = policy

    def all(self) -> list[ZonePolicy]:
        """Return every registered policy."""
        with self._lock:
            return list(self._policies.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._policies)

    def reset(self) -> None:
        """Restore the built-in defaults.  Tests only."""
        with self._lock:
            self._policies = dict(_DEFAULT_POLICIES)


class ZoneManager:
    """Public facade for zone policies."""

    def __init__(self, *, registry: ZoneRegistry | None = None) -> None:
        self._lock = threading.RLock()
        self._registry = registry or ZoneRegistry()

    def get_policy(self, data_class: DataClass | str) -> ZonePolicy:
        """Return the zone policy for ``data_class``."""
        return self._registry.get(data_class)

    def set_policy(self, policy: ZonePolicy) -> None:
        """Install a custom zone policy."""
        self._registry.set(policy)

    def is_allowed(self, data_class: DataClass | str, zone: Zone | str) -> bool:
        """Return True if ``data_class`` may be stored in ``zone``."""
        policy = self.get_policy(data_class)
        if isinstance(zone, str):
            zone = Zone(zone)
        if zone is Zone.LOCAL_ONLY:
            return policy.allows_local()
        return policy.allows_cloud()

    def requires_encryption(self, data_class: DataClass | str) -> bool:
        """Return True if writes to ``data_class`` must be encrypted."""
        return self.get_policy(data_class).encryption_required

    def retention_days(self, data_class: DataClass | str) -> int:
        """Return the TTL (in days) for ``data_class``."""
        return self.get_policy(data_class).retention_days

    def all_policies(self) -> list[ZonePolicy]:
        """Return every registered policy."""
        return self._registry.all()

    def reset(self) -> None:
        """Restore built-in defaults.  Tests only."""
        self._registry.reset()


# -- module-level singleton helpers --------------------------------------------


_DEFAULT_MANAGER: ZoneManager | None = None
_LOCK = threading.RLock()


def get_default_zone_manager() -> ZoneManager:
    """Return the process-singleton :class:`ZoneManager`."""
    global _DEFAULT_MANAGER
    with _LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = ZoneManager()
        return _DEFAULT_MANAGER


def set_default_zone_manager(manager: ZoneManager | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = manager


def reset_default_zone_manager() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = None


__all__ = [
    "Zone",
    "ZoneManager",
    "ZonePolicy",
    "ZoneRegistry",
    "get_default_zone_manager",
    "reset_default_zone_manager",
    "set_default_zone_manager",
]
