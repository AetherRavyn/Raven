"""Thin wrapper around the Piper-TTS local voice synthesizer.

v33 refactor.  Piper is the on-device TTS that replaces
``edge_tts`` (Microsoft cloud).  It runs onnxruntime on a local
``.onnx`` voice model and produces a 22 050 Hz mono WAV.

This module was previously 21 lines of *dead code* that
imported ``edge_tts`` — see git history for the latent bug.
v33 overwrites it with a real :class:`PiperTTS` class.

The class is intentionally tiny:
- Lazy load — the onnx kernel takes ~3 s to init on first
  ``synthesize`` call, so :class:`~app.voice.tts.synthesize`
  pays that cost once and caches the loaded voice.
- Thread-safe — Piper's onnx session is *not* thread-safe, so
  we wrap the load + synthesize in a :class:`threading.Lock`.
- Error-swallowing — the public :meth:`synthesize` returns
  ``b""`` on any exception so a missing model file does not
  break the chat path.

Why ``synthesize`` returns ``bytes`` (not a file path):
:mod:`app.voice.sink_registry` reads the audio into ``bytes``
exactly once to avoid the file-cleanup race the old
``VoicePipeline`` had (``os.unlink`` after the WS push but
before the local sink read).  Returning ``bytes`` directly
removes that class of bug.

Backward-compat note for callers: the previous :mod:`app.voice.tts`
returned a *file path*; see ``synthesize_to_path`` below for a
shim that preserves that contract.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import threading
import wave
from typing import Any

logger = logging.getLogger(__name__)

# Module-level cache so two VoicePipelines in the same process
# share the loaded voice (and the ~3 s onnx kernel init cost).
_voice_cache: dict[str, "PiperTTS"] = {}
_cache_lock = threading.Lock()


class PiperTTS:
    """Lazy-loaded, thread-safe Piper voice.

    Parameters
    ----------
    model_path:
        Absolute or workspace-relative path to the ``.onnx`` file
        (the ``.onnx.json`` sibling is loaded automatically by
        Piper).
    voice_name:
        Human-readable label — defaults to the file stem.  Used
        in the ``/api/voice/config`` response and in log lines.
    """

    def __init__(
        self, model_path: str, voice_name: str | None = None
    ) -> None:
        self.model_path = model_path
        self.voice_name = voice_name or os.path.splitext(
            os.path.basename(model_path)
        )[0]
        self._voice: Any = None
        self._sample_rate: int | None = None
        self._load_lock = threading.Lock()

    @classmethod
    def get(cls, model_path: str) -> "PiperTTS":
        """Return a cached :class:`PiperTTS` for *model_path*.

        The first call loads the voice; subsequent calls return
        the same instance.  Errors during load are caught and
        the call returns a stub whose :meth:`synthesize` returns
        empty bytes — the chat path keeps working with a
        warning, and the next call retries the load.
        """
        key = os.path.abspath(model_path)
        with _cache_lock:
            existing = _voice_cache.get(key)
            if existing is not None:
                return existing
            instance = cls(key)
            _voice_cache[key] = instance
            return instance

    @staticmethod
    def reset_cache_for_tests() -> None:
        """Drop every cached voice.  Tests call this in teardown."""
        with _cache_lock:
            _voice_cache.clear()

    def _ensure_loaded(self) -> Any:
        """Load the onnx voice on first use.  Thread-safe."""
        if self._voice is not None:
            return self._voice
        with self._load_lock:
            if self._voice is not None:
                return self._voice
            try:
                # Local file is named piper.py — be explicit that
                # we want the *PyPI* package named ``piper``,
                # not our own module.  Importing via importlib
                # side-steps the local-name shadow.
                import importlib
                piper_voice = importlib.import_module(
                    "piper.voice"
                ).PiperVoice
                config_path = self._resolve_config_path()
                voice = piper_voice.load(
                    self.model_path, config_path=config_path
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PiperTTS: failed to load model %r: %s",
                    self.model_path, exc,
                )
                return None
            try:
                sample_rate = int(voice.config.sample_rate)
            except Exception:  # noqa: BLE001
                sample_rate = 22050
            self._voice = voice
            self._sample_rate = sample_rate
            logger.info(
                "PiperTTS loaded voice=%s model=%s sample_rate=%d",
                self.voice_name, self.model_path, sample_rate,
            )
            return voice

    def _resolve_config_path(self) -> str | None:
        """Piper expects a ``.onnx.json`` next to the ``.onnx``."""
        candidate = f"{self.model_path}.json"
        if os.path.exists(candidate):
            return candidate
        return None

    @property
    def sample_rate(self) -> int:
        if self._sample_rate is not None:
            return self._sample_rate
        voice = self._ensure_loaded()
        if voice is None:
            return 22050
        try:
            return int(voice.config.sample_rate)
        except Exception:  # noqa: BLE001
            return 22050

    def synthesize(self, text: str) -> bytes:
        """Render *text* to a WAV byte string.

        Returns ``b""`` on any failure (missing model, onnx
        error, empty input).  Never raises.

        piper-tts >= 1.3 changed the API: ``PiperVoice.synthesize``
        returns ``Iterable[AudioChunk]`` namedtuples whose
        ``.audio_float_array`` is a numpy float32 array of
        samples in ``[-1.0, 1.0]``.  We concatenate the chunks,
        convert to int16, and wrap the result in a 16-bit PCM
        mono WAV header.
        """
        if not text or not text.strip():
            return b""
        voice = self._ensure_loaded()
        if voice is None:
            return b""
        try:
            import numpy as _np  # noqa: PLC0415

            chunks: list["_np.ndarray"] = []
            sample_rate = self._sample_rate or 22050
            for audio in voice.synthesize(text):
                # AudioChunk is a namedtuple-like object; v1.4
                # exposes audio_float_array (float32 in [-1, 1]).
                arr = getattr(audio, "audio_float_array", None)
                if arr is None:
                    # Older versions exposed ``.audio`` as int16.
                    arr = getattr(audio, "audio", None)
                if arr is None:
                    continue
                # float32 → int16: clip + scale to [-32768, 32767]
                clipped = _np.clip(arr, -1.0, 1.0)
                pcm = (clipped * 32767.0).astype(_np.int16)
                chunks.append(pcm)
                # Pull sample_rate from the first chunk — Piper
                # voices always emit at their declared rate.
                chunk_rate = getattr(audio, "sample_rate", None)
                if chunk_rate:
                    sample_rate = int(chunk_rate)
            if not chunks:
                logger.debug(
                    "PiperTTS: no audio chunks produced for %r", text
                )
                return b""
            pcm_bytes = _np.concatenate(chunks).tobytes()
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)
            return buffer.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "PiperTTS synthesize failed (voice=%s): %s",
                self.voice_name, exc,
            )
            return b""


def synthesize_to_path(
    text: str, model_path: str, suffix: str = ".wav"
) -> str:
    """Render *text* to a temp file and return the file path.

    Provided for backward-compat with the old
    :mod:`app.voice.tts` API where ``synthesize`` returned a
    file path.  The caller is responsible for unlinking the
    file when finished.  Returns ``""`` on failure.
    """
    audio_bytes = PiperTTS.get(model_path).synthesize(text)
    if not audio_bytes:
        return ""
    try:
        workspace = "workspace"
        os.makedirs(workspace, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=suffix, dir=workspace)
    except OSError as exc:
        logger.debug("synthesize_to_path tempfile failed: %s", exc)
        return ""
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(audio_bytes)
    except OSError as exc:
        logger.debug("synthesize_to_path write failed: %s", exc)
        try:
            os.unlink(path)
        except OSError:
            pass
        return ""
    return path


__all__ = ["PiperTTS", "synthesize_to_path"]
