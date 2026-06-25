"""Per-user data API — Phase 5.6.

A standalone FastAPI router exposing:

- ``GET  /api/user/{user_id}/export`` — full export archive as JSON.
- ``DELETE /api/user/{user_id}`` — hard-delete (GDPR forget-me).
- ``GET  /api/user/{user_id}/audit`` — paginated audit events for a user.

The router is built lazily so the rest of the codebase can import
this module without pulling in FastAPI at module-load time.  Call
:func:`build_user_data_router` and mount it on the main app:

    from app.core.user_data_endpoints import build_user_data_router
    app.include_router(build_user_data_router(), prefix="")
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

logger = logging.getLogger(__name__)


# FastAPI is optional; we only fail if someone actually mounts the router.
try:
    from fastapi import APIRouter, HTTPException, Query  # type: ignore
    from fastapi.responses import JSONResponse  # type: ignore
    _HAVE_FASTAPI = True
except Exception as exc:  # noqa: BLE001
    _HAVE_FASTAPI = False
    # Stubs so module-level imports don't blow up.
    APIRouter = None  # type: ignore
    HTTPException = None  # type: ignore
    Query = None  # type: ignore
    JSONResponse = None  # type: ignore


def build_user_data_router() -> Any:
    """Return a configured FastAPI router.  Raises if FastAPI is missing."""
    if not _HAVE_FASTAPI:
        raise RuntimeError(
            "FastAPI is not installed; cannot build user-data router"
        )

    router = APIRouter(tags=["user-data"])

    @router.get("/api/user/{user_id}/export")
    async def export_user_endpoint(user_id: str) -> JSONResponse:
        """Return the full export archive for ``user_id`` as JSON."""
        from app.core.privacy.user_data_provider import export_user

        try:
            archive = export_user(user_id, actor="api")
        except Exception as exc:  # noqa: BLE001
            logger.exception("user export failed for %s", user_id)
            raise HTTPException(
                status_code=500,
                detail=f"export failed: {exc}",
            ) from exc
        return JSONResponse(archive)

    @router.delete("/api/user/{user_id}")
    async def delete_user_endpoint(user_id: str) -> JSONResponse:
        """Hard-delete ``user_id`` everywhere.  Returns counts."""
        from app.core.privacy.user_data_provider import delete_user

        try:
            result = delete_user(user_id, actor="api")
        except Exception as exc:  # noqa: BLE001
            logger.exception("user delete failed for %s", user_id)
            raise HTTPException(
                status_code=500,
                detail=f"delete failed: {exc}",
            ) from exc
        return JSONResponse(result)

    @router.get("/api/user/{user_id}/audit")
    async def user_audit_endpoint(
        user_id: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Return audit events for ``user_id`` (newest first)."""
        from app.core.privacy.user_data_provider import audit_export

        payload = audit_export(user_id, limit=limit)
        # payload is {events: [...], count: N}; trim by offset/limit
        events = (payload.get("events") or [])[offset : offset + limit]
        return JSONResponse({
            "user_id": user_id,
            "count": len(events),
            "total": payload.get("count", 0),
            "events": events,
        })

    # Phase 5.3 — generic audit search endpoint (mirrors the CLI).
    @router.get("/api/audit/search")
    async def audit_search(
        kind: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        target: str | None = None,
        risk: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
        failed_only: bool = False,
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Search the audit log with structured filters.

        All filters are optional.  ``since`` and ``until`` accept
        ISO-8601 timestamps; relative durations like ``1h`` are not
        supported here (use the CLI for that).
        """
        from datetime import datetime, timezone as _tz
        from app.core.audit.log import get_audit_log

        def _to_dt(s: str | None):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt

        try:
            log = get_audit_log()
            events = log.query(
                kind=kind,
                actor=actor,
                action=action,
                target=target,
                risk_level=risk,
                search=search,
                since=_to_dt(since),
                until=_to_dt(until),
                success=False if failed_only else None,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("audit search failed")
            raise HTTPException(
                status_code=500, detail=f"audit search failed: {exc}"
            ) from exc

        rows = [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "kind": e.kind.value if hasattr(e.kind, "value") else e.kind,
                "actor": e.actor,
                "action": e.action,
                "target": e.target,
                "risk": (
                    e.risk_level.value
                    if hasattr(e.risk_level, "value")
                    else e.risk_level
                ),
                "success": e.success,
            }
            for e in events
        ]
        return JSONResponse({"count": len(rows), "events": rows})

    return router


__all__ = ["build_user_data_router"]


if TYPE_CHECKING:  # pragma: no cover
    from fastapi import APIRouter as _ARouter  # noqa: F401
