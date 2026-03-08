#!/usr/bin/env python3
"""
Conversational wake word activation ("hey jarvis" / custom wake word)
Says greeting, listens and transcribes response, deactivates after silence.
"""

import json
import queue
import signal
import sys
import time

import numpy as np
import sounddevice as sd
from loguru import logger
from openwakeword.model import Model
from vosk import KaldiRecognizer
from vosk import Model as VoskModel

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
    level="INFO",
)

SAMPLERATE = 16000
# OWW requires exactly 1280 samples (80ms at 16kHz) per predict() call.
BLOCKSIZE = 1280

audio_queue: queue.Queue = queue.Queue()
running = True

# ── Wake word ──────────────────────────────────────────────────────────────────
WAKE_WORD_THRESHOLD = 0.5
WAKE_WORD_NAME = (
    "hey_jarvis"  # built-ins: alexa, hey_mycroft, hey_jarvis, timer, weather
)
CUSTOM_MODEL_PATH: str | None = None  # path to custom .onnx, or None for built-in

# After a session ends we feed OWW silence frames to flush its internal
# sliding-window state before re-enabling detection.  32 frames x 1280 samples
# = ~2.6 seconds of context cleared.
OWW_FLUSH_FRAMES = 32

# ── Listening ──────────────────────────────────────────────────────────────────
SILENCE_TIMEOUT = 4.0  # seconds of silence -> deactivate
AUDIO_LEVEL_THRESHOLD = 0.02

# ── Vosk ───────────────────────────────────────────────────────────────────────
MODEL_PATH = "app/voice/vosk-model-small-en-us-0.15"


def signal_handler(sig, frame):
    global running
    logger.info("Stopping...")
    running = False


def audio_callback(indata, frames, time_info, status):
    if status:
        logger.debug(f"Audio status: {status}")
    audio_queue.put(bytes(indata))


def flush_final_result(recognizer: KaldiRecognizer) -> str:
    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip()


def main():
    global running

    logger.info("=" * 60)
    logger.info("Conversational Wake Word ('Hey Pix')")
    logger.info("=" * 60)

    # ── Input device ──────────────────────────────────────────────────────────
    try:
        device_id = sd.query_devices(kind="input")["index"]
        device_info = sd.query_devices(device_id)
        logger.info(f"Using: {device_info['name']} (Device {device_id})")
        logger.info(f"Device sample rate: {int(device_info['default_samplerate'])} Hz")
    except Exception as e:
        logger.error(f"Could not get device: {e}")
        return

    # ── OpenWakeWord ──────────────────────────────────────────────────────────
    logger.info("Loading OpenWakeWord models...")
    try:
        if CUSTOM_MODEL_PATH:
            oww_model = Model(wakeword_model_paths=[CUSTOM_MODEL_PATH])
            logger.info(f"Loaded custom model: {CUSTOM_MODEL_PATH}")
        else:
            oww_model = Model()
            logger.info(f"Loaded {len(oww_model.models)} wake word models")
        logger.info(f"Active models: {list(oww_model.models.keys())}")
        if WAKE_WORD_NAME not in oww_model.models:
            logger.warning(
                f"'{WAKE_WORD_NAME}' not in loaded models: {list(oww_model.models.keys())}"
            )
            logger.warning("Set WAKE_WORD_NAME to one of the above names.")
    except Exception as e:
        logger.error(f"Failed to load OpenWakeWord: {e}")
        return

    # ── Vosk ──────────────────────────────────────────────────────────────────
    logger.info("Loading Vosk model...")
    vosk_model = VoskModel(MODEL_PATH)
    logger.info("Vosk model loaded")

    signal.signal(signal.SIGINT, signal_handler)

    # ── State machine ─────────────────────────────────────────────────────────
    STATE_IDLE = 0
    STATE_FLUSHING = 1  # feeding silence to OWW to clear its sliding window
    STATE_LISTENING = 2

    state = STATE_IDLE
    last_trigger_time = 0.0
    last_audio_time = 0.0
    flush_frames_remaining = 0
    recognizer: KaldiRecognizer | None = None

    # Flush OWW once at startup so it starts from a clean state
    silence = np.zeros(BLOCKSIZE, dtype=np.int16)
    for _ in range(OWW_FLUSH_FRAMES):
        oww_model.predict(silence)
    logger.info("OWW state initialised")

    logger.info("-" * 60)
    logger.info(f"Ready! Say '{WAKE_WORD_NAME.replace('_', ' ')}' to start...")
    logger.info("-" * 60)

    with sd.RawInputStream(
        samplerate=SAMPLERATE,
        blocksize=BLOCKSIZE,
        dtype="int16",
        channels=1,
        device=device_id,
        callback=audio_callback,
    ):
        try:
            while running:
                data = audio_queue.get()
                current_time = time.time()

                audio_np = np.frombuffer(data, dtype=np.int16)
                audio_level = np.abs(audio_np.astype(np.float32)).mean() / 32768.0

                # ── FLUSHING: pump silence into OWW to zero out its context ──
                if state == STATE_FLUSHING:
                    oww_model.predict(silence)
                    flush_frames_remaining -= 1
                    if flush_frames_remaining <= 0:
                        state = STATE_IDLE
                    continue  # discard real audio during flush

                # ── IDLE: wake word detection ─────────────────────────────────
                elif state == STATE_IDLE:
                    predictions = oww_model.predict(audio_np)
                    score = predictions.get(WAKE_WORD_NAME, 0.0)

                    if (
                        score > WAKE_WORD_THRESHOLD
                        and current_time - last_trigger_time > 3.0
                    ):
                        last_trigger_time = current_time
                        last_audio_time = current_time
                        logger.info(
                            f"ACTIVATED: '{WAKE_WORD_NAME}' (confidence: {score:.2f})"
                        )
                        print("\nPIX: Hello! What's up?", flush=True)
                        logger.info("Listening for your response...")

                        # Drain any chunks queued during detection
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except queue.Empty:
                                break

                        recognizer = KaldiRecognizer(vosk_model, SAMPLERATE)
                        state = STATE_LISTENING

                # ── LISTENING: transcribe until silence ───────────────────────
                elif state == STATE_LISTENING:
                    if audio_level > AUDIO_LEVEL_THRESHOLD:
                        last_audio_time = current_time

                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        text = result.get("text", "").strip()
                        if text:
                            print()
                            logger.info(f"YOU: '{text}'")
                    else:
                        partial = json.loads(recognizer.PartialResult())
                        partial_text = partial.get("partial", "").strip()
                        if partial_text:
                            print(f"\r{partial_text}    ", end="", flush=True)

                    # Silence timeout -> deactivate
                    if (current_time - last_audio_time) > SILENCE_TIMEOUT:
                        final_text = flush_final_result(recognizer)
                        if final_text:
                            print()
                            logger.info(f"YOU (final): '{final_text}'")

                        logger.info("Deactivating (silence detected)")
                        logger.info("-" * 60)
                        logger.info(
                            f"Ready! Say '{WAKE_WORD_NAME.replace('_', ' ')}' to start..."
                        )
                        logger.info("-" * 60)

                        recognizer = None
                        last_audio_time = 0.0

                        # Enter FLUSHING state to clear OWW's sliding window
                        # before re-enabling wake word detection — prevents
                        # the echo of this session from immediately re-triggering
                        flush_frames_remaining = OWW_FLUSH_FRAMES
                        state = STATE_FLUSHING

        except KeyboardInterrupt:
            logger.info("\nDone")


if __name__ == "__main__":
    main()
