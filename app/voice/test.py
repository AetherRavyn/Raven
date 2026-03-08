import asyncio

from speechmatics.tts import AsyncClient, OutputFormat, Voice

= "W4KNOIgAfhWkXaSQqRAcS1djqT6YH2u3"


async def main():

    async with AsyncClient(api_key=API_KEY) as client:
        # Must await first
        response = await client.generate(
            text="Hello, how are you doing bro?",
            voice=Voice.SARAH,
            output_format=OutputFormat.WAV_16000,
        )

        # Then use async context manager
        async with response as r:
            with open("output.wav", "wb") as f:
                async for chunk in r.content.iter_chunked(1024):
                    f.write(chunk)

    print("Saved output.wav")


if __name__ == "__main__":
    asyncio.run(main())
