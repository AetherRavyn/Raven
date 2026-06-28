# app/voice/transcribe.py
"""Async audio-to-text transcription.

v33 refactor.  The previous engine was ``faster-whisper``
(CTranslate2 Python wrapper).  v33 swaps it for
``pywhispercpp`` (a Python binding to the C++ ``whisper.cpp``
inference engine) so RAVEN can share the same loaded model
across the on-device pipeline, the Telegram inbound handler,
the Discord/Slack attachment path, and the new browser
``WS /voice/{user_id}`` stream.

Engine priority (lowest resource first that's available):

  1. **whisper.cpp** via ``pywhispercpp`` (CPU, ggml quantised
     model, ~75 MB on disk for ``ggml-tiny.bin``).  Configurable
     via :envvar:`WHISPER_CPP_MODEL`,
     :envvar:`WHISPER_CPP_LANGUAGE`, :envvar:`WHISPER_CPP_THREADS`.
     When :envvar:`WHISPER_CPP_OFFLINE=1` and the model file is
     missing, the loader raises instead of silently falling
     back so test envs fail fast.
  2. **Vosk** small English model — fully offline, no network.
     The model ships at
     :file:`app/voice/vosk-model-small-en-us-0.15/`.

Why the engine-loader API is ``_get_whisper_cpp_model()``
(renamed from ``_get_whisper_model()``):
the new loader is *not* drop-in compatible with the old
``faster_whisper.WhisperModel``.  The C++ binding has a
different constructor signature, supports ggml model files
(not HuggingFace repo names), and exposes its own
``Model.transcribe`` method that returns a *generator of
segments* with a different attribute layout
(``Segment.text`` vs ``Segment.text`` — the same, but
``info.language_probability`` is read once at the start of
``transcribe`` rather than returned alongside).

Usage:
    text = await transcribe_audio("/path/to/audio.ogg")
    # returns "" on failure, never raises
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT = Path(__file__).parent
_VOSK_MODEL_PATH = _CURRENT / "vosk-model-small-en-us-0.15"

# ── whisper.cpp model cache (loaded once, thread-safe) ─────────────────
_whisper_cpp_model: Any = None
_whisper_cpp_lock = threading.Lock()


def _get_whisper_cpp_model() -> Any:
    """Load (or return cached) whisper.cpp model via pywhispercpp.

    Resolution order:
    1. :envvar:`WHISPER_CPP_MODEL` — path to a ``ggml-*.bin`` file.
    2. ``Config.VOICE_STT_MODEL`` (legacy env var) — used as a
       HuggingFace repo name like ``tiny``; passed to pywhispercpp
       which downloads it on first use.
    3. ``tiny`` — the default.

    Returns ``None`` if pywhispercpp is not installed.  Raises
    :class:`FileNotFoundError` when :envvar:`WHISPER_CPP_OFFLINE=1`
    and the model file is missing — this is the test-env
    fast-fail behaviour.
    """
    global _whisper_cpp_model
    with _whisper_cpp_lock:
        if _whisper_cpp_model is not None:
            return _whisper_cpp_model
        try:
            from pywhispercpp.model import Model  # type: ignore
        except ImportError:
            logger.info(
                "pywhispercpp not installed — falling back to Vosk. "
                "Install with: uv add pywhispercpp"
            )
            return None
        try:
            from app.settings.config import Config  # noqa: PLC0415

            model_path = getattr(Config, "WHISPER_CPP_MODEL", None)
            language = getattr(Config, "WHISPER_CPP_LANGUAGE", "en")
            threads = int(getattr(Config, "WHISPER_CPP_THREADS", 2))
        except Exception:  # noqa: BLE001
            model_path = None
            language = "en"
            threads = 2

        offline = os.getenv("WHISPER_CPP_OFFLINE", "").lower() in {"1", "true", "yes", "on"}
        if model_path and not os.path.exists(model_path):
            if offline:
                raise FileNotFoundError(
                    f"WHISPER_CPP_MODEL points at {model_path!r} "
                    "but the file does not exist "
                    "(WHISPER_CPP_OFFLINE=1)."
                )
            logger.debug(
                "WHISPER_CPP_MODEL=%s missing; pywhispercpp will download on first use",
                model_path,
            )

        try:
            _whisper_cpp_model = Model(
                model_path or "tiny",
                language=language,
                n_threads=threads,
            )
            logger.info(
                "whisper.cpp loaded: model=%s language=%s threads=%d",
                model_path or "tiny",
                language,
                threads,
            )
            return _whisper_cpp_model
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "whisper.cpp failed to load: %s — using Vosk fallback",
                exc,
            )
            return None


def reset_whisper_cpp_for_tests() -> None:
    """Drop the cached model.  Tests call this in teardown."""
    global _whisper_cpp_model
    with _whisper_cpp_lock:
        _whisper_cpp_model = None


# ── Public async API ─────────────────────────────────────────────────


async def transcribe_audio(audio_path: str) -> str:
    """Convert any audio file to text.

    Runs the blocking engine in a thread pool so the asyncio
    loop stays free.  Returns empty string on any failure —
    never raises.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_sync, audio_path)


async def transcribe_bytes(audio_bytes: bytes, suffix: str = ".wav") -> str:
    """Transcribe raw audio bytes by writing to a temp file.

    Returns empty string on failure — never raises.
    """
    import tempfile
    import os

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)
        return await transcribe_audio(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Blocking implementations ──────────────────────────────────────────


def _transcribe_sync(audio_path: str) -> str:
    """Pick the best available engine and transcribe *audio_path*."""
    try:
        model = _get_whisper_cpp_model()
    except FileNotFoundError as exc:
        # WHISPER_CPP_OFFLINE=1 + missing model — the loader raised.
        # v33 risk-callout (d): this is a user-actionable config
        # error, not a transient failure.  Log loud (WARNING)
        # so the user notices; fall through to Vosk if it's
        # available, otherwise return "" so the chat path
        # doesn't crash.
        logger.warning(
            "whisper.cpp model missing and WHISPER_CPP_OFFLINE=1: %s "
            "— falling back to Vosk (run "
            "scripts/download-whisper-model.sh to fix)",
            exc,
        )
        model = None
    if model is not None:
        result = _transcribe_whisper_cpp(audio_path, model)
        # Whisper returns "" on silence / non-speech; that's
        # a legitimate answer, not a fallback trigger.
        return result

    return _transcribe_vosk(audio_path)


def _transcribe_whisper_cpp(audio_path: str, model: Any) -> str:
    """Transcribe using the loaded whisper.cpp model.

    ``pywhispercpp``'s ``Model.transcribe`` returns a
    ``list[Segment]`` directly (it materialises the
    generator in C++ land).  Each ``Segment`` exposes ``t0``,
    ``t1``, and ``text``.  No VAD pre-filter — pywhispercpp
    does not expose faster-whisper's ``vad_filter`` parameter
    by default; silence is handled by the natural end-of-audio
    token.
    """
    try:
        segments = model.transcribe(audio_path)
        if not segments:
            return ""
        text = " ".join(seg.text.strip() for seg in segments if seg.text)
        if text:
            logger.debug(
                "whisper.cpp transcribed len=%d from %s",
                len(text),
                os.path.basename(audio_path),
            )
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "whisper.cpp transcription error for %s: %s",
            audio_path,
            exc,
        )
        return ""


def _transcribe_vosk(audio_path: str) -> str:
    """Transcribe using Vosk (fully offline, no network required).

    Converts the input to WAV mono 16 kHz 16-bit before feeding
    Vosk.  Requires the ``vosk-model-small-en-us-0.15/``
    directory next to this file.
    """
    try:
        from pydub import AudioSegment  # type: ignore
        from vosk import KaldiRecognizer, Model  # type: ignore

        audio = AudioSegment.from_file(audio_path)
        audio = audio.set_channels(1).set_frame_rate(16_000).set_sample_width(2)

        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            audio.export(wav_path, format="wav")
            vosk_model = Model(str(_VOSK_MODEL_PATH))
            with wave.open(wav_path, "rb") as wf:
                rec = KaldiRecognizer(vosk_model, wf.getframerate())
                results: list[str] = []
                while True:
                    data = wf.readframes(4000)
                    if not data:
                        break
                    if rec.AcceptWaveform(data):
                        r = json.loads(rec.Result())
                        results.append(r.get("text", ""))
                final = json.loads(rec.FinalResult())
                results.append(final.get("text", ""))
            return " ".join(t for t in results if t).strip()
        finally:
            os.unlink(wav_path)

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "vosk transcription error for %s: %s",
            audio_path,
            exc,
        )
        return ""
