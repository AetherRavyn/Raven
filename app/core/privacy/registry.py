"""Process-singleton helpers for the privacy manager.

Mirrors the pattern from :mod:`app.core.continuity.orchestrator`:
the runtime lazily constructs a single :class:`PrivacyManager`
per process.  Tests can call :func:`reset_privacy` to get a
fresh instance between cases.
"""

from __future__ import annotations

import threading

from app.core.privacy.consent import ConsentStore
from app.core.privacy.detection import PIIDetector
from app.core.privacy.orchestrator import PrivacyConfig, PrivacyManager
from app.core.privacy.redaction import Redactor
from app.core.privacy.retention import RetentionManager, RetentionPolicy

_LOCK = threading.RLock()
_MANAGER: PrivacyManager | None = None


def get_privacy_manager() -> PrivacyManager:
    """Return the process-singleton privacy manager.

    Constructed lazily on first call.  Tests should call
    :func:`reset_privacy` between cases to get a clean
    ledger; production callers should reuse the singleton.
    """
    global _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = _build_default()
        return _MANAGER


def set_privacy_manager(manager: PrivacyManager | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear it.

    The runtime wires this in its ``__init__`` when ``SARAS_PRIVACY_V2``
    is set.  Tests use it to inject mocks.
    """
    global _MANAGER
    with _LOCK:
        _MANAGER = manager


def reset_privacy() -> None:
    """Drop the singleton.  Subsequent :func:`get_privacy_manager`
    calls will lazily construct a fresh one."""
    global _MANAGER
    with _LOCK:
        _MANAGER = None


def _build_default() -> PrivacyManager:
    """Build a default privacy manager with sane defaults."""
    config = PrivacyConfig(retention=RetentionPolicy())
    detector = PIIDetector()
    redactor = Redactor(detector=detector)
    consent_store = ConsentStore()
    retention = RetentionManager(
        policy=config.retention,
        consent_store=consent_store,
    )
    return PrivacyManager(
        detector=detector,
        redactor=redactor,
        consent_store=consent_store,
        retention_manager=retention,
        config=config,
    )


__all__ = ["get_privacy_manager", "set_privacy_manager", "reset_privacy"]
