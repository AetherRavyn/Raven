import asyncio

import edge_tts

TEXT = "Hello. This is SARAS voice test."
VOICE = "en-US-AriaNeural"
OUTPUT = "microsoft.ogg"


async def text_to_speech():

    communicate = edge_tts.Communicate(TEXT, VOICE)

    await communicate.save(OUTPUT)

    print("Audio saved:", OUTPUT)


if __name__ == "__main__":
    asyncio.run(text_to_speech())
