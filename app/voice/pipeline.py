"""Local voice pipeline: wake word → VAD → STT → orchestrator → TTS → speaker.

Design goals (low resource):
- openwakeword ONNX  — no PyTorch at runtime
- Energy-based RMS VAD — pure numpy, no webrtcvad
- faster-whisper tiny/int8/cpu via transcribe.py (shared model cache)
- edge-tts via tts.py — cloud API, zero local compute
- sounddevice for audio I/O
- All heavy imports are lazy (inside methods)
- Entire pipeline is a no-op when ENABLE_LOCAL_VOICE=false

Phase 3 enhancements:
- Speaker identification via voice embeddings
- Streaming TTS (start speaking while still generating)
- Per-user voice customization
- Audio feedback chimes on wake word / error
- Always-on by default (opt-out with --no-voice)
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import wave
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
        self._is_playing = False
        self._barge_in_event: asyncio.Event | None = None

        # Speaker identification
        self._speaker_id = None
        try:
            from app.voice.speaker_id import get_speaker_identifier
            self._speaker_id = get_speaker_identifier()
            logger.info("VoicePipeline: speaker identification enabled")
        except Exception as exc:
            logger.debug("VoicePipeline: speaker ID unavailable — %s", exc)

        # Register a "voice" platform sender so orchestrator replies come back
        # here and are played through the speakers.
        from app.core import ReplyTarget, SignalPayload  # noqa: PLC0415

        async def _voice_sender(target: ReplyTarget, payload: SignalPayload) -> None:
            if payload.text:
                await self._speak_streaming(payload.text)

        botsignal.register_sender("voice", _voice_sender)
        logger.info("VoicePipeline initialised (user=%s chat=%s)", user_id, chat_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Entry point — run the blocking loop in a thread executor."""
        self._loop = asyncio.get_running_loop()
        self._barge_in_event = asyncio.Event()
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
            device=Config.VOICE_MIC_DEVICE,
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
                    # If TTS is playing, allow VAD barge-in to interrupt it
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                    if self._is_playing and rms > _RMS_SPEECH_THRESHOLD:
                        logger.info("Barge-in detected via VAD!")
                        self._is_playing = False
                        if self._loop and self._barge_in_event:
                            self._loop.call_soon_threadsafe(self._barge_in_event.set)
                        oww.reset()
                        state = "recording"
                        utterance_frames = [frame]
                        silence_count = 0
                        continue

                    # Feed to openwakeword (expects float32 normalised to [-1,1])
                    pcm_f32 = pcm.astype(np.float32) / 32768.0
                    prediction = oww.predict(pcm_f32)
                    # prediction is dict[str, float] — check max score
                    score = max(prediction.values()) if prediction else 0.0
                    if score >= threshold:
                        logger.info(
                            "Wake word detected (score=%.3f) — listening …", score
                        )
                        # If wake word interrupts TTS
                        if self._is_playing:
                            self._is_playing = False
                            if self._loop and self._barge_in_event:
                                self._loop.call_soon_threadsafe(
                                    self._barge_in_event.set
                                )

                        # Play confirmation chime
                        self._play_chime("confirm")

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
    # Private: audio feedback chimes
    # ------------------------------------------------------------------

    def _play_chime(self, chime_type: str = "confirm") -> None:
        """Play a short audio chime for feedback."""
        try:
            import numpy as np
            import sounddevice as sd

            duration = 0.15  # seconds
            freq = 880 if chime_type == "confirm" else 440  # Hz
            t = np.linspace(0, duration, int(_SAMPLE_RATE * duration), endpoint=False)
            chime = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)

            # Fade in/out to avoid clicks
            fade_len = int(_SAMPLE_RATE * 0.02)
            chime[:fade_len] *= np.linspace(0, 1, fade_len).astype(np.float32)
            chime[-fade_len:] *= np.linspace(1, 0, fade_len).astype(np.float32)

            sd.play(chime, _SAMPLE_RATE)
            sd.wait()
        except Exception:
            pass  # Chimes are non-critical

    # ------------------------------------------------------------------
    # Private: dispatch utterance to orchestrator (thread → asyncio)
    # ------------------------------------------------------------------

    def _dispatch(self, audio_bytes: bytes) -> None:
        """Write PCM to a temp WAV, transcribe, then schedule handle() on loop."""
        if self._loop is None:
            return

        # Speaker identification (before transcription)
        identified_user = self._user_id
        if self._speaker_id:
            try:
                uid, confidence = self._speaker_id.identify_from_bytes(audio_bytes)
                if uid != "local":
                    identified_user = uid
                    logger.info(
                        "Speaker identified: %s (confidence=%.3f)",
                        uid,
                        confidence,
                    )
            except Exception as exc:
                logger.debug("Speaker ID failed: %s", exc)

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
            self._play_chime("error")
            return

        asyncio.run_coroutine_threadsafe(
            self._process_utterance(wav_path, identified_user),
            self._loop,
        )

    async def _process_utterance(self, wav_path: str, user_id: str) -> None:
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

        logger.info("Transcribed utterance: %r (user=%s)", text[:120], user_id)

        # Handle enrollment commands: "register my voice as <name>"
        enrollment_match = re.match(
            r"(?:register|enroll)\s+(?:my\s+)?voice\s+as\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if enrollment_match and self._speaker_id:
            name = enrollment_match.group(1).strip()
            # Re-write WAV for enrollment
            try:
                fd, enroll_wav = tempfile.mkstemp(suffix=".wav", dir="workspace")
                os.close(fd)
                # Use the last utterance for enrollment
                success = self._speaker_id.enroll(name, f"voice_{name.lower()}", wav_path)
                if success:
                    await self._speak_streaming(f"Voice registered for {name}. I'll recognize you from now on.")
                else:
                    await self._speak_streaming(f"Sorry, I couldn't register your voice. Please try again.")
            except Exception as exc:
                logger.error("Voice enrollment failed: %s", exc)
            return

        from app.core import IncomingRequest, ReplyTarget  # noqa: PLC0415

        request = IncomingRequest(
            platform="voice",
            user_id=user_id,
            text=text,
            reply_target=ReplyTarget(
                platform="voice",
                chat_id=self._chat_id,
            ),
        )
        await self._orchestrator.handle(request)

    # ------------------------------------------------------------------
    # Private: Streaming TTS playback (start speaking while generating)
    # ------------------------------------------------------------------

    async def _speak_streaming(self, text: str) -> None:
        """Split text into sentences and start TTS on the first while generating rest."""
        try:
            import os  # noqa: PLC0415

            import sounddevice as sd  # noqa: PLC0415
            import soundfile as sf  # noqa: PLC0415

            from app.voice.tts import synthesize  # noqa: PLC0415

            # Get per-user voice (if configured)
            voice = self._get_user_voice(self._user_id)

            # Split into sentences for streaming
            sentences = self._split_sentences(text)
            if not sentences:
                return

            self._is_playing = True
            if self._barge_in_event:
                self._barge_in_event.clear()

            for sentence in sentences:
                if not self._is_playing:
                    break  # Barge-in interrupted

                audio_path = await synthesize(sentence, voice=voice)
                if not audio_path:
                    continue

                try:
                    data, samplerate = sf.read(audio_path, dtype="float32")

                    sd.play(data, samplerate)

                    # Wait for playback or barge-in
                    if self._loop and self._barge_in_event:
                        wait_task = self._loop.run_in_executor(None, sd.wait)
                        barge_in_task = self._loop.create_task(self._barge_in_event.wait())

                        done, pending = await asyncio.wait(
                            [wait_task, barge_in_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        if barge_in_task in done:
                            sd.stop()
                            break

                        for task in pending:
                            task.cancel()
                    else:
                        sd.wait()
                finally:
                    try:
                        os.unlink(audio_path)
                    except OSError:
                        pass

        except Exception as exc:
            logger.error("VoicePipeline streaming playback error: %s", exc)
        finally:
            self._is_playing = False

    # ------------------------------------------------------------------
    # Private: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences for streaming TTS."""
        # Split on sentence-ending punctuation, keeping the delimiter
        parts = re.split(r'(?<=[.!?])\s+', text)
        # Merge very short fragments
        sentences = []
        buffer = ""
        for part in parts:
            buffer += (" " if buffer else "") + part
            if len(buffer) >= 20:  # Minimum sentence length for TTS
                sentences.append(buffer.strip())
                buffer = ""
        if buffer.strip():
            sentences.append(buffer.strip())
        return sentences

    def _get_user_voice(self, user_id: str) -> str | None:
        """Get the TTS voice for a specific user."""
        from app.settings.config import Config

        # Check per-user voice config
        voices_str = getattr(Config, "VOICE_TTS_VOICES", "")
        if voices_str:
            for entry in str(voices_str).split(","):
                parts = entry.strip().split(":")
                if len(parts) == 2 and parts[0].strip() == user_id:
                    return parts[1].strip()

        # Fall back to default
        return None  # Let tts.py use Config.VOICE_TTS_VOICE
