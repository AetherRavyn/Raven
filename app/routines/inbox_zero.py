"""Inbox-zero routine — email triage digest.

The routine takes a snapshot of recent emails (provided by a
caller — the actual mail integration is out of scope here) and
produces a deterministic digest grouped by importance / sender
domain.

It's "passive" in the same way as travel_prep: the routine
doesn't fetch mail.  A real email provider feeds it.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.proactive_core import (
    ProactiveSignal,
    SignalKind,
    Urgency,
    get_context,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InboxMessage:
    """Single email row."""

    id: str
    sender: str
    subject: str
    received_at: datetime
    important: bool = False
    unread: bool = True
    # Free-form labels: "needs_reply", "fyi", "calendar", ...
    tags: tuple[str, ...] = field(default_factory=tuple)
    age_hours: float = 0.0

    @property
    def sender_domain(self) -> str:
        s = self.sender.strip()
        if "<" in s:
            s = s.split("<", 1)[1].rstrip(">")
        if "@" in s:
            return s.rsplit("@", 1)[1].lower()
        return s.lower()


@dataclass(slots=True)
class InboxDigest:
    """Composed triage result."""

    total: int
    needs_reply: tuple[InboxMessage, ...]
    important: tuple[InboxMessage, ...]
    by_domain: dict[str, int]
    text: str


def _classify(msg: InboxMessage) -> str:
    if "needs_reply" in msg.tags:
        return "needs_reply"
    if msg.important:
        return "important"
    return "fyi"


def compose_inbox_digest(
    messages: list[InboxMessage],
    *,
    top_n: int = 5,
    now: datetime | None = None,
) -> InboxDigest:
    """Group emails and produce a deterministic digest.

    Categories:
      * ``needs_reply`` — tagged or marked important
      * ``important``   — important, no reply tag yet
      * everything else counted in the domain breakdown
    """
    moment = now or datetime.now(timezone.utc)
    by_domain: Counter[str] = Counter()
    needs: list[InboxMessage] = []
    important: list[InboxMessage] = []

    for msg in messages:
        by_domain[msg.sender_domain] += 1
        if msg.age_hours == 0.0:
            msg.age_hours = max(
                0.0,
                (moment - msg.received_at).total_seconds() / 3600.0,
            )
        cat = _classify(msg)
        if cat == "needs_reply":
            needs.append(msg)
        elif cat == "important" and msg not in needs:
            important.append(msg)

    needs.sort(key=lambda m: m.received_at)
    important.sort(key=lambda m: m.received_at)

    lines: list[str] = [
        f"Inbox: {len(messages)} new — {len(needs)} need reply, {len(important)} important",
    ]
    if needs:
        lines.append("Reply queue:")
        for msg in needs[:top_n]:
            lines.append(f"  • {msg.sender_domain} — {msg.subject}")
    if important:
        lines.append("Important, no tag:")
        for msg in important[:top_n]:
            lines.append(f"  • {msg.sender_domain} — {msg.subject}")
    if by_domain:
        top_domains = by_domain.most_common(3)
        domain_str = ", ".join(f"{d}={n}" for d, n in top_domains)
        lines.append(f"Top senders: {domain_str}")

    return InboxDigest(
        total=len(messages),
        needs_reply=tuple(needs),
        important=tuple(important),
        by_domain=dict(by_domain),
        text="\n".join(lines),
    )


async def send_inbox_zero(user_id: str, messages: list[InboxMessage]) -> bool:
    """Send the inbox digest through the engine.

    Returns True on a successful engine send, False when no
    context is registered (caller falls back to direct send).
    """
    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False

    digest = compose_inbox_digest(messages)

    sig = ProactiveSignal(
        id=f"inbox_zero:{user_id}:{int(datetime.now(timezone.utc).timestamp())}",
        user_id=user_id,
        kind=SignalKind.ROUTINE,
        title=f"Inbox: {digest.total} new",
        body=digest.text,
        urgency=Urgency.LOW,
        # ROUTINE → need to clear the threshold; use 0.95.
        value=0.95,
        confidence=0.95,
        interruption_cost=0.1,
        source="inbox_zero",
        metadata={
            "target_id": user_id,
            "needs_reply_count": len(digest.needs_reply),
            "important_count": len(digest.important),
        },
    )
    decision = await ctx.adapter.dispatch(sig)
    logger.info(
        "inbox_zero: user=%s needs=%d important=%d verdict=%s stage=%s",
        user_id,
        len(digest.needs_reply),
        len(digest.important),
        decision.verdict.value,
        decision.stage,
    )
    return True
