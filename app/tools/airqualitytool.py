# app/tools/airqualitytool.py
"""AirQualityTool — get air quality index and pollution data."""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

WAQI_API = "https://api.waqi.info"


class AirQualityTool(BaseTool):
    """Get air quality index (AQI) and pollution data for any location."""

    def get_name(self) -> str:
        return "air_quality"

    def get_description(self) -> str:
        return (
            "Get air quality index (AQI) and pollution data from World Air Quality Index project. "
            "Get AQI by city name, station, or coordinates. "
            "Supports PM2.5, PM10, O3, NO2, CO, SO2 measurements."
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
                    enum=[
                        "aqi_by_city",
                        "aqi_by_station",
                        "aqi_by_geo",
                        "nearest_station",
                        "search",
                    ],
                ),
                ToolParameter(
                    name="city",
                    type="string",
                    description="City name (e.g., 'London', 'Beijing')",
                    required=False,
                ),
                ToolParameter(
                    name="station",
                    type="string",
                    description="Station name or ID",
                    required=False,
                ),
                ToolParameter(
                    name="latitude",
                    type="number",
                    description="Latitude for geo lookup",
                    required=False,
                ),
                ToolParameter(
                    name="longitude",
                    type="number",
                    description="Longitude for geo lookup",
                    required=False,
                ),
            ],
        )

    def _get_api_key(self) -> str:
        return getattr(Config, "WAQI_API_KEY", None) or "demo"

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "aqi_by_city")
        city = kwargs.get("city", "")
        station = kwargs.get("station", "")
        lat = kwargs.get("latitude")
        lon = kwargs.get("longitude")
        api_key = self._get_api_key()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if operation == "aqi_by_city":
                    if not city:
                        return {"success": False, "error": "city required"}
                    resp = await client.get(
                        f"{WAQI_API}/feed/{city}",
                        params={"token": api_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("status") != "ok":
                        return {
                            "success": False,
                            "error": data.get("data", "Unknown error"),
                        }
                    return self._parse_waqi_data(data["data"])

                if operation == "aqi_by_station":
                    if not station:
                        return {"success": False, "error": "station name required"}
                    resp = await client.get(
                        f"{WAQI_API}/feed/{station}",
                        params={"token": api_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("status") != "ok":
                        return {
                            "success": False,
                            "error": data.get("data", "Unknown error"),
                        }
                    return self._parse_waqi_data(data["data"])

                if operation == "aqi_by_geo":
                    if lat is None or lon is None:
                        return {
                            "success": False,
                            "error": "latitude and longitude required",
                        }
                    resp = await client.get(
                        f"{WAQI_API}/feed/geo:{lat};{lon}",
                        params={"token": api_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("status") != "ok":
                        return {
                            "success": False,
                            "error": data.get("data", "Unknown error"),
                        }
                    return self._parse_waqi_data(data["data"])

                if operation == "nearest_station":
                    if lat is None or lon is None:
                        return {
                            "success": False,
                            "error": "latitude and longitude required",
                        }
                    resp = await client.get(
                        f"{WAQI_API}/feed/geo:{lat};{lon}/",
                        params={"token": api_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("status") != "ok":
                        return {
                            "success": False,
                            "error": data.get("data", "Unknown error"),
                        }
                    return self._parse_waqi_data(data["data"])

                if operation == "search":
                    if not city:
                        return {"success": False, "error": "city required for search"}
                    resp = await client.get(
                        f"{WAQI_API}/search/",
                        params={"token": api_key, "keyword": city},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("data", [])
                    return {
                        "success": True,
                        "results": [
                            {
                                "station": r.get("station", {}).get("name"),
                                "url": r.get("station", {}).get("url"),
                            }
                            for r in results[:10]
                        ],
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"API error: {exc.response.status_code}"}
        except Exception as exc:
            logger.exception("AirQualityTool error")
            return {"success": False, "error": str(exc)}

    def _parse_waqi_data(self, data: Dict) -> Dict[str, Any]:
        aqi = data.get("aqi")
        iaqi = data.get("iaqi", {})
        dominant = data.get("dominentpollutant", "").upper()

        pollutants = {}
        for pol in ["pm25", "pm10", "o3", "no2", "co", "so2", "t", "h", "w"]:
            if pol in iaqi:
                pollutants[pol.upper()] = iaqi[pol].get("v")

        return {
            "success": True,
            "aqi": aqi,
            "category": self._aqi_category(aqi),
            "city": data.get("city", {}).get("name"),
            "dominant_pollutant": dominant,
            "pollutants": pollutants,
            "time": data.get("time", {}).get("s"),
            "last_update": data.get("time", {}).get("local"),
        }

    def _aqi_category(self, aqi: int) -> str:
        if aqi <= 50:
            return "Good 🟢"
        elif aqi <= 100:
            return "Moderate 🟡"
        elif aqi <= 150:
            return "Unhealthy for Sensitive Groups 🟠"
        elif aqi <= 200:
            return "Unhealthy 🔴"
        elif aqi <= 300:
            return "Very Unhealthy 🟣"
        else:
            return "Hazardous ⚫"
