from typing import Any


class CryptoPriceTool:
    """
    A simple Python tool to fetch current cryptocurrency prices.
    Requires no external dependencies (mocked for demo purposes).
    """

    name = "crypto_price_fetcher"
    description = "Fetches the current price of a given cryptocurrency like BTC or ETH."

    def __init__(self):
        pass

    def __call__(self, coin: str) -> str:
        # Mocked price fetch
        prices = {"BTC": "$65,000", "ETH": "$3,500", "SOL": "$150"}
        coin_upper = coin.upper()
        if coin_upper in prices:
            return f"The current price of {coin_upper} is {prices[coin_upper]}"
        return f"Could not find price for {coin}. Supported coins: BTC, ETH, SOL."


def register_plugin() -> Any:
    """Entry point for SkillRegistry to discover the tool."""
    return CryptoPriceTool()
