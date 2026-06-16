"""HTTP dashboard API for the audit log (A4 completion).

This module exposes a small FastAPI ``APIRouter`` covering the
plan-v3 deliverables:

- ``GET  /api/audit/events``       — query events with filters
- ``GET  /api/audit/stats``        — counts by kind / risk / success
- ``GET  /api/audit/timeline``     — human-readable text table
- ``GET  /api/audit/export.csv``   — CSV export
- ``GET  /api/audit/export.json``  — JSON export
- ``GET  /api/audit/approvals/pending``
- ``POST /api/audit/approvals/{id}/resolve``

The router is wired via :func:`build_router` which accepts an
:class:`AuditLog` and an :class:`PolicyEngine`.  This keeps the
endpoints testable with FastAPI's ``TestClient`` and lets the
existing :mod:`app.web.server` mount the routes without taking
on a hard dependency on either component.

If FastAPI isn't installed at import time the module still
imports; :func:`build_router` raises a clear :class:`ImportError`
when called.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI
    from app.core.audit import AuditLog
    from app.core.policy_v2 import PolicyEngine

logger = logging.getLogger(__name__)


def build_router(
    audit_log: "AuditLog | None" = None,
    policy_engine: "PolicyEngine | None" = None,
    *,
    default_export_limit: int = 5000,
) -> "APIRouter":
    """Construct the audit-dashboard APIRouter.

    ``audit_log`` and ``policy_engine`` are optional so the router
    can be mounted before those subsystems are available (the
    endpoints that don't need them still work; the others
    503 gracefully).
    """
    try:
        from fastapi import APIRouter, HTTPException, Query
        from fastapi.responses import JSONResponse, PlainTextResponse
    except ImportError as e:  # pragma: no cover - guarded
        raise ImportError(f"FastAPI is required to build the audit API router: {e}") from e

    from app.core.audit.dashboard import (
        compute_stats,
        format_csv,
        format_json,
        format_timeline,
    )

    router = APIRouter(prefix="/api/audit", tags=["audit"])

    def _log() -> "AuditLog | None":
        return audit_log

    def _engine() -> "PolicyEngine | None":
        return policy_engine

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _coerce_iso(since: str | None = None, until: str | None = None) -> tuple[Any, Any]:
        """Coerce ISO-8601 strings to datetime for AuditLog.query()."""
        from datetime import datetime

        def _p(v: str | None) -> Any:
            if v is None:
                return None
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return None

        return _p(since), _p(until)

    @router.get("/events")
    def list_events(
        kind: str | None = Query(None, description="Filter by AuditKind value"),
        actor: str | None = Query(None),
        action: str | None = Query(None),
        target: str | None = Query(None),
        success: bool | None = Query(None),
        risk_level: str | None = Query(None, description="Filter by risk level"),
        since: str | None = Query(None, description="ISO-8601 lower bound"),
        until: str | None = Query(None, description="ISO-8601 upper bound"),
        search: str | None = Query(None, description="Substring in detail"),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        newest_first: bool = Query(True),
    ) -> dict[str, Any]:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        since_dt, until_dt = _coerce_iso(since, until)
        events = log.query(
            kind=kind,
            actor=actor,
            action=action,
            target=target,
            success=success,
            risk_level=risk_level,
            since=since_dt,
            until=until_dt,
            search=search,
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )
        return {
            "count": len(events),
            "limit": limit,
            "offset": offset,
            "events": [ev.to_dict() for ev in events],
        }

    @router.get("/events/{event_id}")
    def get_event(event_id: str) -> dict[str, Any]:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        for ev in log.query(limit=10_000):
            if ev.id == event_id:
                return ev.to_dict()
        raise HTTPException(404, f"event not found: {event_id}")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @router.get("/stats")
    def get_stats(
        since: str | None = Query(None),
        until: str | None = Query(None),
    ) -> dict[str, Any]:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        events = log.query(limit=10_000)
        stats = compute_stats(events, since=since, until=until)
        return stats.to_dict()

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    @router.get("/timeline", response_class=PlainTextResponse)
    def get_timeline(
        limit: int = Query(50, le=500),
        kind: str | None = Query(None),
        actor: str | None = Query(None),
    ) -> str:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        events = log.query(kind=kind, actor=actor, limit=limit)
        text = format_timeline(events, max_rows=limit)
        if not text:
            return "(no events matched)\n"
        return text + "\n"

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @router.get("/export.csv", response_class=PlainTextResponse)
    def export_csv(
        since: str | None = Query(None),
        until: str | None = Query(None),
        kind: str | None = Query(None),
    ) -> str:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        events = log.query(kind=kind, limit=default_export_limit)
        if since or until:
            # Reuse the time-bounded aggregation path.  The stats
            # builder already filters, so we can lean on it.
            events = list(events)  # materialize
            # Apply bounds by re-running the query helper directly
            from app.core.audit.dashboard import _coerce_ts

            s = _coerce_ts(since)
            u = _coerce_ts(until)
            events = [
                ev
                for ev in events
                if (s is None or ev.timestamp >= s) and (u is None or ev.timestamp <= u)
            ]
        return format_csv(events)

    @router.get("/export.json")
    def export_json(
        since: str | None = Query(None),
        until: str | None = Query(None),
    ) -> JSONResponse:
        log = _log()
        if log is None:
            raise HTTPException(503, "audit log not available")
        events = log.query(limit=default_export_limit)
        from app.core.audit.dashboard import _coerce_ts

        s = _coerce_ts(since)
        u = _coerce_ts(until)
        if s or u:
            events = [
                ev
                for ev in events
                if (s is None or ev.timestamp >= s) and (u is None or ev.timestamp <= u)
            ]
        return JSONResponse(json.loads(format_json(events)))

    # ------------------------------------------------------------------
    # Approvals queue
    # ------------------------------------------------------------------

    @router.get("/approvals/pending")
    def list_pending_approvals() -> dict[str, Any]:
        engine = _engine()
        if engine is None:
            raise HTTPException(503, "policy engine not available")
        pending = engine.pending_approvals()
        return {
            "count": len(pending),
            "approvals": [a.to_dict() for a in pending],
        }

    @router.post("/approvals/{approval_id}/resolve")
    def resolve_approval(
        approval_id: str,
        approved: bool = Query(...),
        resolved_by: str = Query(...),
        note: str | None = Query(None),
    ) -> dict[str, Any]:
        engine = _engine()
        if engine is None:
            raise HTTPException(503, "policy engine not available")
        try:
            approval = engine.resolve_approval(
                approval_id,
                approved=approved,
                resolved_by=resolved_by,
                note=note,
            )
        except KeyError:
            raise HTTPException(404, f"approval not found: {approval_id}")
        # Echo the audit event so the dashboard updates without a refetch
        log = _log()
        if log is not None:
            from app.core.audit import AuditEvent, AuditKind, RiskLevel

            log.record(
                AuditEvent(
                    kind=AuditKind.APPROVAL,
                    actor=resolved_by,
                    action=(approval.request.action if approval.request else "approval"),
                    target=approval_id,
                    success=approved,
                    detail=f"{'approved' if approved else 'denied'}: {note or ''}",
                    risk_level=(RiskLevel.MEDIUM if approved else RiskLevel.HIGH),
                    metadata={"approval_id": approval_id},
                )
            )
        return approval.to_dict()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @router.get("/health")
    def audit_health() -> dict[str, Any]:
        log = _log()
        engine = _engine()
        if log is None:
            return {"ok": False, "reason": "audit log not configured"}
        try:
            health = log.health()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"audit log error: {e}"}
        health["ok"] = True
        health["policy_v2"] = engine is not None
        return health

    return router


def mount(
    app: "FastAPI",
    audit_log: "AuditLog | None" = None,
    policy_engine: "PolicyEngine | None" = None,
) -> None:
    """Convenience: build the router and attach it to ``app``."""
    router = build_router(audit_log=audit_log, policy_engine=policy_engine)
    app.include_router(router)


__all__ = ["build_router", "mount"]
