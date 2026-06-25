from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np
from loguru import logger

from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ── Optional dependency guards ────────────────────────────────────────────────

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore

try:
    from vosk import KaldiRecognizer
    from vosk import Model as VoskModel
except ImportError:
    VoskModel = None  # type: ignore
    KaldiRecognizer = None  # type: ignore

try:
    import edge_tts
except ImportError:
    edge_tts = None  # type: ignore

try:
    from openwakeword.model import Model as OWWModel
except ImportError:
    OWWModel = None  # type: ignore

# ── Shared event bus (imported from your existing module if available) ─────────

try:
    from app.voice.wakeword.events import (
        VoiceEvent,
        VoiceEventType,
        get_voice_event_bus,
    )

    _HAS_EVENT_BUS = True
except ImportError:
    _HAS_EVENT_BUS = False


class VoiceTool(BaseTool):
    """
    Agent tool for voice I/O.

    Operations
    ----------
    detect_wake_word  – Listen on the microphone until a wake word is heard.
    listen            – Record microphone audio for N seconds and return bytes.
    transcribe        – Convert an audio file / recorded bytes to text (Vosk).
    speak             – Convert text to speech using Edge TTS and save to file.
    voice_pipeline    – Full pipeline: wait for wake word → listen → transcribe.
    """

    # Default Vosk model path (matches your existing codebase)
    VOSK_MODEL_PATH = "app/voice/vosk-model-small-en-us-0.15"

    # Default Edge TTS voice
    DEFAULT_VOICE = "en-US-AriaNeural"

    # ── BaseTool interface ────────────────────────────────────────────────────

    def get_name(self) -> str:
        return "voice"

    def get_description(self) -> str:
        return (
            "Voice I/O tool: detect wake words via OpenWakeWord, record live "
            "microphone audio, transcribe speech to text via Vosk, synthesize "
            "text to speech via Edge TTS, or run the full voice pipeline "
            "(wake word → listen → transcribe) in a single call."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    required=True,
                    description="Operation to perform.",
                    enum=[
                        "detect_wake_word",
                        "listen",
                        "transcribe",
                        "speak",
                        "voice_pipeline",
                    ],
                ),
                # ── Wake word ─────────────────────────────────────────────
                ToolParameter(
                    name="wake_words",
                    type="array",
                    required=False,
                    description=(
                        "Wake words to detect (default: ['hey jarvis']). "
                        "Used by 'detect_wake_word' and 'voice_pipeline'."
                    ),
                ),
                ToolParameter(
                    name="wake_threshold",
                    type="number",
                    required=False,
                    description=(
                        "OpenWakeWord confidence threshold 0–1 (default: 0.5). "
                        "Lower = more sensitive."
                    ),
                ),
                ToolParameter(
                    name="wake_timeout",
                    type="number",
                    required=False,
                    description=(
                        "Max seconds to wait for a wake word before giving up "
                        "(default: 30.0).  0 = wait forever."
                    ),
                ),
                ToolParameter(
                    name="custom_model_path",
                    type="string",
                    required=False,
                    description=(
                        "Path to a custom .onnx OpenWakeWord model file. "
                        "Leave empty to use the built-in models."
                    ),
                ),
                # ── Listen / record ───────────────────────────────────────
                ToolParameter(
                    name="record_seconds",
                    type="number",
                    required=False,
                    description=(
                        "How many seconds of microphone audio to record "
                        "(default: 5.0).  Used by 'listen' and 'voice_pipeline'."
                    ),
                ),
                ToolParameter(
                    name="sample_rate",
                    type="integer",
                    required=False,
                    description="Microphone sample rate in Hz (default: 16000).",
                ),
                ToolParameter(
                    name="device_index",
                    type="integer",
                    required=False,
                    description=(
                        "Sounddevice input device index (default: system default)."
                    ),
                ),
                ToolParameter(
                    name="output_audio_path",
                    type="string",
                    required=False,
                    description=(
                        "File path to save recorded audio as a WAV file. "
                        "If omitted, raw PCM bytes are returned as base64."
                    ),
                ),
                # ── Transcribe ────────────────────────────────────────────
                ToolParameter(
                    name="audio_path",
                    type="string",
                    required=False,
                    description=(
                        "Path to a WAV file to transcribe. "
                        "Required for 'transcribe' (unless audio_b64 is supplied)."
                    ),
                ),
                ToolParameter(
                    name="audio_b64",
                    type="string",
                    required=False,
                    description=(
                        "Base64-encoded raw PCM int16 audio to transcribe. "
                        "Used instead of audio_path when transcribing in-memory audio."
                    ),
                ),
                ToolParameter(
                    name="vosk_model_path",
                    type="string",
                    required=False,
                    description=(
                        f"Path to the Vosk model directory "
                        f"(default: '{self.VOSK_MODEL_PATH}')."
                    ),
                ),
                # ── Speak (TTS) ───────────────────────────────────────────
                ToolParameter(
                    name="text",
                    type="string",
                    required=False,
                    description=("Text to synthesize. Required for 'speak'."),
                ),
                ToolParameter(
                    name="tts_voice",
                    type="string",
                    required=False,
                    description=(
                        f"Edge TTS voice name (default: '{self.DEFAULT_VOICE}'). "
                        "See https://learn.microsoft.com/en-us/azure/cognitive-services/"
                        "speech-service/language-support for all options."
                    ),
                ),
                ToolParameter(
                    name="tts_output_path",
                    type="string",
                    required=False,
                    description=(
                        "File path for the generated audio (default: 'tts_output.mp3'). "
                        "Supported formats: .mp3, .ogg, .wav."
                    ),
                ),
            ],
        )

    # ── Main dispatcher ───────────────────────────────────────────────────────

    async def execute(
        self,
        operation: str,
        # Wake word
        wake_words: list[str] | None = None,
        wake_threshold: float = 0.5,
        wake_timeout: float = 30.0,
        custom_model_path: str | None = None,
        # Listen / record
        record_seconds: float = 5.0,
        sample_rate: int = 16_000,
        device_index: int | None = None,
        output_audio_path: str | None = None,
        # Transcribe
        audio_path: str | None = None,
        audio_b64: str | None = None,
        vosk_model_path: str | None = None,
        # Speak
        text: str | None = None,
        tts_voice: str | None = None,
        tts_output_path: str | None = None,
        **_: Any,
    ) -> Dict[str, Any]:

        try:
            if operation == "detect_wake_word":
                return self._detect_wake_word(
                    wake_words=wake_words or ["hey jarvis"],
                    threshold=wake_threshold,
                    timeout=wake_timeout,
                    sample_rate=sample_rate,
                    device_index=device_index,
                    custom_model_path=custom_model_path,
                )

            elif operation == "listen":
                return self._listen(
                    seconds=record_seconds,
                    sample_rate=sample_rate,
                    device_index=device_index,
                    output_path=output_audio_path,
                )

            elif operation == "transcribe":
                return self._transcribe(
                    audio_path=audio_path,
                    audio_b64=audio_b64,
                    sample_rate=sample_rate,
                    model_path=vosk_model_path or self.VOSK_MODEL_PATH,
                )

            elif operation == "speak":
                return await self._speak(
                    text=text,
                    voice=tts_voice or self.DEFAULT_VOICE,
                    output_path=tts_output_path or "tts_output.mp3",
                )

            elif operation == "voice_pipeline":
                return await self._voice_pipeline(
                    wake_words=wake_words or ["hey jarvis"],
                    wake_threshold=wake_threshold,
                    wake_timeout=wake_timeout,
                    custom_model_path=custom_model_path,
                    record_seconds=record_seconds,
                    sample_rate=sample_rate,
                    device_index=device_index,
                    vosk_model_path=vosk_model_path or self.VOSK_MODEL_PATH,
                )

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.exception("VoiceTool error")
            return {"success": False, "error": str(exc)}

    # ── Operation: detect_wake_word ───────────────────────────────────────────

    def _detect_wake_word(
        self,
        wake_words: list[str],
        threshold: float,
        timeout: float,
        sample_rate: int,
        device_index: int | None,
        custom_model_path: str | None,
    ) -> Dict[str, Any]:
        self._require("sounddevice", sd)
        self._require("openwakeword", OWWModel)

        # Load model
        if custom_model_path:
            model = OWWModel(wakeword_model_paths=[custom_model_path])
        else:
            model = OWWModel()

        # Map wake word names → model keys
        ww_keys = [w.lower().replace(" ", "_") for w in wake_words]

        # Flush model state with silence
        silence = np.zeros(1280, dtype=np.int16)
        for _ in range(32):
            model.predict(silence)

        FRAME = 1280  # OpenWakeWord requires exactly 1280 samples at 16kHz
        detected: dict = {}
        audio_buf = np.array([], dtype=np.float32)
        buf_lock = threading.Lock()
        start_time = time.time()

        def _audio_cb(indata, frames, t, status):
            nonlocal audio_buf
            with buf_lock:
                audio_buf = np.concatenate([audio_buf, indata[:, 0].astype(np.float32)])

        logger.info(f"🎤 Listening for wake words: {wake_words}  (timeout={timeout}s)")

        stream = sd.InputStream(
            samplerate=sample_rate,
            blocksize=FRAME,
            dtype="float32",
            channels=1,
            device=device_index,
            callback=_audio_cb,
        )

        with stream:
            while not detected:
                if timeout > 0 and (time.time() - start_time) > timeout:
                    return {
                        "success": False,
                        "error": f"Wake word not detected within {timeout}s",
                        "detected": False,
                    }

                with buf_lock:
                    available = len(audio_buf)

                if available >= FRAME:
                    with buf_lock:
                        chunk = audio_buf[:FRAME].copy()
                        audio_buf = audio_buf[FRAME:]

                    pcm = (chunk * 32767).astype(np.int16)
                    preds = model.predict(pcm)

                    for i, ww in enumerate(ww_keys):
                        score = preds.get(ww, 0.0)
                        if score >= threshold:
                            detected = {
                                "wake_word": wake_words[i],
                                "key": ww,
                                "confidence": float(score),
                            }
                            break
                else:
                    time.sleep(0.01)

        logger.info(
            f"🔔 Wake word detected: {detected['wake_word']} ({detected['confidence']:.2f})"
        )

        # Publish to event bus if available
        if _HAS_EVENT_BUS:
            get_voice_event_bus().publish(
                VoiceEvent(
                    event_type=VoiceEventType.WAKE_WORD_DETECTED,
                    data=detected,
                )
            )

        return {
            "success": True,
            "operation": "detect_wake_word",
            "detected": True,
            **detected,
        }

    # ── Operation: listen ─────────────────────────────────────────────────────

    def _listen(
        self,
        seconds: float,
        sample_rate: int,
        device_index: int | None,
        output_path: str | None,
    ) -> Dict[str, Any]:
        self._require("sounddevice", sd)

        logger.info(f"🎙️  Recording {seconds}s of audio…")

        if _HAS_EVENT_BUS:
            get_voice_event_bus().publish(
                VoiceEvent(event_type=VoiceEventType.SPEECH_STARTED, data={})
            )

        num_samples = int(sample_rate * seconds)
        recording = sd.rec(
            num_samples,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=device_index,
        )
        sd.wait()

        pcm_bytes = recording.tobytes()

        if _HAS_EVENT_BUS:
            get_voice_event_bus().publish(
                VoiceEvent(event_type=VoiceEventType.SPEECH_ENDED, data={})
            )

        if output_path:
            import wave

            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # int16 = 2 bytes
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)
            logger.info(f"💾 Audio saved: {output_path}")
            return {
                "success": True,
                "operation": "listen",
                "duration_seconds": seconds,
                "sample_rate": sample_rate,
                "saved_to": str(output_path),
            }

        # Return as base64 if no file path given
        return {
            "success": True,
            "operation": "listen",
            "duration_seconds": seconds,
            "sample_rate": sample_rate,
            "audio_b64": base64.b64encode(pcm_bytes).decode(),
        }

    # ── Operation: transcribe ─────────────────────────────────────────────────

    def _transcribe(
        self,
        audio_path: str | None,
        audio_b64: str | None,
        sample_rate: int,
        model_path: str,
    ) -> Dict[str, Any]:
        self._require("vosk", VoskModel)

        if not Path(model_path).exists():
            return {
                "success": False,
                "error": f"Vosk model not found at: {model_path}",
            }

        # Load audio bytes
        if audio_path:
            import wave

            with wave.open(audio_path, "rb") as wf:
                sample_rate = wf.getframerate()
                pcm_bytes = wf.readframes(wf.getnframes())
        elif audio_b64:
            pcm_bytes = base64.b64decode(audio_b64)
        else:
            return {
                "success": False,
                "error": "audio_path or audio_b64 required for transcribe",
            }

        model = VoskModel(model_path)
        rec = KaldiRecognizer(model, sample_rate)
        rec.SetWords(True)

        CHUNK = 4000
        transcript_parts: list[str] = []

        for i in range(0, len(pcm_bytes), CHUNK):
            chunk = pcm_bytes[i : i + CHUNK]
            if rec.AcceptWaveform(chunk):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip()
                if text:
                    transcript_parts.append(text)

        # Flush final partial result
        final = json.loads(rec.FinalResult())
        text = final.get("text", "").strip()
        if text:
            transcript_parts.append(text)

        full_transcript = " ".join(transcript_parts).strip()

        logger.info(f"📝 Transcription: {full_transcript}")

        if _HAS_EVENT_BUS:
            get_voice_event_bus().publish(
                VoiceEvent(
                    event_type=VoiceEventType.TRANSCRIPTION_COMPLETE,
                    data={"text": full_transcript},
                )
            )

        return {
            "success": True,
            "operation": "transcribe",
            "transcript": full_transcript,
            "source": audio_path or "in-memory audio",
        }

    # ── Operation: speak ──────────────────────────────────────────────────────

    async def _speak(
        self,
        text: str | None,
        voice: str,
        output_path: str,
    ) -> Dict[str, Any]:
        self._require("edge_tts", edge_tts)

        if not text:
            return {"success": False, "error": "text is required for speak"}

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"🔊 Synthesizing TTS → {output_path}")

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out))

        logger.info(f"✅ TTS saved: {out}")

        if _HAS_EVENT_BUS:
            get_voice_event_bus().publish(
                VoiceEvent(
                    event_type=VoiceEventType.RESPONSE_READY,
                    data={"path": str(out), "text": text},
                )
            )

        return {
            "success": True,
            "operation": "speak",
            "text": text,
            "voice": voice,
            "saved_to": str(out),
        }

    # ── Operation: voice_pipeline ─────────────────────────────────────────────

    async def _voice_pipeline(
        self,
        wake_words: list[str],
        wake_threshold: float,
        wake_timeout: float,
        custom_model_path: str | None,
        record_seconds: float,
        sample_rate: int,
        device_index: int | None,
        vosk_model_path: str,
    ) -> Dict[str, Any]:
        """
        Full pipeline:
          1. Block until wake word heard
          2. Record audio for record_seconds
          3. Transcribe with Vosk
          4. Return transcript + metadata
        """
        # Step 1 – wake word
        wake_result = self._detect_wake_word(
            wake_words=wake_words,
            threshold=wake_threshold,
            timeout=wake_timeout,
            sample_rate=sample_rate,
            device_index=device_index,
            custom_model_path=custom_model_path,
        )

        if not wake_result["success"]:
            return {
                "success": False,
                "operation": "voice_pipeline",
                "stage_failed": "detect_wake_word",
                "error": wake_result.get("error"),
            }

        # Step 2 – record
        listen_result = self._listen(
            seconds=record_seconds,
            sample_rate=sample_rate,
            device_index=device_index,
            output_path=None,  # keep in memory
        )

        if not listen_result["success"]:
            return {
                "success": False,
                "operation": "voice_pipeline",
                "stage_failed": "listen",
                "error": listen_result.get("error"),
            }

        # Step 3 – transcribe
        transcript_result = self._transcribe(
            audio_path=None,
            audio_b64=listen_result["audio_b64"],
            sample_rate=sample_rate,
            model_path=vosk_model_path,
        )

        if not transcript_result["success"]:
            return {
                "success": False,
                "operation": "voice_pipeline",
                "stage_failed": "transcribe",
                "error": transcript_result.get("error"),
            }

        return {
            "success": True,
            "operation": "voice_pipeline",
            "wake_word": wake_result["wake_word"],
            "wake_confidence": wake_result["confidence"],
            "transcript": transcript_result["transcript"],
            "record_seconds": record_seconds,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _require(name: str, module: Any):
        if module is None:
            packages = {
                "sounddevice": "sounddevice",
                "vosk": "vosk",
                "edge_tts": "edge-tts",
                "openwakeword": "openwakeword",
            }
            pkg = packages.get(name, name)
            raise ImportError(
                f"'{name}' is required for this operation.  "
                f"Install with: pip install {pkg}"
            )
