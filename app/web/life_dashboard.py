"""Life dashboard — REST surface for the personal-life trackers.

Exposes the :class:`FinanceTracker`,
:class:`HealthTracker`, and :class:`HabitTracker` over a small
JSON API so the Streamlit / web dashboards can render them
without each dashboard re-implementing tracker logic.

Routes
------

  * ``GET  /life/finance/summary``        → monthly :class:`MonthlySummary`
  * ``POST /life/finance/expense``        → record a new expense
  * ``POST /life/finance/budget``         → set the active budget
  * ``GET  /life/health/<metric>``        → rolling average
  * ``POST /life/health/<metric>``        → record a daily reading
  * ``GET  /life/habits``                 → list known habits + streaks
  * ``POST /life/habits/<name>/done``     → mark habit done today
  * ``POST /life/habits/<name>/skipped``  → mark habit explicitly skipped

The router is **framework-agnostic**: it returns plain dicts,
not FastAPI / Flask response objects.  Mount it into whatever
HTTP framework the deployment uses (the production wiring in
``app/web/server.py`` mounts it via a tiny ``@app.route``
adapter).

This module deliberately **does not** import FastAPI / Flask at
top level so it can be unit-tested in isolation and reused
under any framework.
"""
from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import asdict
from typing import Any, Callable, Mapping

from app.core.finance_tracker import (
    Budget,
    Expense,
    FinanceTracker,
    get_finance_tracker,
)
from app.core.habit_tracker import HabitTracker, get_habit_tracker
from app.core.health_tracker import HealthTracker, get_health_tracker

logger = logging.getLogger(__name__)


# ── Router ─────────────────────────────────────────────────────────────


class LifeDashboardRouter:
    """Dispatch table for the life-dashboard REST surface.

    The router holds lightweight references to the three
    trackers (the production wiring uses the singletons;
    tests inject fakes via :meth:`__init__`).
    """

    def __init__(
        self,
        *,
        finance: FinanceTracker | None = None,
        health: HealthTracker | None = None,
        habits: HabitTracker | None = None,
    ) -> None:
        self._finance = finance or get_finance_tracker()
        self._health = health or get_health_tracker()
        self._habits = habits or get_habit_tracker()
        # route_name → handler
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /life/finance/summary": self.get_finance_summary,
            "POST /life/finance/expense": self.post_finance_expense,
            "POST /life/finance/budget": self.post_finance_budget,
            "GET /life/health/metric": self.get_health_metric,
            "POST /life/health/metric": self.post_health_metric,
            "GET /life/habits": self.get_habits,
            "POST /life/habits/done": self.post_habit_done,
            "POST /life/habits/skipped": self.post_habit_skipped,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Finance ─────────────────────────────────────────────────────

    def get_finance_summary(
        self, *, month: str | None = None,
    ) -> dict[str, Any]:
        summary = self._finance.summary(month=month)
        return {"ok": True, "summary": asdict(summary)}

    def post_finance_expense(
        self,
        *,
        amount: float,
        category: str,
        currency: str = "USD",
        note: str = "",
    ) -> dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "amount_must_be_positive"}
        self._finance.record(Expense(
            amount=float(amount),
            category=str(category or "uncategorised"),
            currency=str(currency or "USD"),
            note=str(note or ""),
        ))
        return {"ok": True}

    def post_finance_budget(
        self,
        *,
        monthly_cap: float,
        currency: str = "USD",
        category_caps: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        self._finance.set_budget(Budget(
            monthly_cap=float(monthly_cap),
            currency=str(currency or "USD"),
            category_caps=dict(category_caps or {}),
        ))
        return {"ok": True}

    # ── Health ──────────────────────────────────────────────────────

    def get_health_metric(
        self,
        metric: str,
        *,
        window_days: int = 7,
        ending: str | None = None,
    ) -> dict[str, Any]:
        avg = self._health.rolling_average(
            metric, window_days=window_days, ending=ending,
        )
        today_total = self._health.today_total(metric)
        return {
            "ok": True,
            "metric": metric,
            "window_days": window_days,
            "rolling_average": avg,
            "today_total": today_total,
        }

    def post_health_metric(
        self,
        metric: str,
        *,
        value: float,
        date: str | None = None,
    ) -> dict[str, Any]:
        self._health.record(metric, float(value), date=date)
        return {"ok": True}

    # ── Habits ──────────────────────────────────────────────────────

    def get_habits(self) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for habit in self._habits.habits():
            out.append({
                "habit": habit,
                "streak": self._habits.streak(habit),
                "completed_today": self._habits.completed_today(habit),
            })
        return {"ok": True, "habits": out}

    def post_habit_done(
        self, habit: str, *, date: str | None = None,
    ) -> dict[str, Any]:
        self._habits.mark_done(habit, date=date)
        return {
            "ok": True,
            "habit": habit,
            "streak": self._habits.streak(habit),
        }

    def post_habit_skipped(
        self, habit: str, *, date: str | None = None,
    ) -> dict[str, Any]:
        self._habits.mark_skipped(habit, date=date)
        return {"ok": True, "habit": habit}

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        """Dispatch a ``route`` by name and return the result dict.

        Production HTTP wiring translates the request into a
        route string + kwargs and feeds it here.  Unknown
        routes return ``{"ok": False, "error": "unknown_route"}``
        rather than raising — the caller (an HTTP layer) maps
        that to a 404.
        """
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:  # noqa: BLE001 - keep the router crash-safe
            logger.exception("Life dashboard route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


# ── Singleton accessor ─────────────────────────────────────────────────


_router_singleton: LifeDashboardRouter | None = None


def get_life_dashboard_router() -> LifeDashboardRouter:
    """Return the process-wide :class:`LifeDashboardRouter`."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = LifeDashboardRouter()
    return _router_singleton


def reset_life_dashboard_router_for_tests() -> None:  # pragma: no cover
    """Drop the cached singleton."""
    global _router_singleton
    _router_singleton = None