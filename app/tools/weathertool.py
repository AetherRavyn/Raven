# app/tools/weathertool.py
"""WeatherTool — current weather + 5-day forecast via OpenWeatherMap free API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.settings.config import Config

logger = logging.getLogger(__name__)
_BASE_URL = "https://api.openweathermap.org/data/2.5"


class WeatherTool(BaseTool):
    def get_name(self) -> str:
        return "get_weather"

    def get_description(self) -> str:
        return "Get current weather or 5-day forecast for a city. action=current or action=forecast."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="current | forecast",
                    required=True,
                    enum=["current", "forecast"],
                ),
                ToolParameter(
                    name="location",
                    type="string",
                    description="City name, e.g. 'London' or 'New York,US'. Defaults to configured DEFAULT_LOCATION.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict:
        action = kwargs.get("action", "current")
        location = kwargs.get("location") or Config.DEFAULT_LOCATION
        api_key = Config.OPENWEATHERMAP_API_KEY

        if not api_key:
            return {"success": False, "error": "OPENWEATHERMAP_API_KEY not set"}

        if action == "current":
            return await self._current(location, api_key)
        elif action == "forecast":
            return await self._forecast(location, api_key)
        return {"success": False, "error": f"Unknown action: {action}"}

    async def _current(self, location: str, api_key: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/weather",
                params={"q": location, "appid": api_key, "units": "metric"},
                timeout=10,
            )
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"API error {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json()
        desc = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        summary = (
            f"{location}: {desc}, {temp:.1f}°C (feels like {feels_like:.1f}°C), "
            f"humidity {humidity}%, wind {wind} m/s"
        )
        return {"success": True, "summary": summary, "raw": data}

    async def _forecast(self, location: str, api_key: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/forecast",
                params={"q": location, "appid": api_key, "units": "metric", "cnt": 8},
                timeout=10,
            )
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"API error {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json()
        entries = []
        for item in data.get("list", []):
            dt = item["dt_txt"]
            temp = item["main"]["temp"]
            desc = item["weather"][0]["description"]
            entries.append(f"{dt}: {desc}, {temp:.1f}°C")
        return {"success": True, "forecast": entries, "raw": data}
