# app/tools/cryptopricetool.py
"""CryptoPriceTool — get cryptocurrency prices and market data."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

COINGECKO_API = "https://api.coingecko.com/api/v3"


class CryptoPriceTool(BaseTool):
    """Get cryptocurrency prices, market cap, volume, and price changes."""

    def get_name(self) -> str:
        return "crypto_price"

    def get_description(self) -> str:
        return (
            "Get cryptocurrency prices and market data from CoinGecko. "
            "Get price, market cap, 24h volume, and price changes for any coin. "
            "List top coins, get price alerts, and convert between cryptos."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=["price", "top_coins", "price_history", "convert", "search"],
                ),
                ToolParameter(
                    name="coin_id",
                    type="string",
                    description="CoinGecko coin ID (e.g., bitcoin, ethereum, solana)",
                    required=False,
                ),
                ToolParameter(
                    name="vs_currency",
                    type="string",
                    description="Currency to compare (usd, eur, gbp, etc.)",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of coins to return (for top_coins)",
                    required=False,
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="Days of history (for price_history, 1-365)",
                    required=False,
                ),
                ToolParameter(
                    name="amount",
                    type="number",
                    description="Amount to convert (for convert)",
                    required=False,
                ),
                ToolParameter(
                    name="from_coin",
                    type="string",
                    description="Source coin for conversion",
                    required=False,
                ),
                ToolParameter(
                    name="to_coin",
                    type="string",
                    description="Target coin for conversion",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for search)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "price")
        coin_id = kwargs.get("coin_id", "bitcoin")
        vs_currency = kwargs.get("vs_currency", "usd")
        limit = kwargs.get("limit", 10)
        days = kwargs.get("days", 1)
        amount = kwargs.get("amount", 1)
        from_coin = kwargs.get("from_coin", "bitcoin")
        to_coin = kwargs.get("to_coin", "ethereum")
        query = kwargs.get("query", "")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if operation == "price":
                    ids = coin_id.replace(" ", "").split(",")
                    resp = await client.get(
                        f"{COINGECKO_API}/simple/price",
                        params={
                            "ids": ",".join(ids),
                            "vs_currencies": vs_currency,
                            "include_24hr_vol": "true",
                            "include_24hr_change": "true",
                            "include_market_cap": "true",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results = []
                    for coin_id_inner, stats in data.items():
                        results.append(
                            {
                                "coin": coin_id_inner,
                                "price": stats.get(vs_currency),
                                "volume_24h": stats.get(f"{vs_currency}_24h_vol"),
                                "change_24h": stats.get(f"{vs_currency}_24h_change"),
                                "market_cap": stats.get(f"{vs_currency}_market_cap"),
                            }
                        )
                    return {"success": True, "prices": results}

                if operation == "top_coins":
                    resp = await client.get(
                        f"{COINGECKO_API}/coins/markets",
                        params={
                            "vs_currency": vs_currency,
                            "order": "market_cap_desc",
                            "per_page": limit,
                            "page": 1,
                            "sparkline": "false",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    coins = []
                    for c in data:
                        coins.append(
                            {
                                "rank": c.get("market_cap_rank"),
                                "id": c.get("id"),
                                "symbol": c.get("symbol"),
                                "name": c.get("name"),
                                "price": c.get("current_price"),
                                "change_24h": c.get("price_change_percentage_24h"),
                                "market_cap": c.get("market_cap"),
                                "volume_24h": c.get("total_volume"),
                            }
                        )
                    return {"success": True, "coins": coins}

                if operation == "price_history":
                    resp = await client.get(
                        f"{COINGECKO_API}/coins/{coin_id}/market_chart",
                        params={
                            "vs_currency": vs_currency,
                            "days": days,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    prices = data.get("prices", [])
                    return {
                        "success": True,
                        "coin": coin_id,
                        "days": days,
                        "prices": [
                            {"timestamp": p[0], "price": p[1]} for p in prices[-50:]
                        ],
                    }

                if operation == "convert":
                    resp = await client.get(
                        f"{COINGECKO_API}/simple/price",
                        params={
                            "ids": f"{from_coin},{to_coin}",
                            "vs_currencies": vs_currency,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    from_price = data.get(from_coin, {}).get(vs_currency, 0)
                    to_price = data.get(to_coin, {}).get(vs_currency, 0)
                    converted = (
                        (amount / from_price) * to_price
                        if from_price and to_price
                        else 0
                    )
                    return {
                        "success": True,
                        "from": from_coin,
                        "to": to_coin,
                        "amount": amount,
                        "converted_amount": round(converted, 8),
                        "rate": round(to_price / from_price, 8) if from_price else 0,
                    }

                if operation == "search":
                    resp = await client.get(
                        f"{COINGECKO_API}/search",
                        params={"query": query},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    coins = data.get("coins", [])[:10]
                    return {
                        "success": True,
                        "results": [
                            {
                                "id": c.get("id"),
                                "name": c.get("name"),
                                "symbol": c.get("symbol"),
                                "market_cap_rank": c.get("market_cap_rank"),
                            }
                            for c in coins
                        ],
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"API error: {exc.response.status_code}"}
        except Exception as exc:
            logger.exception("CryptoPriceTool error")
            return {"success": False, "error": str(exc)}
