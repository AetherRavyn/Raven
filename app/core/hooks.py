from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HookHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(slots=True)
class HookEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class HookDispatcher:
    """Event-driven hook system for lifecycle and tool events."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {}

    def register(self, event_name: str, handler: HookHandler) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    async def dispatch(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return
        event_payload = payload or {}
        for handler in handlers:
            try:
                result = handler(event_payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.debug("Hook handler failed for %s: %s", event_name, exc)


# ── Outbound Webhook / Event Hooks System ──────────────────────────────


class HookEventType(str, Enum):
    TASK_COMPLETED = "task_completed"
    MEMORY_CONSOLIDATED = "memory_consolidated"
    PROVIDER_HEALTH_CHANGED = "provider_health_changed"
    AGENT_TASK_STARTED = "agent_task_started"
    AGENT_TASK_COMPLETED = "agent_task_completed"
    ERROR_CRITICAL = "error_critical"
    MEMORY_EXTRACTED = "memory_extracted"
    SKILL_CRYSTALLIZED = "skill_crystallized"
    SCHEDULER_TRIGGERED = "scheduler_triggered"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0


@dataclass
class EventHook:
    id: int = 0
    name: str = ""
    url: str = ""
    events: list[HookEventType] = field(default_factory=list)
    secret: str = ""
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DeliveryRecord:
    hook_id: int = 0
    event_type: str = ""
    payload: dict = field(default_factory=dict)
    status: str = "pending"
    attempt: int = 0
    last_error: str | None = None
    created_at: str = ""


_HOOKS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS event_hooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]',
    secret TEXT NOT NULL DEFAULT '',
    max_retries INTEGER NOT NULL DEFAULT 3,
    base_delay REAL NOT NULL DEFAULT 1.0,
    max_delay REAL NOT NULL DEFAULT 60.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    response_code INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (hook_id) REFERENCES event_hooks(id)
);
"""


class EventHookManager:
    """SQLite-backed outbound webhook / event hook manager.

    Persists registered hooks and delivery history to
    ``workspace/memory/hooks.db``.  Thread-safe via thread-local
    connections (same pattern as LearningStore).
    """

    def __init__(self, db_path: str | Path = "workspace/memory/hooks.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ── connection management ───────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_HOOKS_SCHEMA_SQL)
        self._conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        url: str,
        events: list[HookEventType],
        secret: str = "",
        retry_policy: RetryPolicy | None = None,
    ) -> EventHook:
        rp = retry_policy or RetryPolicy()
        now = datetime.now(timezone.utc).isoformat()
        events_json = json.dumps([e.value for e in events])
        cur = self._conn.execute(
            """
            INSERT INTO event_hooks (name, url, events, secret, max_retries, base_delay, max_delay, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (name, url, events_json, secret, rp.max_retries, rp.base_delay, rp.max_delay, now, now),
        )
        self._conn.commit()
        return self._row_to_hook(
            self._conn.execute(
                "SELECT * FROM event_hooks WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        )

    def unregister(self, hook_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM event_hooks WHERE id = ?", (hook_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def update(self, hook_id: int, **fields: Any) -> bool:
        allowed = {
            "name",
            "url",
            "events",
            "secret",
            "max_retries",
            "base_delay",
            "max_delay",
            "enabled",
        }
        updates: dict[str, Any] = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "events" in updates:
            updates["events"] = json.dumps(
                [e.value if isinstance(e, HookEventType) else e for e in updates["events"]]
            )
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [hook_id]
        cur = self._conn.execute(f"UPDATE event_hooks SET {set_clause} WHERE id = ?", values)
        self._conn.commit()
        return cur.rowcount > 0

    def list_hooks(self) -> list[EventHook]:
        rows = self._conn.execute("SELECT * FROM event_hooks ORDER BY created_at DESC").fetchall()
        return [self._row_to_hook(r) for r in rows]

    def get_hook(self, hook_id: int) -> EventHook | None:
        row = self._conn.execute("SELECT * FROM event_hooks WHERE id = ?", (hook_id,)).fetchone()
        return self._row_to_hook(row) if row else None

    # ── triggering / delivery ──────────────────────────────────────────

    def trigger(self, event_type: HookEventType | str, payload: dict[str, Any]) -> None:
        event_str = event_type.value if isinstance(event_type, HookEventType) else str(event_type)
        rows = self._conn.execute("SELECT * FROM event_hooks WHERE enabled = 1").fetchall()
        for row in rows:
            hook = self._row_to_hook(row)
            subscribed = [e.value for e in hook.events]
            if event_str in subscribed:
                self._schedule_delivery(hook, event_str, payload)

    def _schedule_delivery(self, hook: EventHook, event_type: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            loop.create_task(self._deliver(hook, event_type, payload))
        else:
            asyncio.ensure_future(self._deliver(hook, event_type, payload))

    async def _deliver(self, hook: EventHook, event_type: str, payload: dict[str, Any]) -> None:
        delivery_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        self._conn.execute(
            "INSERT INTO delivery_log (hook_id, event_type, payload, status, attempt, created_at) VALUES (?, ?, ?, 'pending', 0, ?)",
            (hook.id, event_type, payload_json, now),
        )
        self._conn.commit()
        log_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        body = json.dumps(payload, sort_keys=True)
        headers = {
            "Content-Type": "application/json",
            "X-Raven-Event": event_type,
            "X-Raven-Delivery-Id": delivery_id,
        }
        if hook.secret:
            signature = hmac.new(
                hook.secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Raven-Signature"] = signature

        last_error: str | None = None
        response_code: int | None = None
        max_retries = hook.retry_policy.max_retries
        base_delay = hook.retry_policy.base_delay
        max_delay = hook.retry_policy.max_delay

        for attempt in range(1, max_retries + 2):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(hook.url, content=body, headers=headers)
                    response_code = resp.status_code
                    if 200 <= resp.status_code < 300:
                        self._conn.execute(
                            "UPDATE delivery_log SET status = 'delivered', attempt = ?, response_code = ? WHERE id = ?",
                            (attempt, response_code, log_id),
                        )
                        self._conn.commit()
                        logger.info(
                            "Hook %d delivered %s to %s (attempt %d, status %d)",
                            hook.id,
                            event_type,
                            hook.url,
                            attempt,
                            response_code,
                        )
                        return
                    text = resp.text
                    last_error = f"HTTP {resp.status_code}: {text[:200]}"
            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)

            if attempt <= max_retries:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                self._conn.execute(
                    "UPDATE delivery_log SET status = 'retrying', attempt = ?, last_error = ?, response_code = ? WHERE id = ?",
                    (attempt, last_error, response_code, log_id),
                )
                self._conn.commit()
                logger.warning(
                    "Hook %d delivery attempt %d failed: %s — retrying in %.1fs",
                    hook.id,
                    attempt,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        self._conn.execute(
            "UPDATE delivery_log SET status = 'failed', attempt = ?, last_error = ?, response_code = ? WHERE id = ?",
            (max_retries + 1, last_error, response_code, log_id),
        )
        self._conn.commit()
        logger.error(
            "Hook %d delivery to %s failed after %d attempts: %s",
            hook.id,
            hook.url,
            max_retries + 1,
            last_error,
        )

    # ── history / stats ────────────────────────────────────────────────

    def get_delivery_history(
        self, hook_id: int | None = None, limit: int = 50
    ) -> list[DeliveryRecord]:
        if hook_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM delivery_log WHERE hook_id = ? ORDER BY created_at DESC LIMIT ?",
                (hook_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM delivery_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_delivery(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        total_hooks = self._conn.execute("SELECT COUNT(*) as c FROM event_hooks").fetchone()["c"]
        total_deliveries = self._conn.execute("SELECT COUNT(*) as c FROM delivery_log").fetchone()[
            "c"
        ]
        success_count = self._conn.execute(
            "SELECT COUNT(*) as c FROM delivery_log WHERE status = 'delivered'"
        ).fetchone()["c"]
        pending_retries = self._conn.execute(
            "SELECT COUNT(*) as c FROM delivery_log WHERE status = 'retrying'"
        ).fetchone()["c"]
        success_rate = (success_count / total_deliveries * 100) if total_deliveries > 0 else 0.0
        return {
            "total_hooks": total_hooks,
            "total_deliveries": total_deliveries,
            "success_rate": round(success_rate, 1),
            "pending_retries": pending_retries,
        }

    # ── internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _row_to_hook(row: sqlite3.Row) -> EventHook:
        events_list = json.loads(row["events"]) if isinstance(row["events"], str) else row["events"]
        return EventHook(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            events=[HookEventType(e) for e in events_list],
            secret=row["secret"],
            retry_policy=RetryPolicy(
                max_retries=row["max_retries"],
                base_delay=row["base_delay"],
                max_delay=row["max_delay"],
            ),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_delivery(row: sqlite3.Row) -> DeliveryRecord:
        return DeliveryRecord(
            hook_id=row["hook_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload"])
            if isinstance(row["payload"], str)
            else row["payload"],
            status=row["status"],
            attempt=row["attempt"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Singleton
_hook_manager: EventHookManager | None = None


def get_hook_manager(db_path: str | Path | None = None) -> EventHookManager:
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = EventHookManager(db_path or "workspace/memory/hooks.db")
    return _hook_manager
