#!/usr/bin/env python3
"""
Live microphone speech recognition (no duplicate prints)
"""

import json
import queue
import sys

import sounddevice as sd
import vosk

samplerate = 16000
blocksize = 8000

q = queue.Queue()

last_partial = ""
last_final = ""


def audio_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)

    q.put(bytes(indata))


def main():

    global last_partial
    global last_final

    print("=" * 60)
    print("🎤 Live Speech Recognition")
    print("=" * 60)
    print("\nSpeak into your microphone...\n")
    print("Press Ctrl+C to stop\n")

    model = vosk.Model("/home/swadhin/SARAS/app/voice/vosk-model-small-en-us-0.15")

    recognizer = vosk.KaldiRecognizer(model, samplerate)

    with sd.RawInputStream(
        samplerate=samplerate,
        blocksize=blocksize,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        try:
            while True:
                data = q.get()

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "")

                    if text and text != last_final:
                        print("\n" + text)
                        last_final = text
                        last_partial = ""

                else:
                    partial = json.loads(recognizer.PartialResult())

                    text = partial.get("partial", "")

                    if text and text != last_partial:
                        print(f"\r{text}", end="", flush=True)
                        last_partial = text

        except KeyboardInterrupt:
            print("\n\nDone")


if __name__ == "__main__":
    main()
