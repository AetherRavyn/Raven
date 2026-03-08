# app/voice/transcribe.py
"""Async audio-to-text transcription.

Engine priority (lowest resource first that's available):
  1. faster-whisper ``tiny`` model, CPU, int8 quantisation
     — ~39 MB model, ~100 MB peak RAM, ~0.5× real-time on a single core.
     — Auto-downloaded from Hugging Face on first use.
  2. Vosk small English model (offline fallback)
     — ~50 MB model, needs vosk-model-small-en-us-0.15/ directory.

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

logger = logging.getLogger(__name__)

_CURRENT = Path(__file__).parent
_VOSK_MODEL_PATH = _CURRENT / "vosk-model-small-en-us-0.15"

# ── faster-whisper model cache (loaded once, thread-safe) ─────────────────────
_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    """Load (or return cached) faster-whisper model.

    Uses the model size from Config.VOICE_STT_MODEL (default "tiny").
    Returns None if faster-whisper is not installed.
    """
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel  # type: ignore

            # Dynamically read model size from config without circular imports
            try:
                from app.settings.config import Config

                model_size = getattr(Config, "VOICE_STT_MODEL", "tiny")
            except Exception:
                model_size = "tiny"

            # int8 quantisation cuts RAM by ~4×; cpu_threads=2 caps CPU usage
            _whisper_model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
            )
            logger.info(
                "faster-whisper loaded: model=%s device=cpu compute=int8", model_size
            )
            return _whisper_model
        except ImportError:
            logger.info(
                "faster-whisper not installed — falling back to Vosk. "
                "Install with: uv add faster-whisper"
            )
            return None
        except Exception as exc:
            logger.warning(
                "faster-whisper failed to load: %s — using Vosk fallback", exc
            )
            return None


# ── Public async API ──────────────────────────────────────────────────────────


async def transcribe_audio(audio_path: str) -> str:
    """Convert any audio file to text.

    Runs the blocking engine in a thread pool so the asyncio loop stays free.
    Returns empty string on any failure — never raises.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_sync, audio_path)


# ── Blocking implementations ──────────────────────────────────────────────────


def _transcribe_sync(audio_path: str) -> str:
    """Pick the best available engine and transcribe *audio_path*."""
    model = _get_whisper_model()
    if model is not None:
        result = _transcribe_whisper(audio_path, model)
        if result:
            return result
        # If whisper returned empty (e.g. silence), fall through to Vosk
        return result  # "" is fine

    return _transcribe_vosk(audio_path)


def _transcribe_whisper(audio_path: str, model) -> str:
    """Transcribe using faster-whisper.

    beam_size=1 keeps CPU usage minimal while still being accurate.
    vad_filter=True skips silent segments — saves both time and hallucinations.
    """
    try:
        segments, info = model.transcribe(
            audio_path,
            beam_size=1,  # greedy — lowest CPU, still good accuracy
            vad_filter=True,  # skip silent chunks → avoid hallucinations
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        if text:
            logger.debug(
                "whisper transcribed lang=%s prob=%.2f len=%d",
                info.language,
                info.language_probability,
                len(text),
            )
        return text.strip()
    except Exception as exc:
        logger.warning("faster-whisper transcription error: %s", exc)
        return ""


def _transcribe_vosk(audio_path: str) -> str:
    """Transcribe using Vosk (fully offline, no network required).

    Converts the input to WAV mono 16 kHz 16-bit before feeding Vosk.
    Requires the vosk-model-small-en-us-0.15/ directory next to this file.
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

    except Exception as exc:
        logger.warning("vosk transcription error for %s: %s", audio_path, exc)
        return ""
