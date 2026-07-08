from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HONCHO_API_URL = getenv("HONCHO_API_URL", "https://api.honcho.ai/v1")
HONCHO_API_KEY = getenv("HONCHO_API_KEY", "")
HONCHO_USER_ID = getenv("HONCHO_USER_ID", "default")
HONCHO_SESSION_ID = getenv("HONCHO_SESSION_ID", "default")

_SYNC_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_status (
    provider_name TEXT PRIMARY KEY,
    last_sync_at TEXT,
    last_error TEXT,
    pending_push INTEGER NOT NULL DEFAULT 0,
    pending_pull INTEGER NOT NULL DEFAULT 0,
    total_pushed INTEGER NOT NULL DEFAULT 0,
    total_pulled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    provider_name TEXT NOT NULL,
    local_record TEXT NOT NULL,
    remote_record TEXT NOT NULL,
    field TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution TEXT,
    created_at TEXT NOT NULL
);
"""

VALID_CATEGORIES = frozenset({"fact", "preference", "pattern", "correction", "episode"})

SYNC_DB_PATH_DEFAULT = "workspace/memory/memory_sync.db"


@dataclass
class MemoryRecord:
    id: str
    content: str
    category: str = "fact"
    confidence: float = 0.5
    created_at: str = ""
    updated_at: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{self.category}'. Must be one of {sorted(VALID_CATEGORIES)}"
            )
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dict")


@dataclass
class SyncStatus:
    last_sync_at: str | None = None
    pending_push: int = 0
    pending_pull: int = 0
    conflicts: int = 0
    last_error: str | None = None


@dataclass
class SyncConflict:
    id: str
    local_record: MemoryRecord
    remote_record: MemoryRecord
    field: str
    resolved: bool = False
    resolution: str | None = None


class MemorySyncProvider(ABC):
    @abstractmethod
    async def push(self, records: list[MemoryRecord]) -> int: ...

    @abstractmethod
    async def pull(self, since: str | None = None) -> list[MemoryRecord]: ...

    @abstractmethod
    async def sync(self) -> SyncStatus: ...

    @abstractmethod
    async def resolve_conflict(
        self, conflict: SyncConflict, strategy: str = "last_write_wins"
    ) -> MemoryRecord: ...

    async def close(self) -> None: ...


class HonchoMemorySync(MemorySyncProvider):
    def __init__(
        self,
        api_url: str = HONCHO_API_URL,
        api_key: str = HONCHO_API_KEY,
        user_id: str = HONCHO_USER_ID,
        session_id: str = HONCHO_SESSION_ID,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._user_id = user_id
        self._session_id = session_id
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def push(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0
        batch = []
        for r in records:
            batch.append(self._record_to_payload(r))
        try:
            resp = await self._client.post(
                f"/users/{self._user_id}/sessions/{self._session_id}/memories/batch",
                json={"memories": batch},
            )
            resp.raise_for_status()
            data = resp.json()
            return len(data.get("memories", data.get("ids", batch)))
        except httpx.HTTPStatusError as e:
            logger.error(
                "Honcho push failed (HTTP %s): %s", e.response.status_code, e.response.text
            )
            raise
        except httpx.RequestError as e:
            logger.error("Honcho push request failed: %s", e)
            raise

    async def pull(self, since: str | None = None) -> list[MemoryRecord]:
        params: dict[str, Any] = {}
        if since:
            params["since"] = since
        try:
            resp = await self._client.get(
                f"/users/{self._user_id}/sessions/{self._session_id}/memories",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("memories", data.get("items", []))
            return [self._payload_to_record(item) for item in items]
        except httpx.HTTPStatusError as e:
            logger.error(
                "Honcho pull failed (HTTP %s): %s", e.response.status_code, e.response.text
            )
            raise
        except httpx.RequestError as e:
            logger.error("Honcho pull request failed: %s", e)
            raise

    async def sync(self) -> SyncStatus:
        try:
            resp = await self._client.get(
                f"/users/{self._user_id}/sessions/{self._session_id}/memories/sync",
            )
            resp.raise_for_status()
            data = resp.json()
            return SyncStatus(
                last_sync_at=data.get("last_sync_at"),
                pending_push=data.get("pending_push", 0),
                pending_pull=data.get("pending_pull", 0),
                conflicts=data.get("conflicts", 0),
                last_error=data.get("last_error"),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Honcho sync status failed (HTTP %s): %s", e.response.status_code, e.response.text
            )
            return SyncStatus(last_error=f"HTTP {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            logger.error("Honcho sync status request failed: %s", e)
            return SyncStatus(last_error=str(e))

    async def resolve_conflict(
        self, conflict: SyncConflict, strategy: str = "last_write_wins"
    ) -> MemoryRecord:
        payload = {
            "conflict_id": conflict.id,
            "strategy": strategy,
        }
        try:
            resp = await self._client.post(
                f"/users/{self._user_id}/sessions/{self._session_id}/memories/resolve",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._payload_to_record(data)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Honcho resolve conflict failed (HTTP %s): %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except httpx.RequestError as e:
            logger.error("Honcho resolve conflict request failed: %s", e)
            raise

    async def close(self) -> None:
        await self._client.aclose()

    def _record_to_payload(self, record: MemoryRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "content": record.content,
            "category": record.category,
            "confidence": record.confidence,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "source": record.source,
            "metadata": record.metadata,
        }

    def _payload_to_record(self, payload: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(
            id=str(payload.get("id", "")),
            content=str(payload.get("content", "")),
            category=str(payload.get("category", "fact")),
            confidence=float(payload.get("confidence", 0.5)),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
            source=str(payload.get("source", "")),
            metadata=payload.get("metadata", {}),
        )

    @staticmethod
    def detect_conflicts(
        local_records: list[MemoryRecord],
        remote_records: list[MemoryRecord],
    ) -> list[SyncConflict]:
        conflicts: list[SyncConflict] = []
        local_map = {r.id: r for r in local_records}
        remote_map = {r.id: r for r in remote_records}
        common_ids = set(local_map) & set(remote_map)
        for rid in common_ids:
            lr = local_map[rid]
            rr = remote_map[rid]
            if lr.updated_at == rr.updated_at:
                continue
            for field_name in ("content", "category", "confidence"):
                lv = getattr(lr, field_name)
                rv = getattr(rr, field_name)
                if lv != rv:
                    conflicts.append(
                        SyncConflict(
                            id=f"{rid}_{field_name}",
                            local_record=lr,
                            remote_record=rr,
                            field=field_name,
                        )
                    )
        return conflicts


class MemorySyncManager:
    def __init__(
        self,
        providers: list[MemorySyncProvider] | None = None,
        sync_interval: int = 300,
        db_path: str | Path = SYNC_DB_PATH_DEFAULT,
    ) -> None:
        self._providers: dict[str, MemorySyncProvider] = {}
        self._sync_interval = sync_interval
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._init_db()
        if providers:
            for i, p in enumerate(providers):
                self._providers[f"provider_{i}"] = p

    # ── connection management ──────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_SYNC_DB_SCHEMA)
        self._conn.commit()

    # ── provider management ────────────────────────────────────────────

    def add_provider(self, name: str, provider: MemorySyncProvider) -> None:
        if name in self._providers:
            logger.warning("Overwriting existing provider '%s'", name)
        self._providers[name] = provider

    def remove_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    def get_providers(self) -> dict[str, MemorySyncProvider]:
        return dict(self._providers)

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            logger.warning("Sync loop already running")
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._sync_loop())
        logger.info("Memory sync loop started (interval=%ds)", self._sync_interval)

    async def stop(self) -> None:
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("Memory sync loop stopped")

    # ── sync loop ──────────────────────────────────────────────────────

    async def _sync_loop(self) -> None:
        while self._running:
            try:
                await self.sync_all()
            except Exception as e:
                logger.error("Sync cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(self._sync_interval)

    async def sync_all(self) -> list[SyncStatus]:
        results: list[SyncStatus] = []
        for name, provider in self._providers.items():
            try:
                status = await self._sync_provider(name, provider)
                results.append(status)
            except Exception as e:
                logger.error("Sync failed for provider '%s': %s", name, e)
                results.append(SyncStatus(last_error=str(e)))
        return results

    async def _sync_provider(self, name: str, provider: MemorySyncProvider) -> SyncStatus:
        now = datetime.now(timezone.utc).isoformat()
        row = self._get_status_row(name)
        since = row["last_sync_at"] if row else None

        remote_records = await provider.pull(since=since)
        self._update_pending(name, pending_pull=len(remote_records))

        local_records: list[MemoryRecord] = []
        conflicts = HonchoMemorySync.detect_conflicts(local_records, remote_records)

        for conflict in conflicts:
            self._store_conflict(name, conflict)

        local_to_push: list[MemoryRecord] = []
        pushed = 0
        if local_to_push:
            pushed = await provider.push(local_to_push)

        self._upsert_status(
            provider_name=name,
            last_sync_at=now,
            last_error=None,
            pending_push=0,
            pending_pull=0,
            total_pushed=pushed,
            total_pulled=len(remote_records),
        )

        return SyncStatus(
            last_sync_at=now,
            pending_push=0,
            pending_pull=0,
            conflicts=len(conflicts),
        )

    # ── conflict management ────────────────────────────────────────────

    def get_pending_conflicts(self) -> list[SyncConflict]:
        rows = self._conn.execute(
            "SELECT * FROM sync_conflicts WHERE resolved = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_conflict(r) for r in rows]

    def get_conflicts(self) -> list[SyncConflict]:
        rows = self._conn.execute(
            "SELECT * FROM sync_conflicts ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_conflict(r) for r in rows]

    async def resolve_conflict(self, conflict_id: str, strategy: str = "last_write_wins") -> bool:
        rows = self._conn.execute(
            "SELECT * FROM sync_conflicts WHERE id = ?", (conflict_id,)
        ).fetchall()
        if not rows:
            return False
        row = rows[0]
        conflict = self._row_to_conflict(row)
        provider = self._providers.get(row["provider_name"])
        if provider is None:
            logger.error(
                "Provider '%s' not found for conflict '%s'", row["provider_name"], conflict_id
            )
            return False
        try:
            await provider.resolve_conflict(conflict, strategy=strategy)
            self._conn.execute(
                "UPDATE sync_conflicts SET resolved = 1, resolution = ? WHERE id = ?",
                (strategy, conflict_id),
            )
            self._conn.commit()
            logger.info("Conflict '%s' resolved with strategy '%s'", conflict_id, strategy)
            return True
        except Exception as e:
            logger.error("Failed to resolve conflict '%s': %s", conflict_id, e)
            return False

    # ── status query ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, SyncStatus]:
        rows = self._conn.execute("SELECT * FROM sync_status").fetchall()
        result: dict[str, SyncStatus] = {}
        for r in rows:
            result[r["provider_name"]] = SyncStatus(
                last_sync_at=r["last_sync_at"],
                pending_push=r["pending_push"],
                pending_pull=r["pending_pull"],
                conflicts=self._count_conflicts(r["provider_name"]),
                last_error=r["last_error"],
            )
        for name in self._providers:
            if name not in result:
                result[name] = SyncStatus()
        return result

    # ── internal helpers ───────────────────────────────────────────────

    def _get_status_row(self, provider_name: str) -> dict[str, Any] | None:
        rows = self._conn.execute(
            "SELECT * FROM sync_status WHERE provider_name = ?", (provider_name,)
        ).fetchall()
        if not rows:
            return None
        return dict(rows[0])

    def _upsert_status(
        self,
        *,
        provider_name: str,
        last_sync_at: str,
        last_error: str | None,
        pending_push: int = 0,
        pending_pull: int = 0,
        total_pushed: int = 0,
        total_pulled: int = 0,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sync_status (provider_name, last_sync_at, last_error, pending_push, pending_pull, total_pushed, total_pulled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_name) DO UPDATE SET
                last_sync_at = excluded.last_sync_at,
                last_error = excluded.last_error,
                pending_push = excluded.pending_push,
                pending_pull = excluded.pending_pull,
                total_pushed = total_pushed + excluded.total_pushed,
                total_pulled = total_pulled + excluded.total_pulled
            """,
            (
                provider_name,
                last_sync_at,
                last_error,
                pending_push,
                pending_pull,
                total_pushed,
                total_pulled,
            ),
        )
        self._conn.commit()

    def _update_pending(
        self, provider_name: str, *, pending_push: int = 0, pending_pull: int = 0
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sync_status (provider_name, last_sync_at, last_error, pending_push, pending_pull, total_pushed, total_pulled)
            VALUES (?, ?, ?, ?, ?, 0, 0)
            ON CONFLICT(provider_name) DO UPDATE SET
                pending_push = pending_push + ?,
                pending_pull = pending_pull + ?
            """,
            (provider_name, None, None, pending_push, pending_pull, pending_push, pending_pull),
        )
        self._conn.commit()

    def _store_conflict(self, provider_name: str, conflict: SyncConflict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO sync_conflicts (id, provider_name, local_record, remote_record, field, resolved, resolution, created_at)
            VALUES (?, ?, ?, ?, ?, 0, NULL, ?)
            """,
            (
                conflict.id,
                provider_name,
                json.dumps(self._record_to_dict(conflict.local_record)),
                json.dumps(self._record_to_dict(conflict.remote_record)),
                conflict.field,
                now,
            ),
        )
        self._conn.commit()

    def _count_conflicts(self, provider_name: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM sync_conflicts WHERE provider_name = ? AND resolved = 0",
            (provider_name,),
        ).fetchone()
        return row["cnt"] if row else 0

    def _row_to_conflict(self, row: sqlite3.Row) -> SyncConflict:
        return SyncConflict(
            id=row["id"],
            local_record=self._dict_to_record(json.loads(row["local_record"])),
            remote_record=self._dict_to_record(json.loads(row["remote_record"])),
            field=row["field"],
            resolved=bool(row["resolved"]),
            resolution=row["resolution"],
        )

    @staticmethod
    def _record_to_dict(record: MemoryRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "content": record.content,
            "category": record.category,
            "confidence": record.confidence,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "source": record.source,
            "metadata": record.metadata,
        }

    @staticmethod
    def _dict_to_record(d: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(
            id=str(d.get("id", "")),
            content=str(d.get("content", "")),
            category=str(d.get("category", "fact")),
            confidence=float(d.get("confidence", 0.5)),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            source=str(d.get("source", "")),
            metadata=d.get("metadata", {}),
        )

    async def close(self) -> None:
        await self.stop()
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                await provider.close()
