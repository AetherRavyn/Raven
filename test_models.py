import asyncio
from app.core.model_router import AutoModelRouter

async def test():
    models = AutoModelRouter.get_available_models()
    print("Available models:", models)

if __name__ == "__main__":
    asyncio.run(test())
