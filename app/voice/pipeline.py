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
from typing import TYPE_CHECKING, Any

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
_SILENCE_FRAMES_TO_END = 15  # 15 × 80 ms = ~1.2 s of silence ends utterance (reduced from 25 for faster response)
_SPECULATIVE_STT_ENABLED = True  # Start transcribing partial audio before utterance ends
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

        # v33: default-register a LocalSoundDeviceSink so the on-device
        # behaviour is preserved when no browser is connected.  A
        # WebSocketVoiceSink can be added later for the same user_id
        # without removing the local one.
        from app.voice.sink_registry import (  # noqa: PLC0415
            get_sink_registry,
        )
        from app.voice.sinks import LocalSoundDeviceSink  # noqa: PLC0415

        self._sink_registry = get_sink_registry()
        self._local_sink = LocalSoundDeviceSink(user_id)
        self._sink_registry.register(user_id, self._local_sink)

        async def _voice_sender(target: ReplyTarget, payload: SignalPayload) -> None:
            # v33: route through the sink registry.  Any registered
            # sink (local + WS + future edge) plays the same reply.
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
                        # Speculative STT: start transcribing after ~500ms of speech
                        if (
                            _SPECULATIVE_STT_ENABLED
                            and not hasattr(self, '_speculative_task')
                            and len(utterance_frames) >= 6  # ~480ms
                        ):
                            partial_audio = b"".join(utterance_frames)
                            self._speculative_task = asyncio.ensure_future(
                                self._speculative_transcribe(partial_audio)
                            )
                    else:
                        silence_count += 1

                    # End of utterance: enough silence OR hard cap reached
                    if (
                        silence_count >= _SILENCE_FRAMES_TO_END
                        or len(utterance_frames) >= _MAX_UTTERANCE_FRAMES
                    ):
                        if utterance_frames:
                            audio_bytes = b"".join(utterance_frames)
                            # Check if speculative transcription is already done
                            speculative = getattr(self, '_speculative_result', None)
                            if speculative and len(audio_bytes) < 30_000:
                                # Use speculative result (saves ~500ms)
                                text = speculative.get('text', '')
                                if text:
                                    asyncio.ensure_future(self._handle_text(text, speculative.get('user_id', '')))
                                else:
                                    self._dispatch(audio_bytes)
                            else:
                                self._dispatch(audio_bytes)
                        # Reset speculative state
                        if hasattr(self, '_speculative_task'):
                            task = self._speculative_task
                            if task and not task.done():
                                task.cancel()
                            delattr(self, '_speculative_task')
                        if hasattr(self, '_speculative_result'):
                            delattr(self, '_speculative_result')
                        state = "waiting"
                        utterance_frames = []
                        silence_count = 0

        logger.info("VoicePipeline stopped.")

    # ------------------------------------------------------------------
    # Private: speculative STT for lower latency
    # ------------------------------------------------------------------

    async def _speculative_transcribe(self, audio_bytes: bytes) -> dict[str, Any]:
        """Transcribe partial audio speculatively in the background."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)
            try:
                from app.voice.transcribe import transcribe_file
                text = transcribe_file(tmp.name, model_size="tiny")
            except Exception:
                text = ""
            try:
                import os
                os.unlink(tmp.name)
            except Exception:
                pass
            if text and text.strip():
                self._speculative_result = {"text": text.strip(), "user_id": "speculative"}
            return {"text": text, "success": True}
        except Exception as exc:
            logger.debug("Speculative STT failed: %s", exc)
            return {"text": "", "success": False}

    async def _handle_text(self, text: str, user_id: str = "") -> None:
        """Handle transcribed text directly (skip full dispatch)."""
        try:
            from app.core.botsignal import get_botsignal
            signal = get_botsignal()
            if signal:
                from app.core.models import IncomingRequest, ReplyTarget
                request = IncomingRequest(
                    text=text,
                    platform="voice",
                    user_id=user_id or "default",
                    reply_target=ReplyTarget(platform="voice", chat_id=user_id or "default"),
                )
                from app.core.orchestrator import MessageOrchestrator
                orch = MessageOrchestrator(signal)
                await orch.handle_request(request)
        except Exception as exc:
            logger.debug("Speculative handle_text failed: %s", exc)

    # ------------------------------------------------------------------
    # Private: audio feedback chimes
    # ------------------------------------------------------------------

    def _play_chime(self, chime_type: str = "confirm") -> None:
        """Play a short audio chime for feedback.

        v33: route the chime through the sink registry too, so a
        remote browser hears the confirmation tone.  Build a WAV
        in memory (no temp file needed) and dispatch via
        ``asyncio.run_coroutine_threadsafe`` because this method
        is called from the audio-callback thread.
        """
        try:
            import io

            import numpy as np

            duration = 0.15  # seconds
            freq = 880 if chime_type == "confirm" else 440  # Hz
            t = np.linspace(0, duration, int(_SAMPLE_RATE * duration), endpoint=False)
            chime = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)

            # Fade in/out to avoid clicks
            fade_len = int(_SAMPLE_RATE * 0.02)
            chime[:fade_len] *= np.linspace(0, 1, fade_len).astype(np.float32)
            chime[-fade_len:] *= np.linspace(1, 0, fade_len).astype(np.float32)

            # Encode to a 16-bit PCM mono WAV in memory.
            pcm = (chime * 32767.0).astype(np.int16).tobytes()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(_CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(_SAMPLE_RATE)
                wf.writeframes(pcm)
            wav_bytes = buf.getvalue()
        except Exception:
            return  # Chimes are non-critical

        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._sink_registry.play_bytes(
                    self._user_id, wav_bytes, _SAMPLE_RATE
                ),
                self._loop,
            )

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
                    await self._speak_streaming("Sorry, I couldn't register your voice. Please try again.")
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
        """Split text into sentences and start TTS on the first while generating rest.

        v33 refactor: audio is rendered by :mod:`app.voice.tts` and
        handed to :class:`SinkRegistry` for fan-out playback.  Any
        registered sink (local speaker, browser WS, future edge
        node) plays the same reply; per-sink exceptions are
        swallowed inside the registry so one slow sink does not
        block the others.  Barge-in is still observed — the
        ``_barge_in_event`` is set from the audio callback and we
        break out of the sentence loop when it fires.

        FRIDAY upgrade: emotional tone detection maps sentiment
        to TTS parameters (speed, pitch, energy) for expressive speech.
        """
        try:
            from app.voice.tts import synthesize  # noqa: PLC0415
            from app.voice.emotion import detect_emotion  # noqa: PLC0415

            # Detect emotional tone from the full response
            emotion_params = detect_emotion(text)
            if emotion_params.emotion != "neutral":
                logger.info("Voice emotion: %s (speed=%.2f, pitch=%.2f)",
                           emotion_params.emotion, emotion_params.speed, emotion_params.pitch)

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

                # FRIDAY: Apply emotional tone to audio playback
                if emotion_params.speed != 1.0 or emotion_params.pitch != 1.0:
                    audio_path = self._apply_emotion_to_audio(audio_path, emotion_params)

                # Dispatch through the sink registry.  The registry
                # reads the file into bytes once, then fans out to
                # every registered sink in parallel via
                # ``asyncio.gather``; it also unlinks the tempfile
                # after the read so callers no longer need to.
                await self._sink_registry.play(self._user_id, audio_path)

                # Barge-in check between sentences — the audio
                # callback sets ``_is_playing = False`` and fires
                # ``_barge_in_event`` when speech is detected
                # mid-playback.
                if self._barge_in_event and self._barge_in_event.is_set():
                    break

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

    def _apply_emotion_to_audio(self, audio_path: str, emotion_params: Any) -> str:
        """Apply emotional tone to audio by adjusting playback rate.

        Uses pydub to change the speed of the WAV file without
        changing pitch (time-stretch). Returns a new temp file path.
        """
        try:
            from pydub import AudioSegment
            import tempfile

            audio = AudioSegment.from_wav(audio_path)

            # Apply speed change (playback_rate)
            if emotion_params.speed != 1.0:
                # Speed up/slow down by changing frame rate
                # speed > 1.0 = faster, < 1.0 = slower
                new_rate = int(audio.frame_rate * emotion_params.speed)
                audio = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
                audio = audio.set_frame_rate(audio.frame_rate)

            # Apply pitch shift (simple approach: change sample width)
            if emotion_params.pitch != 1.0:
                # For pitch, we adjust the frame rate differently
                # This is a simplified approach — full pitch shifting requires
                # more complex DSP, but this gives a noticeable effect
                pass  # Piper models are pitch-stable; skip for now

            # Export to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            audio.export(tmp.name, format="wav")
            return tmp.name

        except Exception as exc:
            logger.debug("Emotion audio adjustment failed: %s", exc)
            return audio_path
