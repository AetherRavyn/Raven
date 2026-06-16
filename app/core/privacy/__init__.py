"""Phase E — Privacy & Trust.

Six modules:

  * :mod:`app.core.privacy.detection`   — PII pattern detection
  * :mod:`app.core.privacy.redaction`   — apply per-kind policies
  * :mod:`app.core.privacy.consent`     — per-user consent ledger
  * :mod:`app.core.privacy.retention`   — purge scheduling
  * :mod:`app.core.privacy.policy`      — tool name → DataClass
  * :mod:`app.core.privacy.orchestrator` — :class:`PrivacyManager` facade
  * :mod:`app.core.privacy.registry`    — process-singleton helpers

The :class:`PrivacyManager` is the runtime-facing entry point.
The existing :mod:`app.core.audit.redaction` module (secrets in
audit events) is a consumer of this package; the two are
intentionally complementary.
"""

from __future__ import annotations

from app.core.privacy.consent import (
    Consent,
    ConsentLevel,
    ConsentStore,
    DataClass,
)
from app.core.privacy.detection import (
    PIIDetection,
    PIIDetector,
    PIIKind,
    all_default_kinds,
    detector_audit_safe,
    detector_with_kinds,
)
from app.core.privacy.orchestrator import (
    PrivacyConfig,
    PrivacyError,
    PrivacyManager,
)
from app.core.privacy.policy import data_class_for
from app.core.privacy.redaction import (
    Redaction,
    RedactionPolicy,
    RedactionResult,
    Redactor,
    redact_for_log,
)
from app.core.privacy.registry import (
    get_privacy_manager,
    reset_privacy,
    set_privacy_manager,
)
from app.core.privacy.retention import (
    PurgeRecord,
    Purger,
    RetentionManager,
    RetentionPolicy,
)

__all__ = [
    "Consent",
    "ConsentLevel",
    "ConsentStore",
    "DataClass",
    "PIIDetection",
    "PIIDetector",
    "PIIKind",
    "PrivacyConfig",
    "PrivacyError",
    "PrivacyManager",
    "Purger",
    "PurgeRecord",
    "Redaction",
    "RedactionPolicy",
    "RedactionResult",
    "Redactor",
    "RetentionManager",
    "RetentionPolicy",
    "all_default_kinds",
    "data_class_for",
    "detector_audit_safe",
    "detector_with_kinds",
    "get_privacy_manager",
    "redact_for_log",
    "reset_privacy",
    "set_privacy_manager",
]
