import ctypes
from ctypes.util import find_library

import speech_recognition as sr

# Hide ALSA errors
asound = ctypes.cdll.LoadLibrary(find_library("asound"))
asound.snd_lib_error_set_handler(None)

recognizer = sr.Recognizer()

# Use default microphone
mic = sr.Microphone()

print("Say 'Hi Alexa'...")

while True:
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio)
        print("You said:", text)
    except:
        pass
