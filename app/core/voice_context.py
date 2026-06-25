"""Voice context engine.

Tracks per-session voice state so the persona + proactive
subsystems have a coherent picture of the user's spoken context
without re-reading the raw audio stream every turn.

The engine is intentionally **stateless across processes**: the
:class:`VoiceContextEngine` is constructed fresh inside the
:class:`app.voice.pipeline.VoicePipeline` and lives only as long
as the active listening session.  When the wake-word goes quiet
the engine is reset.

What it tracks
--------------

* ``speaker_id`` — the resolved speaker identity from
  ``app.voice.speaker_id``.  ``None`` when the speaker is
  unrecognised (anonymous / first contact).
* ``mood`` — a coarse label ``"calm" | "engaged" | "tired" |
  "frustrated"`` inferred from the latency / energy / pitch of
  the last utterance.  ``"neutral"`` when no signal is available.
* ``command_history`` — the rolling list of recent commands
  (capped at ``history_limit``) so follow-ups ("and also ...")
  can resolve against the previous intent.
* ``ambient_noise_db`` — the running estimate of the ambient
  noise level in dBFS, updated from the wake-word engine.
* ``last_active_at`` — the monotonic timestamp of the most
  recent user utterance (Unix epoch seconds).  Used by the
  proactive loop to decide whether the user is "in the room"
  vs. away.

The engine is consulted by:

  * :class:`app.core.soul_engine.SoulEngine` — picks the
    greeting style / TTS voice based on mood + recency.
  * :class:`app.core.context_awareness.ContextAwareness` —
    folds voice state into the merged context snapshot.
  * :class:`app.core.proactive_intelligence.ProactiveIntelligence` —
    gates voice-channel proactive pushes on the ambient noise
    level (no use shouting over a vacuum cleaner).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

logger = logging.getLogger(__name__)


# ── Mood label set ─────────────────────────────────────────────────────


#: Allowed mood labels.  Any string not in this set is rejected
#: by :meth:`VoiceContextEngine.record_mood` and falls back to
#: ``"neutral"``.
VALID_MOODS = frozenset({"neutral", "calm", "engaged", "tired", "frustrated"})


# ── Snapshot ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class VoiceContextSnapshot:
    """Immutable view of the voice engine state at a point in time."""

    speaker_id: str | None
    mood: str
    ambient_noise_db: float
    last_active_at: float
    command_history: tuple[str, ...]
    session_started_at: float

    def is_recent(
        self,
        *,
        within_seconds: float = 30.0,
        now: float | None = None,
    ) -> bool:
        """True iff the last utterance was within ``within_seconds``.

        Used by the proactive loop to gate "in the room" pushes.
        ``now`` is accepted so tests with a fake clock can pin
        the comparison; production callers leave it ``None``
        and the method reads ``time.time()``.
        """
        reference = now if now is not None else time.time()
        return (reference - self.last_active_at) <= within_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "mood": self.mood,
            "ambient_noise_db": self.ambient_noise_db,
            "last_active_at": self.last_active_at,
            "command_history": list(self.command_history),
            "session_started_at": self.session_started_at,
        }


# ── Engine ─────────────────────────────────────────────────────────────


class VoiceContextEngine:
    """In-process voice-session state.

    Thread-safety: every mutator takes the GIL (CPython) and the
    state is plain Python objects; the engine is intended for a
    single voice pipeline thread.  Concurrent reads from the
    ambient loop are safe because each read returns a fresh
    snapshot dataclass.
    """

    DEFAULT_HISTORY_LIMIT = 16

    def __init__(
        self,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        clock: Any = None,
    ) -> None:
        self._history: Deque[str] = deque(maxlen=max(1, history_limit))
        self._speaker_id: str | None = None
        self._mood: str = "neutral"
        self._ambient_noise_db: float = -60.0  # quiet room default
        self._last_active_at: float = 0.0
        self._session_started_at: float = (clock or time.time)()
        self._clock = clock or time.time

    # ── Mutators (called by the voice pipeline) ────────────────────

    def record_command(self, text: str) -> None:
        """Append ``text`` to the rolling command history."""
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._history.append(cleaned)
        self._last_active_at = self._clock()

    def set_speaker(self, speaker_id: str | None) -> None:
        """Update the resolved speaker identity.

        ``None`` is allowed and means "anonymous / unrecognised".
        The previous identity is overwritten; the persona engine
        uses the new value on the next snapshot.
        """
        self._speaker_id = speaker_id or None

    def record_mood(self, mood: str) -> None:
        """Update the user's mood label.

        Unknown labels are coerced to ``"neutral"`` with a
        debug log so a future persona heuristic can be added
        without breaking older snapshots.
        """
        candidate = (mood or "").strip().lower()
        if candidate not in VALID_MOODS:
            logger.debug("Ignoring unknown mood label %r", mood)
            return
        self._mood = candidate

    def update_ambient_noise(self, db: float) -> None:
        """Update the rolling ambient noise estimate (dBFS).

        Negative values are quieter than the digital floor;
        ``-60.0`` is the default "quiet room" baseline.  Values
        outside ``[-100, 0]`` are clamped to the valid range.
        """
        clamped = max(-100.0, min(0.0, float(db)))
        self._ambient_noise_db = clamped

    # ── Read API ────────────────────────────────────────────────────

    def snapshot(self) -> VoiceContextSnapshot:
        """Return an immutable point-in-time view of the state."""
        return VoiceContextSnapshot(
            speaker_id=self._speaker_id,
            mood=self._mood,
            ambient_noise_db=self._ambient_noise_db,
            last_active_at=self._last_active_at,
            command_history=tuple(self._history),
            session_started_at=self._session_started_at,
        )

    def last_command(self) -> str | None:
        """Return the most recent command, or ``None`` if empty."""
        return self._history[-1] if self._history else None

    def recent_commands(self, n: int = 3) -> tuple[str, ...]:
        """Return the last ``n`` commands in chronological order."""
        if n <= 0:
            return ()
        return tuple(list(self._history)[-n:])

    # ── Session lifecycle ───────────────────────────────────────────

    def reset(self) -> None:
        """Wipe all session state.  Called when the wake-word
        goes quiet for longer than the silence threshold."""
        self._history.clear()
        self._speaker_id = None
        self._mood = "neutral"
        self._ambient_noise_db = -60.0
        self._last_active_at = 0.0
        self._session_started_at = self._clock()


# ── Singleton accessor ─────────────────────────────────────────────────


_voice_context_singleton: VoiceContextEngine | None = None


def get_voice_context() -> VoiceContextEngine:
    """Return the process-wide :class:`VoiceContextEngine`.

    Lazy-initialised on first call.  The voice pipeline calls
    :meth:`VoiceContextEngine.reset` when the wake-word session
    ends so the singleton reflects the current session.
    """
    global _voice_context_singleton
    if _voice_context_singleton is None:
        _voice_context_singleton = VoiceContextEngine()
    return _voice_context_singleton


def reset_voice_context_for_tests() -> None:  # pragma: no cover - test seam
    """Drop the cached singleton.  Used by the test fixtures."""
    global _voice_context_singleton
    _voice_context_singleton = None
