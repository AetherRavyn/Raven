"""Per-session conversation manager with SQLite persistence.

A :class:`ConversationManager` is the runtime-facing wrapper
around :class:`WorkingMemory`, :class:`Compressor`, and
:class:`FollowUpResolver`.  It maps a session id to a
working memory and exposes three operations the runtime
calls on every turn:

  * :meth:`ingest_turn`  — add a turn to the working memory
  * :meth:`context_for_prompt` — render the working memory
    as a string the runtime can prepend to the LLM prompt
  * :meth:`resolve_reference` — turn a "that thing"
    reference into a specific prior turn

Persistence is automatic: every turn is checkpointed to SQLite,
and sessions are restored on first access. Old sessions (>24h
idle) are pruned periodically.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.core.conversation.compression import (
    Compressed,
    Compressor,
    apply_to_working_memory,
    deterministic_summary,
)
from app.core.conversation.memory import (
    Turn,
    WorkingMemory,
)
from app.core.conversation.persistence import ConversationPersistence
from app.core.conversation.resolver import (
    FollowUpResolver,
    Resolved,
)

logger = logging.getLogger(__name__)


SummaryFn = Callable[[list[Turn], str], str]


class ConversationManager:
    """Process-singleton (or per-runtime) conversation state.

    Holds:
      * a map of session_id → WorkingMemory
      * a single Compressor (shared across sessions, stateless)
      * the current summary function (default deterministic)
      * SQLite persistence for crash recovery

    Thread-safe (RLock everywhere). Auto-checkpoints to SQLite.
    """

    def __init__(
        self,
        *,
        compressor: Compressor | None = None,
        window_size: int = 6,
        compress_threshold_multiplier: int = 2,
        summary_fn: SummaryFn | None = None,
        persistence: ConversationPersistence | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._memories: dict[str, WorkingMemory] = {}
        self._restored: set[str] = set()  # sessions just restored from SQLite
        self._dirty: set[str] = set()  # sessions needing checkpoint
        self._compressor = compressor or Compressor(window_size=window_size)
        self._window_size = window_size
        self._compress_threshold = window_size * compress_threshold_multiplier
        self._summary_fn: SummaryFn = summary_fn or deterministic_summary
        self._compressor.summary_fn = self._summary_fn
        self._persistence = persistence  # None = no persistence (default)
        self._restored: set[str] = set()
        self._prune_counter = 0

    # ---- configuration ----

    def set_summary_fn(self, fn: SummaryFn) -> None:
        with self._lock:
            self._summary_fn = fn
            self._compressor.summary_fn = fn

    def set_window_size(self, window_size: int) -> None:
        with self._lock:
            self._window_size = window_size
            self._compress_threshold = window_size * 2
            self._compressor.window_size = window_size

    # ---- session lifecycle ----

    def get_or_create(self, session_id: str, user_id: str = "") -> WorkingMemory:
        with self._lock:
            wm = self._memories.get(session_id)
            if wm is not None:
                return wm
            # Try restoring from SQLite (if persistence enabled)
            if self._persistence is not None:
                data = self._persistence.load(session_id)
                if data is not None:
                    wm = WorkingMemory.from_dict(data)
                    self._memories[session_id] = wm
                    self._restored.add(session_id)
                    logger.debug("Restored session %s from SQLite", session_id)
                    return wm
            wm = WorkingMemory(user_id=user_id)
            self._memories[session_id] = wm
            return wm

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._memories.pop(session_id, None)
            self._dirty.discard(session_id)
            if self._persistence is not None:
                self._persistence.delete(session_id)

    def clear_all(self) -> None:
        with self._lock:
            self._memories.clear()
            self._dirty.clear()

    def list_sessions(self) -> list[str]:
        with self._lock:
            return list(self._memories.keys())

    # ---- core operations ----

    def ingest_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str = "",
        metadata: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> Turn:
        """Add a turn to the session's working memory.

        Auto-checkpoints to SQLite after each turn.
        First turn on a restored session appends without overwrite.
        """
        wm = self.get_or_create(session_id, user_id=user_id)
        was_restored = session_id in self._restored
        if was_restored:
            self._restored.discard(session_id)
        idx = len(wm.recent_turns)
        tid = turn_id or f"{session_id}:t{idx}"
        turn = Turn(
            id=tid,
            role=role,
            content=content,
            metadata=dict(metadata or {}),
        )
        wm.add_turn(turn)
        if self._compressor.should_compress(len(wm.recent_turns)):
            self._maybe_compress_locked(wm)
        # Checkpoint — safe because wm already has restored data merged with new turn
        self._checkpoint(session_id, wm)
        return turn

    def _maybe_compress_locked(self, wm: WorkingMemory) -> Compressed | None:
        with self._lock:
            if not self._compressor.should_compress(len(wm.recent_turns)):
                return None
            result = self._compressor.compress(list(wm.recent_turns), wm.summary)
            new_summary, new_deque = apply_to_working_memory(
                result.summary,
                result.kept_turns,
                maxlen=self._window_size * 4,
            )
            wm.summary = new_summary
            wm.recent_turns = new_deque
            logger.info(
                "conversation.compress dropped=%d kept=%d summary_len=%d",
                result.dropped_count,
                len(result.kept_turns),
                len(result.summary),
            )
            return result

    def maybe_compress(self, session_id: str) -> Compressed | None:
        wm = self.get_or_create(session_id)
        result = self._maybe_compress_locked(wm)
        if result:
            self._checkpoint(session_id, wm)
        return result

    # ---- prompt construction ----

    def context_for_prompt(
        self,
        session_id: str,
        *,
        max_chars: int = 2000,
        max_facts: int = 20,
    ) -> str:
        wm = self._memories.get(session_id)
        if wm is None:
            return ""
        text = wm.context_string(max_facts=max_facts)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    def facts(self, session_id: str) -> dict[str, str]:
        wm = self._memories.get(session_id)
        return dict(wm.facts) if wm is not None else {}

    def topic(self, session_id: str) -> str | None:
        wm = self._memories.get(session_id)
        return wm.current_topic if wm is not None else None

    # ---- reference resolution ----

    def resolve_reference(
        self,
        session_id: str,
        reference: str,
    ) -> Resolved:
        wm = self._memories.get(session_id)
        if wm is None:
            return Resolved(turn=None, strategy="none", confidence=0.0)
        return FollowUpResolver(wm).resolve(reference)

    def resolve_references(
        self,
        session_id: str,
        references: list[str],
    ) -> list[Resolved]:
        wm = self._memories.get(session_id)
        if wm is None:
            return [Resolved(turn=None, strategy="none", confidence=0.0) for _ in references]
        r = FollowUpResolver(wm)
        return [r.resolve(ref) for ref in references]

    # ---- persistence ----

    def _checkpoint(self, session_id: str, wm: WorkingMemory) -> None:
        """Save working memory to SQLite. Best-effort. No-op if persistence disabled."""
        if self._persistence is None:
            return
        try:
            data = wm.to_dict()
            self._persistence.save(session_id, data, user_id=wm.user_id)
            self._dirty.discard(session_id)
        except Exception as exc:
            logger.debug("Checkpoint failed for %s: %s", session_id, exc)

    def sync(self, session_id: str | None = None) -> None:
        """Force checkpoint one or all dirty sessions."""
        with self._lock:
            if session_id:
                wm = self._memories.get(session_id)
                if wm:
                    self._checkpoint(session_id, wm)
            else:
                for sid in list(self._dirty):
                    wm = self._memories.get(sid)
                    if wm:
                        self._checkpoint(sid, wm)
        # Periodic prune (only if persistence enabled)
        if self._persistence is not None:
            self._prune_counter += 1
            if self._prune_counter >= 100:
                self._prune_counter = 0
                pruned = self._persistence.prune_old()
                if pruned:
                    logger.info("Pruned %d old conversation sessions", pruned)

    def serialize(self, session_id: str) -> dict[str, Any] | None:
        wm = self._memories.get(session_id)
        if wm is None:
            return None
        return wm.to_dict()

    def restore(self, session_id: str, data: dict[str, Any]) -> WorkingMemory:
        with self._lock:
            wm = WorkingMemory.from_dict(data)
            self._memories[session_id] = wm
            self._checkpoint(session_id, wm)
            return wm

    # ---- diagnostics ----

    def explain(self, session_id: str) -> dict[str, Any]:
        wm = self._memories.get(session_id)
        if wm is None:
            return {"session_id": session_id, "present": False}
        return {
            "session_id": session_id,
            "present": True,
            "user_id": wm.user_id,
            "summary_len": len(wm.summary),
            "recent_turns": len(wm.recent_turns),
            "facts": dict(wm.facts),
            "entities_top": dict(wm.entities.most_common(5)),
            "current_topic": wm.current_topic,
            "persisted": session_id not in self._dirty,
        }
