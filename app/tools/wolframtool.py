# app/tools/wolframtool.py
"""WolframAlphaTool — math, science, and factual queries via Wolfram Alpha + local fallback."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict

import httpx

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

_WA_SHORT_URL = "https://api.wolframalpha.com/v1/result"


class WolframAlphaTool(BaseTool):
    """Query Wolfram Alpha for math, science, unit conversions, and general facts.
    Falls back to a local Python math/sympy evaluator when no API key is configured
    or when the query is a simple arithmetic expression."""

    def get_name(self) -> str:
        return "wolfram_alpha"

    def get_description(self) -> str:
        return (
            "Compute math expressions, unit conversions, scientific constants, "
            "and factual queries using Wolfram Alpha. "
            "Falls back to local Python math evaluation for arithmetic expressions "
            "when WOLFRAM_ALPHA_APP_ID is not set."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "The question or expression to evaluate. Examples: "
                        "'integrate x^2 from 0 to 3', 'speed of light in mph', "
                        "'population of Japan', '2^32', 'sqrt(144)'."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="units",
                    type="string",
                    description="Unit system: 'metric' (default) or 'imperial'.",
                    required=False,
                    enum=["metric", "imperial"],
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  execute                                                              #
    # ------------------------------------------------------------------ #

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        query: str = (kwargs.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "'query' is required."}

        units: str = kwargs.get("units", "metric")
        app_id = Config.WOLFRAM_ALPHA_APP_ID

        # Try Wolfram Alpha API first
        if app_id:
            result = await self._query_wolfram(query, app_id, units)
            if result["success"]:
                return result
            # If WA fails, fall through to local eval
            logger.warning("Wolfram Alpha API failed: %s", result.get("error"))

        # Local fallback
        local_result = self._local_eval(query)
        if local_result is not None:
            return {
                "success": True,
                "query": query,
                "result": str(local_result),
                "source": "local_python",
            }

        # If WA failed and local eval also failed
        if app_id:
            return {
                "success": False,
                "query": query,
                "error": (
                    "Wolfram Alpha returned no result and local eval could not "
                    "handle this expression."
                ),
            }

        return {
            "success": False,
            "query": query,
            "error": (
                "WOLFRAM_ALPHA_APP_ID not set and local eval could not handle "
                "this expression. Set WOLFRAM_ALPHA_APP_ID for full functionality."
            ),
        }

    # ------------------------------------------------------------------ #
    #  Wolfram Alpha API                                                   #
    # ------------------------------------------------------------------ #

    async def _query_wolfram(
        self, query: str, app_id: str, units: str
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    _WA_SHORT_URL,
                    params={"appid": app_id, "i": query, "units": units},
                )
            if resp.status_code == 501:
                return {
                    "success": False,
                    "error": "Wolfram Alpha could not interpret the query.",
                }
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"Wolfram Alpha API error {resp.status_code}: {resp.text[:200]}",
                }
            return {
                "success": True,
                "query": query,
                "result": resp.text.strip(),
                "source": "wolfram_alpha",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------ #
    #  Local Python math fallback                                          #
    # ------------------------------------------------------------------ #

    def _local_eval(self, query: str) -> Any:
        """Attempt to evaluate a math expression locally using math + sympy (if available)."""
        # Try sympy first for symbolic math
        try:
            import sympy  # type: ignore

            result = sympy.sympify(query)
            numeric = float(result.evalf())
            # Return integer if it's whole
            if numeric == int(numeric):
                return int(numeric)
            return round(numeric, 10)
        except Exception:
            pass

        # Fall back to safe Python eval with math builtins
        safe_globals: Dict[str, Any] = {
            "__builtins__": {},
            **{
                name: getattr(math, name)
                for name in dir(math)
                if not name.startswith("_")
            },
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
        }
        try:
            return eval(query, safe_globals, {})  # noqa: S307
        except Exception:
            return None
