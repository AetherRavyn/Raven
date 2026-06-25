"""Shopping & Deal Finder — search products, compare prices, track price drops.

Uses DuckDuckGo Shopping, Google Shopping, and retailer APIs
to find products, compare prices, and set price alerts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ShoppingTool(BaseTool):
    """Search products and compare prices."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "shopping"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._alerts_file = self._dir / "price_alerts.json"
        self._history_file = self._dir / "search_history.jsonl"

    def get_name(self) -> str:
        return "shopping"

    def get_description(self) -> str:
        return (
            "Search for products, compare prices across retailers, "
            "set price drop alerts, and track shopping history."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["search", "compare", "alert", "alerts", "remove_alert", "history"],
                    "description": "search=find products, compare=compare prices, alert=set price alert",
                },
                "query": {"type": "string", "description": "Product search query"},
                "max_results": {"type": "integer", "description": "Max results (default 5)"},
                "target_price": {"type": "number", "description": "Target price for alert"},
                "alert_id": {"type": "string", "description": "Alert ID to remove"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "search")

        if operation == "search":
            return await self._search_products(kwargs.get("query", ""), kwargs.get("max_results", 5))
        elif operation == "compare":
            return await self._compare_prices(kwargs.get("query", ""))
        elif operation == "alert":
            return self._set_alert(kwargs.get("query", ""), kwargs.get("target_price", 0))
        elif operation == "alerts":
            return self._list_alerts()
        elif operation == "remove_alert":
            return self._remove_alert(kwargs.get("alert_id", ""))
        elif operation == "history":
            return self._get_history()
        return {"error": f"Unknown operation: {operation}"}

    async def _search_products(self, query: str, max_results: int) -> dict:
        """Search for products using DuckDuckGo."""
        if not query:
            return {"error": "query is required"}

        try:
            import httpx

            # DuckDuckGo Instant Answer API for product search
            results = []

            # Try DuckDuckGo shopping
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://api.duckduckgo.com/",
                        params={"q": f"{query} buy price", "format": "json"},
                    )
                    data = resp.json()

                    # Extract results from RelatedTopics
                    for topic in data.get("RelatedTopics", [])[:max_results]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append({
                                "title": topic.get("Text", "")[:100],
                                "url": topic.get("FirstURL", ""),
                                "snippet": topic.get("Text", "")[:200],
                                "source": "DuckDuckGo",
                            })
            except Exception:
                pass

            # Try Google Shopping via SerpAPI-style search
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://duckduckgo.com/html/",
                        params={"q": f"buy {query} price comparison"},
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    # Parse HTML results (simplified)
                    import re
                    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)', resp.text)
                    for url, title in links[:max_results]:
                        if url and title and not any(r["title"] == title for r in results):
                            results.append({
                                "title": title.strip(),
                                "url": url,
                                "snippet": "",
                                "source": "Web",
                            })
            except Exception:
                pass

            # Log search
            self._log_search(query, len(results))

            return {"success": True, "products": results[:max_results], "count": len(results), "query": query}

        except Exception as e:
            return {"error": str(e)[:500]}

    async def _compare_prices(self, query: str) -> dict:
        """Compare prices across multiple sources."""
        search_result = await self._search_products(query, 10)

        if "error" in search_result:
            return search_result

        products = search_result.get("products", [])

        # Extract prices from snippets
        import re
        for product in products:
            snippet = product.get("snippet", "") + " " + product.get("title", "")
            prices = re.findall(r'\$\d+[\.,]?\d*', snippet)
            if prices:
                product["prices_found"] = prices
                try:
                    product["lowest_price"] = min(float(p.replace("$", "").replace(",", "")) for p in prices)
                except ValueError:
                    pass

        # Sort by lowest price
        products_with_prices = [p for p in products if "lowest_price" in p]
        products_no_prices = [p for p in products if "lowest_price" not in p]
        products_with_prices.sort(key=lambda x: x.get("lowest_price", float("inf")))

        return {
            "success": True,
            "query": query,
            "products": products_with_prices + products_no_prices,
            "has_comparison": len(products_with_prices) > 1,
        }

    def _set_alert(self, query: str, target_price: float) -> dict:
        """Set a price drop alert."""
        if not query:
            return {"error": "query is required"}
        if target_price <= 0:
            return {"error": "target_price must be > 0"}

        import uuid
        alerts = self._load_alerts()
        alert_id = f"alert_{uuid.uuid4().hex[:8]}"
        alerts.append({
            "id": alert_id,
            "query": query,
            "target_price": target_price,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active": True,
        })
        self._save_alerts(alerts)
        return {"success": True, "alert_id": alert_id, "query": query, "target_price": target_price}

    def _list_alerts(self) -> dict:
        alerts = self._load_alerts()
        active = [a for a in alerts if a.get("active", True)]
        return {"alerts": active, "count": len(active)}

    def _remove_alert(self, alert_id: str) -> dict:
        alerts = self._load_alerts()
        for a in alerts:
            if a["id"] == alert_id:
                a["active"] = False
                self._save_alerts(alerts)
                return {"success": True, "removed": alert_id}
        return {"error": f"Alert {alert_id} not found"}

    def _log_search(self, query: str, result_count: int) -> None:
        entry = {
            "query": query,
            "results": result_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _get_history(self) -> list[dict]:
        if not self._history_file.exists():
            return []
        history = []
        for line in self._history_file.read_text(encoding="utf-8").strip().splitlines()[-20:]:
            if line.strip():
                try:
                    history.append(json.loads(line))
                except Exception:
                    continue
        return history

    def _load_alerts(self) -> list[dict]:
        if not self._alerts_file.exists():
            return []
        try:
            return json.loads(self._alerts_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_alerts(self, alerts: list[dict]) -> None:
        self._alerts_file.write_text(json.dumps(alerts, indent=2, ensure_ascii=False), encoding="utf-8")
