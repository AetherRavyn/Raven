"""Public API for the privacy package.

A :class:`PrivacyManager` ties detection, redaction,
consent, and retention into one facade the runtime calls:

  * :meth:`redact_text` — detect + redact text in one call.
    Returns a :class:`RedactionResult` so callers can
    decide whether to keep the mapping (e.g. for the
    user's own session) or discard it (e.g. for logs).
  * :meth:`check_consent` — does this user allow this
    data class right now?
  * :meth:`schedule_retention` — mark a record for
    eventual deletion.
  * :meth:`purge_due` — run a purge pass.
  * :meth:`delete_user` — GDPR-style "forget me".

The manager is in-memory by default.  Persistence (to
HelixDB) is layered by the runtime at the appropriate
boundary, the same pattern as :mod:`app.core.continuity`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.core.privacy.consent import (
    Consent,
    ConsentLevel,
    ConsentStore,
    DataClass,
)
from app.core.privacy.detection import PIIDetector, PIIKind
from app.core.privacy.redaction import (
    RedactionPolicy,
    RedactionResult,
    Redactor,
    redact_for_log,
)
from app.core.privacy.retention import (
    PurgeRecord,
    Purger,
    RetentionManager,
    RetentionPolicy,
)

logger = logging.getLogger(__name__)


class PrivacyError(PermissionError):
    """Raised when a privacy/consent check refuses an operation.

    Carries the user id, data class, and current consent level
    (if any) so the runtime can render a clear error message
    to the user.
    """

    def __init__(
        self,
        message: str,
        *,
        user_id: str,
        data_class: DataClass,
        current_level: ConsentLevel | None = None,
    ) -> None:
        super().__init__(message)
        self.user_id = user_id
        self.data_class = data_class
        self.current_level = current_level

    def __repr__(self) -> str:
        return (
            f"PrivacyError(user_id={self.user_id!r}, "
            f"data_class={self.data_class!r}, "
            f"current_level={self.current_level!r})"
        )


@dataclass(slots=True)
class PrivacyConfig:
    """Knobs for the privacy manager."""

    # Default redaction policy per kind.  TOKEN preserves
    # reversibility inside the user's session.
    default_policies: dict[PIIKind, RedactionPolicy] = field(default_factory=dict)
    # Whether to detect IPs by default.
    detect_ip: bool = False
    # Retention policy.
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)


class PrivacyManager:
    """Process-level facade for the privacy package."""

    def __init__(
        self,
        *,
        detector: PIIDetector | None = None,
        redactor: Redactor | None = None,
        consent_store: ConsentStore | None = None,
        retention_manager: RetentionManager | None = None,
        config: PrivacyConfig | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config or PrivacyConfig()
        self._detector = detector or PIIDetector(detect_ip=self._config.detect_ip)
        self._redactor = redactor
        if self._redactor is None:
            redactor_kwargs: dict[str, Any] = {"detector": self._detector}
            if self._config.default_policies:
                redactor_kwargs["policies"] = dict(self._config.default_policies)
            self._redactor = Redactor(**redactor_kwargs)
        self.consent_store = consent_store or ConsentStore()
        self.retention = retention_manager or RetentionManager(
            policy=self._config.retention,
            consent_store=self.consent_store,
        )

    # ---- redaction ----

    def redact_text(self, text: str) -> RedactionResult:
        assert self._redactor is not None
        return self._redactor.redact(text)

    def redact_for_log(self, text: str) -> str:
        return redact_for_log(text, audit_safe=False)

    def detector(self) -> PIIDetector:
        return self._detector

    def redactor(self) -> Redactor:
        assert self._redactor is not None
        return self._redactor

    # ---- consent ----

    def grant_consent(
        self,
        user_id: str,
        data_class: DataClass,
        level: ConsentLevel = ConsentLevel.ALLOW,
        *,
        ttl: timedelta | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Consent:
        return self.consent_store.grant(user_id, data_class, level, ttl=ttl, metadata=metadata)

    def revoke_consent(self, user_id: str, data_class: DataClass) -> bool:
        return self.consent_store.revoke(user_id, data_class)

    def check_consent(
        self,
        user_id: str,
        data_class: DataClass,
    ) -> Consent | None:
        return self.consent_store.check(user_id, data_class)

    def is_allowed(self, user_id: str, data_class: DataClass) -> bool:
        consent = self.consent_store.check(user_id, data_class)
        if consent is None:
            return False  # no consent = default deny
        return consent.is_active and consent.level in (
            ConsentLevel.ALLOW,
            ConsentLevel.AUTO_PURGE,
        )

    def check_tool(
        self,
        user_id: str,
        tool_name: str,
        *,
        data_class: DataClass | None = None,
    ) -> DataClass:
        """Verify a tool call is allowed for the user.

        Resolves ``tool_name`` to a :class:`DataClass` via
        :func:`app.core.privacy.policy.data_class_for` (or
        ``data_class=`` override), then checks consent.  Raises
        :class:`PrivacyError` if consent is missing or denied.
        Returns the :class:`DataClass` on success so callers
        can use it for downstream audit.

        Conservative: when no user_id is supplied, the check
        fails closed (``PrivacyError``).  The runtime should
        always pass a real user id.
        """
        from app.core.privacy.policy import data_class_for

        if not user_id:
            raise PrivacyError(
                "privacy: missing user_id",
                user_id="",
                data_class=data_class or DataClass.PROFILE,
            )
        dc = data_class or data_class_for(tool_name)
        consent = self.consent_store.check(user_id, dc)
        if consent is None:
            raise PrivacyError(
                f"privacy: no consent for {dc.value}",
                user_id=user_id,
                data_class=dc,
            )
        if not consent.is_active:
            raise PrivacyError(
                f"privacy: consent for {dc.value} expired or revoked",
                user_id=user_id,
                data_class=dc,
                current_level=consent.level,
            )
        if consent.level not in (ConsentLevel.ALLOW, ConsentLevel.AUTO_PURGE):
            raise PrivacyError(
                f"privacy: consent for {dc.value} is {consent.level.value}",
                user_id=user_id,
                data_class=dc,
                current_level=consent.level,
            )
        return dc

    # ---- retention ----

    def schedule_retention(
        self,
        record_id: str,
        data_class: DataClass,
        user_id: str,
        *,
        retention_until: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> PurgeRecord:
        return self.retention.mark_for_purge(
            record_id,
            data_class,
            user_id,
            retention_until=retention_until,
            metadata=metadata,
        )

    def set_purger(self, purger: Purger) -> None:
        self.retention.set_purger(purger)

    def purge_due(self) -> list[str]:
        return self.retention.purge_due()

    def delete_user(self, user_id: str, *, reason: str = "user-request") -> list[str]:
        return self.retention.purge_user(user_id, reason=reason)

    # ---- diagnostics ----

    def explain(self) -> dict[str, Any]:
        return {
            "consent": self.consent_store.summary(),
            "retention": self.retention.explain(),
        }
