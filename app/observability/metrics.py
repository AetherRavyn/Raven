"""Prometheus metrics for SARAS observability (A5).

Extends the existing :mod:`app.core.metrics` with the gauges and
counters that the A4 audit + policy v2 + vault subsystems need
to expose to a Prometheus scrape endpoint.

The module is import-safe even if Prometheus isn't installed —
all metric accessors return ``None`` so callers can use them
unconditionally.

Naming convention
-----------------

All metrics are prefixed with ``saras_`` and follow the
``<unit>_<subject>_<verb>`` pattern.  Counters end in ``_total``;
histograms in ``_seconds``; gauges have no suffix.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy metric definitions
# ---------------------------------------------------------------------------


_INIT_LOCK = threading.Lock()
_INITIALIZED = False

# A4 — Audit
audit_events_total: Any = None
audit_events_by_risk: Any = None
audit_redactions_total: Any = None
audit_log_size_bytes: Any = None

# A4 — Policy v2
policy_evaluations_total: Any = None
policy_decisions_by_verdict: Any = None
policy_approvals_pending: Any = None
policy_trust_tier_users: Any = None

# A4 — Vault
vault_secrets_total: Any = None
vault_rotations_total: Any = None
vault_lookup_failures_total: Any = None

# A5 — Tracing
otel_spans_exported_total: Any = None
otel_spans_dropped_total: Any = None

# A5 — Logging
log_redactions_total: Any = None


def _init_prometheus() -> bool:
    """Create the metric objects.  Returns True on success."""
    try:
        from prometheus_client import Counter, Gauge
    except ImportError as e:
        logger.debug("prometheus_client not installed: %s", e)
        return False

    global audit_events_total, audit_events_by_risk, audit_redactions_total
    global audit_log_size_bytes
    global policy_evaluations_total, policy_decisions_by_verdict
    global policy_approvals_pending, policy_trust_tier_users
    global vault_secrets_total, vault_rotations_total, vault_lookup_failures_total
    global otel_spans_exported_total, otel_spans_dropped_total
    global log_redactions_total

    audit_events_total = Counter(
        "saras_audit_events_total",
        "Audit events recorded",
        ["kind", "risk"],
    )
    audit_events_by_risk = Counter(
        "saras_audit_events_by_risk_total",
        "Audit events by risk level",
        ["risk"],
    )
    audit_redactions_total = Counter(
        "saras_audit_redactions_total",
        "PII redactions applied during audit serialization",
        ["rule"],
    )
    audit_log_size_bytes = Gauge(
        "saras_audit_log_size_bytes",
        "Size of the audit log JSONL file",
    )

    policy_evaluations_total = Counter(
        "saras_policy_evaluations_total",
        "Policy v2 evaluations",
        ["verdict"],
    )
    policy_decisions_by_verdict = Counter(
        "saras_policy_decisions_by_verdict_total",
        "Policy v2 verdicts issued",
        ["verdict", "risk_band"],
    )
    policy_approvals_pending = Gauge(
        "saras_policy_approvals_pending",
        "Pending approval requests in the queue",
    )
    policy_trust_tier_users = Gauge(
        "saras_policy_trust_tier_users",
        "Number of users per trust tier",
        ["tier"],
    )

    vault_secrets_total = Gauge(
        "saras_vault_secrets_total",
        "Number of secrets stored in the vault",
    )
    vault_rotations_total = Counter(
        "saras_vault_rotations_total",
        "Key rotations performed",
    )
    vault_lookup_failures_total = Counter(
        "saras_vault_lookup_failures_total",
        "Vault lookups that fell back to env (vault disabled or missing)",
    )

    otel_spans_exported_total = Counter(
        "saras_otel_spans_exported_total",
        "OpenTelemetry spans successfully exported",
    )
    otel_spans_dropped_total = Counter(
        "saras_otel_spans_dropped_total",
        "OpenTelemetry spans dropped (sample, error, or shutdown)",
    )

    log_redactions_total = Counter(
        "saras_log_redactions_total",
        "Log values that were redacted by the structured logger",
    )
    return True


def init_metrics() -> bool:
    """Initialize all metrics.  Idempotent.

    Returns True on success, False if prometheus_client is
    unavailable (in which case every accessor returns None
    and call sites can use them unconditionally).
    """
    global _INITIALIZED
    with _INIT_LOCK:
        if _INITIALIZED:
            return True
        ok = _init_prometheus()
        _INITIALIZED = ok
        return ok


def is_available() -> bool:
    """True if prometheus_client is installed and metrics are live."""
    if not _INITIALIZED:
        init_metrics()
    return _INITIALIZED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def inc_audit_event(kind: str, risk: str) -> None:
    if not is_available():
        return
    try:
        audit_events_total.labels(kind=kind, risk=risk).inc()
        audit_events_by_risk.labels(risk=risk).inc()
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def inc_audit_redaction(rule: str) -> None:
    if not is_available():
        return
    try:
        audit_redactions_total.labels(rule=rule).inc()
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def set_policy_approvals_pending(n: int) -> None:
    if not is_available():
        return
    try:
        policy_approvals_pending.set(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric set failed: %s", e)


def set_trust_tier_counts(counts: dict[str, int]) -> None:
    if not is_available():
        return
    try:
        for tier, n in counts.items():
            policy_trust_tier_users.labels(tier=tier).set(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric set failed: %s", e)


def inc_policy_evaluation(verdict: str, risk_band: str) -> None:
    if not is_available():
        return
    try:
        policy_evaluations_total.labels(verdict=verdict).inc()
        policy_decisions_by_verdict.labels(verdict=verdict, risk_band=risk_band).inc()
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def set_vault_secrets(n: int) -> None:
    if not is_available():
        return
    try:
        vault_secrets_total.set(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric set failed: %s", e)


def inc_vault_rotation() -> None:
    if not is_available():
        return
    try:
        vault_rotations_total.inc()
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def inc_vault_lookup_failure() -> None:
    if not is_available():
        return
    try:
        vault_lookup_failures_total.inc()
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def inc_otel_exported(n: int = 1) -> None:
    if not is_available():
        return
    try:
        otel_spans_exported_total.inc(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def inc_otel_dropped(n: int = 1) -> None:
    if not is_available():
        return
    try:
        otel_spans_dropped_total.inc(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def inc_log_redaction(n: int = 1) -> None:
    if not is_available():
        return
    try:
        log_redactions_total.inc(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric inc failed: %s", e)


def set_audit_log_size(n: int) -> None:
    if not is_available():
        return
    try:
        audit_log_size_bytes.set(n)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric set failed: %s", e)


__all__ = [
    "init_metrics",
    "is_available",
    "inc_audit_event",
    "inc_audit_redaction",
    "set_policy_approvals_pending",
    "set_trust_tier_counts",
    "inc_policy_evaluation",
    "set_vault_secrets",
    "inc_vault_rotation",
    "inc_vault_lookup_failure",
    "inc_otel_exported",
    "inc_otel_dropped",
    "inc_log_redaction",
    "set_audit_log_size",
    "audit_events_total",
    "audit_events_by_risk",
    "audit_redactions_total",
    "audit_log_size_bytes",
    "policy_evaluations_total",
    "policy_decisions_by_verdict",
    "policy_approvals_pending",
    "policy_trust_tier_users",
    "vault_secrets_total",
    "vault_rotations_total",
    "vault_lookup_failures_total",
    "otel_spans_exported_total",
    "otel_spans_dropped_total",
    "log_redactions_total",
]
