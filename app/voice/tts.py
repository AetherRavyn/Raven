"""TTS engine — Piper-TTS (local) for the autherRaven personality.

v33 refactor.  Replaces the previous :mod:`edge_tts` (Microsoft
cloud) backend with :mod:`piper` (local onnx).  The
:func:`synthesize` signature is preserved so the
:class:`~app.voice.pipeline.VoicePipeline` and the Telegram
voice sender (which both call this) need no changes.

Why the signature is ``synthesize(text, voice=None) -> str`` (a
file path) and not ``-> bytes`` (a blob):
- Backward-compat — the old edge-tts backend wrote ``.ogg``
  to disk and returned the path.  The Telegram voice sender at
  :file:`app/telegram/bot.py:226` opens that file with
  ``InputFile(path)`` to attach it to the reply.  Switching
  to ``bytes`` would have meant changing Telegram too.
- File-on-disk is fine for the local sink — it reads the path
  once and the registry handles cleanup.  The browser-WS sink
  reads the file into ``bytes`` itself.

Public API:
- :func:`synthesize(text, voice=None) -> str` — returns the
  path to a generated ``.wav`` file, or ``""`` on failure.
  The caller is responsible for unlinking the file when done.
- :func:`synthesize_bytes(text, voice=None) -> bytes` —
  convenience for the browser-WS sink that wants bytes
  directly.

The *default voice* is the autherRaven model shipped at
:file:`app/voice/en_US-lessac-medium.onnx`.  Operators can
swap by setting :envvar:`PIPER_VOICE_MODEL` to a different
``.onnx`` path (and matching ``PIPER_VOICE_CONFIG`` if the
filename is not the model stem + ``.json``).

Backward-compat for ``Config.VOICE_TTS_VOICE``:
before v33 this env var held a BCP-47 voice name like
``en-US-AriaNeural``.  After v33 the synthesizer logs a
``DeprecationWarning`` if the value is not a path to an
``.onnx`` file and falls back to :attr:`Config.PIPER_VOICE_MODEL`.
The v33 release note calls this out.
"""
from __future__ import annotations

import logging
import os
import warnings
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_model_path(voice: str | None) -> str:
    """Return the Piper ``.onnx`` model path for *voice*.

    Resolution order:
    1. *voice* arg if it looks like a path (contains ``/`` or
       ends with ``.onnx``) and exists on disk.
    2. :attr:`Config.PIPER_VOICE_MODEL` (the default
       autherRaven model).
    3. The legacy :attr:`Config.VOICE_TTS_VOICE` value, if it
       is a path that exists — this lets a single env var swap
       voices without restarting the orchestrator.
    """
    if voice and (
        voice.endswith(".onnx")
        or "/" in voice
        or os.sep in voice
    ):
        if os.path.exists(voice):
            return voice
        logger.debug(
            "synthesize: voice=%r is a path but does not exist; "
            "falling back to default",
            voice,
        )

    from app.settings.config import Config  # noqa: PLC0415

    default = getattr(Config, "PIPER_VOICE_MODEL", None)
    if default and os.path.exists(default):
        return default

    legacy = getattr(Config, "VOICE_TTS_VOICE", None)
    if legacy and os.path.exists(legacy):
        warnings.warn(
            "Config.VOICE_TTS_VOICE is now a *path* to a Piper "
            f".onnx model, not a BCP-47 voice name.  Found file "
            f"at {legacy!r}; using it.  Set "
            "PIPER_VOICE_MODEL instead to silence this warning.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy

    if legacy and not (
        legacy.endswith(".onnx")
        or "/" in legacy
        or os.sep in legacy
    ):
        warnings.warn(
            "Config.VOICE_TTS_VOICE looks like a legacy BCP-47 "
            f"name ({legacy!r}); falling back to autherRaven.  "
            "Set PIPER_VOICE_MODEL to a .onnx path.",
            DeprecationWarning,
            stacklevel=2,
        )

    # If we got here, the default is missing — let PiperTTS
    # raise the clearer error itself.
    return default or "app/voice/en_US-lessac-medium.onnx"


async def synthesize(text: str, voice: str | None = None) -> str:
    """Generate speech for *text* and return the WAV file path.

    The caller is responsible for unlinking the file.  Returns
    ``""`` on any failure (missing model, onnx error, empty
    input).  Never raises.
    """
    from app.voice.piper import synthesize_to_path  # noqa: PLC0415

    if not text or not text.strip():
        return ""
    model_path = _resolve_model_path(voice)
    return synthesize_to_path(text, model_path)


async def synthesize_bytes(
    text: str, voice: str | None = None
) -> bytes:
    """Convenience: return the WAV bytes directly.

    The browser-WS sink in :mod:`app.voice.sinks` uses this to
    skip the temp-file round trip.
    """
    from app.voice.piper import PiperTTS  # noqa: PLC0415

    if not text or not text.strip():
        return b""
    model_path = _resolve_model_path(voice)
    return PiperTTS.get(model_path).synthesize(text)


def get_active_voice_metadata() -> dict[str, Any]:
    """Return metadata about the active TTS voice for the
    ``GET /api/voice/config`` endpoint."""
    from app.settings.config import Config  # noqa: PLC0415

    from app.voice.piper import PiperTTS  # noqa: PLC0415

    model_path = _resolve_model_path(None)
    voice = PiperTTS.get(model_path)
    return {
        "engine": "piper",
        "voice_name": getattr(
            Config, "PIPER_VOICE_NAME", None
        ) or voice.voice_name,
        "model_path": model_path,
        "sample_rate": voice.sample_rate,
        "personality": "autherRaven",
    }


__all__ = [
    "synthesize",
    "synthesize_bytes",
    "get_active_voice_metadata",
]
