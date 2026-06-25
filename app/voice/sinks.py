"""VoiceSink — pluggable output devices for RAVEN TTS.

v33 refactor.  Before this module existed, TTS playback was a
hardcoded ``sounddevice.play(...)`` call buried inside
``VoicePipeline._speak_streaming``.  That worked for the on-device
case but blocked every other path — the dashboard browser, a
remote edge node, a phone over a future bridge.

This file defines the *contract* every output device must satisfy.
``SinkRegistry`` (in :mod:`app.voice.sink_registry`) owns one or
more sinks per ``user_id`` and fans out a single TTS stream to
all of them.

Design constraints (v33):
- Sinks are async.  ``play(audio_bytes, sample_rate)`` is awaited
  by the registry; an implementation may schedule work in a thread
  but must return promptly.
- Sinks must not raise.  The registry wraps every ``play`` call in
  a try/except; a broken sink logs and is *not* unregistered
  automatically (the next successful call may recover).
- ``audio_bytes`` is always a fully-decoded WAV blob (Piper's
  native output).  No codec negotiation; the browser's
  ``<audio type="audio/wav">`` element handles it natively.
- The ``user_id`` passed at construction is the one the registry
  uses to route.  Multiple sinks for the same user are expected
  (local speaker + browser tab simultaneously).
"""
from __future__ import annotations

import abc
import asyncio
import logging
import struct
import threading
import wave
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class VoiceSink(abc.ABC):
    """Abstract base for TTS output destinations.

    Subclasses must implement :meth:`play`.  Optional hooks:
    :meth:`open` (called when the registry first registers the
    sink) and :meth:`close` (called on unregister).  Both default
    to no-ops.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    @abc.abstractmethod
    async def play(
        self, audio_bytes: bytes, sample_rate: int
    ) -> None:
        """Play or forward the audio.  Never raise."""

    async def open(self) -> None:  # noqa: D401
        """Optional lifecycle hook — default no-op."""
        return None

    async def close(self) -> None:  # noqa: D401
        """Optional lifecycle hook — default no-op."""
        return None


# ──────────────────────────────────────────────────────────────────────
# Concrete sinks
# ──────────────────────────────────────────────────────────────────────


class LocalSoundDeviceSink(VoiceSink):
    """Play audio out of the local sound card via ``sounddevice``.

    This is the default sink for the on-device pipeline.  It
    replaces the inline ``sd.play/sd.wait`` block that used to
    live in ``VoicePipeline._speak_streaming``.

    Concurrency: ``sounddevice.play`` is *not* re-entrant — calling
    it twice queues the second call.  The implementation uses an
    ``_idle`` ``threading.Event`` to drop overlapping plays
    (barge-in semantics: the new reply wins, the previous is
    interrupted).  A future cycle can change this to a
    ``sounddevice.OutputStream`` for proper overlap, but for v33
    the barge-in-first behaviour matches the user expectation.
    """

    def __init__(self, user_id: str) -> None:
        super().__init__(user_id)
        self._idle = threading.Event()
        self._idle.set()
        self._stop = threading.Event()

    async def play(
        self, audio_bytes: bytes, sample_rate: int
    ) -> None:
        if self._stop.is_set():
            return
        # Mark busy, drop the previous play, then play the new one.
        # The previous play is implicitly interrupted because
        # sounddevice.stop() is called on the next iteration.
        if not self._idle.is_set():
            try:
                import sounddevice as sd  # noqa: PLC0415

                sd.stop()
            except Exception:  # noqa: BLE001
                pass
        self._idle.clear()
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._blocking_play, audio_bytes, sample_rate
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "LocalSoundDeviceSink play failed (user=%s): %s",
                self.user_id, exc,
            )
        finally:
            self._idle.set()

    def _blocking_play(
        self, audio_bytes: bytes, sample_rate: int
    ) -> None:
        try:
            import numpy as np  # noqa: PLC0415
            import sounddevice as sd  # noqa: PLC0415
        except ImportError as exc:
            logger.debug("sounddevice unavailable: %s", exc)
            return

        try:
            with wave.open(BytesIO(audio_bytes), "rb") as wf:
                sample_width = wf.getsampwidth()
                n_channels = wf.getnchannels()
                wav_rate = wf.getframerate()
                pcm = wf.readframes(wf.getnframes())
            if sample_width != 2:
                logger.debug(
                    "LocalSoundDeviceSink: unsupported sample width %d",
                    sample_width,
                )
                return
            audio = np.frombuffer(pcm, dtype=np.int16)
            # sounddevice plays float32 in [-1, 1]; convert.
            audio = audio.astype(np.float32) / 32768.0
            if n_channels > 1:
                audio = audio.reshape(-1, n_channels)
            sd.play(audio, wav_rate or sample_rate)
            sd.wait()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "LocalSoundDeviceSink blocking play error: %s", exc
            )

    async def close(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd  # noqa: PLC0415

            sd.stop()
        except Exception:  # noqa: BLE001
            pass


class WebSocketVoiceSink(VoiceSink):
    """Forward audio to a connected browser tab over WebSocket.

    Binary frame layout: 4-byte little-endian sample-rate prefix +
    raw WAV bytes.  The browser's ``voice.js`` decodes the prefix
    and constructs the right ``AudioContext`` for the payload.

    Why a sample-rate prefix?  Piper voices vary (22 050 Hz for
    ``en_US-lessac-medium``; 16 000 Hz for some smaller voices).
    A fixed prefix lets the client choose the correct
    ``AudioContext`` rate without a separate metadata fetch.

    The FastAPI worker serves the WebSocket on the asyncio loop
    already; ``send_bytes`` is coroutine-safe.  No thread
    marshalling is required.
    """

    HEADER_FORMAT = "<I"  # uint32 little-endian
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(
        self, user_id: str, websocket: "WebSocket", connection_id: str
    ) -> None:
        super().__init__(user_id)
        self._ws = websocket
        self._connection_id = connection_id
        self._closed = False

    async def play(
        self, audio_bytes: bytes, sample_rate: int
    ) -> None:
        if self._closed:
            return
        try:
            header = struct.pack(self.HEADER_FORMAT, sample_rate)
            await self._ws.send_bytes(header + audio_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "WebSocketVoiceSink send failed (user=%s cid=%s): %s",
                self.user_id, self._connection_id, exc,
            )
            self._closed = True

    async def close(self) -> None:
        self._closed = True
        # Do NOT call ws.close() here — FastAPI manages the
        # connection lifecycle from the WS handler scope.  We
        # just mark ourselves so subsequent plays no-op.


class NoOpSink(VoiceSink):
    """Placeholder for future output channels (edge node, MQTT, etc.).

    v33 ships this so the registry can register a slot for
    remote users who have no local audio path.  v34+ can subclass
    ``NoOpSink`` to add the real protocol — the registry contract
    does not change.
    """

    def __init__(self, user_id: str, name: str = "noop") -> None:
        super().__init__(user_id)
        self.name = name
        self.played: list[tuple[bytes, int]] = []

    async def play(
        self, audio_bytes: bytes, sample_rate: int
    ) -> None:
        # Record the play for test introspection, but do nothing.
        self.played.append((audio_bytes, sample_rate))


# ──────────────────────────────────────────────────────────────────────
# Helper: read a WAV file's sample rate from its header.
# ──────────────────────────────────────────────────────────────────────


def read_wav_sample_rate(audio_bytes: bytes) -> int:
    """Return the sample rate encoded in a WAV blob's header.

    Returns 0 if the bytes are not a valid WAV.  Used by
    :mod:`app.voice.tts` to attach the right rate to a
    :class:`SignalPayload.audio_path` and by
    :class:`LocalSoundDeviceSink` to pick the sound card rate.
    """
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wf:
            return wf.getframerate()
    except Exception:  # noqa: BLE001
        return 0
