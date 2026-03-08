#!/usr/bin/env python3
"""
Test with PipeWire monitor/Easy Effects source
This captures audio that's already being processed by the system
"""

import signal
import sys
import time

import numpy as np
import sounddevice as sd
from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
    level="INFO",
)

running = True

# Try monitor/effect sources
DEVICES_TO_TRY = [
    (43, "Easy Effects Source"),  # Captures processed audio
    (37, "Chromium-76"),  # Browser input
    (38, "Chromium"),  # Browser input
    (44, "Chromium input"),  # Browser input
    (24, "pipewire"),  # PipeWire source
    (25, "pulse"),  # PulseAudio source
    (12, "sysdefault"),  # System default
]


def signal_handler(sig, frame):
    global running
    logger.info("\n⛔ Stopping...")
    running = False


def test_device(device_id, device_name):
    global running

    logger.info(f"🎤 Testing: {device_name} (Device {device_id})")
    logger.info("   Speak now or play audio...")

    frame_count = 0
    max_level = 0

    def audio_callback(indata, frames, time_info, status):
        nonlocal frame_count, max_level

        if status:
            logger.debug(f"Status: {status}")

        audio_data = indata[:, 0].astype(np.float32)
        audio_level = np.abs(audio_data).mean()
        max_level = max(max_level, audio_level)

        frame_count += 1
        if frame_count % 10 == 0:
            bar_len = int(min(audio_level * 100, 50))
            bar = "█" * bar_len + "░" * (50 - bar_len)
            print(
                f"\r   [{bar}] {audio_level:.4f} (max: {max_level:.4f})    ",
                end="",
                flush=True,
            )

    try:
        # Get device info for proper sample rate
        device_info = sd.query_devices(device_id)
        device_sr = int(device_info["default_samplerate"])

        with sd.InputStream(
            samplerate=device_sr,
            blocksize=512,
            dtype="float32",
            channels=1,
            device=device_id,
            callback=audio_callback,
        ):
            start_time = time.time()
            while running and (time.time() - start_time) < 5:
                sd.sleep(100)
    except Exception as e:
        logger.error(f"   ❌ Failed: {e}")
        return False

    print()
    if max_level > 0.01:
        logger.info(f"   ✅ GOOD! Max level: {max_level:.4f}")
        return True
    else:
        logger.info(f"   ❌ Too quiet (max: {max_level:.4f})")
        return False


def main():
    global running

    logger.info("=" * 60)
    logger.info("🎤 PipeWire Monitor Test")
    logger.info("=" * 60)
    logger.info("Testing monitor/effect sources...")
    logger.info("Speak or play audio during test!")
    logger.info("-" * 60)

    signal.signal(signal.SIGINT, signal_handler)

    for device_id, device_name in DEVICES_TO_TRY:
        if not running:
            break

        if test_device(device_id, device_name):
            logger.info("=" * 60)
            logger.info(f"✅ Found working device: {device_name} (ID: {device_id})")
            logger.info("=" * 60)
            return

    logger.info("=" * 60)
    logger.info("❌ No device detected audio")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
