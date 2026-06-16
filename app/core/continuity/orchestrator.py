"""Public API for cross-platform continuity.

This module ties identity, session, and handoff together into
a small facade used by the rest of the codebase.  It's a
process-singleton, not a class — the underlying components
are independently injectable, but most callers just want
``continuity()`` and to be done with it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Any

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
from app.core.continuity.session import (
    Session,
    SessionEvent,
    SessionManager,
)

logger = logging.getLogger(__name__)


class Continuity:
    """Process-singleton orchestrator.

    Holds:
      * an IdentityRegistry
      * a SessionManager
      * a HandoffLog

    Plus a small set of high-level helpers that exercise all
    three.
    """

    def __init__(self) -> None:
        self.identity = IdentityRegistry()
        self.sessions = SessionManager()
        self.handoffs = HandoffLog()

    # ---- identity passthroughs ----

    def ensure_handle(
        self,
        platform: str,
        chat_id: str,
        user_id: str | None = None,
        device_kind: str = "phone",
        **kwargs: Any,
    ) -> tuple[UserIdentity, Device, Channel]:
        uid = user_id or derive_user_id(platform, chat_id)
        return self.identity.bind(platform, chat_id, uid, device_kind, **kwargs)

    def find_user_by_handle(self, platform: str, chat_id: str) -> UserIdentity | None:
        ch = self.identity.find_channel(platform, chat_id)
        if ch is None:
            return None
        device = self.identity.get_device(ch.device_id)
        if device is None:
            return None
        return self.identity.get_user(device.user_id)

    # ---- session passthroughs ----

    def get_or_create_session(
        self,
        user_id: str,
        channel_id: str,
        **kwargs: Any,
    ) -> tuple[Session, bool]:
        return self.sessions.get_or_create(user_id, channel_id, **kwargs)

    def primary_session(self, user_id: str) -> Session | None:
        return self.sessions.primary_for_user(user_id)

    # ---- handoff ----

    def handoff(
        self,
        source_session_id: str,
        target_channel_id: str,
        *,
        reason: str = "user-request",
        tags: Iterable[str] = (),
    ) -> tuple[Session, HandoffReceipt]:
        target, receipt = handoff_session(
            self.sessions,
            source_session_id,
            target_channel_id,
            reason=reason,
            tags=tags,
        )
        self.handoffs.append(receipt)
        return target, receipt

    def summarise(self, session: Session, **kwargs: Any) -> dict[str, Any]:
        return summarise_for_handoff(session, **kwargs)


# -------------------------------------------------------------------
# singleton plumbing
# -------------------------------------------------------------------


_lock = threading.Lock()
_instance: Continuity | None = None


def continuity() -> Continuity:
    """Return the process-singleton Continuity orchestrator."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = Continuity()
    return _instance


def reset_continuity() -> None:
    """Drop the singleton (test helper)."""
    global _instance
    with _lock:
        _instance = None


__all__ = [
    "Channel",
    "Continuity",
    "Device",
    "HandoffLog",
    "HandoffReceipt",
    "IdentityRegistry",
    "Session",
    "SessionEvent",
    "SessionManager",
    "UserIdentity",
    "continuity",
    "derive_device_id",
    "derive_user_id",
    "handoff_session",
    "reset_continuity",
    "summarise_for_handoff",
]
