"""Cross-platform continuity: identity, session, handoff.

The package exposes:

  * ``IdentityRegistry``  — users, devices, channels
  * ``SessionManager``    — start, resume, end, append events
  * ``HandoffLog``        — receipt log + ``handoff_session()``
  * ``Continuity``        — process-singleton orchestrator
  * ``HelixContinuityStore`` — best-effort HelixDB persistence

The in-memory components are the source of truth at runtime;
the Helix store is a snapshot layer for restart recovery.
"""

from __future__ import annotations

from app.core.continuity.handoff import (
    HandoffLog,
    HandoffReceipt,
    handoff_session,
    summarise_for_handoff,
)
from app.core.continuity.identity import (
    Channel,
    Device,
    IdentityRegistry,
    UserIdentity,
    derive_device_id,
    derive_user_id,
)
from app.core.continuity.orchestrator import (
    Continuity,
    continuity,
    reset_continuity,
)
from app.core.continuity.session import (
    Session,
    SessionEvent,
    SessionManager,
)
from app.core.continuity.store import (
    HelixContinuityStore,
    load_sessions,
    snapshot,
)

__all__ = [
    "Channel",
    "Continuity",
    "Device",
    "HandoffLog",
    "HandoffReceipt",
    "HelixContinuityStore",
    "IdentityRegistry",
    "Session",
    "SessionEvent",
    "SessionManager",
    "UserIdentity",
    "continuity",
    "derive_device_id",
    "derive_user_id",
    "handoff_session",
    "load_sessions",
    "reset_continuity",
    "snapshot",
    "summarise_for_handoff",
]
