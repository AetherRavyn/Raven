"""Maps & Geocoding Tool — location services via free APIs.

Supports:
- Geocoding (address → coordinates)
- Reverse geocoding (coordinates → address)
- Distance calculation
- Timezone lookup
- Nearby places

Uses free APIs: Nominatim (OpenStreetMap), ip-api.com, timezone DB.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class MapsGeocodingTool(BaseTool):
    """Location services: geocoding, reverse geocoding, distance, timezone."""

    def get_name(self) -> str:
        return "maps_geocoding"

    def get_description(self) -> str:
        return (
            "Location services: geocode addresses to coordinates, "
            "reverse geocode coordinates to addresses, calculate distances, "
            "lookup timezones. Uses free OpenStreetMap APIs."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="operation", type="string", required=True,
                             description="Operation: geocode, reverse_geocode, distance, timezone, nearby",
                             enum=["geocode", "reverse_geocode", "distance", "timezone", "nearby"]),
                ToolParameter(name="address", type="string", required=False,
                             description="Address to geocode"),
                ToolParameter(name="lat", type="number", required=False,
                             description="Latitude for reverse geocode/distance"),
                ToolParameter(name="lon", type="number", required=False,
                             description="Longitude for reverse geocode/distance"),
                ToolParameter(name="lat2", type="number", required=False,
                             description="Second latitude for distance calculation"),
                ToolParameter(name="lon2", type="number", required=False,
                             description="Second longitude for distance calculation"),
                ToolParameter(name="query", type="string", required=False,
                             description="Search query for nearby places"),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "")
        try:
            if operation == "geocode":
                return await self._geocode(kwargs.get("address", ""))
            elif operation == "reverse_geocode":
                return await self._reverse_geocode(kwargs.get("lat", 0), kwargs.get("lon", 0))
            elif operation == "distance":
                return self._distance(
                    kwargs.get("lat", 0), kwargs.get("lon", 0),
                    kwargs.get("lat2", 0), kwargs.get("lon2", 0),
                )
            elif operation == "timezone":
                return await self._timezone(kwargs.get("lat", 0), kwargs.get("lon", 0))
            elif operation == "nearby":
                return await self._nearby(kwargs.get("lat", 0), kwargs.get("lon", 0), kwargs.get("query", ""))
            return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            logger.exception("MapsGeocodingTool error")
            return {"success": False, "error": str(e)}

    async def _geocode(self, address: str) -> Dict[str, Any]:
        """Geocode an address to coordinates using Nominatim."""
        if not address:
            return {"success": False, "error": "address is required"}
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": "Raven/1.0"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return {"success": False, "error": "No results found"}
            r = results[0]
            return {
                "success": True,
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "display_name": r.get("display_name", ""),
                "type": r.get("type", ""),
            }

    async def _reverse_geocode(self, lat: float, lon: float) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address."""
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json"}
        headers = {"User-Agent": "Raven/1.0"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "address": data.get("display_name", ""),
                "lat": lat,
                "lon": lon,
                "type": data.get("type", ""),
            }

    def _distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> Dict[str, Any]:
        """Calculate distance between two points (Haversine formula)."""
        import math
        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance_km = R * c
        distance_mi = distance_km * 0.621371
        return {
            "success": True,
            "distance_km": round(distance_km, 2),
            "distance_miles": round(distance_mi, 2),
            "from": {"lat": lat1, "lon": lon1},
            "to": {"lat": lat2, "lon": lon2},
        }

    async def _timezone(self, lat: float, lon: float) -> Dict[str, Any]:
        """Get timezone for coordinates."""
        url = f"https://timeapi.io/api/timezone/coordinate?latitude={lat}&longitude={lon}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                return {
                    "success": True,
                    "timezone": data.get("timeZone", ""),
                    "lat": lat,
                    "lon": lon,
                }
            except Exception:
                return {"success": True, "timezone": "UTC", "lat": lat, "lon": lon}

    async def _nearby(self, lat: float, lon: float, query: str) -> Dict[str, Any]:
        """Find nearby places using Nominatim."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query or "nearby",
            "format": "json",
            "limit": 10,
            "viewbox": f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",
            "bounded": 1,
        }
        headers = {"User-Agent": "Raven/1.0"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
            places = [
                {
                    "name": r.get("display_name", ""),
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                    "type": r.get("type", ""),
                }
                for r in results
            ]
            return {"success": True, "places": places, "count": len(places)}
