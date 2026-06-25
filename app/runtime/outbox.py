"""Outbox — durable queue for outbound side effects.

When the system is offline (or any side-effecting path is unavailable)
we must not lose the user's intent.  Every outbound action that *might*
go over the network goes through this outbox first:

  1. The caller computes an idempotency key (e.g. ``"send:<chat_id>:<intent>:<hash>"``).
  2. The outbox writes an entry to a JSONL append-only file on disk.
  3. The outbox tries to deliver the action immediately.
  4. If delivery fails, the entry stays in the file and the outbox
     retries when connectivity returns.
  5. On success the entry is removed from the file (or marked sent).

Properties:

  * **At-least-once delivery** — duplicates are possible, hence the
    idempotency key.  Receivers should dedupe on the key.
  * **Ordered drain** — within a single outbox instance, entries are
    drained in the order they were enqueued.  Across instances each
    outbox is independent.
  * **Crash-safe** — the file is opened in append mode and fsync'd
    on every enqueue.  A crash between enqueue and fsync loses the
    last entry, not anything else.
  * **Small** — no third-party deps.  Pure stdlib.

The outbox is intentionally synchronous-friendly: enqueue returns a
record immediately and delivery is fire-and-forget by default.  Tests
can drive delivery manually with :meth:`Outbox.drain_once` to avoid
race conditions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────

#: Cap on the number of in-flight retries per entry.
MAX_ATTEMPTS = 8

#: Backoff factor (seconds) — attempt N waits ``BASE_BACKOFF * 2 ** (N-1)``
#: seconds before the next retry, capped at 600 s.
BASE_BACKOFF_S = 1.0
MAX_BACKOFF_S = 600.0


# ── Records ─────────────────────────────────────────────────────────


@dataclass
class OutboxEntry:
    """One pending action in the outbox."""

    id: str
    idempotency_key: str
    channel: str          # e.g. "telegram", "slack", "voice", "mcp"
    target: str           # free-form — chat id, url, etc.
    action: str           # free-form verb — "send_text", "post", ...
    payload: dict[str, Any] = field(default_factory=dict)
    enqueued_at: float = 0.0
    attempts: int = 0
    last_attempt_at: float = 0.0
    last_error: str = ""
    state: str = "pending"  # "pending" | "sending" | "sent" | "failed"
    sent_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutboxEntry":
        # Tolerate older records that don't have all fields.
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex),
            idempotency_key=str(d.get("idempotency_key", "")),
            channel=str(d.get("channel", "")),
            target=str(d.get("target", "")),
            action=str(d.get("action", "")),
            payload=dict(d.get("payload") or {}),
            enqueued_at=float(d.get("enqueued_at", 0.0)),
            attempts=int(d.get("attempts", 0)),
            last_attempt_at=float(d.get("last_attempt_at", 0.0)),
            last_error=str(d.get("last_error", "")),
            state=str(d.get("state", "pending")),
            sent_at=float(d.get("sent_at", 0.0)),
        )

    def next_retry_in(self) -> float:
        """How long until we should try this entry again."""
        if self.attempts <= 0:
            return 0.0
        delay = BASE_BACKOFF_S * (2 ** (self.attempts - 1))
        return min(delay, MAX_BACKOFF_S)


# ── Outbox ──────────────────────────────────────────────────────────


# A sender is an async function that performs the side effect.  It
# raises on failure; success returns normally.  The outbox treats a
# raised exception as a transient failure (and will retry).
Sender = Callable[[OutboxEntry], Awaitable[None]]


class Outbox:
    """Durable outbox with reconnect drain.

    Parameters
    ----------
    path:
        JSONL file the outbox persists to.  If absent, the outbox
        runs in-memory only (useful for tests).
    sender:
        Async function that actually performs the side effect.  If
        ``None`` the outbox only persists entries; the caller drives
        delivery manually.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        sender: Sender | None = None,
        *,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._path: Optional[Path] = Path(path) if path else None
        self._sender = sender
        self._now = now_fn
        self._entries: list[OutboxEntry] = []
        self._lock = asyncio.Lock()
        self._by_key: dict[str, OutboxEntry] = {}
        # Senders consulted by channel name.  When a sender is set on
        # the constructor, it's used for *every* channel unless the
        # caller registers a more specific one via :meth:`register_sender`.
        self._channel_senders: dict[str, Sender] = {}
        self._load()

    # ── Sender registration ──────────────────────────────────────

    def register_sender(self, channel: str, sender: Sender) -> None:
        """Register a per-channel sender.  Overrides the default."""
        self._channel_senders[channel.lower()] = sender

    def _resolve_sender(self, entry: OutboxEntry) -> Optional[Sender]:
        if entry.channel.lower() in self._channel_senders:
            return self._channel_senders[entry.channel.lower()]
        return self._sender

    # ── Enqueue ───────────────────────────────────────────────────

    async def enqueue(
        self,
        *,
        idempotency_key: str,
        channel: str,
        target: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> OutboxEntry:
        """Add a new entry.  Idempotent on the key.

        If an entry with the same key is already pending or sent, we
        return the existing one (the caller can decide to wait for
        ``state == "sent"``).
        """
        async with self._lock:
            existing = self._by_key.get(idempotency_key)
            if existing is not None:
                return existing
            entry = OutboxEntry(
                id=uuid.uuid4().hex,
                idempotency_key=idempotency_key,
                channel=channel,
                target=target,
                action=action,
                payload=dict(payload or {}),
                enqueued_at=self._now(),
            )
            self._entries.append(entry)
            self._by_key[idempotency_key] = entry
            self._append_to_disk(entry)
            return entry

    # ── Drain ─────────────────────────────────────────────────────

    async def drain_once(self, *, force: bool = False) -> dict[str, int]:
        """Attempt to send every pending entry once.

        Returns a small report: ``{"sent": N, "failed": M, "skipped": K}``.
        Skipped entries are still in their backoff window.

        ``force=True`` ignores the backoff window — use it when you
        know connectivity has just returned and you want to clear
        the backlog in one pass.
        """
        sent = 0
        failed = 0
        skipped = 0
        now = self._now()
        async with self._lock:
            # We deliver in enqueue order.  Snapshot a copy of the
            # entries so callbacks can re-enqueue without mutating
            # the list mid-iteration.
            snapshot = list(self._entries)
        for entry in snapshot:
            if entry.state in ("sent",):
                continue
            if entry.state == "sending":
                # Another drain is already on it; skip.
                skipped += 1
                continue
            if (
                not force
                and entry.last_attempt_at
                and entry.last_attempt_at + entry.next_retry_in() > now
            ):
                skipped += 1
                continue
            ok = await self._try_send(entry)
            if ok:
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed, "skipped": skipped}

    async def drain_until_drained(
        self, max_passes: int = 5
    ) -> dict[str, int]:
        """Run :meth:`drain_once` repeatedly until nothing is left or
        we hit ``max_passes`` iterations.

        This is what you call when connectivity comes back.  We pass
        ``force=True`` after the first pass so a freshly-recovered
        link is not bottlenecked by per-entry backoff windows.
        """
        total = {"sent": 0, "failed": 0, "skipped": 0}
        for i in range(max_passes):
            report = await self.drain_once(force=(i > 0))
            total["sent"] += report["sent"]
            total["failed"] += report["failed"]
            total["skipped"] += report["skipped"]
            # Stop when there's nothing left to do.
            if not self._has_pending():
                break
            # Stop if we did no work this pass — further passes won't
            # help either (we're either rate-limited, the sender is
            # always-failing, or there are no candidates).
            if report["sent"] == 0 and report["failed"] == 0 and report["skipped"] == 0:
                break
        return total

    def _has_pending(self) -> bool:
        return any(e.state == "pending" for e in self._entries)

    # ── Query ─────────────────────────────────────────────────────

    def list(self, *, state: str | None = None) -> list[OutboxEntry]:
        """Return a copy of the entries.  Optional state filter."""
        if state is None:
            return list(self._entries)
        return [e for e in self._entries if e.state == state]

    def get(self, entry_id: str) -> Optional[OutboxEntry]:
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    def by_key(self, idempotency_key: str) -> Optional[OutboxEntry]:
        return self._by_key.get(idempotency_key)

    def __len__(self) -> int:
        return len(self._entries)

    def pending_count(self) -> int:
        return sum(1 for e in self._entries if e.state in ("pending", "sending"))

    # ── Internals ─────────────────────────────────────────────────

    async def _try_send(self, entry: OutboxEntry) -> bool:
        sender = self._resolve_sender(entry)
        if sender is None:
            return False
        entry.state = "sending"
        entry.attempts += 1
        entry.last_attempt_at = self._now()
        try:
            await sender(entry)
        except Exception as exc:  # noqa: BLE001
            entry.state = "pending"
            entry.last_error = f"{exc.__class__.__name__}: {exc}"
            logger.warning(
                "outbox send failed: key=%s err=%s (attempt %d)",
                entry.idempotency_key,
                entry.last_error,
                entry.attempts,
            )
            if entry.attempts >= MAX_ATTEMPTS:
                entry.state = "failed"
            self._append_to_disk(entry)
            return False
        entry.state = "sent"
        entry.sent_at = self._now()
        entry.last_error = ""
        self._append_to_disk(entry)
        logger.info(
            "outbox sent: key=%s channel=%s target=%s (attempts=%d)",
            entry.idempotency_key,
            entry.channel,
            entry.target,
            entry.attempts,
        )
        return True

    # ── Persistence ──────────────────────────────────────────────

    def _append_to_disk(self, entry: OutboxEntry) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            logger.error("outbox persist failed: %s", exc)

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            with self._path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry = OutboxEntry.from_dict(d)
                    # The same entry may appear on multiple lines
                    # (we append on every state change so a crash
                    # mid-drain doesn't lose the in-flight status).
                    # The last write wins.
                    key = entry.idempotency_key
                    if not key:
                        continue
                    if key in self._by_key:
                        # Replace the older copy in place.
                        old = self._by_key[key]
                        try:
                            idx = self._entries.index(old)
                            self._entries[idx] = entry
                        except ValueError:
                            self._entries.append(entry)
                    else:
                        self._entries.append(entry)
                    self._by_key[key] = entry
        except OSError as exc:
            logger.warning("outbox load failed: %s", exc)


# ── Helpers ────────────────────────────────────────────────────────


def make_idempotency_key(*parts: Any) -> str:
    """Build a stable idempotency key from a few parts.

    ``None`` parts are skipped.  Booleans, ints, strings, and dicts
    (via ``json.dumps(sort_keys=True)``) are accepted.
    """
    out_parts: list[str] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, (str, int, float, bool)):
            out_parts.append(str(p))
        elif isinstance(p, dict):
            out_parts.append(json.dumps(p, sort_keys=True, default=str))
        else:
            out_parts.append(str(p))
    return ":".join(out_parts)


__all__ = [
    "BASE_BACKOFF_S",
    "MAX_ATTEMPTS",
    "MAX_BACKOFF_S",
    "Outbox",
    "OutboxEntry",
    "Sender",
    "get_outbox",
    "reset_outbox_for_tests",
    "make_idempotency_key",
]


# ── Process-wide singleton ───────────────────────────────────────────
#
# BotSignal (and other consumers) wire through the same outbox
# instance so a single JSONL file backs every outbound side effect
# in the process.  The path defaults to ``~/.raven/runtime/outbox.jsonl``
# but can be overridden with ``$RAVEN_OUTBOX_PATH`` for tests and
# for users who want the file in a different location.
#
# The env var is re-read on every :func:`get_outbox` call so tests
# that swap the env var (via ``monkeypatch.setenv`` or our
# ``isolated_outbox`` autouse fixture) take effect immediately,
# without needing to re-import the module.


def _resolve_default_path() -> Path:
    return Path(
        os.environ.get("RAVEN_OUTBOX_PATH")
        or (Path.home() / ".raven" / "runtime" / "outbox.jsonl")
    )


_outbox_singleton: Outbox | None = None


def get_outbox() -> Outbox:
    """Return the process-wide Outbox instance.

    Lazy-initialised on first call.  The singleton is created
    with no default sender; callers (e.g. BotSignal) register
    per-channel senders as platforms come online.
    """
    global _outbox_singleton
    if _outbox_singleton is None:
        _outbox_singleton = Outbox(path=_resolve_default_path())
    return _outbox_singleton


def reset_outbox_for_tests() -> None:
    """Drop the cached singleton.  Used by the test fixtures."""
    global _outbox_singleton
    _outbox_singleton = None
