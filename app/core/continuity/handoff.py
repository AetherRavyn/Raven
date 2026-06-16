"""Cross-channel state handoff.

A handoff transfers a session from one channel to another.  The
"why" is always the same: the user is moving (phone -> laptop,
voice -> text, public bot -> private channel).  The "what" is:

  * the working context (small structured blob)
  * the recent transcript tail
  * the target channel id

Handoffs are explicit, audit-logged, and reversible.  The
originating session is *ended*; the receiving session is
*new* — we never mutate the source, so the source of truth
is preserved.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.continuity.session import Session, SessionEvent, SessionManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HandoffReceipt:
    """Audit record for a single handoff."""

    id: str
    source_session_id: str
    target_session_id: str
    source_channel_id: str
    target_channel_id: str
    user_id: str
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events_transferred: int = 0
    context_keys: tuple[str, ...] = ()


@dataclass(slots=True)
class HandoffLog:
    """In-memory append-only log of handoffs."""

    _receipts: list[HandoffReceipt] = field(default_factory=list)

    def append(self, receipt: HandoffReceipt) -> None:
        self._receipts.append(receipt)

    def list_for_user(self, user_id: str) -> list[HandoffReceipt]:
        return [r for r in self._receipts if r.user_id == user_id]

    def latest_for_session(self, session_id: str) -> HandoffReceipt | None:
        for r in reversed(self._receipts):
            if r.source_session_id == session_id or r.target_session_id == session_id:
                return r
        return None

    def clear(self) -> None:
        self._receipts.clear()


# -------------------------------------------------------------------
# public api
# -------------------------------------------------------------------


def handoff_session(
    manager: SessionManager,
    source_session_id: str,
    target_channel_id: str,
    *,
    reason: str = "user-request",
    tags: Iterable[str] = (),
) -> tuple[Session, HandoffReceipt]:
    """Move a session to a different channel.

    Returns the *new* session and the receipt.  The source
    session is ended.  Transcript tail is preserved verbatim.
    """
    source = manager.get(source_session_id)
    if source is None:
        raise KeyError(f"unknown source session: {source_session_id}")

    target_sess = manager.start(
        user_id=source.user_id,
        channel_id=target_channel_id,
        tags=list(tags) or list(source.tags),
        context=dict(source.context),
    )
    target_sess.target_channel_id = target_channel_id

    # Copy transcript tail verbatim.
    for ev in source.events:
        target_sess.events.append(
            SessionEvent(
                id=ev.id,
                session_id=target_sess.id,
                role=ev.role,
                content=ev.content,
                created_at=ev.created_at,
                metadata=dict(ev.metadata),
            )
        )

    # System event marking the transfer.
    target_sess.events.append(
        SessionEvent(
            id="e_handoff",
            session_id=target_sess.id,
            role="system",
            content=f"handoff from {source.channel_id}: {reason}",
            created_at=datetime.now(timezone.utc),
            metadata={
                "source_session_id": source.id,
                "source_channel_id": source.channel_id,
            },
        )
    )

    manager.end(source.id)

    receipt = HandoffReceipt(
        id="h_" + target_sess.id.split("_", 1)[1],
        source_session_id=source.id,
        target_session_id=target_sess.id,
        source_channel_id=source.channel_id,
        target_channel_id=target_channel_id,
        user_id=source.user_id,
        reason=reason,
        events_transferred=len(source.events),
        context_keys=tuple(source.context.keys()),
    )
    logger.info(
        "session.handoff user=%s from=%s to=%s events=%d",
        source.user_id,
        source.channel_id,
        target_channel_id,
        receipt.events_transferred,
    )
    return target_sess, receipt


def summarise_for_handoff(session: Session, *, max_events: int = 5) -> dict[str, Any]:
    """Produce a JSON-safe summary suitable for a 'welcome back' message.

    Returns a small dict — *not* the full session.  Used when
    the handoff target wants to introduce itself.
    """
    recent = list(session.events)[-max_events:]
    return {
        "session_id": session.id,
        "user_id": session.user_id,
        "channel_id": session.channel_id,
        "context_keys": sorted(session.context.keys()),
        "recent_turns": [{"role": e.role, "content": e.content[:200]} for e in recent],
        "started_at": session.started_at.isoformat(),
        "event_count": len(session.events),
    }
