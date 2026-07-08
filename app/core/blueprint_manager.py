from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.blueprint_models import Blueprint

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS blueprints (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT 'community',
    tags TEXT NOT NULL DEFAULT '[]',
    yaml_content TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    installed_at TEXT NOT NULL,
    last_run_at TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    last_status TEXT NOT NULL DEFAULT 'never_run'
);

CREATE TABLE IF NOT EXISTS blueprint_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    steps_total INTEGER NOT NULL DEFAULT 0,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY (blueprint_name) REFERENCES blueprints(name)
);
"""


@dataclass(slots=True)
class BlueprintMetadata:
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    enabled: bool
    installed_at: str
    last_run_at: str | None
    run_count: int
    last_status: str


class BlueprintManager:
    def __init__(self, db_path: str | Path = "workspace/memory/blueprints.db") -> None:
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
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    def install(self, path_or_yaml: str | Path | dict) -> str:
        if isinstance(path_or_yaml, dict):
            blueprint = Blueprint._from_dict(path_or_yaml)
        else:
            blueprint = Blueprint.from_yaml(path_or_yaml)

        now = datetime.now(timezone.utc).isoformat()
        yaml_bytes = json.dumps(blueprint._to_dict())

        self._conn.execute(
            """
            INSERT OR REPLACE INTO blueprints
                (name, version, description, author, tags, yaml_content,
                 enabled, installed_at, last_run_at, run_count, last_status)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL, 0, 'never_run')
            """,
            (
                blueprint.name,
                blueprint.version,
                blueprint.description,
                blueprint.author,
                json.dumps(blueprint.tags),
                yaml_bytes,
                now,
            ),
        )
        self._conn.commit()
        logger.info("Installed blueprint '%s' v%s", blueprint.name, blueprint.version)
        return blueprint.name

    def uninstall(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM blueprints WHERE name = ?", (name,))
        self._conn.commit()
        removed = cur.rowcount > 0
        if removed:
            logger.info("Uninstalled blueprint '%s'", name)
        return removed

    def list_blueprints(self) -> list[BlueprintMetadata]:
        rows = self._conn.execute(
            "SELECT name, version, description, author, tags, enabled, "
            "installed_at, last_run_at, run_count, last_status "
            "FROM blueprints ORDER BY installed_at DESC"
        ).fetchall()
        result: list[BlueprintMetadata] = []
        for r in rows:
            tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else []
            result.append(
                BlueprintMetadata(
                    name=r["name"],
                    version=r["version"],
                    description=r["description"],
                    author=r["author"],
                    tags=tags,
                    enabled=bool(r["enabled"]),
                    installed_at=r["installed_at"],
                    last_run_at=r["last_run_at"],
                    run_count=r["run_count"],
                    last_status=r["last_status"],
                )
            )
        return result

    def get_blueprint(self, name: str) -> Blueprint | None:
        row = self._conn.execute(
            "SELECT yaml_content FROM blueprints WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        data: dict[str, Any] = json.loads(row["yaml_content"])
        return Blueprint._from_dict(data)

    def enable(self, name: str) -> bool:
        cur = self._conn.execute(
            "UPDATE blueprints SET enabled = 1 WHERE name = ?", (name,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def disable(self, name: str) -> bool:
        cur = self._conn.execute(
            "UPDATE blueprints SET enabled = 0 WHERE name = ?", (name,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_run_history(self, name: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, blueprint_name, started_at, finished_at, status, "
            "steps_total, steps_completed, error "
            "FROM blueprint_runs WHERE blueprint_name = ? "
            "ORDER BY id DESC LIMIT ?",
            (name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── internal helpers for the runner ─────────────────────────────────

    def _record_run_start(self, name: str, steps_total: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO blueprint_runs (blueprint_name, started_at, steps_total) "
            "VALUES (?, ?, ?)",
            (name, now, steps_total),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def _record_run_finish(
        self,
        run_id: int,
        name: str,
        status: str,
        steps_completed: int,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE blueprint_runs SET finished_at = ?, status = ?, "
            "steps_completed = ?, error = ? WHERE id = ?",
            (now, status, steps_completed, error, run_id),
        )
        self._conn.execute(
            "UPDATE blueprints SET last_run_at = ?, run_count = run_count + 1, "
            "last_status = ? WHERE name = ?",
            (now, status, name),
        )
        self._conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
