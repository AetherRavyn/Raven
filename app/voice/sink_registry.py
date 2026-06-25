"""SinkRegistry — fan-out TTS playback across all sinks for a user.

v33 refactor.  This module is the *dispatcher*: the rest of
RAVEN (the voice pipeline, the Telegram voice sender, the
``MessageOrchestrator``'s reply path) hands audio bytes to
``get_sink_registry().play(user_id, audio_path)`` and the
registry takes care of:

1. Reading the audio file into ``bytes`` *once* (so a slow sink
   never races with a fast sink's cleanup of the same file).
2. Looking up every sink registered for ``user_id``.
3. Dispatching to each sink via :func:`asyncio.gather`, so one
   slow sink does not block the others.
4. Isolating per-sink exceptions — a broken browser WS does
   not silence the local speaker.

The pattern follows the dispatch-table convention used elsewhere
in RAVEN (e.g. :mod:`app.web.life_dashboard`, :mod:`app.web.endpoints.cron`):
module-level singleton, lazy default, ``reset_*_for_tests`` helper.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from typing import Iterable

from app.voice.sinks import (
    LocalSoundDeviceSink,
    NoOpSink,
    VoiceSink,
    WebSocketVoiceSink,
    read_wav_sample_rate,
)

logger = logging.getLogger(__name__)


class SinkRegistry:
    """Dispatch TTS audio to every sink registered for a user."""

    def __init__(self) -> None:
        # user_id -> ordered list of sinks (insertion order).
        # defaultdict so first register on a new user is cheap.
        self._sinks: dict[str, list[VoiceSink]] = defaultdict(list)
        # Per-user lock to serialise registry mutations; reads
        # use the existing list reference.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    def register(self, user_id: str, sink: VoiceSink) -> None:
        """Attach *sink* to *user_id*'s dispatch list."""
        existing = self._sinks[user_id]
        if sink in existing:
            return
        existing.append(sink)
        logger.debug(
            "SinkRegistry: registered %s for user=%s (total=%d)",
            type(sink).__name__, user_id, len(existing),
        )
        # Fire-and-forget open() — no event loop in __init__.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(sink.open())
        except RuntimeError:
            pass

    def unregister(self, user_id: str, sink: VoiceSink) -> None:
        """Remove *sink* from *user_id*'s dispatch list."""
        existing = self._sinks.get(user_id)
        if not existing:
            return
        try:
            existing.remove(sink)
        except ValueError:
            return
        logger.debug(
            "SinkRegistry: unregistered %s for user=%s (remaining=%d)",
            type(sink).__name__, user_id, len(existing),
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(sink.close())
        except RuntimeError:
            pass
        if not existing:
            self._sinks.pop(user_id, None)
            self._locks.pop(user_id, None)

    def sinks_for(self, user_id: str) -> list[VoiceSink]:
        """Return a snapshot of the registered sinks for *user_id*."""
        return list(self._sinks.get(user_id, ()))

    def all_users(self) -> Iterable[str]:
        return list(self._sinks.keys())

    async def play(
        self, user_id: str, audio_path: str | bytes
    ) -> int:
        """Dispatch *audio_path* (file path or raw bytes) to every
        sink registered for *user_id*.  Returns the number of sinks
        that were attempted (regardless of success).

        Reads the audio into ``bytes`` *once* so a slow sink's
        cleanup can never race with a fast sink's read.  Per-sink
        exceptions are caught + logged; one failing sink does not
        cancel the others.
        """
        if isinstance(audio_path, bytes):
            audio_bytes = audio_path
        else:
            try:
                with open(audio_path, "rb") as fh:
                    audio_bytes = fh.read()
            except OSError as exc:
                logger.debug(
                    "SinkRegistry: cannot read audio %r: %s",
                    audio_path, exc,
                )
                return 0
            # The synth path writes a tempfile in ``workspace/`` and
            # the caller used to ``os.unlink`` after the local sink
            # read — but with multiple sinks (local + browser WS +
            # edge), the unlink could fire before a slow sink
            # finished reading.  Read-first-then-unlink here removes
            # that race for every caller uniformly.
            try:
                os.unlink(audio_path)
            except OSError:
                pass
        sample_rate = read_wav_sample_rate(audio_bytes)
        return await self.play_bytes(user_id, audio_bytes, sample_rate)

    async def play_bytes(
        self, user_id: str, audio_bytes: bytes, sample_rate: int
    ) -> int:
        sinks = self.sinks_for(user_id)
        if not sinks:
            logger.debug(
                "SinkRegistry: no sinks registered for user=%s "
                "(audio bytes=%d)",
                user_id, len(audio_bytes),
            )
            return 0

        async def _safe_play(sink: VoiceSink) -> None:
            try:
                await sink.play(audio_bytes, sample_rate)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "SinkRegistry: %s play raised (user=%s): %s",
                    type(sink).__name__, user_id, exc,
                )

        # gather (not as_completed) so a slow sink does not
        # extend the total wall time — every sink gets the same
        # 1-second WAV in parallel.
        await asyncio.gather(*(_safe_play(s) for s in sinks))
        return len(sinks)

    def clear(self) -> None:
        """Drop every sink and every user.  Tests only."""
        self._sinks.clear()
        self._locks.clear()


# ──────────────────────────────────────────────────────────────────────
# Singleton + test reset
# ──────────────────────────────────────────────────────────────────────

_registry_singleton: SinkRegistry | None = None


def get_sink_registry() -> SinkRegistry:
    """Return the process-global :class:`SinkRegistry`.

    Lazy-instantiated so test fixtures can replace it via
    :func:`reset_sink_registry_for_tests` before any code grabs
    a reference.
    """
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = SinkRegistry()
    return _registry_singleton


def reset_sink_registry_for_tests() -> None:
    """Tear down the singleton so the next ``get_sink_registry()``
    call returns a fresh empty :class:`SinkRegistry`.  Tests call
    this in their setup / autouse fixture.
    """
    global _registry_singleton
    _registry_singleton = None


__all__ = [
    "SinkRegistry",
    "get_sink_registry",
    "reset_sink_registry_for_tests",
    "LocalSoundDeviceSink",
    "WebSocketVoiceSink",
    "NoOpSink",
]
