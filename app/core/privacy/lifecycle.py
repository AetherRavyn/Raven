"""Phase F2 — Privacy: Data Lifecycle.

Export, hard-delete, and per-data-class retention.  This is
the "forget me" + "give me my data" surface the user
controls from settings.

Design
------

* :class:`LifecycleManager.export_all(user_id)` returns a
  JSON-serialisable archive of everything the agent knows
  about the user: consent ledger, retention records, and
  whatever other stores the runtime wires in via
  :meth:`register_provider`.
* :class:`LifecycleManager.delete_user(user_id)` is the
  GDPR "right to be forgotten" — wipes the consent ledger,
  retention records, and calls every registered provider's
  ``delete_user`` method.
* :class:`LifecycleManager.access_audit(user_id)` returns a
  record of who read or wrote each :class:`DataClass`.

Providers are pluggable so the memory store, knowledge
graph, and any future backing service can participate
without this module knowing their internals.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.privacy.consent import ConsentStore, DataClass
from app.core.privacy.retention import RetentionManager


# -- provider protocol --------------------------------------------------------

ExportProvider = Callable[[str], dict[str, Any]]
"""Signature: ``provider(user_id) -> {section: payload, ...}``.

The payload is merged into the export archive under the
section name (e.g. ``"memory"``, ``"kg"``).  Returning an
empty dict is fine — the section will be present but empty.
"""

DeleteProvider = Callable[[str], dict[str, int]]
"""Signature: ``provider(user_id) -> {section: count_deleted, ...}``.

The counts are reported in the :class:`DeleteResult`.  The
function should be idempotent and never raise.
"""


# -- data model ---------------------------------------------------------------


@dataclass(slots=True)
class ExportArchive:
    """Single-file export of everything the agent knows about a user."""

    user_id: str
    exported_at: datetime
    consent: list[dict[str, Any]] = field(default_factory=list)
    retention: list[dict[str, Any]] = field(default_factory=list)
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "exported_at": self.exported_at.isoformat(),
            "consent": self.consent,
            "retention": self.retention,
            "sections": self.sections,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportArchive":
        return cls(
            user_id=data["user_id"],
            exported_at=datetime.fromisoformat(data["exported_at"]),
            consent=list(data.get("consent", [])),
            retention=list(data.get("retention", [])),
            sections=dict(data.get("sections", {})),
        )


@dataclass(slots=True)
class DeleteResult:
    """Outcome of a hard-delete operation."""

    user_id: str
    deleted_at: datetime
    consent_cleared: int = 0
    retention_cleared: int = 0
    provider_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_deleted(self) -> int:
        return self.consent_cleared + self.retention_cleared + sum(self.provider_counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "deleted_at": self.deleted_at.isoformat(),
            "consent_cleared": self.consent_cleared,
            "retention_cleared": self.retention_cleared,
            "provider_counts": dict(self.provider_counts),
            "total_deleted": self.total_deleted,
        }


@dataclass(slots=True)
class AccessAuditEntry:
    """One row in the access audit trail."""

    user_id: str
    data_class: DataClass | str
    actor: str
    action: str  # "read" | "write" | "delete" | "export"
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "data_class": (
                self.data_class.value if isinstance(self.data_class, DataClass) else self.data_class
            ),
            "actor": self.actor,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


# -- manager ------------------------------------------------------------------


class LifecycleManager:
    """Public facade for export / delete / audit access."""

    def __init__(
        self,
        *,
        consent: ConsentStore | None = None,
        retention: RetentionManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._consent = consent or ConsentStore()
        self._retention = retention or RetentionManager()
        self._export_providers: dict[str, ExportProvider] = {}
        self._delete_providers: dict[str, DeleteProvider] = {}
        self._access_log: list[AccessAuditEntry] = []

    # -- provider registration -------------------------------------------

    def register_export_provider(self, name: str, provider: ExportProvider) -> None:
        """Wire in a new data source for exports."""
        with self._lock:
            self._export_providers[name] = provider

    def register_delete_provider(self, name: str, provider: DeleteProvider) -> None:
        """Wire in a new data source for hard-deletes."""
        with self._lock:
            self._delete_providers[name] = provider

    def unregister(self, name: str) -> None:
        """Remove a provider by name.  Both kinds."""
        with self._lock:
            self._export_providers.pop(name, None)
            self._delete_providers.pop(name, None)

    def export_providers(self) -> list[str]:
        """Names of every registered export provider."""
        with self._lock:
            return list(self._export_providers)

    def delete_providers(self) -> list[str]:
        """Names of every registered delete provider."""
        with self._lock:
            return list(self._delete_providers)

    # -- export ----------------------------------------------------------

    def export_all(self, user_id: str, *, actor: str = "user") -> ExportArchive:
        """Build a complete export archive for ``user_id``."""
        with self._lock:
            archive = ExportArchive(
                user_id=user_id,
                exported_at=datetime.now(timezone.utc),
                consent=[_consent_to_dict(c) for c in self._consent.all_for_user(user_id)],
                retention=[_retention_to_dict(r) for r in self._retention.list_for_user(user_id)],
            )
            for name, provider in self._export_providers.items():
                try:
                    archive.sections[name] = provider(user_id)
                except Exception as exc:  # noqa: BLE001
                    archive.sections[name] = {"error": str(exc)}
            self._record(
                user_id=user_id,
                data_class=DataClass.PROFILE,
                actor=actor,
                action="export",
                metadata={"sections": list(archive.sections)},
            )
        return archive

    # -- delete ----------------------------------------------------------

    def delete_user(self, user_id: str, *, actor: str = "user") -> DeleteResult:
        """Hard-delete everything for ``user_id``.

        Wipes the consent ledger, retention records, and asks
        every registered delete provider to do the same.
        Returns a per-section count of what was deleted.
        """
        with self._lock:
            result = DeleteResult(
                user_id=user_id,
                deleted_at=datetime.now(timezone.utc),
            )
            # Consent (hard-delete for GDPR forget-me)
            for c in list(self._consent.all_for_user(user_id)):
                self._consent.remove(c.user_id, c.data_class)
                result.consent_cleared += 1
            # Retention
            for r in list(self._retention.list_for_user(user_id)):
                self._retention.cancel(r.record_id)
                result.retention_cleared += 1
            # Providers
            for name, provider in self._delete_providers.items():
                try:
                    counts = provider(user_id)
                except Exception as exc:  # noqa: BLE001
                    counts = {"error": -1}
                    self._record(
                        user_id=user_id,
                        data_class=DataClass.PROFILE,
                        actor=actor,
                        action="delete",
                        metadata={"provider": name, "error": str(exc)},
                    )
                for section, count in counts.items():
                    if isinstance(count, int) and count >= 0:
                        result.provider_counts[f"{name}.{section}"] = count
            self._record(
                user_id=user_id,
                data_class=DataClass.PROFILE,
                actor=actor,
                action="delete",
                metadata={"total": result.total_deleted},
            )
        return result

    # -- access audit ----------------------------------------------------

    def record_access(
        self,
        *,
        user_id: str,
        data_class: DataClass | str,
        actor: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a row to the access audit trail."""
        self._record(
            user_id=user_id,
            data_class=data_class,
            actor=actor,
            action=action,
            metadata=metadata or {},
        )

    def access_log(
        self,
        *,
        user_id: str | None = None,
        data_class: DataClass | str | None = None,
    ) -> list[AccessAuditEntry]:
        """Return the audit trail, optionally filtered."""
        with self._lock:
            entries = list(self._access_log)
        if user_id is not None:
            entries = [e for e in entries if e.user_id == user_id]
        if data_class is not None:
            entries = [e for e in entries if e.data_class == data_class]
        return entries

    def _record(
        self,
        *,
        user_id: str,
        data_class: DataClass | str,
        actor: str,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        entry = AccessAuditEntry(
            user_id=user_id,
            data_class=data_class,
            actor=actor,
            action=action,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )
        with self._lock:
            self._access_log.append(entry)

    def reset(self) -> None:
        """Drop the access log.  Tests only."""
        with self._lock:
            self._access_log.clear()


# -- helpers ------------------------------------------------------------------


def _consent_to_dict(c: Any) -> dict[str, Any]:
    return {
        "user_id": c.user_id,
        "data_class": c.data_class.value,
        "level": c.level.value,
        "granted_at": c.granted_at.isoformat() if c.granted_at else None,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "metadata": dict(c.metadata),
    }


def _retention_to_dict(r: Any) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "data_class": r.data_class.value,
        "user_id": r.user_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "retention_until": (r.retention_until.isoformat() if r.retention_until else None),
        "metadata": dict(r.metadata),
    }


# -- module-level singleton helpers --------------------------------------------


_DEFAULT_MANAGER: LifecycleManager | None = None
_LOCK = threading.RLock()


def get_default_lifecycle_manager() -> LifecycleManager:
    """Return the process-singleton :class:`LifecycleManager`."""
    global _DEFAULT_MANAGER
    with _LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = LifecycleManager()
        return _DEFAULT_MANAGER


def set_default_lifecycle_manager(manager: LifecycleManager | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = manager


def reset_default_lifecycle_manager() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = None


__all__ = [
    "AccessAuditEntry",
    "DeleteProvider",
    "DeleteResult",
    "ExportArchive",
    "ExportProvider",
    "LifecycleManager",
    "get_default_lifecycle_manager",
    "reset_default_lifecycle_manager",
    "set_default_lifecycle_manager",
]

# Keep `field` and `Iterable` import-visible for type-checkers.
_ = (field, Iterable)
