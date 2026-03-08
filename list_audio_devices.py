#!/usr/bin/env python3
"""List all available audio input devices"""

import sounddevice as sd

print("=" * 60)
print(" Available Audio Input Devices")
print("=" * 60)

devices = sd.query_devices()
default_input = sd.query_devices(kind="input")["index"]

print(f"\nDefault Input Device: {default_input}")
print("-" * 60)

for i, device in enumerate(devices):
    if device["max_input_channels"] > 0:
        marker = ">>>" if i == default_input else "   "
        print(f"{marker} [{i}] {device['name']}")
        print(
            f"    Channels: {device['max_input_channels']}, "
            f"Sample Rate: {device['default_samplerate']} Hz"
        )
        print()
