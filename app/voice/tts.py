"""TTS engine — edge-tts primary (free cloud API, zero local compute).

synthesize(text) -> str
    Returns path to a generated .ogg file, or "" on failure.
    Files are written to workspace/voice_output/ with tempfile names.
    The caller is responsible for unlinking the file after use.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def synthesize(text: str, voice: str | None = None) -> str:
    """Generate speech for *text* using edge-tts and return the .ogg file path.

    Parameters
    ----------
    text:
        The text to speak.  Long texts are fine — edge-tts streams.
    voice:
        Optional BCP-47 voice name, e.g. ``"en-US-AriaNeural"``.
        Falls back to ``Config.VOICE_TTS_VOICE`` when not supplied.

    Returns
    -------
    str
        Absolute path to the generated .ogg file, or empty string on failure.
    """
    # Lazy imports — keep module-level cost at zero
    import edge_tts  # noqa: PLC0415

    from app.settings.config import Config  # noqa: PLC0415

    _voice = voice or Config.VOICE_TTS_VOICE

    out_dir = Path("workspace/voice_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    fd, out_path = tempfile.mkstemp(suffix=".ogg", dir=out_dir)
    os.close(fd)

    try:
        communicate = edge_tts.Communicate(text, _voice)
        await communicate.save(out_path)
        logger.debug(
            "TTS synthesis complete: %s (%d bytes)", out_path, os.path.getsize(out_path)
        )
        return out_path
    except Exception as exc:
        logger.error("TTS synthesis failed: %s", exc)
        try:
            os.unlink(out_path)
        except OSError:
            pass
        return ""
