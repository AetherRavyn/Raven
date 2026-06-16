"""Process-singleton helpers for the privacy manager.

Mirrors the pattern from :mod:`app.core.continuity.orchestrator`:
the runtime lazily constructs a single :class:`PrivacyManager`
per process.  Tests can call :func:`reset_privacy` to get a
fresh instance between cases.
"""

from __future__ import annotations

import logging
import threading

from app.core.privacy.consent import ConsentStore
from app.core.privacy.detection import PIIDetector
from app.core.privacy.orchestrator import PrivacyConfig, PrivacyManager
from app.core.privacy.redaction import Redactor
from app.core.privacy.retention import RetentionManager, RetentionPolicy
from app.db.helix import get_client as get_default_helix_client

logger = logging.getLogger(__name__)

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
    """Build a default privacy manager with sane defaults.

    If a HelixDB client is reachable and ``SARAS_PRIVACY_HELIX`` is
    enabled (default), the manager is wired with a
    :class:`HelixPrivacyStore` that mirrors consent/retention
    writes to durable storage.  If Helix is unavailable the
    manager still works in-memory and a warning is logged.
    """
    config = PrivacyConfig(retention=RetentionPolicy())
    detector = PIIDetector()
    redactor = Redactor(detector=detector)
    consent_store = ConsentStore()
    retention = RetentionManager(
        policy=config.retention,
        consent_store=consent_store,
    )
    helix_store = _try_build_helix_store(consent_store, retention)
    return PrivacyManager(
        detector=detector,
        redactor=redactor,
        consent_store=consent_store,
        retention_manager=retention,
        config=config,
        helix_store=helix_store,
    )


def _try_build_helix_store(
    consent_store: ConsentStore,
    retention: RetentionManager,
) -> object | None:
    """Attempt to construct a :class:`HelixPrivacyStore`.

    Returns ``None`` (with a logged warning) when HelixDB is
    not reachable or the feature is disabled.  Tests inject
    the store directly via :func:`set_privacy_manager` or by
    passing a custom ``helix_store=`` to :class:`PrivacyManager`.
    """
    import os

    if os.environ.get("SARAS_PRIVACY_HELIX", "1").lower() in ("0", "false", "no"):
        logger.info("HelixPrivacyStore disabled by SARAS_PRIVACY_HELIX=0")
        return None
    try:
        from app.core.privacy.persistence import HelixPrivacyStore
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("HelixPrivacyStore unavailable: %s", exc)
        return None
    client = get_default_helix_client()
    if client is None:
        logger.info("HelixPrivacyStore: no default Helix client registered")
        return None
    store = HelixPrivacyStore(client, consent_store, retention)
    # Best-effort load at construction; failure is non-fatal.
    try:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await from a running loop here; the
                # bootstrap will call ``store.initialize()``
                # explicitly.
                pass
            else:
                loop.run_until_complete(store.initialize())
        except RuntimeError:
            asyncio.run(store.initialize())
    except Exception as exc:  # noqa: BLE001
        logger.warning("HelixPrivacyStore initialize failed: %s", exc)
    return store


__all__ = [
    "get_privacy_manager",
    "set_privacy_manager",
    "reset_privacy",
]
