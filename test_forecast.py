from app.core.forecast import ForecastEngine
import asyncio

async def test():
    fe = ForecastEngine("workspace")
    res = await fe.generate_forecasts("u1")
    print(res)

if __name__ == "__main__":
    asyncio.run(test())
