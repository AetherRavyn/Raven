import asyncio
from app.tools.edgetool import EdgeDeviceTool


async def test():
    tool = EdgeDeviceTool()
    print("Testing Edge Device Tool...")
    res = await tool.execute(operation="list_devices")
    print(f"Result: {res}")


if __name__ == "__main__":
    asyncio.run(test())
