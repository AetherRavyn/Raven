"""Free Information APIs Tool — access 15+ free APIs for information gathering.

From the FRIDAY AI Bot API Hub — all free, no API keys required:
- Wikipedia (knowledge)
- Open-Meteo (weather)
- DuckDuckGo (search)
- CoinGecko (crypto)
- WorldTimeAPI (time)
- OpenStreetMap Nominatim (geocoding)
- REST Countries (country info)
- Open Notify (ISS position)
- Exchange Rates (currency)
- Open Library (books)
- Wikidata (structured knowledge)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class FreeInformationAPIs(BaseTool):
    """Access 15+ free information APIs — no API keys required."""

    def get_name(self) -> str:
        return "free_apis"

    def get_description(self) -> str:
        return (
            "Access free information APIs: Wikipedia, weather, search, crypto, "
            "time zones, geocoding, country info, ISS position, exchange rates, "
            "books. No API keys needed."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="api", type="string", required=True,
                             description="API to use",
                             enum=["wikipedia", "wikidata", "open_library", "weather",
                                   "search", "crypto", "exchange_rates", "geocode",
                                   "ip_geo", "countries", "iss", "time", "qr_code"]),
                ToolParameter(name="query", type="string", required=False,
                             description="Search query or entity name"),
                ToolParameter(name="city", type="string", required=False,
                             description="City name (for weather/geocode)"),
                ToolParameter(name="lat", type="number", required=False,
                             description="Latitude (for geocode/weather)"),
                ToolParameter(name="lon", type="number", required=False,
                             description="Longitude (for geocode/weather)"),
                ToolParameter(name="text", type="string", required=False,
                             description="Text to process (for QR/translate)"),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        api = kwargs.get("api", "")
        try:
            handlers = {
                "wikipedia": self._wikipedia,
                "wikidata": self._wikidata,
                "open_library": self._open_library,
                "weather": self._open_meteo,
                "search": self._duckduckgo,
                "crypto": self._coingecko,
                "exchange_rates": self._exchange_rates,
                "geocode": self._nominatim,
                "ip_geo": self._ip_api,
                "countries": self._rest_countries,
                "iss": self._iss_position,
                "time": self._world_time,
                "qr_code": self._qr_code,
            }
            handler = handlers.get(api)
            if not handler:
                return {"success": False, "error": f"Unknown API: {api}"}
            return await handler(**kwargs)
        except Exception as e:
            logger.exception("FreeAPIs error")
            return {"success": False, "error": str(e)}

    async def _wikipedia(self, **kwargs: Any) -> Dict[str, Any]:
        """Wikipedia REST API — free, no key."""
        query = kwargs.get("query", "")
        if not query:
            return {"success": False, "error": "query required"}
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            if resp.status_code == 404:
                # Try search
                search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={query}&format=json"
                resp = await client.get(search_url, headers={"User-Agent": "Raven/1.0"})
                data = resp.json()
                results = data.get("query", {}).get("search", [])[:5]
                return {"success": True, "type": "search", "results": [
                    {"title": r.get("title", ""), "snippet": r.get("snippet", "")[:200]}
                    for r in results
                ]}
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "type": "summary", "title": data.get("title", ""),
                    "extract": data.get("extract", ""), "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")}

    async def _wikidata(self, **kwargs: Any) -> Dict[str, Any]:
        """Wikidata API — free, no key."""
        query = kwargs.get("query", "")
        if not query:
            return {"success": False, "error": "query required"}
        url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=en&format=json"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            data = resp.json()
            results = data.get("search", [])[:5]
            return {"success": True, "results": [
                {"id": r.get("id", ""), "label": r.get("label", ""), "description": r.get("description", "")}
                for r in results
            ]}

    async def _open_library(self, **kwargs: Any) -> Dict[str, Any]:
        """Open Library API — free, no key."""
        query = kwargs.get("query", "")
        if not query:
            return {"success": False, "error": "query required"}
        url = f"https://openlibrary.org/search.json?q={query}&limit=5"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            data = resp.json()
            docs = data.get("docs", [])
            return {"success": True, "results": [
                {"title": d.get("title", ""), "author": ", ".join(d.get("author_name", [])[:3]),
                 "year": d.get("first_publish_year", ""), "isbn": d.get("isbn", [""])[0] if d.get("isbn") else ""}
                for d in docs[:5]
            ]}

    async def _open_meteo(self, **kwargs: Any) -> Dict[str, Any]:
        """Open-Meteo — free weather, no key."""
        lat = kwargs.get("lat", 28.6139)  # Default: Delhi
        lon = kwargs.get("lon", 77.2090)
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            current = data.get("current", {})
            daily = data.get("daily", {})
            return {"success": True, "current": {
                "temperature": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "weather_code": current.get("weather_code"),
            }, "forecast": {
                "max_temps": daily.get("temperature_2m_max", [])[:3],
                "min_temps": daily.get("temperature_2m_min", [])[:3],
                "weather_codes": daily.get("weather_code", [])[:3],
            }}

    async def _duckduckgo(self, **kwargs: Any) -> Dict[str, Any]:
        """DuckDuckGo Instant Answers — free, no key."""
        query = kwargs.get("query", "")
        if not query:
            return {"success": False, "error": "query required"}
        url = f"https://api.duckduckgo.com/?q={query}&format=json"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            data = resp.json()
            return {"success": True, "abstract": data.get("Abstract", ""),
                    "abstract_source": data.get("AbstractSource", ""),
                    "abstract_url": data.get("AbstractURL", ""),
                    "answer": data.get("Answer", ""),
                    "related": [r.get("Text", "") for r in data.get("RelatedTopics", [])[:5]]}

    async def _coingecko(self, **kwargs: Any) -> Dict[str, Any]:
        """CoinGecko — free crypto data, no key."""
        coin = kwargs.get("query", "bitcoin")
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd&include_24hr_change=true"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            if coin in data:
                return {"success": True, "coin": coin, "usd": data[coin].get("usd"),
                        "change_24h": data[coin].get("usd_24h_change")}
            return {"success": False, "error": f"Coin '{coin}' not found"}

    async def _exchange_rates(self, **kwargs: Any) -> Dict[str, Any]:
        """Exchange Rates — free, no key."""
        base = kwargs.get("query", "USD")
        url = f"https://api.exchangerate.host/latest?base={base}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            rates = data.get("rates", {})
            return {"success": True, "base": base, "rates": dict(list(rates.items())[:10])}

    async def _nominatim(self, **kwargs: Any) -> Dict[str, Any]:
        """OpenStreetMap Nominatim — free geocoding."""
        query = kwargs.get("query", kwargs.get("city", ""))
        if not query:
            return {"success": False, "error": "query required"}
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            data = resp.json()
            if data:
                r = data[0]
                return {"success": True, "lat": float(r["lat"]), "lon": float(r["lon"]),
                        "display_name": r.get("display_name", ""), "type": r.get("type", "")}
            return {"success": False, "error": "No results found"}

    async def _ip_api(self, **kwargs: Any) -> Dict[str, Any]:
        """ip-api — free IP geolocation."""
        url = "http://ip-api.com/json/"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            return {"success": True, "ip": data.get("query"), "country": data.get("country"),
                    "city": data.get("city"), "lat": data.get("lat"), "lon": data.get("lon"),
                    "timezone": data.get("timezone"), "isp": data.get("isp")}

    async def _rest_countries(self, **kwargs: Any) -> Dict[str, Any]:
        """REST Countries — free country info."""
        query = kwargs.get("query", "India")
        url = f"https://restcountries.com/v3.1/name/{query}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            if data and isinstance(data, list):
                c = data[0]
                return {"success": True, "name": c.get("name", {}).get("common", ""),
                        "capital": c.get("capital", [""])[0] if c.get("capital") else "",
                        "population": c.get("population"),
                        "region": c.get("region"),
                        "languages": list(c.get("languages", {}).values())[:3],
                        "currency": list(c.get("currencies", {}).keys())[:1]}
            return {"success": False, "error": "Country not found"}

    async def _iss_position(self, **kwargs: Any) -> Dict[str, Any]:
        """Open Notify — ISS position, free."""
        url = "http://api.open-notify.org/iss-now.json"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            pos = data.get("iss_position", {})
            return {"success": True, "latitude": pos.get("latitude"), "longitude": pos.get("longitude"),
                    "timestamp": data.get("timestamp")}

    async def _world_time(self, **kwargs: Any) -> Dict[str, Any]:
        """WorldTimeAPI — free timezone info."""
        tz = kwargs.get("query", "UTC")
        url = f"http://worldtimeapi.org/api/timezone/{tz}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            return {"success": True, "timezone": data.get("timezone"),
                    "datetime": data.get("datetime"), "utc_offset": data.get("utc_offset")}

    async def _qr_code(self, **kwargs: Any) -> Dict[str, Any]:
        """QR Code API — free, no key."""
        text = kwargs.get("text", kwargs.get("query", "https://raven.ai"))
        url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={text}"
        return {"success": True, "qr_url": url, "text": text}
