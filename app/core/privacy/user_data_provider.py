"""Built-in user-data export / delete providers — Phase 5.6.

Wires the existing :class:`LifecycleManager` to the data stores that
actually know about per-user data.  These are registered at
import-time via :func:`register_default_providers` and used by the
HTTP endpoints in :mod:`app.web.server` (and any CLI front-end).

The providers are deliberately **conservative**:

- :func:`memory_export` reads from the simple ``MemoryStore`` if it's
  available; otherwise returns an empty dict.
- :func:`memory_delete` removes user-keyed facts and never touches
  global facts.
- :func:`identity_export` / :func:`identity_delete` operate on the
  SQLite-backed :class:`UserIdentityStore`.
- :func:`audit_export` reads the audit log via the envelope bridge.

The memory store is best-effort: we never raise from a provider,
so a missing store (e.g. in CI) doesn't break export.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.core.privacy.lifecycle import (
    DeleteProvider,
    ExportProvider,
    LifecycleManager,
    get_default_lifecycle_manager,
)

logger = logging.getLogger(__name__)


# ── Memory providers ────────────────────────────────────────────────


def memory_export(user_id: str) -> dict[str, Any]:
    """Return facts the memory store has for ``user_id``.

    Returns ``{"facts": [...], "count": N, "error": ...}``.  Never raises.
    """
    try:
        from app.core.memory import MemoryStore  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"facts": [], "count": 0, "error": f"memory store unavailable: {exc}"}
    try:
        store = MemoryStore()
        # The store interface varies; fall back to a generic search.
        facts: list[dict[str, Any]] = []
        if hasattr(store, "list_for_user"):
            facts = list(store.list_for_user(user_id))  # type: ignore[attr-defined]
        elif hasattr(store, "all"):
            facts = [f for f in store.all() if getattr(f, "user_id", None) == user_id]  # type: ignore[attr-defined]
        return {"facts": facts, "count": len(facts)}
    except Exception as exc:  # noqa: BLE001
        return {"facts": [], "count": 0, "error": str(exc)}


def memory_delete(user_id: str) -> dict[str, int]:
    """Delete every fact owned by ``user_id`` from the memory store.

    Returns ``{"facts": N}`` with the number of facts removed.
    Never raises — a missing store is treated as 0 deletions.
    """
    try:
        from app.core.memory import MemoryStore  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_delete: store unavailable: %s", exc)
        return {"facts": 0}
    try:
        store = MemoryStore()
        removed = 0
        if hasattr(store, "delete_for_user"):
            removed = int(store.delete_for_user(user_id))  # type: ignore[attr-defined]
        return {"facts": removed}
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_delete: %s", exc)
        return {"facts": 0}


# ── Identity providers ──────────────────────────────────────────────


def _identity_db_path() -> str:
    try:
        from app.settings.config import Config
        from pathlib import Path

        return str(Path(Config.MEMORY_ROOT) / "identity.sqlite")
    except Exception:  # noqa: BLE001
        return "workspace/memory/identity.sqlite"


def identity_export(user_id: str) -> dict[str, Any]:
    """Return identity links for ``user_id`` from the identity store."""
    db = _identity_db_path()
    out: dict[str, Any] = {"links": [], "canonical": None, "error": None}
    try:
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT platform, platform_user_id, canonical_id, display_name, linked_at "
                "FROM user_links WHERE canonical_id = ?",
                (user_id,),
            ).fetchall()
            out["links"] = [
                {
                    "platform": r[0],
                    "platform_user_id": r[1],
                    "canonical_id": r[2],
                    "display_name": r[3],
                    "linked_at": r[4],
                }
                for r in rows
            ]
            row = conn.execute(
                "SELECT canonical_id, primary_name, created_at, last_seen_at "
                "FROM canonical_users WHERE canonical_id = ?",
                (user_id,),
            ).fetchone()
            if row:
                out["canonical"] = {
                    "canonical_id": row[0],
                    "primary_name": row[1],
                    "created_at": row[2],
                    "last_seen_at": row[3],
                }
    except sqlite3.OperationalError as exc:
        out["error"] = f"identity store unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def identity_delete(user_id: str) -> dict[str, int]:
    """Delete identity rows for ``user_id``. Never raises."""
    db = _identity_db_path()
    removed = 0
    try:
        with sqlite3.connect(db) as conn:
            cur = conn.execute(
                "DELETE FROM user_links WHERE canonical_id = ?", (user_id,)
            )
            removed += cur.rowcount
            cur = conn.execute(
                "DELETE FROM canonical_users WHERE canonical_id = ?", (user_id,)
            )
            removed += cur.rowcount
            conn.commit()
    except sqlite3.OperationalError as exc:
        logger.debug("identity_delete: db unavailable: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("identity_delete: %s", exc)
    return {"rows": removed}


# ── Audit export ────────────────────────────────────────────────────


def audit_export(user_id: str, *, limit: int = 1000) -> dict[str, Any]:
    """Return audit events that mention ``user_id``.

    The audit log's query API is rich; we filter by ``actor`` and
    ``context.user_id`` because there is no first-class user index
    in the audit log.  Limit caps the result to keep exports fast.
    """
    try:
        from app.core.audit import get_audit_log
    except Exception as exc:  # noqa: BLE001
        return {"events": [], "count": 0, "error": f"audit log unavailable: {exc}"}
    try:
        log = get_audit_log()
        events = log.query(actor=user_id, limit=limit)
        # Also check context.user_id via a free-text search.
        events.extend(log.query(search=f'"user_id": "{user_id}"', limit=limit))
        seen_ids = set()
        unique: list[Any] = []
        for e in events:
            if e.id in seen_ids:
                continue
            seen_ids.add(e.id)
            unique.append(e.to_dict(redact=True))
        return {"events": unique, "count": len(unique)}
    except Exception as exc:  # noqa: BLE001
        return {"events": [], "count": 0, "error": str(exc)}


# ── Registration ────────────────────────────────────────────────────


def register_default_providers(
    manager: LifecycleManager | None = None,
) -> LifecycleManager:
    """Register the built-in export/delete providers on a manager.

    Idempotent — safe to call more than once.  Returns the manager.
    """
    mgr = manager or get_default_lifecycle_manager()
    mgr.register_export_provider("memory", memory_export)
    mgr.register_delete_provider("memory", memory_delete)
    mgr.register_export_provider("identity", identity_export)
    mgr.register_delete_provider("identity", identity_delete)
    mgr.register_export_provider("audit", audit_export)
    return mgr


# ── Convenience facade for HTTP/CLI ────────────────────────────────


def export_user(user_id: str, *, actor: str = "user") -> dict[str, Any]:
    """Build a full export archive for ``user_id`` as a dict."""
    mgr = register_default_providers()
    archive = mgr.export_all(user_id, actor=actor)
    return archive.to_dict()


def delete_user(user_id: str, *, actor: str = "user") -> dict[str, Any]:
    """Hard-delete ``user_id`` everywhere.  Returns counts."""
    mgr = register_default_providers()
    result = mgr.delete_user(user_id, actor=actor)
    return result.to_dict()


__all__ = [
    "memory_export",
    "memory_delete",
    "identity_export",
    "identity_delete",
    "audit_export",
    "register_default_providers",
    "export_user",
    "delete_user",
]