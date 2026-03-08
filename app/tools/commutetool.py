# app/tools/commutetool.py
"""CommuteTool — traffic and route information using free OSRM API."""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

OSRM_API = "http://router.project-osrm.org"


class CommuteTool(BaseTool):
    """Get commute times and route information using free OSRM (no API key needed)."""

    def get_name(self) -> str:
        return "commute"

    def get_description(self) -> str:
        return (
            "Get commute times and route information. "
            "Calculate travel time between coordinates, get driving/walking/cycling routes, "
            "and estimated arrival times. Uses free OSRM API (no API key required)."
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
                    enum=["route", "nearest", "route_between"],
                ),
                ToolParameter(
                    name="from_lat",
                    type="number",
                    description="Starting latitude",
                    required=False,
                ),
                ToolParameter(
                    name="from_lon",
                    type="number",
                    description="Starting longitude",
                    required=False,
                ),
                ToolParameter(
                    name="to_lat",
                    type="number",
                    description="Destination latitude",
                    required=False,
                ),
                ToolParameter(
                    name="to_lon",
                    type="number",
                    description="Destination longitude",
                    required=False,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="Travel mode: driving, walking, cycling",
                    required=False,
                ),
                ToolParameter(
                    name="from_place",
                    type="string",
                    description="Place name (for display only)",
                    required=False,
                ),
                ToolParameter(
                    name="to_place",
                    type="string",
                    description="Place name (for display only)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "route")
        from_lat = kwargs.get("from_lat")
        from_lon = kwargs.get("from_lon")
        to_lat = kwargs.get("to_lat")
        to_lon = kwargs.get("to_lon")
        mode = kwargs.get("mode", "driving")
        from_place = kwargs.get("from_place", "")
        to_place = kwargs.get("to_place", "")

        osrm_mode = {
            "driving": "driving",
            "walking": "foot",
            "cycling": "bike",
        }.get(mode, "driving")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if operation == "route" or operation == "route_between":
                    if (
                        from_lat is None
                        or from_lon is None
                        or to_lat is None
                        or to_lon is None
                    ):
                        return {
                            "success": False,
                            "error": "from_lat, from_lon, to_lat, to_lon are required",
                        }

                    coords = f"{from_lon},{from_lat};{to_lon},{to_lat}"
                    url = f"{OSRM_API}/route/v1/{osrm_mode}/{coords}"
                    params = {
                        "overview": "full",
                        "geometries": "geojson",
                        "steps": "true",
                        "annotations": "duration,distance",
                    }

                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("code") != "Ok":
                        return {
                            "success": False,
                            "error": data.get("message", "Route not found"),
                        }

                    route = data["routes"][0]
                    duration = route["duration"]
                    distance = route["distance"]
                    geometry = route["geometry"]["coordinates"]

                    legs = route["legs"][0]
                    distance_km = distance / 1000
                    distance_miles = distance / 1609.34
                    duration_min = duration / 60

                    return {
                        "success": True,
                        "mode": mode,
                        "duration_minutes": round(duration_min, 1),
                        "duration_text": f"{int(duration_min)} min",
                        "distance_km": round(distance_km, 1),
                        "distance_miles": round(distance_miles, 1),
                        "from": from_place or f"{from_lat},{from_lon}",
                        "to": to_place or f"{to_lat},{to_lon}",
                        "eta_minutes": round(duration_min, 1),
                        "geometry_points": len(geometry),
                        "message": f"🚗 {mode.title()}: {int(duration_min)} min ({round(distance_km, 1)} km)",
                    }

                if operation == "nearest":
                    if from_lat is None or from_lon is None:
                        return {
                            "success": False,
                            "error": "from_lat and from_lon required",
                        }

                    url = f"{OSRM_API}/nearest/v1/{osrm_mode}/{from_lon},{from_lat}"
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("code") != "Ok":
                        return {
                            "success": False,
                            "error": "Could not find nearest road",
                        }

                    waypoint = data["waypoints"][0]
                    return {
                        "success": True,
                        "latitude": waypoint["location"][1],
                        "longitude": waypoint["location"][0],
                        "name": waypoint.get("name", "Unknown road"),
                        "distance": waypoint.get("distance"),
                    }

                return {"success": False, "error": f"Unknown operation: {operation}"}

        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"API error: {exc.response.status_code}"}
        except Exception as exc:
            logger.exception("CommuteTool error")
            return {"success": False, "error": str(exc)}
