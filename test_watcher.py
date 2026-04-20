import asyncio
import logging
from app.routines.internet_watcher import InternetWatcher

logging.basicConfig(level=logging.INFO)


async def main():
    watcher = InternetWatcher()

    # Mocking the profile returning some topics
    class MockProfileStore:
        def load(self, user_id):
            class Prof:
                preferences = ["Track AI advancements", "Watch SpaceX"]

            return Prof()

    watcher.profile = MockProfileStore()

    print("Running Internet sweep...")
    await watcher.run_sweep("u1", "telegram", "123")

    print("Done. Checking inbox...")
    inbox_items = watcher.inbox.list_items("u1")
    for t in inbox_items:
        if t.get("kind") == "signal":
            print(f"- {t['title']} ({t['context'].get('topic')})")


if __name__ == "__main__":
    asyncio.run(main())
