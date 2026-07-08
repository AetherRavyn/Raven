---
title: Machine Learning Depth
description: The on-device ML components powering RAVEN voice, speech, and tool-calling
---

# 07 - Machine Learning Depth

## Why This Document Matters

Calling an API is not machine learning. Downloading a pre-trained model and running
inference is not machine learning. This document covers what RAVEN **actually runs
and wires into its production system** today: the on-device / local ML components that
power voice, speech understanding, speaker verification, and tool-calling — and how
they are integrated.

> **Scope note (honesty):** RAVEN does **not** ship a bespoke training corpus, a
> fine-tuning pipeline with published benchmark numbers, or an experiment-tracking
> stack (no MLflow / W&B). The components below are *integration* points around
> strong open-source models. Where this document previously cited specific accuracy,
> WER, or dataset-size figures, those numbers were illustrative and have been removed
> because they were not measured against a documented, reproducible dataset. Any
> future quantitative evaluation will be reported against a clearly described,
> versioned dataset.

---

## ML Components Overview

| Component | Approach | Status | Section |
|---|---|---|---|
| Speech-to-Text (STT) | Local Whisper-family models (whisper.cpp / faster-whisper) with a Vosk fallback | Shipped / integrated | 1 |
| Text-to-Speech (TTS) | Piper neural TTS (VITS architecture, ONNX) | Shipped / integrated | 2 |
| Speaker verification | Embedding-based voice ID (e.g. resemblyzer) | Shipped / integrated | 3 |
| Voice cloning (optional) | XTTS-style reference-clip cloning | Available, optional | 4 |
| Personality & tone | System-prompt engineering + retrieval-augmented memory | Shipped / integrated | 5 |
| Tool selection | Constrained / structured JSON decoding | Shipped / integrated | 6 |
| Sensor anomaly detection | Statistical + (optional) learned models | Conceptual / partial | 7 |

---

## 1. Speech-to-Text (STT)

RAVEN transcribes user speech locally so audio never has to leave the host. The
transcription engine lives in `app/voice/transcribe.py` and is built around a
pluggable model loader:

- **Primary engine:** a local Whisper-family model — `whisper.cpp` (via the
  `pywhispercpp` binding) for CPU-friendly, ggml-quantised inference. `faster-whisper`
  can also be used where the environment provides it.
- **Fallback engine:** `Vosk` small-model recognition is used when the Whisper engine
  is unavailable, keeping the voice pipeline functional on minimal hardware.

The loader exposes a single transcription entry point so the rest of the voice stack
(`pipeline.py`, `voice_bridge.py`) does not depend on which backend is active. Models
are loaded once and cached (thread-safe) to avoid repeated startup cost.

```text
Microphone / audio source
        │
        ▼
  Transcribe engine (app/voice/transcribe.py)
        │   ├─ whisper.cpp (pywhispercpp)   ← primary, quantised, CPU
        │   └─ Vosk                         ← fallback
        ▼
  Transcript → orchestrator / LLM
```

Design considerations (not measured benchmarks):

- Quantised models trade a small amount of accuracy for dramatically lower latency and
  memory footprint on CPU / edge devices.
- IoT-specific vocabulary (device names, protocol names) is the main source of
  transcription error and is mitigated through prompting/context rather than a custom
  fine-tune in the shipped build.

---

## 2. Text-to-Speech (TTS) — Piper

RAVEN speaks using **Piper**, a neural TTS engine based on the VITS (Variational
Inference with adversarial learning for end-to-end Text-to-Speech) architecture. The
wrapper lives in `app/voice/piper.py` (`PiperTTS`).

Key properties of the shipped integration:

- The voice model is a pre-trained Piper voice (e.g. `en_US-lessac-medium.onnx`,
  shipped in `app/voice/`).
- The class is intentionally tiny: it lazily loads the underlying Piper voice module,
  caches the loaded voice, and exposes a simple `synthesize(text) -> bytes` API.
- Output is returned as raw WAV bytes that the voice pipeline streams to the user's
  channel.

```text
Text ("Done, lights are on.")
        │
        ▼
  PiperTTS.synthesize()  (app/voice/piper.py)
        │   └─ loads piper.voice model from .onnx
        ▼
  WAV audio → sink / channel
```

The Piper architecture itself (for reference, not a RAVEN-specific measurement):

```text
Text → Phoneme encoder → Duration predictor → Flow-based decoder
     → HiFi-GAN vocoder → waveform
```

---

## 3. Speaker Verification

Before acting on sensitive voice commands, RAVEN can verify *who is speaking* using
`app/voice/speaker_id.py` (`SpeakerIdentifier`). This is an embedding-based approach:

- A voice **embedding** is computed for any utterance (using an available speaker
  encoder such as `resemblyzer`'s pretrained `SpeakerEncoder`).
- Enrolled users each store a reference embedding in a `SpeakerProfile`.
- A new utterance is accepted as matching a user when the cosine similarity between
  its embedding and the enrolled profile exceeds a threshold
  (`_SIMILARITY_THRESHOLD = 0.75`).

```text
Utterance → SpeakerEncoder → embedding
                        │
                        ▼
        cosine similarity vs enrolled profiles
                        │
        > threshold ──► verified owner
        ≤ threshold ──► unknown / rejected for sensitive actions
```

This integrates with the security model (see `features-safety.md`): speaker
verification gates privileged voice commands, complementing DM-pairing and the
governance engine.

---

## 4. Voice Cloning (Optional)

For higher-fidelity speech, `app/voice/cloning.py` (`VoiceProfile`,
`VoiceProfileManager`) manages optional voice profiles. Reference-clip cloning
approaches (XTTS-style) can be layered on top where a clean reference sample is
available. This is an **optional** capability and is not required for the default
Piper voice path.

---

## 5. Personality & Tone

RAVEN's "personality" is primarily delivered through **prompt engineering**, not a
trained model:

- Each agent assembles a rich system prompt from `soul`, `personality`, `goals`,
  skills, and retrieved memory (`BaseAgent.get_enhanced_prompt()`).
- Conversation and factual memory are stored (SQLite + FTS5 `LearningDB`, plus
  semantic stores) and retrieved to keep responses consistent and grounded.
- Tone (concise, casual, friendly) is expressed in the prompt and reinforced by
  examples, not by a separate fine-tuned LoRA in the shipped build.

This keeps the system adaptable: personality can be tuned by editing prompts and
memory rather than retraining a model.

---

## 6. Tool Selection

When the LLM must invoke a tool, RAVEN relies on **structured / constrained decoding**
rather than hoping the model emits valid JSON:

- Tools expose a `ToolSchema` (name, description, typed parameters) compatible with
  OpenAI-style function calling.
- The orchestrator validates parameters against the schema before execution and
  rejects malformed or missing-required-field calls.
- Where supported, the model backend is asked to emit tool calls in a constrained
  format so invalid tool names / arguments are caught at the decoding or validation
  layer.

This avoids the most common failure modes (hallucinated tool names, malformed
arguments) without requiring a bespoke classifier model.

---

## 7. Sensor Anomaly Detection (Conceptual)

Sensor readings arrive via MQTT (`app/sensors/mqtt_listener.py`) and the webhook
server. A reasonable anomaly strategy combines:

- **Statistical baselines** — rolling z-scores with seasonal (time-of-day) adjustment
  to tell "temperature drops at night" from "unexpected spike".
- **Learned models (optional)** — an autoencoder can be trained on *normal* sensor
  windows so reconstruction error flags deviations. This is a conceptual / partial
  integration: it is only as good as the normal-data it is trained on, and RAVEN does
  not ship a pre-trained sensor model or labelled anomaly corpus.

The takeaway: anomaly detection is a heuristic + (optional) learned hybrid, and any
reported precision/recall figures would depend entirely on the user's own labelled
data, which is not bundled.

---

## Summary

| Skill Area | Evidence in RAVEN |
|---|---|
| On-device inference | Local Whisper STT + Piper TTS, no cloud required for voice I/O |
| Embedding systems | Speaker verification via voice embeddings; semantic memory search |
| Prompt engineering | Per-agent enhanced prompts, soul/personality/goals, retrieved memory |
| Structured decoding | ToolSchema validation + constrained tool-calling |
| Sensor processing | MQTT ingestion + statistical anomaly heuristics |
| Safety integration | Speaker ID + DM-pairing + deny-by-default governance |

RAVEN's ML depth today is best described as **production-grade integration of strong
open-source models with a safety- and latency-aware runtime**, rather than a portfolio
of internally trained, benchmarked models. Future work may add measured, reproducible
evaluations — and when it does, this document will report them against versioned
datasets rather than round numbers.
