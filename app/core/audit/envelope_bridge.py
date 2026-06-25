"""Audit ↔ Envelope bridge — Phase 2.6.

The unified :class:`Envelope` is the transport format that crosses
process / sidecar boundaries. The internal :class:`AuditEvent` is
richer and lives only inside a single process. This module provides:

- :func:`audit_event_to_envelope` — wrap an :class:`AuditEvent` inside
  an :class:`Envelope` for cross-process emission.
- :func:`envelope_to_audit_event` — reconstruct an :class:`AuditEvent`
  from a received :class:`Envelope` (after signature verification).
- :func:`AuditLog.emit_envelope` — convenience: record via envelope
  transport (so a remote sidecar can replay its audit stream).

The bridge never silently drops an envelope. It returns ``None`` on
failure with a logger warning, and the caller decides what to do.

This is a **new** file — no existing audit code is changed. The
intent is to make the audit log usable as a sidecar-replicated stream
without disturbing the local fast-path writes.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.audit.types import AuditEvent, AuditKind, RiskLevel
from app.core.events import (
    CURRENT_SCHEMA_VERSION,
    Envelope,
    EventKind,
    Header,
    make_envelope,
)

logger = logging.getLogger(__name__)


# Map AuditKind → EventKind. Anything we don't recognise falls back
# to a generic "audit" envelope kind.
_AUDIT_TO_EVENT: dict[str, str] = {
    AuditKind.TOOL_CALL.value: EventKind.TOOL_CALL.value,
    AuditKind.AGENT_HANDOFF.value: EventKind.LIFE_EVENT.value,
    AuditKind.APPROVAL.value: EventKind.AUDIT.value,
    AuditKind.POLICY.value: EventKind.AUDIT.value,
    AuditKind.CONFIG.value: EventKind.AUDIT.value,
    AuditKind.SECURITY.value: EventKind.ALERT.value,
    AuditKind.LLM_CALL.value: EventKind.METRIC.value,
    AuditKind.PLAN.value: EventKind.PLAN_STEP.value,
    AuditKind.GOAL.value: EventKind.LIFE_EVENT.value,
    AuditKind.COST.value: EventKind.METRIC.value,
    AuditKind.CUSTOM.value: EventKind.AUDIT.value,
}


def audit_event_to_envelope(
    event: AuditEvent, *, source: str = "audit"
) -> Envelope:
    """Wrap an :class:`AuditEvent` in an :class:`Envelope`.

    The envelope's ``body`` carries the redacted audit payload; the
    ``header.kind`` is the most-specific :class:`EventKind` we can
    infer. Signature is left empty — the caller signs if it has a
    keypair.
    """
    raw_kind = event.kind.value if hasattr(event.kind, "value") else str(event.kind)
    env_kind = _AUDIT_TO_EVENT.get(raw_kind, EventKind.AUDIT.value)
    body: dict[str, Any] = {
        "audit": event.to_dict(redact=True),
    }
    env = make_envelope(
        kind=env_kind,
        source=source,
        body=body,
        correlation_id=event.id,
        causation_id=event.target or "",
    )
    # Override the timestamp so the envelope time matches the audit
    # event time, not "now". This matters for replay.
    env.header.timestamp = event.timestamp.isoformat()
    return env


def envelope_to_audit_event(env: Envelope) -> AuditEvent | None:
    """Reconstruct an :class:`AuditEvent` from an :class:`Envelope`.

    Returns ``None`` if the envelope doesn't carry an audit payload
    (e.g. it was a chat or tool_call envelope, not an audit). Never
    raises — malformed bodies are logged and dropped.
    """
    if not isinstance(env, Envelope):
        logger.warning("envelope_to_audit_event: not an Envelope instance")
        return None
    body = env.body or {}
    audit_payload = body.get("audit")
    if not isinstance(audit_payload, dict):
        return None
    try:
        return AuditEvent.from_dict(audit_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("envelope_to_audit_event: bad audit payload: %s", exc)
        return None


def is_audit_envelope(env: Envelope) -> bool:
    """Return True if this envelope is carrying an audit payload."""
    return isinstance(env.body, dict) and isinstance(env.body.get("audit"), dict)


# ── Convenience shim for AuditLog -----------------------------------------


def install_envelope_emitter(log: Any) -> Any:
    """Attach ``emit_envelope(env)`` to an existing :class:`AuditLog`.

    Pure-monkey-patch helper: the audit log gains a method that takes
    a verified :class:`Envelope`, reconstructs the :class:`AuditEvent`,
    and records it via the normal :meth:`record` path.

    This is intentionally non-destructive: existing call sites that
    use ``log.record(AuditEvent(...))`` keep working.
    """
    if getattr(log, "emit_envelope", None) is not None:
        return log  # already installed

    def _emit_envelope(self: Any, env: Envelope) -> str | None:
        evt = envelope_to_audit_event(env)
        if evt is None:
            logger.debug("emit_envelope: envelope has no audit payload")
            return None
        return self.record(evt)

    log.emit_envelope = _emit_envelope.__get__(log, type(log))  # type: ignore[attr-defined]
    return log


__all__ = [
    "audit_event_to_envelope",
    "envelope_to_audit_event",
    "is_audit_envelope",
    "install_envelope_emitter",
    "CURRENT_SCHEMA_VERSION",
]
