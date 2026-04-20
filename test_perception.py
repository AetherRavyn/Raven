import asyncio
import logging
from app.core.perception import PerceptionEngine

logging.basicConfig(level=logging.INFO)

async def test():
    engine = PerceptionEngine("workspace")
    engine.add_topic("AI Agents Open Source", interval_seconds=30)
    print("Testing Perception Engine...")
    await engine.run_cycle()
    print("Done. Checking evidence.jsonl:")
    with open("workspace/evidence.jsonl", "r") as f:
        for line in f:
            print(line.strip())

if __name__ == "__main__":
    asyncio.run(test())
