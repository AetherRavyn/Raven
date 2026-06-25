import asyncio
import os

from speechmatics.tts import AsyncClient, OutputFormat, Voice


async def main():
    api_key = os.environ.get("API_KEY_SPEECHMATE", "")
    if not api_key:
        print("Error: API_KEY_SPEECHMATE env var not set")
        return

    async with AsyncClient(api_key=api_key) as client:
        response = await client.generate(
            text="Hello, how are you doing bro?",
            voice=Voice.SARAH,
            output_format=OutputFormat.WAV_16000,
        )

        async with response as r:
            with open("output.wav", "wb") as f:
                async for chunk in r.content.iter_chunked(1024):
                    f.write(chunk)

    print("Saved output.wav")


if __name__ == "__main__":
    asyncio.run(main())
