import speech_recognition as sr

recognizer = sr.Recognizer()


def callback(recognizer, audio):
    try:
        text = recognizer.recognize_google(audio).lower()
        print("Heard:", text)

        if "hi alexa" in text:
            print("\nAlexa Activated! Speak...\n")

    except:
        pass


mic = sr.Microphone()

with mic as source:
    recognizer.adjust_for_ambient_noise(source)

print("Say 'Hi Alexa'...")

stop_listening = recognizer.listen_in_background(mic, callback)

while True:
    pass
