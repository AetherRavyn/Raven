"""Local voice pipeline: wake word → VAD → STT → orchestrator → TTS → speaker.

Design goals (low resource):
- openwakeword ONNX  — no PyTorch at runtime
- Energy-based RMS VAD — pure numpy, no webrtcvad
- faster-whisper tiny/int8/cpu via transcribe.py (shared model cache)
- edge-tts via tts.py — cloud API, zero local compute
- sounddevice for audio I/O
- All heavy imports are lazy (inside methods)
- Entire pipeline is a no-op when ENABLE_LOCAL_VOICE=false
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.botsignal import BotSignal
    from app.core.orchestrator import MessageOrchestrator

logger = logging.getLogger(__name__)

# Audio constants
_SAMPLE_RATE = 16_000
_CHANNELS = 1
_DTYPE = "int16"
_BLOCKSIZE = 1280  # 80 ms frames at 16 kHz  (openwakeword needs ≥80ms)
_RMS_SPEECH_THRESHOLD = 300  # empirical; tune via VOICE_VAD_THRESHOLD
_SILENCE_FRAMES_TO_END = 25  # 25 × 80 ms = ~2 s of silence ends utterance
_MAX_UTTERANCE_FRAMES = 300  # 300 × 80 ms = 24 s hard cap


class VoicePipeline:
    """Blocking microphone → LLM → speaker pipeline.

    Start with ``await pipeline.start()``.
    Stop with ``pipeline.stop()`` (thread-safe, sets an internal flag).
    """

    def __init__(
        self,
        orchestrator: MessageOrchestrator,
        botsignal: BotSignal,
        user_id: str = "local",
        chat_id: str = "local",
    ) -> None:
        self._orchestrator = orchestrator
        self._botsignal = botsignal
        self._user_id = user_id
        self._chat_id = chat_id
        self._stop = False
        self._loop: asyncio.AbstractEventLoop | None = None

        # Register a "voice" platform sender so orchestrator replies come back
        # here and are played through the speakers.
        from app.core import ReplyTarget, SignalPayload  # noqa: PLC0415

        async def _voice_sender(target: ReplyTarget, payload: SignalPayload) -> None:
            if payload.text:
                await self._speak(payload.text)

        botsignal.register_sender("voice", _voice_sender)
        logger.info("VoicePipeline initialised (user=%s chat=%s)", user_id, chat_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Entry point — run the blocking loop in a thread executor."""
        self._loop = asyncio.get_running_loop()
        await self._loop.run_in_executor(None, self._loop_blocking)

    def stop(self) -> None:
        """Signal the blocking loop to exit on next iteration."""
        self._stop = True

    # ------------------------------------------------------------------
    # Private: blocking audio loop (runs in thread executor)
    # ------------------------------------------------------------------

    def _loop_blocking(self) -> None:  # noqa: C901 (complexity is acceptable)
        """Main recording loop — blocks until stop() is called."""
        try:
            import numpy as np  # noqa: PLC0415
            import sounddevice as sd  # noqa: PLC0415
            from openwakeword.model import Model as OWWModel  # noqa: PLC0415
        except ImportError as exc:
            logger.error(
                "VoicePipeline cannot start — missing dependency: %s. "
                "Install sounddevice, numpy, openwakeword.",
                exc,
            )
            return

        from app.settings.config import Config  # noqa: PLC0415

        # Load openwakeword model (ONNX, no PyTorch)
        try:
            oww = OWWModel(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
            logger.info("openwakeword model loaded (hey_jarvis / onnx)")
        except Exception as exc:
            logger.error("Failed to load openwakeword model: %s", exc)
            return

        threshold = Config.VOICE_WAKE_WORD_THRESHOLD

        logger.info("VoicePipeline listening — say 'Hey Jarvis'")

        audio_queue: list[bytes] = []

        def _audio_callback(
            indata: "np.ndarray",  # type: ignore[type-arg]
            frames: int,
            time_info: object,
            status: object,
        ) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            audio_queue.append(bytes(indata))

        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=_CHANNELS,
            dtype=_DTYPE,
            blocksize=_BLOCKSIZE,
            callback=_audio_callback,
        ):
            state = "waiting"  # waiting | recording
            utterance_frames: list[bytes] = []
            silence_count = 0

            while not self._stop:
                if not audio_queue:
                    import time  # noqa: PLC0415

                    time.sleep(0.01)
                    continue

                frame = audio_queue.pop(0)
                pcm = np.frombuffer(frame, dtype=np.int16)

                if state == "waiting":
                    # Feed to openwakeword (expects float32 normalised to [-1,1])
                    pcm_f32 = pcm.astype(np.float32) / 32768.0
                    prediction = oww.predict(pcm_f32)
                    # prediction is dict[str, float] — check max score
                    score = max(prediction.values()) if prediction else 0.0
                    if score >= threshold:
                        logger.info(
                            "Wake word detected (score=%.3f) — listening …", score
                        )
                        oww.reset()
                        state = "recording"
                        utterance_frames = []
                        silence_count = 0

                elif state == "recording":
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                    is_speech = rms > _RMS_SPEECH_THRESHOLD
                    utterance_frames.append(frame)

                    if is_speech:
                        silence_count = 0
                    else:
                        silence_count += 1

                    # End of utterance: enough silence OR hard cap reached
                    if (
                        silence_count >= _SILENCE_FRAMES_TO_END
                        or len(utterance_frames) >= _MAX_UTTERANCE_FRAMES
                    ):
                        if utterance_frames:
                            audio_bytes = b"".join(utterance_frames)
                            self._dispatch(audio_bytes)
                        state = "waiting"
                        utterance_frames = []
                        silence_count = 0

        logger.info("VoicePipeline stopped.")

    # ------------------------------------------------------------------
    # Private: dispatch utterance to orchestrator (thread → asyncio)
    # ------------------------------------------------------------------

    def _dispatch(self, audio_bytes: bytes) -> None:
        """Write PCM to a temp WAV, transcribe, then schedule handle() on loop."""
        if self._loop is None:
            return

        # Write raw PCM → WAV so transcribe_audio() can process it
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav", dir="workspace")
            import os  # noqa: PLC0415

            os.close(fd)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(_CHANNELS)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(_SAMPLE_RATE)
                wf.writeframes(audio_bytes)
        except Exception as exc:
            logger.error("Failed to write utterance WAV: %s", exc)
            return

        asyncio.run_coroutine_threadsafe(
            self._process_utterance(wav_path),
            self._loop,
        )

    async def _process_utterance(self, wav_path: str) -> None:
        """Transcribe WAV, then forward to orchestrator."""
        import os  # noqa: PLC0415

        from app.voice.transcribe import transcribe_audio  # noqa: PLC0415

        try:
            text = await transcribe_audio(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        if not text:
            logger.debug("Empty transcription — ignoring utterance")
            return

        logger.info("Transcribed utterance: %r", text[:120])

        from app.core import IncomingRequest, ReplyTarget  # noqa: PLC0415

        request = IncomingRequest(
            platform="voice",
            user_id=self._user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="voice",
                chat_id=self._chat_id,
            ),
        )
        await self._orchestrator.handle(request)

    # ------------------------------------------------------------------
    # Private: TTS playback
    # ------------------------------------------------------------------

    async def _speak(self, text: str) -> None:
        """Synthesise *text* with edge-tts and play through speakers."""
        try:
            import os  # noqa: PLC0415

            import numpy as np  # noqa: PLC0415
            import sounddevice as sd  # noqa: PLC0415
            import soundfile as sf  # noqa: PLC0415

            from app.voice.tts import synthesize  # noqa: PLC0415

            audio_path = await synthesize(text)
            if not audio_path:
                return

            try:
                data, samplerate = sf.read(audio_path, dtype="float32")
                sd.play(data, samplerate)
                sd.wait()
            finally:
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass
        except Exception as exc:
            logger.error("VoicePipeline playback error: %s", exc)
