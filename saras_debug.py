#!/usr/bin/env python3
"""
SARAS Voice Assistant - Debug Version
Shows real-time audio levels and recognition
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
    level="DEBUG",
)

MODEL_PATH = "app/voice/vosk-model-small-en-us-0.15"
TARGET_SR = 16000
FRAME_SIZE = 1024
DEVICE_ID = 37

ENERGY_THRESHOLD = 0.010
SILENCE_DURATION = 1.5

running = True


def signal_handler(sig, frame):
    global running
    logger.info("\n⛔ Stopping...")
    running = False


def main():
    global running

    logger.info("=" * 60)
    logger.info("🎤 SARAS Debug Mode")
    logger.info("=" * 60)

    device_id = DEVICE_ID
    device_info = sd.query_devices(device_id)
    device_sr = int(device_info["default_samplerate"])
    logger.info(f"📍 Device: {device_info['name']} (ID: {device_id})")
    logger.info(f"📊 Sample rate: {device_sr} Hz -> {TARGET_SR} Hz")

    logger.info("📥 Loading Vosk model...")
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, TARGET_SR)
    logger.info("✅ Ready!")
    logger.info("-" * 60)

    def resample_audio(audio_data, orig_sr, target_sr):
        if orig_sr == target_sr:
            return audio_data
        duration = len(audio_data) / orig_sr
        num_samples = int(duration * target_sr)
        orig_time = np.linspace(0, len(audio_data) - 1, len(audio_data))
        target_time = np.linspace(0, len(audio_data) - 1, num_samples)
        return np.interp(target_time, orig_time, audio_data)

    state = "WAITING"
    audio_buffer = []
    silence_start = None
    last_trigger = 0
    frame_count = 0

    def audio_callback(indata, frames, time_info, status):
        nonlocal \
            state, \
            audio_buffer, \
            silence_start, \
            last_trigger, \
            frame_count, \
            recognizer

        audio_data = indata[:, 0].astype(np.float32)
        if device_sr != TARGET_SR:
            audio_data = resample_audio(audio_data, device_sr, TARGET_SR)

        energy = np.abs(audio_data).mean()
        frame_count += 1

        # Show levels every 20 frames
        if frame_count % 20 == 0:
            bar_len = int(min(energy * 100, 50))
            bar = "█" * bar_len + "░" * (50 - bar_len)
            print(f"\r📊 [{bar}] {energy:.4f} | State: {state}    ", end="", flush=True)

        # State machine
        if state == "WAITING":
            if energy > ENERGY_THRESHOLD:
                if time.time() - last_trigger > 3.0:
                    state = "LISTENING"
                    audio_buffer = [audio_data.astype(np.int16).tobytes()]
                    logger.info(f"🎤 Speech detected! (energy: {energy:.3f})")

        elif state == "LISTENING":
            audio_buffer.append(audio_data.astype(np.int16).tobytes())

            if energy > ENERGY_THRESHOLD:
                silence_start = None
            else:
                if silence_start is None:
                    silence_start = time.time()
                elif time.time() - silence_start > SILENCE_DURATION:
                    state = "PROCESSING"

    def process_audio():
        nonlocal state, audio_buffer, last_trigger, recognizer

        if state == "PROCESSING" and audio_buffer:
            logger.info("🔄 Processing speech...")

            for chunk in audio_buffer:
                if recognizer.AcceptWaveform(chunk):
                    result = json.loads(recognizer.FinalResult())
                    text = result.get("text", "").strip()
                    if text:
                        logger.info(f"💬 Heard: '{text}'")

            # Final result
            result = json.loads(recognizer.FinalResult())
            text = result.get("text", "").strip()

            if text:
                logger.info(f"💬 FINAL: '{text}'")
                text_lower = text.lower()
                if "saras" in text_lower or "x" in text_lower:
                    logger.info("🔔 ✅ WAKE WORD DETECTED!")
                else:
                    logger.info("🤔 Say 'hey saras' first")
            else:
                logger.info("🤷 No speech recognized")

            audio_buffer = []
            recognizer = KaldiRecognizer(model, TARGET_SR)
            last_trigger = time.time()
            state = "WAITING"
            print()

    signal.signal(signal.SIGINT, signal_handler)

    logger.info("🚀 Listening... Speak now!")
    logger.info("💡 Try: 'hey saras what is the weather'")
    logger.info("-" * 60)

    with sd.InputStream(
        samplerate=device_sr,
        blocksize=FRAME_SIZE,
        dtype="float32",
        channels=1,
        device=device_id,
        callback=audio_callback,
    ):
        while running:
            process_audio()
            sd.sleep(50)


if __name__ == "__main__":
    main()
