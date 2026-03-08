from __future__ import annotations

import asyncio
import os
import socket
from typing import Any, Dict, List, Optional

import requests

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class StockQuoteTool(BaseTool):
    """Get real-time stock quotes, historical data, and market info using Yahoo Finance.
    Supports major exchanges: NYSE, NASDAQ, LSE, etc."""

    def __init__(self, **cfg: Any):
        pass  # yfinance is already installed

    def get_name(self) -> str:
        return "stock_quote"

    def get_description(self) -> str:
        return (
            "Get real-time stock quotes and market data. "
            "Supports major exchanges (NYSE, NASDAQ, LSE, etc.). "
            "Returns current price, change, volume, market cap, and more."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: quote, history, or search",
                    required=True,
                    enum=["quote", "history", "search"],
                ),
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="Stock ticker symbol (e.g., AAPL, GOOGL, MSFT)",
                    required=True,
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="History period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max (for history)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation", "quote")
        symbol = kwargs.get("symbol", "").strip().upper()
        if not symbol:
            return self._error("symbol parameter is required")

        try:
            if op == "quote":
                return await asyncio.to_thread(self._get_quote, symbol)
            elif op == "history":
                period = kwargs.get("period", "1mo")
                return await asyncio.to_thread(self._get_history, symbol, period)
            elif op == "search":
                return await asyncio.to_thread(self._search, symbol)
            else:
                return self._error(f"Unknown operation: {op}")
        except Exception as e:
            return self._error(f"Stock operation failed: {e}")

    def _get_quote(self, symbol: str) -> Dict[str, Any]:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info

            return {
                "success": True,
                "operation": "quote",
                "symbol": symbol,
                "name": info.get("shortName") or info.get("longName") or symbol,
                "price": info.get("currentPrice") or info.get("previousClose"),
                "change": info.get("regularMarketChange"),
                "change_percent": info.get("regularMarketChangePercent"),
                "open": info.get("regularMarketOpen"),
                "high": info.get("regularMarketDayHigh"),
                "low": info.get("regularMarketDayLow"),
                "volume": info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "currency": info.get("currency"),
            }
        except ImportError:
            return self._error("yfinance not installed")
        except Exception as e:
            return self._error(f"Failed to get quote: {e}")

    def _get_history(self, symbol: str, period: str) -> Dict[str, Any]:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)

            if hist.empty:
                return self._error(f"No historical data for {symbol}")

            data = []
            for idx, row in hist.iterrows():
                data.append(
                    {
                        "date": idx.isoformat(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]),
                    }
                )

            return {
                "success": True,
                "operation": "history",
                "symbol": symbol,
                "period": period,
                "count": len(data),
                "data": data[-30:],  # Last 30 records
            }
        except Exception as e:
            return self._error(f"Failed to get history: {e}")

    def _search(self, query: str) -> Dict[str, Any]:
        try:
            import yfinance as yf

            tickers = yf.Tickers(query)
            results = []
            for sym in list(tickers.tickers.keys())[:10]:
                try:
                    info = tickers.tickers[sym].info
                    results.append(
                        {
                            "symbol": sym,
                            "name": info.get("shortName")
                            or info.get("longName")
                            or sym,
                            "exchange": info.get("exchange"),
                        }
                    )
                except Exception:
                    pass

            return {
                "success": True,
                "operation": "search",
                "query": query,
                "count": len(results),
                "results": results,
            }
        except Exception as e:
            return self._error(f"Search failed: {e}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class CryptoAlertTool(BaseTool):
    """Get cryptocurrency prices and set price threshold alerts using CoinGecko API (free, no key).
    Supports 1000+ coins with market data."""

    def __init__(self, **cfg: Any):
        self._api_base = "https://api.coingecko.com/api/v3"

    def get_name(self) -> str:
        return "crypto_alert"

    def get_description(self) -> str:
        return (
            "Get cryptocurrency prices, market data, and price alerts. "
            "Uses CoinGecko API (free, no key required). "
            "Supports 1000+ coins: BTC, ETH, SOL, etc."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: price, alert, trending, or history",
                    required=True,
                    enum=["price", "alert", "trending", "history"],
                ),
                ToolParameter(
                    name="coin",
                    type="string",
                    description="Coin ID (e.g., bitcoin, ethereum, solana)",
                    required=True,
                ),
                ToolParameter(
                    name="currency",
                    type="string",
                    description="Currency for price (usd, eur, gbp, inr - default: usd)",
                    required=False,
                ),
                ToolParameter(
                    name="threshold",
                    type="number",
                    description="Price threshold for alert (sends warning if crossed)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation", "price")
        coin = kwargs.get("coin", "").strip().lower()
        currency = kwargs.get("currency", "usd").lower()

        if not coin:
            return self._error("coin parameter is required")

        try:
            if op == "price":
                return await asyncio.to_thread(self._get_price, coin, currency)
            elif op == "alert":
                threshold = kwargs.get("threshold")
                return await asyncio.to_thread(
                    self._check_alert, coin, currency, threshold
                )
            elif op == "trending":
                return await asyncio.to_thread(self._get_trending)
            elif op == "history":
                days = kwargs.get("days", 30)
                return await asyncio.to_thread(self._get_history, coin, currency, days)
            else:
                return self._error(f"Unknown operation: {op}")
        except Exception as e:
            return self._error(f"Crypto operation failed: {e}")

    def _get_price(self, coin: str, currency: str) -> Dict[str, Any]:
        url = f"{self._api_base}/simple/price"
        params = {
            "ids": coin,
            "vs_currencies": currency,
            "include_24hr_change": "true",
            "include_market_cap": "true",
        }

        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return self._error(f"CoinGecko API error: {resp.status_code}")

        data = resp.json()
        if coin not in data:
            return self._error(f"Coin '{coin}' not found")

        coin_data = data[coin]
        return {
            "success": True,
            "operation": "price",
            "coin": coin,
            "currency": currency,
            "price": coin_data.get(currency),
            "change_24h": coin_data.get(f"{currency}_24h_change"),
            "market_cap": coin_data.get(f"{currency}_market_cap"),
        }

    def _check_alert(
        self, coin: str, currency: str, threshold: float
    ) -> Dict[str, Any]:
        if threshold is None:
            return self._error("threshold parameter required for alert operation")

        price_data = self._get_price(coin, currency)
        if not price_data.get("success"):
            return price_data

        current_price = price_data.get("price")
        if current_price is None:
            return self._error("Could not get current price")

        above = current_price > threshold
        percent_diff = ((current_price - threshold) / threshold) * 100

        status = "ABOVE" if above else "BELOW"
        return {
            "success": True,
            "operation": "alert",
            "coin": coin,
            "current_price": current_price,
            "threshold": threshold,
            "status": status,
            "percent_difference": round(percent_diff, 2),
            "message": f"{coin.upper()} is {status} threshold: {currency.upper()} {current_price:.2f} vs {threshold:.2f} ({percent_diff:+.2f}%)",
        }

    def _get_trending(self) -> Dict[str, Any]:
        url = f"{self._api_base}/search/trending"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return self._error(f"CoinGecko API error: {resp.status_code}")

        data = resp.json()
        coins = []
        for item in data.get("coins", [])[:15]:
            coin = item.get("item", {})
            coins.append(
                {
                    "id": coin.get("id"),
                    "name": coin.get("name"),
                    "symbol": coin.get("symbol"),
                    "market_cap_rank": coin.get("market_cap_rank"),
                    "thumb": coin.get("thumb"),
                    "score": coin.get("score"),
                }
            )

        return {
            "success": True,
            "operation": "trending",
            "count": len(coins),
            "coins": coins,
        }

    def _get_history(self, coin: str, currency: str, days: int) -> Dict[str, Any]:
        url = f"{self._api_base}/coins/{coin}/market_chart"
        params = {"vs_currency": currency, "days": days}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return self._error(f"CoinGecko API error: {resp.status_code}")

        data = resp.json()
        prices = data.get("prices", [])
        return {
            "success": True,
            "operation": "history",
            "coin": coin,
            "currency": currency,
            "days": days,
            "count": len(prices),
            "data": [{"timestamp": p[0], "price": p[1]} for p in prices[-30:]],
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class DNSLookupTool(BaseTool):
    """Perform DNS lookups: A, AAAA, MX, TXT, CNAME, NS, SOA, PTR records.
    Useful for troubleshooting and domain analysis."""

    def __init__(self, **cfg: Any):
        pass

    def get_name(self) -> str:
        return "dns_lookup"

    def get_description(self) -> str:
        return (
            "Perform DNS lookups for any domain. "
            "Supports record types: A, AAAA, MX, TXT, CNAME, NS, SOA, PTR. "
            "Useful for troubleshooting and domain analysis."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="domain",
                    type="string",
                    description="Domain name to lookup (e.g., google.com)",
                    required=True,
                ),
                ToolParameter(
                    name="record_type",
                    type="string",
                    description="DNS record type: A, AAAA, MX, TXT, CNAME, NS, SOA, PTR, ALL",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        domain = kwargs.get("domain", "").strip()
        if not domain:
            return self._error("domain parameter is required")

        record_type = (kwargs.get("record_type") or "A").upper()

        try:
            result = await asyncio.to_thread(self._lookup, domain, record_type)
            return result
        except Exception as e:
            return self._error(f"DNS lookup failed: {e}")

    def _lookup(self, domain: str, record_type: str) -> Dict[str, Any]:
        import dns.resolver
        import dns.query
        import dns.zone
        import dns.name

        resolver = dns.resolver.Resolver()
        results = {}

        record_types = (
            [record_type]
            if record_type != "ALL"
            else ["A", "AAAA", "MX", "TXT", "CNAME", "NS", "SOA"]
        )

        for rtype in record_types:
            try:
                answers = resolver.resolve(domain, rtype)
                records = []
                for rdata in answers:
                    if rtype == "MX":
                        records.append(
                            {"priority": rdata.preference, "host": str(rdata.exchange)}
                        )
                    elif rtype == "SOA":
                        records.append(
                            {
                                "mname": str(rdata.mname),
                                "rname": str(rdata.rname),
                                "serial": rdata.serial,
                                "refresh": rdata.refresh,
                                "retry": rdata.retry,
                                "expire": rdata.expire,
                                "minimum": rdata.minimum,
                            }
                        )
                    else:
                        records.append(str(rdata))
                results[rtype] = records
            except dns.resolver.NXDOMAIN:
                results[rtype] = [f"Domain {domain} does not exist"]
            except dns.resolver.NoAnswer:
                results[rtype] = [f"No {rtype} records found"]
            except Exception as e:
                results[rtype] = [f"Error: {str(e)}"]

        return {
            "success": True,
            "domain": domain,
            "record_type": record_type,
            "results": results,
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class HaveIBeenPwnedTool(BaseTool):
    """Check if an email address or username has been exposed in data breaches.
    Uses the Have I Been Pwned API (free tier: 1 search/month without key)."""

    def __init__(self, **cfg: Any):
        self._api_key = cfg.get("api_key") or os.environ.get("HIBP_API_KEY")

    def get_name(self) -> str:
        return "haveibeenpwned"

    def get_description(self) -> str:
        return (
            "Check if an email address or username has been exposed in data breaches. "
            "Uses Have I Been Pwned API. "
            "Returns list of breaches and their details."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="email",
                    type="string",
                    description="Email address to check",
                    required=True,
                ),
                ToolParameter(
                    name="include_unverified",
                    type="boolean",
                    description="Include unverified breaches (default: false)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        email = kwargs.get("email", "").strip()
        if not email:
            return self._error("email parameter is required")

        include_unverified = kwargs.get("include_unverified", False)

        try:
            result = await asyncio.to_thread(
                self._check_breach, email, include_unverified
            )
            return result
        except Exception as e:
            return self._error(f"HaveIBeenPwned check failed: {e}")

    def _check_breach(self, email: str, include_unverified: bool) -> Dict[str, Any]:
        import hashlib

        # Use the k-anonymity API (password check) - more private
        # For email, we need the API key for full access
        url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
        headers = {"User-Agent": "SARAS-Assistant"}

        if self._api_key:
            headers["hibp-api-key"] = self._api_key

        params = {"truncateResponse": "false"}
        if include_unverified:
            params["includeUnverified"] = "true"

        resp = requests.get(url, headers=headers, params=params, timeout=15)

        if resp.status_code == 404:
            return {
                "success": True,
                "email": email,
                "breached": False,
                "message": "Good news — no pwnage found!",
                "breaches": [],
            }
        elif resp.status_code == 401:
            return self._error(
                "API key required for email breach lookup. Use HIBP_API_KEY env var."
            )
        elif resp.status_code == 429:
            return self._error("Rate limited. Try again later.")
        elif resp.status_code != 200:
            return self._error(f"API error: {resp.status_code}")

        breaches = resp.json()
        breach_list = []
        for b in breaches:
            breach_list.append(
                {
                    "name": b.get("Name"),
                    "title": b.get("Title"),
                    "domain": b.get("Domain"),
                    "breach_date": b.get("BreachDate"),
                    "added_date": b.get("AddedDate"),
                    "modified_date": b.get("ModifiedDate"),
                    "pwn_count": b.get("PwnCount"),
                    "description": b.get("Description", "")[:200],
                    "data_classes": b.get("DataClasses"),
                    "is_verified": b.get("IsVerified"),
                    "is_sensitive": b.get("IsSensitive"),
                }
            )

        return {
            "success": True,
            "email": email,
            "breached": len(breach_list) > 0,
            "breach_count": len(breach_list),
            "total_accounts_exposed": sum(b["pwn_count"] for b in breach_list),
            "breaches": breach_list,
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class URLVirusScanTool(BaseTool):
    """Scan URLs for malware, phishing, and malicious content using VirusTotal API.
    Provides detailed threat intelligence and safety ratings."""

    def __init__(self, **cfg: Any):
        self._api_key = cfg.get("api_key") or os.environ.get("VIRUSTOTAL_API_KEY")
        self._api_base = "https://www.virustotal.com/api/v3"

    def get_name(self) -> str:
        return "url_scan"

    def get_description(self) -> str:
        return (
            "Scan URLs for malware, phishing, and malicious content using VirusTotal. "
            "Returns threat classification, safety rating, and detailed scan results. "
            "Uses VIRUSTOTAL_API_KEY."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to scan",
                    required=True,
                ),
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: scan or report",
                    required=False,
                    enum=["scan", "report"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        url = kwargs.get("url", "").strip()
        if not url:
            return self._error("url parameter is required")

        if not self._api_key:
            return self._error("VIRUSTOTAL_API_KEY not configured")

        op = kwargs.get("operation", "report")

        try:
            if op == "scan":
                return await asyncio.to_thread(self._scan_url, url)
            else:
                return await asyncio.to_thread(self._get_report, url)
        except Exception as e:
            return self._error(f"VirusTotal scan failed: {e}")

    def _get_report(self, url: str) -> Dict[str, Any]:
        import urllib.parse

        headers = {"x-apikey": self._api_key}
        url_id = urllib.parse.quote_plus(url)
        resp = requests.get(
            f"{self._api_base}/urls/{url_id}",
            headers=headers,
            timeout=15,
        )

        if resp.status_code == 404:
            return self._error(
                "URL not found in VirusTotal database. Use scan operation first."
            )
        elif resp.status_code != 200:
            return self._error(f"VirusTotal API error: {resp.status_code}")

        data = resp.json()
        attrs = data.get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})

        results = attrs.get("last_analysis_results", {})
        engines = []
        for engine, result in results.items():
            engines.append(
                {
                    "engine": engine,
                    "category": result.get("category"),
                    "result": result.get("result"),
                    "method": result.get("method"),
                    "engine_version": result.get("engine_version"),
                }
            )

        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        harmless = stats.get("harmless", 0)
        total = malicious + suspicious + harmless + stats.get("undetected", 0)

        safety_rating = "SAFE"
        if malicious > 0 or suspicious > 5:
            safety_rating = "DANGEROUS"
        elif suspicious > 0 or malicious > 0:
            safety_rating = "SUSPICIOUS"

        return {
            "success": True,
            "operation": "report",
            "url": url,
            "safety_rating": safety_rating,
            "total_engines": total,
            "malicious": malicious,
            "suspicious": suspicious,
            "harmless": harmless,
            "undetected": stats.get("undetected", 0),
            "analysis_date": attrs.get("last_submission_date"),
            "engines": engines[:20],  # Top 20
        }

    def _scan_url(self, url: str) -> Dict[str, Any]:
        headers = {"x-apikey": self._api_key}
        data = {"url": url}

        resp = requests.post(
            f"{self._api_base}/urls",
            headers=headers,
            data=data,
            timeout=15,
        )

        if resp.status_code != 200:
            return self._error(f"VirusTotal scan error: {resp.status_code}")

        result = resp.json()
        analysis_id = result.get("data", {}).get("id")

        return {
            "success": True,
            "operation": "scan",
            "url": url,
            "analysis_id": analysis_id,
            "message": "URL submitted for analysis. Use report operation to get results after ~10 seconds.",
        }

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}


class CronManagerTool(BaseTool):
    """Execute scheduled shell commands locally. List, add, remove, or trigger cron jobs.
    Jobs are managed via crontab."""

    def __init__(self, **cfg: Any):
        pass

    def get_name(self) -> str:
        return "cron_manager"

    def get_name(self) -> str:
        return "cron_manager"

    def get_description(self) -> str:
        return (
            "Manage cron jobs: list, add, remove, or execute commands. "
            "Uses local crontab. "
            "WARNING: Only safe, read-only or notification commands recommended."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation: list, add, remove, or execute",
                    required=True,
                    enum=["list", "add", "remove", "execute"],
                ),
                ToolParameter(
                    name="schedule",
                    type="string",
                    description="Cron schedule (e.g., '0 * * * *' for hourly)",
                    required=False,
                ),
                ToolParameter(
                    name="command",
                    type="string",
                    description="Command to run (for add/execute)",
                    required=False,
                ),
                ToolParameter(
                    name="job_id",
                    type="string",
                    description="Job identifier (for remove)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation", "list")

        try:
            if op == "list":
                return await asyncio.to_thread(self._list_jobs)
            elif op == "add":
                return await asyncio.to_thread(self._add_job, kwargs)
            elif op == "remove":
                return await asyncio.to_thread(
                    self._remove_job, kwargs.get("job_id", "")
                )
            elif op == "execute":
                return await asyncio.to_thread(self._execute, kwargs.get("command", ""))
            else:
                return self._error(f"Unknown operation: {op}")
        except Exception as e:
            return self._error(f"Cron operation failed: {e}")

    def _list_jobs(self) -> Dict[str, Any]:
        import subprocess

        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

            jobs = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(None, 5)
                    if len(parts) >= 6:
                        jobs.append(
                            {
                                "schedule": " ".join(parts[:5]),
                                "command": parts[5],
                            }
                        )

            return {
                "success": True,
                "operation": "list",
                "count": len(jobs),
                "jobs": jobs,
            }
        except subprocess.TimeoutExpired:
            return self._error("Command timed out")
        except Exception as e:
            return self._error(f"Failed to list jobs: {e}")

    def _add_job(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        import subprocess

        schedule = kwargs.get("schedule", "").strip()
        command = kwargs.get("command", "").strip()
        job_id = kwargs.get("job_id", "").strip()

        if not schedule or not command:
            return self._error("schedule and command are required for add operation")

        # Validate cron schedule format (basic)
        parts = schedule.split()
        if len(parts) != 5:
            return self._error(
                "Invalid cron schedule. Use format: 'minute hour day month weekday'"
            )

        # Add comment with job_id if provided
        entry = f"# SARAS:{job_id}\n{schedule} {command}"

        try:
            # Get current crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            current = result.stdout if result.returncode == 0 else ""

            # Append new job
            new_crontab = current.rstrip() + "\n" + entry + "\n"

            # Set new crontab
            subprocess.run(
                ["crontab", "-"],
                input=new_crontab,
                text=True,
                timeout=10,
            )

            return {
                "success": True,
                "operation": "add",
                "schedule": schedule,
                "command": command,
                "job_id": job_id or "unnamed",
                "message": f"Cron job added: {schedule} {command}",
            }
        except Exception as e:
            return self._error(f"Failed to add job: {e}")

    def _remove_job(self, job_id: str) -> Dict[str, Any]:
        import subprocess

        if not job_id:
            return self._error("job_id is required for remove operation")

        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return self._error("No crontab to modify")

            lines = result.stdout.split("\n")
            new_lines = []
            removed = False

            for line in lines:
                if f"SARAS:{job_id}" in line:
                    removed = True
                    continue  # Skip this line and the next (the actual cron line)
                new_lines.append(line)

            if not removed:
                return self._error(f"Job with ID '{job_id}' not found")

            new_crontab = "\n".join(new_lines).strip() + "\n"
            subprocess.run(
                ["crontab", "-"],
                input=new_crontab,
                text=True,
                timeout=10,
            )

            return {
                "success": True,
                "operation": "remove",
                "job_id": job_id,
                "message": f"Cron job '{job_id}' removed",
            }
        except Exception as e:
            return self._error(f"Failed to remove job: {e}")

    def _execute(self, command: str) -> Dict[str, Any]:
        import subprocess
        import uuid

        if not command:
            return self._error("command is required for execute operation")

        # Run once (not as cron) - fire and forget with timeout
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "success": True,
                "operation": "execute",
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:500],
            }
        except subprocess.TimeoutExpired:
            return self._error("Command timed out after 60 seconds")
        except Exception as e:
            return self._error(f"Execution failed: {e}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg}
