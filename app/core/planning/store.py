"""Persistence for plans, steps, and goals.

The store wraps a :class:`HelixClient`, an optional SQLite database
and a simple in-process dict cache.

Storage tiers (in priority order):
  1. **HelixDB** (production) — durable across hosts.
  2. **SQLite** (Phase 6.4) — append-only, survives process restart.
     Enabled when ``PLAN_STORE_SQLITE`` is set (default: enabled,
     ``workspace/plan_store.sqlite``).  Writes are append-only —
     updates never ``DELETE`` rows; they ``INSERT`` a new row with a
     monotonically-increasing ``version`` column so the most recent
     version of any plan / goal is the row with the highest version.
  3. **In-memory cache** (tests, fallback) — fast, ephemeral.

A plan survives a process restart because:
  - On every ``save()`` we ``INSERT`` into SQLite.
  - On first ``load()`` / ``list_plans()`` we hydrate the in-memory
    cache from SQLite (when configured) so subsequent reads are O(1).
  - Writes go to *all* configured tiers.  A failed tier is logged
    and skipped, never raised.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from app.core.planning.goal_tracker import Goal, GoalStatus
from app.core.planning.types import PlanStatus, TaskPlan

logger = logging.getLogger(__name__)


def _plan_to_node_props(plan: TaskPlan) -> dict[str, Any]:
    """Convert a TaskPlan into a flat dict for KV storage."""
    return {
        "id": plan.id,
        "goal": plan.goal,
        "user_id": plan.user_id or "",
        "status": plan.status.value,
        "cost_total": json.dumps(plan.cost_total),
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else "",
        "replan_count": plan.replan_count,
        "metadata": json.dumps(plan.metadata),
        "payload": json.dumps(plan.to_dict()),
    }


def _goal_to_node_props(goal: Goal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "user_id": goal.user_id or "",
        "status": goal.status.value,
        "deadline": goal.deadline.isoformat() if goal.deadline else "",
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
        "completed_at": goal.completed_at.isoformat() if goal.completed_at else "",
        "progress": goal.progress,
        "metadata": json.dumps(goal.metadata),
        "payload": json.dumps(goal.to_dict()),
    }


class PlanStore:
    """Persist plans and goals.  HelixDB + SQLite + in-memory tiers."""

    def __init__(
        self,
        helix: Any = None,
        # Phase 6.4 — optional SQLite backend.
        # Pass a path string to enable; pass ``None`` to disable.
        # The default ``":memory:"`` would mean SQLite-only-in-RAM.
        sqlite_path: str | os.PathLike[str] | None = None,
        # When True, load every existing plan / goal from SQLite on
        # first access.  Default True; tests can disable for speed.
        hydrate_on_init: bool = True,
    ) -> None:
        self._helix = helix  # may be None
        self._cache: dict[str, dict[str, Any]] = {}
        self._goals: dict[str, dict[str, Any]] = {}
        self._sqlite_path: Optional[Path] = (
            Path(sqlite_path) if sqlite_path else None
        )
        self._sqlite_lock = threading.RLock()
        self._sqlite_hydrated: bool = False
        if self._sqlite_path is not None:
            try:
                self._init_sqlite()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PlanStore: SQLite init failed (%s); falling back to "
                    "in-memory only", exc,
                )
                self._sqlite_path = None
        if hydrate_on_init and self._sqlite_path is not None:
            self._hydrate_from_sqlite()

    # ------------------------------------------------------------------
    # SQLite (Phase 6.4)
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        if self._sqlite_path is None:
            return
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_versions (
                    id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT,
                    created_at TEXT,
                    PRIMARY KEY (id, version)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_versions (
                    id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT,
                    created_at TEXT,
                    PRIMARY KEY (id, version)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plan_user "
                "ON plan_versions(user_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_goal_user "
                "ON goal_versions(user_id, status)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self._sqlite_path is None:
            raise RuntimeError("sqlite_path not configured")
        # check_same_thread=False lets us share the connection across
        # the asyncio event loop and helper threads; the lock above
        # serialises access.
        return sqlite3.connect(str(self._sqlite_path), check_same_thread=False)

    def _hydrate_from_sqlite(self) -> None:
        """Populate the in-memory cache from SQLite.

        For each id we keep the row with the highest version (the
        "current" snapshot).
        """
        with self._sqlite_lock:
            if self._sqlite_hydrated:
                return
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT id, version, payload, user_id, status "
                        "FROM plan_versions "
                        "WHERE (id, version) IN ("
                        "  SELECT id, MAX(version) FROM plan_versions GROUP BY id"
                        ")"
                    ).fetchall()
                    for r in rows:
                        props = self._row_to_plan_props(r)
                        self._cache[r[0]] = props
                    rows = conn.execute(
                        "SELECT id, version, payload, user_id, status "
                        "FROM goal_versions "
                        "WHERE (id, version) IN ("
                        "  SELECT id, MAX(version) FROM goal_versions GROUP BY id"
                        ")"
                    ).fetchall()
                    for r in rows:
                        props = self._row_to_goal_props(r)
                        self._goals[r[0]] = props
            except Exception as exc:  # noqa: BLE001
                logger.debug("PlanStore: SQLite hydrate failed: %s", exc)
            self._sqlite_hydrated = True

    def _row_to_plan_props(self, row: tuple) -> dict[str, Any]:
        # (id, version, payload, user_id, status)
        return {
            "id": row[0],
            "version": row[1],
            "payload": row[2],
            "user_id": row[3] or "",
            "status": row[4] or "",
        }

    def _row_to_goal_props(self, row: tuple) -> dict[str, Any]:
        return {
            "id": row[0],
            "version": row[1],
            "payload": row[2],
            "user_id": row[3] or "",
            "status": row[4] or "",
        }

    def _next_version(self, conn: sqlite3.Connection, table: str, id_: str) -> int:
        row = conn.execute(
            f"SELECT MAX(version) FROM {table} WHERE id = ?", (id_,)
        ).fetchone()
        return int(row[0] or 0) + 1

    def _save_to_sqlite(self, table: str, props: dict[str, Any]) -> None:
        if self._sqlite_path is None:
            return
        with self._sqlite_lock:
            try:
                with self._connect() as conn:
                    version = self._next_version(conn, table, props["id"])
                    conn.execute(
                        f"INSERT INTO {table} "
                        "(id, version, payload, user_id, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            props["id"],
                            version,
                            props["payload"],
                            props.get("user_id", ""),
                            props.get("status", ""),
                            props.get("created_at", ""),
                        ),
                    )
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("PlanStore: SQLite save (%s) failed: %s", table, exc)

    def _load_from_sqlite(self, table: str, id_: str) -> Optional[dict[str, Any]]:
        if self._sqlite_path is None:
            return None
        with self._sqlite_lock:
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        f"SELECT id, version, payload, user_id, status "
                        f"FROM {table} WHERE id = ? "
                        f"ORDER BY version DESC LIMIT 1",
                        (id_,),
                    ).fetchone()
                    if row is None:
                        return None
                    return (
                        self._row_to_plan_props(row)
                        if table == "plan_versions"
                        else self._row_to_goal_props(row)
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("PlanStore: SQLite load (%s) failed: %s", table, exc)
                return None

    def _list_from_sqlite(
        self,
        table: str,
        *,
        user_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self._sqlite_path is None:
            return []
        with self._sqlite_lock:
            try:
                sql = (
                    f"SELECT id, version, payload, user_id, status "
                    f"FROM {table} t "
                    f"WHERE version = (SELECT MAX(version) FROM {table} "
                    f"                  WHERE id = t.id) "
                )
                params: list[Any] = []
                if user_id:
                    sql += " AND user_id = ?"
                    params.append(user_id)
                if status:
                    sql += " AND status = ?"
                    params.append(status)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
                    return [
                        self._row_to_plan_props(r)
                        if table == "plan_versions"
                        else self._row_to_goal_props(r)
                        for r in rows
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.debug("PlanStore: SQLite list (%s) failed: %s", table, exc)
                return []

    @property
    def sqlite_path(self) -> Optional[Path]:
        """Path to the SQLite database, or ``None`` if disabled."""
        return self._sqlite_path

    @property
    def is_persistent(self) -> bool:
        """True if either HelixDB or SQLite is configured."""
        return self._helix is not None or self._sqlite_path is not None

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    async def save(self, plan: TaskPlan) -> None:
        props = _plan_to_node_props(plan)
        self._cache[plan.id] = props
        # SQLite tier (Phase 6.4) — append-only.
        self._save_to_sqlite("plan_versions", props)
        if self._helix is not None:
            try:
                # KV-style write — the Helix schema defines a Plan node + KV index.
                await self._helix.kv_set(f"plan:{plan.id}", props)
            except Exception as e:  # noqa: BLE001
                logger.warning("helix plan save failed: %s", e)

    async def load(self, plan_id: str) -> Optional[TaskPlan]:
        # Try cache first
        cached = self._cache.get(plan_id)
        if cached is None:
            # Phase 6.4 — fall back to SQLite when in-memory misses.
            cached = self._load_from_sqlite("plan_versions", plan_id)
            if cached is not None:
                self._cache[plan_id] = cached
        if cached is None and self._helix is not None:
            try:
                cached = await self._helix.kv_get(f"plan:{plan_id}")
                if cached is not None:
                    self._cache[plan_id] = cached
            except Exception as e:  # noqa: BLE001
                logger.warning("helix plan load failed: %s", e)
        if cached is None:
            return None
        payload = cached.get("payload")
        if not payload:
            return None
        try:
            return TaskPlan.from_dict(json.loads(payload))
        except Exception as e:  # noqa: BLE001
            logger.warning("plan parse failed for %s: %s", plan_id, e)
            return None

    async def list_plans(
        self,
        user_id: str | None = None,
        status: PlanStatus | None = None,
        limit: int = 50,
    ) -> list[TaskPlan]:
        # Phase 6.4 — when the in-memory cache is empty but SQLite
        # has data, hydrate first so list_plans works after a restart.
        if not self._cache and self._sqlite_path is not None:
            self._hydrate_from_sqlite()
        out: list[TaskPlan] = []
        for cached in list(self._cache.values()):
            if user_id and cached.get("user_id") != user_id:
                continue
            if status and cached.get("status") != status.value:
                continue
            try:
                out.append(TaskPlan.from_dict(json.loads(cached["payload"])))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda p: p.updated_at, reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    async def save_goal(self, goal: Goal) -> None:
        props = _goal_to_node_props(goal)
        self._goals[goal.id] = props
        # Phase 6.4 — SQLite tier.
        self._save_to_sqlite("goal_versions", props)
        if self._helix is not None:
            try:
                await self._helix.kv_set(f"goal:{goal.id}", props)
            except Exception as e:  # noqa: BLE001
                logger.warning("helix goal save failed: %s", e)

    async def load_goal(self, goal_id: str) -> Optional[Goal]:
        cached = self._goals.get(goal_id)
        if cached is None:
            cached = self._load_from_sqlite("goal_versions", goal_id)
            if cached is not None:
                self._goals[goal_id] = cached
        if cached is None and self._helix is not None:
            try:
                cached = await self._helix.kv_get(f"goal:{goal_id}")
                if cached is not None:
                    self._goals[goal_id] = cached
            except Exception as e:  # noqa: BLE001
                logger.warning("helix goal load failed: %s", e)
        if cached is None:
            return None
        try:
            return Goal.from_dict(json.loads(cached["payload"]))
        except Exception:  # noqa: BLE001
            return None

    async def list_goals(
        self,
        user_id: str | None = None,
        status: GoalStatus | None = None,
        limit: int = 50,
    ) -> list[Goal]:
        if not self._goals and self._sqlite_path is not None:
            self._hydrate_from_sqlite()
        out: list[Goal] = []
        for cached in list(self._goals.values()):
            if user_id and cached.get("user_id") != user_id:
                continue
            if status and cached.get("status") != status.value:
                continue
            try:
                out.append(Goal.from_dict(json.loads(cached["payload"])))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda g: g.updated_at, reverse=True)
        return out[:limit]


__all__ = ["PlanStore"]
