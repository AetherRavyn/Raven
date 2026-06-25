"""Live Data Feeds — real-time data streaming for FRIDAY-level awareness.

Provides:
- Weather alerts (push-based, not just on-demand)
- News monitoring (keyword-based push alerts)
- Stock price alerts (threshold-based)
- Calendar sync (real-time event updates)

Unlike on-demand tools, these run continuously and push
alerts when interesting events occur.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeedAlert:
    """An alert from a live data feed."""
    feed_type: str  # weather, news, stock, calendar
    title: str
    summary: str
    urgency: float = 0.5  # 0.0 = informational, 1.0 = critical
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WeatherFeed:
    """Push-based weather alerts."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "feeds/weather"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._last_check = 0.0
        self._check_interval = 1800  # 30 minutes
        self._alerts: list[FeedAlert] = []

    async def check(self) -> list[FeedAlert]:
        """Check for weather alerts. Returns new alerts."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return []

        self._last_check = now
        alerts = []

        try:
            from app.tools.weathertool import WeatherTool
            tool = WeatherTool()
            result = await tool.execute(operation="current")

            if result.get("success"):
                temp = result.get("temperature", 0)
                condition = result.get("condition", "")
                humidity = result.get("humidity", 0)

                # Alert on extreme conditions
                if temp > 35:
                    alerts.append(FeedAlert(
                        feed_type="weather",
                        title="Extreme Heat Warning",
                        summary=f"Temperature is {temp}°C — stay hydrated!",
                        urgency=0.7,
                        data={"temperature": temp, "condition": condition},
                    ))
                elif temp < 0:
                    alerts.append(FeedAlert(
                        feed_type="weather",
                        title="Freezing Alert",
                        summary=f"Temperature is {temp}°C — dress warmly!",
                        urgency=0.6,
                        data={"temperature": temp, "condition": condition},
                    ))

                # Alert on severe weather
                severe = ["thunderstorm", "tornado", "hurricane", "blizzard", "flood"]
                if any(s in condition.lower() for s in severe):
                    alerts.append(FeedAlert(
                        feed_type="weather",
                        title=f"Weather Alert: {condition}",
                        summary=f"Current conditions: {condition}, {temp}°C, {humidity}% humidity",
                        urgency=0.9,
                        data={"temperature": temp, "condition": condition, "humidity": humidity},
                    ))

        except Exception as exc:
            logger.debug("Weather feed check failed: %s", exc)

        self._alerts.extend(alerts)
        return alerts

    def get_recent(self, n: int = 10) -> list[FeedAlert]:
        return self._alerts[-n:]


class NewsFeed:
    """Push-based news monitoring."""

    def __init__(self, workspace_dir: str = "workspace", keywords: list[str] | None = None) -> None:
        self._dir = Path(workspace_dir) / "feeds/news"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._keywords = keywords or []
        self._last_check = 0.0
        self._check_interval = 3600  # 1 hour
        self._alerts: list[FeedAlert] = []
        self._seen_urls: set[str] = set()

    async def check(self) -> list[FeedAlert]:
        """Check for relevant news. Returns new alerts."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return []

        self._last_check = now
        alerts = []

        if not self._keywords:
            return []

        try:
            from app.tools.rssreadertool import RSSReaderTool
            tool = RSSReaderTool()
            # Search for news matching keywords
            for keyword in self._keywords[:3]:  # Limit to 3 keywords
                result = await tool.execute(operation="search", query=keyword, limit=5)
                if result.get("success"):
                    for item in result.get("results", []):
                        url = item.get("url", "")
                        if url and url not in self._seen_urls:
                            self._seen_urls.add(url)
                            alerts.append(FeedAlert(
                                feed_type="news",
                                title=item.get("title", "News"),
                                summary=item.get("snippet", "")[:200],
                                urgency=0.4,
                                data={"url": url, "source": item.get("source", "")},
                            ))
        except Exception as exc:
            logger.debug("News feed check failed: %s", exc)

        self._alerts.extend(alerts)
        return alerts

    def add_keyword(self, keyword: str) -> None:
        if keyword not in self._keywords:
            self._keywords.append(keyword)

    def get_recent(self, n: int = 10) -> list[FeedAlert]:
        return self._alerts[-n:]


class StockFeed:
    """Push-based stock price alerts."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "feeds/stocks"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._watchlist: list[dict[str, Any]] = []  # [{symbol, alert_above, alert_below}]
        self._last_prices: dict[str, float] = {}
        self._last_check = 0.0
        self._check_interval = 300  # 5 minutes
        self._alerts: list[FeedAlert] = []

    def add_watch(self, symbol: str, alert_above: float | None = None, alert_below: float | None = None) -> None:
        self._watchlist.append({"symbol": symbol.upper(), "alert_above": alert_above, "alert_below": alert_below})

    async def check(self) -> list[FeedAlert]:
        now = time.time()
        if now - self._last_check < self._check_interval:
            return []

        self._last_check = now
        alerts = []

        try:
            from app.tools.financetools import StockQuoteTool
            tool = StockQuoteTool()

            for watch in self._watchlist:
                symbol = watch["symbol"]
                result = await tool.execute(operation="quote", symbol=symbol)
                if result.get("success"):
                    price = result.get("price", 0)
                    prev = self._last_prices.get(symbol, price)
                    self._last_prices[symbol] = price

                    # Check thresholds
                    if watch.get("alert_above") and price >= watch["alert_above"]:
                        alerts.append(FeedAlert(
                            feed_type="stock",
                            title=f"{symbol} reached target price",
                            summary=f"{symbol} is now ${price:.2f} (target: ${watch['alert_above']:.2f})",
                            urgency=0.6,
                            data={"symbol": symbol, "price": price, "change": price - prev},
                        ))
                    elif watch.get("alert_below") and price <= watch["alert_below"]:
                        alerts.append(FeedAlert(
                            feed_type="stock",
                            title=f"{symbol} dropped below target",
                            summary=f"{symbol} is now ${price:.2f} (target: ${watch['alert_below']:.2f})",
                            urgency=0.6,
                            data={"symbol": symbol, "price": price, "change": price - prev},
                        ))

                    # Alert on big moves (>5%)
                    if prev > 0:
                        change_pct = abs(price - prev) / prev
                        if change_pct > 0.05:
                            direction = "up" if price > prev else "down"
                            alerts.append(FeedAlert(
                                feed_type="stock",
                                title=f"{symbol} moved {direction} {change_pct*100:.1f}%",
                                summary=f"{symbol}: ${prev:.2f} → ${price:.2f}",
                                urgency=0.5,
                                data={"symbol": symbol, "price": price, "change_pct": change_pct},
                            ))

        except Exception as exc:
            logger.debug("Stock feed check failed: %s", exc)

        self._alerts.extend(alerts)
        return alerts

    def get_recent(self, n: int = 10) -> list[FeedAlert]:
        return self._alerts[-n:]


class LiveDataManager:
    """Manages all live data feeds."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.weather = WeatherFeed(workspace_dir)
        self.news = NewsFeed(workspace_dir)
        self.stocks = StockFeed(workspace_dir)
        self._callbacks: list[Callable] = []

    def on_alert(self, callback: Callable) -> None:
        """Register a callback for feed alerts."""
        self._callbacks.append(callback)

    async def check_all(self) -> list[FeedAlert]:
        """Check all feeds and return new alerts."""
        all_alerts = []

        for feed in [self.weather, self.news, self.stocks]:
            try:
                alerts = await feed.check()
                all_alerts.extend(alerts)
            except Exception as exc:
                logger.debug("Feed check failed: %s", exc)

        # Notify callbacks
        for alert in all_alerts:
            for cb in self._callbacks:
                try:
                    cb(alert)
                except Exception:
                    pass

        return all_alerts

    def get_all_recent(self, n: int = 5) -> dict[str, list[FeedAlert]]:
        return {
            "weather": self.weather.get_recent(n),
            "news": self.news.get_recent(n),
            "stocks": self.stocks.get_recent(n),
        }
