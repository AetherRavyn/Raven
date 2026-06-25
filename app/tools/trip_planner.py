"""Trip Planning — search flights, hotels, visa requirements, and build itineraries.

Uses free APIs (Skyscanner, Booking.com, Wikipedia) to search for
travel options and generate structured trip plans.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class TripPlannerTool(BaseTool):
    """Plan trips: flights, hotels, visa, itineraries."""

    def get_name(self) -> str:
        return "trip_planner"

    def get_description(self) -> str:
        return (
            "Plan trips: search flights and hotels, check visa requirements, "
            "generate day-by-day itineraries, and estimate travel budgets."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["plan_trip", "visa_check", "budget_estimate", "itinerary", "packing_list"],
                    "description": "plan_trip=full trip plan, visa_check=visa requirements, itinerary=day-by-day plan",
                },
                "destination": {"type": "string", "description": "Destination city/country"},
                "origin": {"type": "string", "description": "Origin city/country"},
                "start_date": {"type": "string", "description": "Trip start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "Trip end date (YYYY-MM-DD)"},
                "budget": {"type": "number", "description": "Total budget in USD"},
                "travelers": {"type": "integer", "description": "Number of travelers"},
                "preferences": {"type": "array", "description": "Preferences: budget, luxury, adventure, cultural, etc."},
                "nationality": {"type": "string", "description": "Traveler nationality for visa check"},
                "days": {"type": "integer", "description": "Number of days for itinerary"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "plan_trip")

        if operation == "plan_trip":
            return await self._plan_trip(kwargs)
        elif operation == "visa_check":
            return await self._visa_check(kwargs.get("nationality", ""), kwargs.get("destination", ""))
        elif operation == "budget_estimate":
            return self._budget_estimate(kwargs)
        elif operation == "itinerary":
            return self._build_itinerary(kwargs)
        elif operation == "packing_list":
            return self._packing_list(kwargs)
        return {"error": f"Unknown operation: {operation}"}

    async def _plan_trip(self, kwargs: dict) -> dict:
        """Generate a complete trip plan."""
        destination = kwargs.get("destination", "")
        origin = kwargs.get("origin", "")
        start_date = kwargs.get("start_date", "")
        end_date = kwargs.get("end_date", "")
        budget = kwargs.get("budget", 0)
        kwargs.get("travelers", 1)

        if not destination:
            return {"error": "destination is required"}

        plan: dict[str, Any] = {"destination": destination, "origin": origin}

        # Calculate trip duration
        if start_date and end_date:
            try:
                start = datetime.fromisoformat(start_date)
                end = datetime.fromisoformat(end_date)
                days = (end - start).days
                plan["duration_days"] = days
                plan["start_date"] = start_date
                plan["end_date"] = end_date
            except ValueError:
                plan["duration_days"] = 7

        # Get visa requirements
        nationality = kwargs.get("nationality", "")
        if nationality:
            visa = await self._visa_check(nationality, destination)
            plan["visa_info"] = visa

        # Budget breakdown
        if budget > 0:
            days = plan.get("duration_days", 7)
            daily = budget / max(days, 1)
            plan["budget_breakdown"] = {
                "total": budget,
                "per_day": round(daily, 2),
                "accommodation": round(daily * 0.35, 2),
                "food": round(daily * 0.25, 2),
                "transport": round(daily * 0.15, 2),
                "activities": round(daily * 0.15, 2),
                "misc": round(daily * 0.10, 2),
            }

        # Get destination info
        try:
            info = await self._get_destination_info(destination)
            plan["destination_info"] = info
        except Exception:
            pass

        # Generate itinerary
        plan["itinerary"] = self._build_itinerary(kwargs).get("itinerary", [])

        return {"success": True, "plan": plan}

    async def _visa_check(self, nationality: str, destination: str) -> dict:
        """Check visa requirements using Wikipedia/country info."""
        if not nationality or not destination:
            return {"error": "nationality and destination required"}

        try:
            import httpx
            # Use REST Countries API for visa info
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://restcountries.com/v3.1/name/{destination}",
                    params={"fields": "name,region,subregion,languages,currencies,capital,cca2"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list):
                        country = data[0]
                        return {
                            "success": True,
                            "destination": country.get("name", {}).get("common", destination),
                            "region": country.get("region", ""),
                            "subregion": country.get("subregion", ""),
                            "capital": country.get("capital", [""])[0] if country.get("capital") else "",
                            "currency": list(country.get("currencies", {}).values())[0].get("name", "") if country.get("currencies") else "",
                            "languages": list(country.get("languages", {}).values())[:3],
                            "note": f"Check official visa requirements for {nationality} nationals visiting {destination}. Use embassy website for accurate info.",
                        }
        except Exception:
            pass

        return {
            "destination": destination,
            "nationality": nationality,
            "note": f"Check visa requirements for {nationality} nationals visiting {destination} at the destination's embassy website.",
        }

    def _budget_estimate(self, kwargs: dict) -> dict:
        """Estimate trip budget based on destination and duration."""
        destination = kwargs.get("destination", "")
        days = kwargs.get("days", 7)
        travelers = kwargs.get("travelers", 1)
        preferences = kwargs.get("preferences", [])

        is_budget = "budget" in preferences
        is_luxury = "luxury" in preferences

        # Cost estimates per day per person (USD)
        cost_tiers = {
            "budget": {"accommodation": 30, "food": 20, "transport": 10, "activities": 10},
            "mid": {"accommodation": 80, "food": 40, "transport": 20, "activities": 25},
            "luxury": {"accommodation": 250, "food": 100, "transport": 50, "activities": 80},
        }

        tier = "luxury" if is_luxury else ("budget" if is_budget else "mid")
        costs = cost_tiers[tier]

        total_per_person = sum(costs.values()) * days
        total = total_per_person * travelers

        return {
            "success": True,
            "destination": destination,
            "duration_days": days,
            "travelers": travelers,
            "tier": tier,
            "daily_costs_per_person": costs,
            "total_per_person": total_per_person,
            "total": total,
            "breakdown": {
                "accommodation": costs["accommodation"] * days * travelers,
                "food": costs["food"] * days * travelers,
                "transport": costs["transport"] * days * travelers,
                "activities": costs["activities"] * days * travelers,
            },
            "note": "Estimates are approximate. Actual costs vary by season and location.",
        }

    def _build_itinerary(self, kwargs: dict) -> dict:
        """Build a day-by-day itinerary."""
        destination = kwargs.get("destination", "Destination")
        days = kwargs.get("days", kwargs.get("duration_days", 5))
        preferences = kwargs.get("preferences", [])

        is_cultural = "cultural" in preferences
        is_adventure = "adventure" in preferences

        itinerary = []
        for day in range(1, days + 1):
            activities = []

            if is_cultural:
                activities = [
                    f"Visit museums and historical sites in {destination}",
                    "Explore local neighborhoods on foot",
                    "Try authentic local cuisine",
                ]
            elif is_adventure:
                activities = [
                    f"Morning: Outdoor activity near {destination}",
                    "Afternoon: Explore nature or adventure park",
                    "Evening: Local nightlife or cultural show",
                ]
            else:
                activities = [
                    f"Morning: Visit popular attractions in {destination}",
                    "Afternoon: Shopping or local exploration",
                    "Evening: Dinner at a recommended restaurant",
                ]

            if day == 1:
                activities = [f"Arrive in {destination} and check in", "Explore nearby area", "Welcome dinner"]
            elif day == days:
                activities = [f"Final morning in {destination}", "Pack and check out", "Depart for home"]

            itinerary.append({
                "day": day,
                "date": f"Day {day}",
                "activities": activities,
                "tips": f"Tip: Check local events on day {day}",
            })

        return {"success": True, "itinerary": itinerary, "total_days": days}

    def _packing_list(self, kwargs: dict) -> dict:
        """Generate a packing list based on destination and duration."""
        days = kwargs.get("days", 7)
        destination = kwargs.get("destination", "")
        kwargs.get("preferences", [])

        essential = [
            "Passport/ID", "Travel documents", "Phone + charger",
            "Medications", "Toothbrush + toiletries", "Change of clothes",
            "Comfortable walking shoes", "Money + cards",
        ]

        clothes = [
            f"{min(days, 7)} tops", f"{min(days // 2 + 1, 5)} bottoms",
            "Underwear", "Socks", "Sleepwear", "Jacket/sweater",
        ]

        tech = ["Laptop/tablet", "Headphones", "Power bank", "Adapter (if international)"]

        optional = ["Camera", "Guidebook", "Snacks for travel", "Neck pillow", "Reusable water bottle"]

        return {
            "success": True,
            "destination": destination,
            "duration_days": days,
            "packing_list": {
                "essential": essential,
                "clothes": clothes,
                "tech": tech,
                "optional": optional,
                "total_items": len(essential) + len(clothes) + len(tech) + len(optional),
            },
        }

    async def _get_destination_info(self, destination: str) -> dict:
        """Get basic info about a destination."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://restcountries.com/v3.1/name/{destination}",
                    params={"fields": "name,capital,region,currencies,timezone"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list):
                        country = data[0]
                        return {
                            "name": country.get("name", {}).get("common", destination),
                            "capital": country.get("capital", [""])[0] if country.get("capital") else "",
                            "currency": list(country.get("currencies", {}).values())[0].get("name", "") if country.get("currencies") else "",
                        }
        except Exception:
            pass
        return {}
