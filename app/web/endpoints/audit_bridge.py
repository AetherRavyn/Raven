"""Audit dashboard bridge — mounts the existing audit router.

The full audit router is defined in :mod:`app.core.audit.api`
and exposes 9 endpoints (events, stats, timeline, export,
approvals, health).  None of them are mounted in the
``app.web.server`` app today; v32 mounts them so the audit
section of the dashboard (LOG page) can link to the timeline
and the CSV export.

This bridge keeps the server wiring small: one
``include_router`` call, fed by the global action logger and
a NoOp policy engine stub (the live policy engine is a
singleton that the dashboard does not need to depend on).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


def _noop_policy_engine() -> Any:
    """Build a tiny stand-in ``PolicyEngine`` for the audit router.

    The audit endpoints that touch the policy engine
    (``/api/audit/approvals/pending`` and
    ``/api/audit/approvals/{id}/resolve``) raise ``503`` if
    the engine is ``None``; we want a real but minimal
    engine so those endpoints return ``200`` with an empty
    pending list during normal dashboard renders.

    The live ``app.core.policy_v2.engine.PolicyEngine`` is
    the right choice when it is available; the stub is a
    belt-and-braces fallback for tests.
    """
    try:
        from app.core.policy_v2 import PolicyEngine  # noqa: PLC0415
        return PolicyEngine()
    except Exception as exc:  # noqa: BLE001
        logger.debug("PolicyEngine unavailable for audit bridge: %s", exc)

    class _NoOpPolicyEngine:  # pragma: no cover - defensive
        def pending_approvals(self) -> list:
            return []

        def resolve_approval(self, *args: Any, **kwargs: Any) -> Any:
            raise KeyError("no_op_engine")

    return _NoOpPolicyEngine()


def mount_audit(app: Any) -> None:
    """Mount the audit router on ``app``.

    Builds a fresh :class:`AuditLog` so the audit endpoints
    always have a working backend (the singleton is exposed
    via :func:`app.core.audit.log.get_audit_log` but not
    re-exported through the package ``__init__``).  The
    policy engine is the global one if present, else a NoOp
    stub.  Wrapped in a try/except so a misconfigured audit
    subsystem never blocks the dashboard from coming up.
    """
    try:
        from app.core.audit import AuditLog  # noqa: PLC0415
        from app.core.audit.api import build_router  # noqa: PLC0415

        audit_log = AuditLog()
        engine = _noop_policy_engine()
        router = build_router(audit_log=audit_log, policy_engine=engine)
        app.include_router(router)
        logger.info("audit dashboard router mounted (9 endpoints)")
    except Exception as exc:  # noqa: BLE001
        logger.debug("audit router mount skipped: %s", exc)


if TYPE_CHECKING:
    pass
