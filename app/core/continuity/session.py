"""Session management for cross-platform continuity.

A session is a logical thread of work owned by a user.  A user
can have multiple active sessions (one per device, per
project, per intent).  A session tracks:

  * a stable id
  * a list of recent events (the conversation transcript tail)
  * structured context (working memory: variables, state)
  * a target channel id (where the next reply should go)

The session manager is the source of truth for "what's the
current session for this user / this channel?"  The state
handoff module (handoff.py) is responsible for moving a
session between channels.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# event log
# -------------------------------------------------------------------


@dataclass(slots=True)
class SessionEvent:
    """A single event in the session transcript."""

    id: str
    session_id: str
    role: str  # "user", "assistant", "tool", "system"
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


# -------------------------------------------------------------------
# session
# -------------------------------------------------------------------


# Default idle timeout: 30 minutes.  Configurable per session.
DEFAULT_IDLE_TIMEOUT = timedelta(minutes=30)


@dataclass(slots=True)
class Session:
    """A logical thread of work."""

    id: str
    user_id: str
    channel_id: str  # platform:chat_id
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    # Working memory: small structured blob the runtime can read.
    context: dict[str, Any] = field(default_factory=dict)
    # The recent transcript tail.
    events: deque[SessionEvent] = field(default_factory=lambda: deque(maxlen=200))
    # Where the next proactive reply should go.
    target_channel_id: str = ""
    # Free-form tags: "voice", "research", "code-review".
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_active(self) -> bool:
        if self.ended_at is not None:
            return False
        return (datetime.now(timezone.utc) - self.last_active_at) < DEFAULT_IDLE_TIMEOUT

    def append_event(self, event: SessionEvent) -> None:
        self.events.append(event)
        self.last_active_at = event.created_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize for handoff or persistence."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "started_at": self.started_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "context": dict(self.context),
            "events": [
                {
                    "id": e.id,
                    "role": e.role,
                    "content": e.content,
                    "created_at": e.created_at.isoformat(),
                    "metadata": dict(e.metadata),
                }
                for e in self.events
            ],
            "target_channel_id": self.target_channel_id,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        sess = cls(
            id=data["id"],
            user_id=data["user_id"],
            channel_id=data["channel_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            last_active_at=datetime.fromisoformat(data["last_active_at"]),
            ended_at=(datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None),
            context=dict(data.get("context", {})),
            target_channel_id=data.get("target_channel_id", ""),
            tags=tuple(data.get("tags", ())),
        )
        for ev in data.get("events", []):
            sess.events.append(
                SessionEvent(
                    id=ev["id"],
                    session_id=sess.id,
                    role=ev["role"],
                    content=ev["content"],
                    created_at=datetime.fromisoformat(ev["created_at"]),
                    metadata=dict(ev.get("metadata", {})),
                )
            )
        return sess


# -------------------------------------------------------------------
# manager
# -------------------------------------------------------------------


class SessionManager:
    """In-memory session store with thread-safe CRUD.

    A "primary" session is the user's most-recently-active one.
    Looking up by channel id always returns the *active* session
    for that channel; looking up by user id returns the primary.
    """

    def __init__(
        self,
        *,
        idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT,
        max_events: int = 200,
    ) -> None:
        self._lock = threading.RLock()
        self._idle_timeout = idle_timeout
        self._max_events = max_events
        self._sessions: dict[str, Session] = {}
        # Index: user_id -> sorted list of session ids (most recent first).
        self._by_user: dict[str, list[str]] = {}

    # ---- creation ----

    def start(
        self,
        user_id: str,
        channel_id: str,
        *,
        tags: Iterable[str] = (),
        context: dict[str, Any] | None = None,
    ) -> Session:
        sid = "s_" + uuid.uuid4().hex[:16]
        sess = Session(
            id=sid,
            user_id=user_id,
            channel_id=channel_id,
            target_channel_id=channel_id,
            context=dict(context or {}),
            events=deque(maxlen=self._max_events),
            tags=tuple(tags),
        )
        with self._lock:
            self._sessions[sid] = sess
            self._by_user.setdefault(user_id, []).insert(0, sid)
        logger.info("session.start user=%s channel=%s id=%s", user_id, channel_id, sid)
        return sess

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    # ---- lookup ----

    def primary_for_user(self, user_id: str) -> Session | None:
        with self._lock:
            ids = self._by_user.get(user_id, [])
            for sid in ids:
                sess = self._sessions.get(sid)
                if sess is not None and sess.is_active:
                    return sess
            return None

    def active_for_channel(self, channel_id: str) -> Session | None:
        with self._lock:
            for sess in self._sessions.values():
                if sess.channel_id == channel_id and sess.is_active:
                    return sess
            return None

    def get_or_create(
        self,
        user_id: str,
        channel_id: str,
        **kwargs: Any,
    ) -> tuple[Session, bool]:
        """Return (session, created).  Reuses the active session for the channel."""
        existing = self.active_for_channel(channel_id)
        if existing is not None and existing.user_id == user_id:
            return existing, False
        return self.start(user_id, channel_id, **kwargs), True

    # ---- mutation ----

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SessionEvent:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(f"unknown session: {session_id}")
            ev = SessionEvent(
                id="e_" + uuid.uuid4().hex[:12],
                session_id=session_id,
                role=role,
                content=content,
                metadata=dict(metadata or {}),
            )
            sess.append_event(ev)
            # Bump user index position to front.
            if sess.user_id in self._by_user:
                ids = self._by_user[sess.user_id]
                if ids and ids[0] != session_id:
                    ids.remove(session_id)
                    ids.insert(0, session_id)
            return ev

    def update_context(self, session_id: str, **fields: Any) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(f"unknown session: {session_id}")
            sess.context.update(fields)
            sess.last_active_at = datetime.now(timezone.utc)
            return sess

    def set_target_channel(self, session_id: str, channel_id: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(f"unknown session: {session_id}")
            sess.target_channel_id = channel_id
            sess.last_active_at = datetime.now(timezone.utc)
            return sess

    def end(self, session_id: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(f"unknown session: {session_id}")
            sess.ended_at = datetime.now(timezone.utc)
            return sess

    # ---- listing ----

    def list_sessions(self, user_id: str, *, include_ended: bool = False) -> list[Session]:
        with self._lock:
            ids = self._by_user.get(user_id, [])
            out: list[Session] = []
            for sid in ids:
                sess = self._sessions.get(sid)
                if sess is None:
                    continue
                if not include_ended and not sess.is_active:
                    continue
                out.append(sess)
            return out

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._by_user.clear()
