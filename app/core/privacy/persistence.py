"""HelixDB persistence for the privacy ledger (Day 25).

The :class:`ConsentStore` and :class:`RetentionManager` are
in-memory by design — fast reads from
:meth:`PrivacyManager.check_tool`, no network round-trips
on the hot path.  But in-memory state is lost on restart,
which is unacceptable for a privacy ledger: a user who
revoked consent for ``location`` data yesterday should
not be re-prompted today.

This module adds a :class:`HelixPrivacyStore` that:

* wraps the in-memory ``ConsentStore`` + ``RetentionManager``
* persists every mutation to HelixDB as a node
* loads existing records on startup
* falls back to in-memory only if HelixDB is unavailable
  (offline mode — a warning is logged, the in-memory
  ledger still works for the current process lifetime)

The :class:`PrivacyManager` is unchanged — it continues to
read from the in-memory stores.  The persistence layer is
a write-through cache: mutations are applied to the
in-memory store first, then mirrored to HelixDB.  If the
write fails, the in-memory state is still consistent
(``HelixPrivacyStore`` logs and continues).

The schema is intentionally flat: two node labels
(``PrivacyConsent``, ``PrivacyPurge``) with no edges.  The
natural key for consents is ``(user_id, data_class)``; the
natural key for purges is ``record_id``.  Both are encoded
into the node ``id`` property for fast scan-by-id.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.privacy.consent import Consent, ConsentLevel, ConsentStore, DataClass
from app.core.privacy.retention import PurgeRecord, RetentionManager

logger = logging.getLogger(__name__)


# HelixDB node labels.
_CONSENT_LABEL = "PrivacyConsent"
_PURGE_LABEL = "PrivacyPurge"

#: Prefix for consent node ids.  Full id format:
#: ``"consent:{user_id}:{data_class.value}"``.
_CONSENT_ID_PREFIX = "consent:"

#: Prefix for purge node ids.  Full id format:
#: ``"purge:{record_id}"``.
_PURGE_ID_PREFIX = "purge:"


def _consent_id(user_id: str, data_class: DataClass) -> str:
    return f"{_CONSENT_ID_PREFIX}{user_id}:{data_class.value}"


def _purge_id(record_id: str) -> str:
    return f"{_PURGE_ID_PREFIX}{record_id}"


def _parse_consent_id(node_id: str) -> tuple[str, DataClass] | None:
    """Reverse :func:`_consent_id` — returns ``(user_id, DataClass)`` or None."""
    if not node_id.startswith(_CONSENT_ID_PREFIX):
        return None
    suffix = node_id[len(_CONSENT_ID_PREFIX) :]
    if ":" not in suffix:
        return None
    user_id, _, class_name = suffix.partition(":")
    if not user_id or not class_name:
        return None
    try:
        return user_id, DataClass(class_name)
    except ValueError:
        return None


def _parse_purge_id(node_id: str) -> str | None:
    """Reverse :func:`_purge_id` — returns the record_id or None."""
    if not node_id.startswith(_PURGE_ID_PREFIX):
        return None
    return node_id[len(_PURGE_ID_PREFIX) :]


def _consent_props(consent: Consent) -> dict[str, Any]:
    return {
        "id": _consent_id(consent.user_id, consent.data_class),
        "user_id": consent.user_id,
        "data_class": consent.data_class.value,
        "level": consent.level.value,
        "granted_at": consent.granted_at.isoformat(),
        "expires_at": consent.expires_at.isoformat() if consent.expires_at else None,
        "revoked_at": consent.metadata.get("revoked_at"),
        "metadata": _to_json_str(dict(consent.metadata)),
    }


def _purge_props(record: PurgeRecord) -> dict[str, Any]:
    return {
        "id": _purge_id(record.record_id),
        "record_id": record.record_id,
        "data_class": record.data_class.value,
        "user_id": record.user_id,
        "retention_until": (
            record.retention_until.isoformat() if record.retention_until else None
        ),
        "created_at": record.created_at.isoformat(),
        "metadata": _to_json_str(dict(record.metadata)),
    }


def _to_json_str(value: Any) -> str:
    """JSON-encode a value for storage in a HelixDB string property."""
    import json

    return json.dumps(value, default=str, sort_keys=True)


def _from_json_str(value: str | None) -> Any:
    """Decode a HelixDB string property back to a Python object."""
    import json

    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _consent_from_node(node: dict[str, Any]) -> Consent | None:
    """Build a :class:`Consent` from a HelixDB node dict."""
    user_id = node.get("user_id")
    class_name = node.get("data_class")
    level = node.get("level")
    if not (user_id and class_name and level):
        return None
    try:
        data_class = DataClass(class_name)
        consent_level = ConsentLevel(level)
    except ValueError:
        return None

    granted_at_raw = node.get("granted_at")
    granted_at = (
        datetime.fromisoformat(granted_at_raw) if granted_at_raw
        else datetime.now(timezone.utc)
    )
    expires_at_raw = node.get("expires_at")
    expires_at = (
        datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
    )
    metadata = _from_json_str(node.get("metadata"))
    revoked_at = node.get("revoked_at")
    if revoked_at and "revoked_at" not in metadata:
        metadata["revoked_at"] = revoked_at

    return Consent(
        user_id=user_id,
        data_class=data_class,
        level=consent_level,
        granted_at=granted_at,
        expires_at=expires_at,
        metadata=metadata,
    )


def _purge_from_node(node: dict[str, Any]) -> PurgeRecord | None:
    """Build a :class:`PurgeRecord` from a HelixDB node dict."""
    record_id = node.get("record_id")
    class_name = node.get("data_class")
    user_id = node.get("user_id")
    if not (record_id and class_name and user_id):
        return None
    try:
        data_class = DataClass(class_name)
    except ValueError:
        return None

    retention_until_raw = node.get("retention_until")
    retention_until = (
        datetime.fromisoformat(retention_until_raw) if retention_until_raw else None
    )
    created_at_raw = node.get("created_at")
    created_at = (
        datetime.fromisoformat(created_at_raw) if created_at_raw
        else datetime.now(timezone.utc)
    )
    metadata = _from_json_str(node.get("metadata"))

    return PurgeRecord(
        record_id=record_id,
        data_class=data_class,
        user_id=user_id,
        retention_until=retention_until,
        created_at=created_at,
        metadata=metadata,
    )


class HelixPrivacyStore:
    """Write-through HelixDB persistence for the privacy ledger.

    Wraps a :class:`ConsentStore` and a :class:`RetentionManager`
    and mirrors every mutation to HelixDB.  Reads are served
    from the in-memory stores (fast).  Loads happen on
    :meth:`initialize`.

    Parameters
    ----------
    client:
        A :class:`app.db.helix.HelixClient` instance.  May be
        ``None`` for tests; in that case all persistence
        operations are no-ops.
    consent_store, retention_manager:
        The in-memory stores to mirror.

    All async methods are safe to call even when HelixDB is
    unreachable — they return ``False`` and log a warning
    rather than raising.  Callers should treat the return
    value as "best-effort, do not retry".
    """

    def __init__(
        self,
        client: Any,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        self._client = client
        self._consent = consent_store
        self._retention = retention_manager
        self._lock = threading.RLock()
        self._available = False
        # Counters
        self.persisted_consent = 0
        self.persisted_purge = 0
        self.deleted_consent = 0
        self.deleted_purge = 0
        self.failed_writes = 0
        self.loaded_consent = 0
        self.loaded_purge = 0

    # -- availability -----------------------------------------------------

    async def initialize(self) -> bool:
        """Connect to HelixDB and load existing records.

        Returns ``True`` if HelixDB is reachable and the
        load succeeded.  On failure, the store stays in
        in-memory-only mode and the ledger still works for
        the current process lifetime.
        """
        if self._client is None:
            logger.info("HelixPrivacyStore: no client; in-memory only")
            return False
        try:
            available = await self._client.is_available()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HelixPrivacyStore: client probe failed: %s", exc)
            self._available = False
            return False
        if not available:
            logger.warning("HelixPrivacyStore: HelixDB unavailable; in-memory only")
            self._available = False
            return False

        consent_count, purge_count = await asyncio.gather(
            self._load_all_consents(),
            self._load_all_purges(),
            return_exceptions=False,
        )
        with self._lock:
            self._available = True
            self.loaded_consent = consent_count
            self.loaded_purge = purge_count
        logger.info(
            "HelixPrivacyStore online: loaded %d consent(s), %d purge(s)",
            consent_count,
            purge_count,
        )
        return True

    @property
    def available(self) -> bool:
        return self._available

    # -- high-level mutators (wrap in-memory + persist) -------------------

    async def grant_consent(
        self,
        user_id: str,
        data_class: DataClass,
        level: ConsentLevel,
        *,
        ttl: timedelta | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Consent:
        """Grant consent and persist.

        Updates the in-memory :class:`ConsentStore` first, then
        mirrors the resulting :class:`Consent` to HelixDB.
        """
        consent = self._consent.grant(
            user_id, data_class, level, ttl=ttl, metadata=metadata,
        )
        await self._write_consent(consent)
        return consent

    async def revoke_consent(
        self, user_id: str, data_class: DataClass
    ) -> bool:
        """Revoke consent and persist the updated record.

        The in-memory store updates the level in-place; we
        re-fetch and re-write the same node id so HelixDB
        sees the new level + ``revoked_at`` metadata.
        """
        ok = self._consent.revoke(user_id, data_class)
        if not ok:
            return False
        existing = self._consent.check(user_id, data_class)
        if existing is not None:
            await self._write_consent(existing)
        return True

    async def mark_for_purge(
        self,
        record_id: str,
        data_class: DataClass,
        user_id: str,
        *,
        retention_until: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PurgeRecord:
        """Schedule a record for purge and persist.

        Updates the in-memory :class:`RetentionManager` first,
        then mirrors the resulting :class:`PurgeRecord` to
        HelixDB.
        """
        record = self._retention.mark_for_purge(
            record_id, data_class, user_id,
            retention_until=retention_until, metadata=metadata,
        )
        await self._write_purge(record)
        return record

    async def cancel_purge(self, record_id: str) -> bool:
        """Cancel a scheduled purge and remove from HelixDB."""
        ok = self._retention.cancel(record_id)
        if not ok:
            return False
        await self._delete_purge(record_id)
        return True

    async def purge_user(self, user_id: str) -> bool:
        """GDPR-style "forget me": drop all consent + purge records
        for the user from in-memory and from HelixDB."""
        consents = list(self._consent.all_for_user(user_id))
        records = list(self._retention.list_for_user(user_id))
        # Wipe in-memory first.
        for c in consents:
            with self._lock:
                self._consent._records.pop((c.user_id, c.data_class), None)
        for r in records:
            with self._lock:
                self._retention._records.pop(r.record_id, None)
        # Drop from HelixDB.
        if not self._available:
            return True
        from app.db.helix import step_n_where_eq, write_query

        try:
            for c in consents:
                await self._client.execute(
                    write_query(
                        (
                            "d",
                            [
                                step_n_where_eq("id", _consent_id(c.user_id, c.data_class)),
                                "Drop",
                            ],
                        )
                    )
                )
            for r in records:
                await self._client.execute(
                    write_query(
                        (
                            "d",
                            [
                                step_n_where_eq("id", _purge_id(r.record_id)),
                                "Drop",
                            ],
                        )
                    )
                )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.failed_writes += 1
            logger.warning(
                "HelixPrivacyStore: purge_user(%s) failed: %s", user_id, exc,
            )
            return False
        return True

    # -- low-level writes -------------------------------------------------

    async def _write_consent(self, consent: Consent) -> bool:
        return await self._upsert(_CONSENT_LABEL, _consent_props(consent))

    async def _write_purge(self, record: PurgeRecord) -> bool:
        return await self._upsert(_PURGE_LABEL, _purge_props(record))

    async def _delete_purge(self, record_id: str) -> bool:
        if not self._available:
            return False
        from app.db.helix import step_n_where_eq, write_query

        env = write_query(
            (
                "d",
                [
                    step_n_where_eq("id", _purge_id(record_id)),
                    "Drop",
                ],
            )
        )
        try:
            await self._client.execute(env)
            with self._lock:
                self.deleted_purge += 1
            return True
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.failed_writes += 1
            logger.warning(
                "HelixPrivacyStore: delete_purge failed for %s: %s",
                record_id,
                exc,
            )
            return False

    async def _upsert(self, label: str, properties: dict[str, Any]) -> bool:
        """Delete-then-add upsert.

        HelixDB's :func:`AddN` is not idempotent on ``id``;
        to update an existing node we first drop by id, then
        add.  The window between drop and add is invisible
        to readers because the same id is re-created before
        the next read cycle.
        """
        if not self._available:
            return False
        from app.db.helix import step_add_n, step_n_where_eq, write_query

        node_id = properties.get("id")
        if not node_id:
            return False
        # Drop ``None`` properties — Helix's ``_literal`` cannot encode them.
        properties = {k: v for k, v in properties.items() if v is not None}
        try:
            # Delete any existing node with the same id.
            await self._client.execute(
                write_query(
                    (
                        "d",
                        [step_n_where_eq("id", node_id), "Drop"],
                    )
                )
            )
            # Add the new node.
            await self._client.execute(
                write_query(("m", [step_add_n(label, properties)]))
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.failed_writes += 1
            logger.warning(
                "HelixPrivacyStore: upsert failed for label=%s id=%s: %s",
                label,
                node_id,
                exc,
            )
            return False

        with self._lock:
            if label == _CONSENT_LABEL:
                self.persisted_consent += 1
            elif label == _PURGE_LABEL:
                self.persisted_purge += 1
        return True

    # -- low-level reads --------------------------------------------------

    async def _load_all_consents(self) -> int:
        if self._client is None:
            return 0
        from app.db.helix import read_query

        env = read_query(
            ("m", [{"N": {"Label": _CONSENT_LABEL}}]),  # type: ignore[list-item]
            returns=["m"],
        )
        try:
            result = await self._client.execute(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HelixPrivacyStore: load_all_consents failed: %s", exc)
            return 0
        nodes = self._extract_nodes(result)
        loaded = 0
        for node in nodes:
            consent = _consent_from_node(node)
            if consent is None:
                continue
            with self._lock:
                self._consent._records[  # type: ignore[attr-defined]
                    (consent.user_id, consent.data_class)
                ] = consent
            loaded += 1
        return loaded

    async def _load_all_purges(self) -> int:
        if self._client is None:
            return 0
        from app.db.helix import read_query

        env = read_query(
            ("m", [{"N": {"Label": _PURGE_LABEL}}]),  # type: ignore[list-item]
            returns=["m"],
        )
        try:
            result = await self._client.execute(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HelixPrivacyStore: load_all_purges failed: %s", exc)
            return 0
        nodes = self._extract_nodes(result)
        loaded = 0
        for node in nodes:
            record = _purge_from_node(node)
            if record is None:
                continue
            with self._lock:
                self._retention._records[  # type: ignore[attr-defined]
                    record.record_id
                ] = record
            loaded += 1
        return loaded

    @staticmethod
    def _extract_nodes(result: Any) -> list[dict[str, Any]]:
        """Pull a list of node dicts out of a HelixQueryResult."""
        if result is None:
            return []
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return []
        # HelixDB returns results in a few shapes depending on
        # the query.  The scan query typically returns a list
        # under "m" or a single object; normalise both.
        for key in ("m", "result", "data"):
            payload = data.get(key)
            if isinstance(payload, list):
                return [n for n in payload if isinstance(n, dict)]
            if isinstance(payload, dict):
                return [payload]
        # Last resort: scan the top-level dict for any list value.
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        return []

    # -- diagnostics ------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self._available,
                "persisted_consent": self.persisted_consent,
                "persisted_purge": self.persisted_purge,
                "deleted_purge": self.deleted_purge,
                "failed_writes": self.failed_writes,
                "loaded_consent": self.loaded_consent,
                "loaded_purge": self.loaded_purge,
            }


# -- module-level singleton --------------------------------------------------

_store: HelixPrivacyStore | None = None
_store_lock = threading.Lock()


def get_default_privacy_store() -> HelixPrivacyStore | None:
    """Return the process-wide :class:`HelixPrivacyStore` if wired."""
    return _store


def set_default_privacy_store(store: HelixPrivacyStore | None) -> None:
    """Set or clear the process-wide persistence store (mainly for tests)."""
    global _store
    with _store_lock:
        _store = store


def reset_default_privacy_store() -> None:
    set_default_privacy_store(None)


__all__ = [
    "HelixPrivacyStore",
    "get_default_privacy_store",
    "reset_default_privacy_store",
    "set_default_privacy_store",
]
