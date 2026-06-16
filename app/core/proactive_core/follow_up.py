"""Follow-up tracker — commitments, promises, deadlines.

A :class:`Commitment` is anything the user (or the system on the
user's behalf) has promised to do, with a due time.  The tracker
is in-process for now; a future commit can swap in HelixDB
persistence via the same API.

Detection of "remind me about X" or "I'll do that tomorrow" from
free text is deliberately out of scope for this module — it's a
separate NLP problem.  The canonical input is the structured
``add_commitment(...)`` call, so callers (or future LLM-powered
detectors) can produce clean records.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)


class CommitmentKind(str, Enum):
    """Why this commitment exists."""

    REMINDER = "reminder"  # user said "remind me about X"
    PROMISE = "promise"  # user said "I'll do X tomorrow"
    DEADLINE = "deadline"  # external (calendar, file mtime, email thread)
    FOLLOW_UP = "follow_up"  # generic "check back on this"


class CommitmentStatus(str, Enum):
    PENDING = "pending"
    SNOOZED = "snoozed"  # user asked to be reminded later
    DONE = "done"  # user marked it done
    EXPIRED = "expired"  # past due + grace period
    DROPPED = "dropped"  # explicitly cancelled


@dataclass(slots=True)
class Commitment:
    """A single promise or deadline."""

    id: str
    user_id: str
    kind: CommitmentKind
    text: str
    created_at: datetime
    due_at: datetime | None = None
    status: CommitmentStatus = CommitmentStatus.PENDING
    source: str = "user"  # user | calendar | file | email | …
    metadata: dict[str, Any] = field(default_factory=dict)
    # When the user snoozes, we set snoozed_until to push the
    # next reminder out.
    snoozed_until: datetime | None = None
    # Last time the user was reminded about this commitment.
    last_reminded_at: datetime | None = None

    def is_overdue(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        if self.due_at is None or self.status != CommitmentStatus.PENDING:
            return False
        return moment > self.due_at

    def is_due_soon(self, lead_time_s: float, now: datetime | None = None) -> bool:
        """True if the commitment becomes due within ``lead_time_s``."""
        moment = now or datetime.now(timezone.utc)
        if self.due_at is None or self.status != CommitmentStatus.PENDING:
            return False
        delta = (self.due_at - moment).total_seconds()
        return 0 <= delta <= lead_time_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "kind": self.kind.value,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "status": self.status.value,
            "source": self.source,
            "metadata": self.metadata,
            "snoozed_until": (self.snoozed_until.isoformat() if self.snoozed_until else None),
            "last_reminded_at": (
                self.last_reminded_at.isoformat() if self.last_reminded_at else None
            ),
        }


class CommitmentStore(Protocol):
    """Persistence protocol.  In-memory is the default impl."""

    def add(self, commitment: Commitment) -> None:  # pragma: no cover
        ...

    def get(self, commitment_id: str) -> Commitment | None:  # pragma: no cover
        ...

    def list(
        self, user_id: str, statuses: Iterable[CommitmentStatus] | None = None
    ) -> list[Commitment]:  # pragma: no cover
        ...

    def update(self, commitment: Commitment) -> None:  # pragma: no cover
        ...

    def all(self) -> list[Commitment]:  # pragma: no cover
        ...


class InMemoryCommitmentStore:
    """Default :class:`CommitmentStore` for tests and single-process use."""

    def __init__(self) -> None:
        self._items: dict[str, Commitment] = {}

    def add(self, commitment: Commitment) -> None:
        self._items[commitment.id] = commitment

    def get(self, commitment_id: str) -> Commitment | None:
        return self._items.get(commitment_id)

    def list(
        self, user_id: str, statuses: Iterable[CommitmentStatus] | None = None
    ) -> list[Commitment]:
        wanted = set(statuses) if statuses is not None else None
        results: list[Commitment] = []
        for c in self._items.values():
            if c.user_id != user_id:
                continue
            if wanted is not None and c.status not in wanted:
                continue
            results.append(c)
        # Earliest due_at first; commitments without a due_at come last.
        results.sort(key=lambda c: (c.due_at is None, c.due_at or c.created_at))
        return results

    def update(self, commitment: Commitment) -> None:
        self._items[commitment.id] = commitment

    def all(self) -> list[Commitment]:
        return list(self._items.values())


class FollowUpTracker:
    """High-level API over a :class:`CommitmentStore`.

    The tracker is the single place to add, query, and update
    commitments.  It does *not* decide *when* to remind — that's
    the proactive engine's job.  It just answers "what's pending
    and what's due soon?".
    """

    def __init__(self, store: CommitmentStore | None = None) -> None:
        self._store: CommitmentStore = store or InMemoryCommitmentStore()

    @property
    def store(self) -> CommitmentStore:
        return self._store

    def add_commitment(
        self,
        user_id: str,
        text: str,
        *,
        kind: CommitmentKind = CommitmentKind.REMINDER,
        due_at: datetime | None = None,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
        commitment_id: str | None = None,
    ) -> Commitment:
        c = Commitment(
            id=commitment_id or f"cmt-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            kind=kind,
            text=text,
            created_at=datetime.now(timezone.utc),
            due_at=due_at,
            source=source,
            metadata=metadata or {},
        )
        self._store.add(c)
        return c

    def mark_done(self, commitment_id: str) -> bool:
        c = self._store.get(commitment_id)
        if c is None:
            return False
        c.status = CommitmentStatus.DONE
        self._store.update(c)
        return True

    def mark_dropped(self, commitment_id: str) -> bool:
        c = self._store.get(commitment_id)
        if c is None:
            return False
        c.status = CommitmentStatus.DROPPED
        self._store.update(c)
        return True

    def snooze(self, commitment_id: str, until: datetime) -> bool:
        c = self._store.get(commitment_id)
        if c is None:
            return False
        c.snoozed_until = until
        c.status = CommitmentStatus.SNOOZED
        self._store.update(c)
        return True

    def mark_reminded(self, commitment_id: str) -> None:
        c = self._store.get(commitment_id)
        if c is None:
            return
        c.last_reminded_at = datetime.now(timezone.utc)
        self._store.update(c)

    def list_pending(self, user_id: str) -> list[Commitment]:
        return self._store.list(
            user_id,
            statuses={
                CommitmentStatus.PENDING,
                CommitmentStatus.SNOOZED,
            },
        )

    def list_overdue(self, user_id: str, now: datetime | None = None) -> list[Commitment]:
        return [c for c in self.list_pending(user_id) if c.is_overdue(now)]

    def list_due_soon(
        self, user_id: str, lead_time_s: float, now: datetime | None = None
    ) -> list[Commitment]:
        return [c for c in self.list_pending(user_id) if c.is_due_soon(lead_time_s, now)]

    def expire_overdue(
        self, user_id: str, grace_period_s: float, now: datetime | None = None
    ) -> list[Commitment]:
        """Flip PENDING commitments past ``due_at + grace_period`` to EXPIRED.

        Returns the list of commitments that were just expired.
        """
        moment = now or datetime.now(timezone.utc)
        expired: list[Commitment] = []
        for c in self.list_pending(user_id):
            if c.due_at is None:
                continue
            if (moment - c.due_at).total_seconds() >= grace_period_s:
                c.status = CommitmentStatus.EXPIRED
                self._store.update(c)
                expired.append(c)
        return expired
