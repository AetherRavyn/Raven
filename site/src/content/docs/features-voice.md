---
title: "Voice Engine & Audio Pipeline"
---

# Voice Engine & Audio Pipeline

## 1. Architecture Overview

Raven's voice engine is a local-first, full-duplex audio pipeline that runs entirely on-device (CPU-only, no GPU required). The pipeline flows through six stages:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Pipeline (app/voice/)                    │
│                                                                   │
│  ┌──────────┐   ┌──────┐   ┌──────┐   ┌──────┐   ┌──────┐       │
│  │ Wake Word │──▶│  VAD │──▶│  STT │──▶│  LLM │──▶│  TTS │       │
│  │openwake-  │   │Energy│   │py-   │   │Message│   │Piper │       │
│  │ word ONNX │   │ RMS  │   │whisper│   │Orches-│   │ONNX  │       │
│  └──────────┘   └──────┘   │cpp / │   │trator │   └──┬───┘       │
│                            │ Vosk  │   └──────┘      │           │
│                            └──────┘                  │           │
│                                                 ┌────▼───────┐   │
│                                                 │SinkRegistry│   │
│                                                 │  Fan-out   │   │
│                                                 └────┬───────┘   │
│                                        ┌─────────────┼──────────┐│
│                                        ▼             ▼          ││
│                                   LocalSound    WebSocket       ││
│                                   DeviceSink    VoiceSink       ││
│                                   (speaker)     (browser WS)    ││
│                                        │             │          ││
│                                        ▼             ▼          ││
│                                   ┌────────┐  ┌──────────┐     ││
│                                   │Speaker │  │Browser   │     ││
│                                   │(local) │  │Dashboard │     ││
│                                   └────────┘  └──────────┘     ││
└─────────────────────────────────────────────────────────────────┘
```

All audio is processed as 16 kHz, 16-bit signed mono PCM in 80 ms frames (1280 samples). Heavy imports (whisper.cpp, onnxruntime, sounddevice) are lazy-loaded inside methods so the pipeline is a no-op when `ENABLE_LOCAL_VOICE=false`.

Cross-channel voice sessions (Telegram, Discord, Slack) are managed by the **Voice Bridge** (`voice_bridge.py`), which reuses the same STT/TTS components and routes audio through the `VoiceSessionManager`.

## 2. Speech-to-Text (STT)

### Primary Engine: pywhispercpp

The primary transcription engine is `pywhispercpp` — a Python binding to the C++ `whisper.cpp` inference engine. It runs on CPU with ggml-quantized models (~75 MB for `ggml-tiny.bin`). The model is loaded once and cached globally via a `threading.Lock` so the on-device pipeline, Telegram voice handler, Discord attachments, and browser WebSocket streams all share the same loaded model.

- **Model resolution**: `WHISPER_CPP_MODEL` env var (path to `ggml-*.bin`) → `Config.VOICE_STT_MODEL` (legacy) → `"tiny"` (default)
- **Language**: `WHISPER_CPP_LANGUAGE` (default: `"en"`)
- **Threads**: `WHISPER_CPP_THREADS` (default: `2`)
- **Offline mode**: `WHISPER_CPP_OFFLINE=1` raises `FileNotFoundError` if the model file is missing (test-env fast-fail)

### Fallback: Vosk

When `pywhispercpp` is not installed, the system falls back to Vosk with the `vosk-model-small-en-us-0.15` model shipped at `app/voice/vosk-model-small-en-us-0.15/`. Vosk is fully offline, requires no network, and converts input to WAV mono 16 kHz 16-bit before feeding the recognizer.

### API

```python
# Async (runs blocking engine in thread pool)
text = await transcribe_audio("/path/to/audio.wav")
text = await transcribe_bytes(audio_bytes)

# Sync (blocking, called by transcribe_audio internally)
text = _transcribe_sync(audio_path)
```

Both return `""` on failure and never raise.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `WHISPER_CPP_MODEL` | `"tiny"` | Path to ggml model file |
| `WHISPER_CPP_LANGUAGE` | `"en"` | Transcription language |
| `WHISPER_CPP_THREADS` | `2` | CPU threads for inference |
| `WHISPER_CPP_OFFLINE` | `""` | Fail if model file is missing |

## 3. Text-to-Speech (TTS)

### Engine: Piper-TTS ONNX

Piper is the local TTS engine. It uses `onnxruntime` to run a quantized voice model (`en_US-lessac-medium.onnx`, ~50 MB) and produces 22 050 Hz mono WAV output.

The `PiperTTS` class (`app/voice/piper.py`) is designed for minimal overhead:

- **Lazy-loaded**: The ONNX kernel (~3 s to init) is loaded on first `synthesize` call and cached at module level so two `VoicePipeline` instances share the same voice.
- **Thread-safe**: Load + synthesize is wrapped in a `threading.Lock` (Piper's ONNX session is not re-entrant).
- **Error-swallowing**: Returns `b""` on any exception so a missing model file does not crash the chat path.
- **Backward-compat shim**: `synthesize_to_path()` writes bytes to a temp file for callers expecting a file path.

### autherRaven Personality Voice

The default voice model is `app/voice/en_US-lessac-medium.onnx` (`autherRaven`). Operators can swap it by setting `PIPER_VOICE_MODEL` to a different `.onnx` path (with matching `.onnx.json` config file).

### Public API (`app/voice/tts.py`)

```python
# Returns path to generated .wav file (or "" on failure)
audio_path = await synthesize(text, voice=None)

# Returns WAV bytes directly (used by browser WS sink)
wav_bytes = await synthesize_bytes(text, voice=None)
```

### Configuration

| Variable | Default | Description |
|---|---|---|
| `PIPER_VOICE_MODEL` | `"app/voice/en_US-lessac-medium.onnx"` | Path to Piper `.onnx` model |
| `PIPER_VOICE_CONFIG` | `{model_stem}.json` | Path to model config |
| `PIPER_VOICE_NAME` | model file stem | Human-readable voice name |

**Deprecation note**: The legacy `VOICE_TTS_VOICE` env var (which held BCP-47 strings like `en-US-AriaNeural`) is still read but logs a `DeprecationWarning`. Set `PIPER_VOICE_MODEL` instead.

### Streaming TTS

The `VoicePipeline._speak_streaming()` method splits the LLM response into sentences (via regex on `[.!?]`) and synthesizes them one at a time. Audio playback begins on the first sentence while later sentences are still being generated. A barge-in check happens between sentences.

### Emotion-Driven TTS

The `detect_emotion()` function in `app/voice/emotion.py` performs keyword/regex-based sentiment analysis on the response text (sub-millisecond, no LLM). It returns `EmotionParams`:

| Emotion | Speed | Pitch | Energy |
|---|---|---|---|
| neutral | 1.0 | 1.0 | normal |
| happy | 1.05 | 1.05 | high |
| sad | 0.9 | 0.95 | low |
| urgent | 1.15 | 1.0 | high |
| angry | 1.1 | 1.1 | high |
| concerned | 0.95 | 1.0 | normal |
| calm | 0.92 | 0.98 | low |
| excited | 1.12 | 1.08 | high |

Emotion parameters are applied via pydub time-stretch in `_apply_emotion_to_audio()`.

## 4. Full Pipeline

The full-duplex pipeline lives in `app/voice/pipeline.py` (`VoicePipeline` class). It runs in a blocking loop inside a thread executor, bridging to asyncio for the orchestrator and sink registry calls.

### Wake Word Detection

Uses **openwakeword** with ONNX runtime (no PyTorch dependency). The model (`hey_jarvis`) runs at every 80 ms audio frame:

1. PCM frames are normalized to float32 `[-1, 1]`
2. `oww.predict(pcm_f32)` returns a `dict[str, float]` of wake word scores
3. If `max(score) >= VOICE_WAKE_WORD_THRESHOLD`, the pipeline transitions to `recording` state
4. A confirmation chime (880 Hz, 150 ms sine tone) is played

### Voice Activity Detection (VAD)

Energy-based RMS thresholding — pure numpy, no `webrtcvad` dependency:

- **Threshold**: `_RMS_SPEECH_THRESHOLD = 300` (configurable via `VOICE_VAD_THRESHOLD`)
- **Frame size**: 1280 samples at 16 kHz = 80 ms
- **End-of-utterance**: 15 consecutive silence frames (~1.2 s) or hard cap of 300 frames (24 s)
- **Barge-in**: If `_is_playing` is true and RMS exceeds threshold, `_is_playing` is set to `False` and `_barge_in_event` is fired

### Speculative STT

After ~480 ms (6 frames) of speech, the pipeline starts a background transcription of the partial audio via `_speculative_transcribe()`. If the utterance ends and the full audio length is under 30 KB, the speculative result is used directly — saving ~500 ms of latency.

### Audio Constants

| Constant | Value | Description |
|---|---|---|
| `_SAMPLE_RATE` | 16000 | Sample rate (Hz) |
| `_CHANNELS` | 1 | Mono |
| `_DTYPE` | `"int16"` | Sample format |
| `_BLOCKSIZE` | 1280 | 80 ms at 16 kHz |
| `_RMS_SPEECH_THRESHOLD` | 300 | VAD threshold |
| `_SILENCE_FRAMES_TO_END` | 15 | ~1.2 s silence → end |
| `_MAX_UTTERANCE_FRAMES` | 300 | 24 s hard cap |
| `_SPECULATIVE_STT_ENABLED` | `True` | Speculative transcription |

### Configuration

| Variable | Default | Description |
|---|---|---|
| `ENABLE_LOCAL_VOICE` | `true` | Enable the local pipeline |
| `VOICE_WAKE_WORD_THRESHOLD` | `0.5` | OpenWakeWord confidence threshold |
| `VOICE_VAD_THRESHOLD` | `300` | RMS energy threshold for speech |
| `VOICE_MIC_DEVICE` | system default | sounddevice input device index |

## 5. Sink Registry

The `SinkRegistry` (`app/voice/sink_registry.py`) decouples TTS production from audio output. Instead of hardcoding `sounddevice.play()` in the pipeline, TTS audio is dispatched to every registered `VoiceSink` for a given user.

### VoiceSink ABC

```python
class VoiceSink(abc.ABC):
    async def play(self, audio_bytes: bytes, sample_rate: int) -> None: ...
    async def open(self) -> None: ...   # lifecycle hook
    async def close(self) -> None: ...  # lifecycle hook
```

### Concrete Sinks

| Sink | Description |
|---|---|
| `LocalSoundDeviceSink` | Plays audio via `sounddevice.play()` on the local speaker. Uses a `threading.Event` to drop overlapping plays (barge-in semantics). |
| `WebSocketVoiceSink` | Forwards audio to a browser tab over WebSocket. Frame layout: 4-byte LE sample-rate prefix + raw WAV bytes. |
| `NoOpSink` | Records plays for test introspection; does nothing with audio. |

### Dispatch Pattern

`SinkRegistry` provides two methods:

```python
# From a file path (reads bytes once, then unlinks)
await registry.play(user_id, "/path/to/audio.wav")

# From raw bytes (no file I/O)
await registry.play_bytes(user_id, audio_bytes, sample_rate)
```

Both methods:

1. Look up all sinks registered for `user_id`
2. Dispatch to every sink via `asyncio.gather()` (parallel, non-blocking)
3. Per-sink exceptions are caught and logged — one failing sink does not cancel the others
4. The singleton is accessed via `get_sink_registry()`

The pipeline registers a `LocalSoundDeviceSink` at startup for the on-device user. Additional `WebSocketVoiceSink` instances can be registered for the same `user_id` without removing the local one — both play simultaneously.

## 6. Voice Bridge

The `VoiceSessionManager` (`app/voice/voice_bridge.py`) provides cross-channel voice sessions. It manages active `VoiceSession` instances that track per-user/per-platform conversation state.

### VoiceSession

```python
@dataclass
class VoiceSession:
    session_id: str
    platform: str      # "telegram", "discord", "slack"
    user_id: str
    chat_id: str
    transcription: list[str]
```

### Lifecycle

1. **start_session**(platform, user_id, chat_id) → creates a `VoiceSession` with unique `session_id`
2. **feed_audio**(session_id, audio_bytes) → transcribes via `transcribe_bytes()` and appends to session transcription
3. **process_transcription**(session_id, text) → forwards to `MessageOrchestrator` as an `IncomingRequest` with platform-specific tags
4. **end_session**(session_id) → logs duration and utterance count, removes from active sessions

The singleton is `get_voice_session_manager(orchestrator, botsignal)`.

## 7. Voice Tool

The `VoiceTool` (`app/voice/voicetool.py`) is registered as an agent-callable tool that wraps the voice pipeline into discrete operations.

### Operations

| Operation | Description |
|---|---|
| `detect_wake_word` | Listen for wake words via OpenWakeWord |
| `listen` | Record N seconds of microphone audio |
| `transcribe` | Convert audio to text (Vosk) |
| `speak` | Text-to-speech via edge TTS |
| `voice_pipeline` | Full: wake word → listen → transcribe |

### Tool Schema

The tool accepts parameters for each operation: `wake_words`, `wake_threshold`, `wake_timeout`, `record_seconds`, `sample_rate`, `device_index`, `audio_path`, `audio_b64`, `tts_voice`, `tts_output_path`, etc.

Returns a `Dict[str, Any]` with `success`, `transcript` (for transcribe operations), `saved_to` (for speak), and operation-specific metadata.

## 8. Speaker Identification

`SpeakerIdentifier` (`app/voice/speaker_id.py`) provides voice biometrics for multi-user recognition.

### Backends (priority order)

1. **resemblyzer** — `VoiceEncoder` lightweight pretrained model
2. **speechbrain** — `spkrec-ecapa-voxceleb` larger model, higher accuracy
3. **Fallback** — always returns `"local"` with confidence 0.0

### API

```python
# Enroll a new speaker
success = speaker_id.enroll("Alice", "alice_001", "/path/to/audio.wav")

# Identify speaker from audio
user_id, confidence = speaker_id.identify("/path/to/audio.wav")
# Returns ("local", 0.0) if no match
```

### Enrollment

The pipeline supports voice enrollment via natural language commands: "register my voice as Alice". The voice sample is embedded and stored in `workspace/voice/speaker_profiles/` as a `.json` metadata file + `.npy` embedding file (cosine similarity threshold: 0.75).

When a speaker is identified, the pipeline sets the `user_id` on the `IncomingRequest` so the orchestrator can route responses per-user.

## 9. Voice Cloning

`VoiceProfileManager` (`app/voice/cloning.py`) provides per-user voice profiles and adaptive TTS configuration.

### VoiceProfile

```python
@dataclass
class VoiceProfile:
    user_id: str
    voice_model: str        # Piper model path
    speed: float            # 0.5–2.0
    pitch: float            # 0.5–2.0
    energy: str             # low, normal, high
    language: str
    enrolled: bool
    enrollment_samples: int
```

### Adaptive Voice

`get_adaptive_voice(user_id, context)` adjusts TTS parameters based on:

- **User preferences**: Saved speed/pitch/energy from profile
- **Time of day**: Morning = faster, late night = slower/calmer
- **Activity**: Working = focused, relaxing = casual
- **Mood/emotion**: Detected from conversation context

Profiles are stored as JSON in `workspace/voice_profiles/`.

## 10. Voice Channels

The `VoiceChannel` abstraction layer (`app/voice/channels/base.py`) provides a unified interface for all calling platforms.

### CallState Machine

```
IDLE → RINGING → CONNECTING → ACTIVE → ENDED
                         ↘ HOLD → ACTIVE
                          → FAILED
```

### VoiceChannel Interface

```python
class VoiceChannel(ABC):
    platform_name: str
    async def start(stop_event)
    async def make_call(target) → CallInfo
    async def answer_call(call_id)
    async def hangup_call(call_id)
    async def hold_call(call_id)
    async def resume_call(call_id)
    async def send_audio(call_id, audio_bytes)
    async def send_dtmf(call_id, digits)
```

### Platform Implementations

| File | Platform | Media Transport |
|---|---|---|
| `channels/sip.py` | SIP | RTP/Opus |
| `channels/telegram.py` | Telegram | Telegram Voice Chat API |
| `channels/whatsapp.py` | WhatsApp | WhatsApp Cloud API audio |

Callbacks (`on_audio_received`, `on_call_state_change`, `on_dtmf_received`) are registered by the `CallManager` and wired to the STT pipeline and orchestrator.

### CallManager

`CallManager` (`app/voice/call_manager.py`) is the central call router. It registers channel adapters, tracks active calls with `ActiveCall` state (including transcript buffers and optional WAV recording), and routes audio through the STT → orchestrator → TTS pipeline.

## 11. A2A Server

The A2A-compliant `ModuleServer` (`app/voice/a2a_server.py`) exposes voice capabilities via the Raven Protocol. Registered methods:

| Method | Handler |
|---|---|
| `voice.synthesize` | `handle_synthesize` — TTS from text |
| `voice.detect_emotion` | `handle_detect_emotion` — sentiment → parameters |
| `voice.detect_language` | `handle_detect_language` — language identification |

## 12. Configuration Reference

| Variable | Default | Component | Description |
|---|---|---|---|
| `ENABLE_LOCAL_VOICE` | `true` | Pipeline | Enable the on-device voice pipeline |
| `VOICE_WAKE_WORD_THRESHOLD` | `0.5` | Pipeline | OpenWakeWord confidence threshold (0–1) |
| `VOICE_VAD_THRESHOLD` | `300` | Pipeline | RMS energy threshold for VAD |
| `VOICE_MIC_DEVICE` | system default | Pipeline | sounddevice input device index |
| `VOICE_TTS_VOICES` | `""` | Pipeline | Per-user voice mapping (`user:model,user:model`) |
| `WHISPER_CPP_MODEL` | `"tiny"` | STT | Path to ggml model file |
| `WHISPER_CPP_LANGUAGE` | `"en"` | STT | Transcription language |
| `WHISPER_CPP_THREADS` | `2` | STT | CPU threads for inference |
| `WHISPER_CPP_OFFLINE` | `""` | STT | Fail if model file is missing |
| `PIPER_VOICE_MODEL` | `"app/voice/en_US-lessac-medium.onnx"` | TTS | Piper `.onnx` model path |
| `PIPER_VOICE_CONFIG` | `{model}.json` | TTS | Piper model config file |
| `PIPER_VOICE_NAME` | `"autherRaven"` | TTS | Voice display name |
| `VOICE_TTS_VOICE` | (deprecated) | TTS | Legacy BCP-47 voice name |

## 13. Developer Guide

### Adding a New Sink

1. Subclass `VoiceSink` in `app/voice/sinks.py`
2. Implement `play(self, audio_bytes: bytes, sample_rate: int) -> None` (must be async, must never raise)
3. Optionally implement `open()` and `close()` lifecycle hooks
4. Register with the sink registry:
   ```python
   from app.voice.sink_registry import get_sink_registry
   registry = get_sink_registry()
   registry.register("user_id", MySink("user_id"))
   ```

### Using a Custom Voice Model

1. Download or train a Piper `.onnx` model (with its `.onnx.json` config)
2. Set `PIPER_VOICE_MODEL=/path/to/your-model.onnx`
3. (Optional) Set `PIPER_VOICE_NAME="my-voice"` for display purposes

### Replacing the Wake Word

The default model is `hey_jarvis`. To use a custom wake word:

1. Train or download an OpenWakeWord `.onnx` model
2. Replace the call in `pipeline.py:_loop_blocking`:
   ```python
   oww = OWWModel(
       wakeword_models=["path/to/custom_model"],
       inference_framework="onnx",
   )
   ```

### Running Tests

The STT, TTS, sink registry, and speaker ID modules all expose `reset_*_for_tests()` functions to drop caches between tests. Call these in pytest autouse fixtures:

```python
from app.voice.transcribe import reset_whisper_cpp_for_tests
from app.voice.piper import PiperTTS
from app.voice.sink_registry import reset_sink_registry_for_tests

@pytest.fixture(autouse=True)
def reset_voice_modules():
    reset_whisper_cpp_for_tests()
    PiperTTS.reset_cache_for_tests()
    reset_sink_registry_for_tests()
```
