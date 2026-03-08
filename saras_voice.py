#!/usr/bin/env python3
"""
SARAS Voice Assistant - Energy-based wake word detection
Triggers on loud speech and listens for "hey saras" command
"""

import json
import signal
import sys
import time

import numpy as np
import sounddevice as sd
from loguru import logger
from vosk import KaldiRecognizer, Model

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
    level="INFO",
)

MODEL_PATH = "app/voice/vosk-model-small-en-us-0.15"
TARGET_SR = 16000
FRAME_SIZE = 1024

# Use Chromium-76 device which captures your voice
DEVICE_ID = 37  # Chromium-76 (found from test)

# Voice activation thresholds
ENERGY_THRESHOLD = 0.015  # Audio level to trigger listening
SILENCE_DURATION = 1.5  # Seconds of silence to stop listening

running = True


def signal_handler(sig, frame):
    global running
    logger.info("\n⛔ Stopping...")
    running = False


def main():
    global running

    logger.info("=" * 60)
    logger.info("🎤 SARAS Voice Assistant")
    logger.info("=" * 60)

    # Use the Chromium-76 device that captures your voice
    device_id = DEVICE_ID
    try:
        device_info = sd.query_devices(device_id)
        device_sr = int(device_info["default_samplerate"])
        logger.info(f"📍 Using: {device_info['name']} (Device {device_id})")
        logger.info(f"📊 Device sample rate: {device_sr} Hz")
    except Exception as e:
        logger.error(f"Could not get device {device_id}: {e}")
        logger.info("Trying default device...")
        device_id = sd.query_devices(kind="input")["index"]
        device_info = sd.query_devices(device_id)
        device_sr = int(device_info["default_samplerate"])
        logger.info(f"📍 Using default: {device_info['name']} (Device {device_id})")

    # Load Vosk model
    logger.info("📥 Loading Vosk model...")
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, TARGET_SR)
    logger.info("✅ Model loaded")

    def resample_audio(audio_data, orig_sr, target_sr):
        if orig_sr == target_sr:
            return audio_data
        duration = len(audio_data) / orig_sr
        num_samples = int(duration * target_sr)
        orig_time = np.linspace(0, len(audio_data) - 1, len(audio_data))
        target_time = np.linspace(0, len(audio_data) - 1, num_samples)
        return np.interp(target_time, orig_time, audio_data)

    # State machine
    WAITING = 0
    LISTENING = 1

    state = WAITING
    silence_start = None
    speech_start = None
    audio_buffer = []
    last_trigger_time = 0
    cooldown = 3.0

    def audio_callback(indata, frames, time_info, status):
        nonlocal \
            state, \
            silence_start, \
            speech_start, \
            audio_buffer, \
            last_trigger_time, \
            recognizer

        if status:
            logger.debug(f"Status: {status}")

        audio_data = indata[:, 0].astype(np.float32)

        # Resample if needed
        if device_sr != TARGET_SR:
            audio_data = resample_audio(audio_data, device_sr, TARGET_SR)

        # Calculate energy
        energy = np.abs(audio_data).mean()

        current_time = time.time()

        if state == WAITING:
            # Look for loud speech
            if energy > ENERGY_THRESHOLD:
                if (current_time - last_trigger_time) > cooldown:
                    speech_start = current_time
                    state = LISTENING
                    audio_buffer = [audio_data.astype(np.int16).tobytes()]
                    logger.info(f"🎤 Listening... (energy: {energy:.3f})")
            elif energy > 0.003:
                logger.debug(f"📊 Audio: {energy:.4f}")

        elif state == LISTENING:
            # Accumulate audio
            audio_buffer.append(audio_data.astype(np.int16).tobytes())

            if energy > ENERGY_THRESHOLD:
                # Still speaking
                silence_start = None
            else:
                # Check for silence
                if silence_start is None:
                    silence_start = current_time
                elif (current_time - silence_start) > SILENCE_DURATION:
                    # End of speech, process
                    state = WAITING
                    last_trigger_time = current_time

                    # Process accumulated audio
                    for chunk in audio_buffer:
                        recognizer.AcceptWaveform(chunk)

                    result = json.loads(recognizer.FinalResult())
                    text = result.get("text", "").strip()

                    if text:
                        logger.info(f"💬 YOU SAID: '{text}'")

                        # Check for wake word
                        text_lower = text.lower()
                        if (
                            "saras" in text_lower
                            or "x" in text_lower
                            or "assist" in text_lower
                        ):
                            logger.info("🔔 ✅ Wake word detected!")
                            logger.info(f"✨ COMMAND: {text}")
                        else:
                            logger.info(f"🤔 Say 'hey saras' first, then your command")
                    else:
                        logger.debug("🤷 No speech recognized")

                    # Reset
                    audio_buffer = []
                    recognizer = KaldiRecognizer(model, TARGET_SR)

    signal.signal(signal.SIGINT, signal_handler)

    logger.info("-" * 60)
    logger.info(f"⚡ Energy threshold: {ENERGY_THRESHOLD}")
    logger.info(f"⏱️  Speak loudly to activate")
    logger.info(f"💡 Say: 'hey saras, what is the weather'")
    logger.info("-" * 60)
    logger.info("🚀 Ready! Start speaking...")

    # Start streaming
    with sd.InputStream(
        samplerate=device_sr,
        blocksize=FRAME_SIZE,
        dtype="float32",
        channels=1,
        device=device_id,
        callback=audio_callback,
    ):
        while running:
            sd.sleep(100)


if __name__ == "__main__":
    main()
