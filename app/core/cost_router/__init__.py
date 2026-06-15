"""Cost-aware model router (A2 in the foundation plan).

Public API:
- :class:`CostRouter` — the entry point.  Call :meth:`route` to pick a
  model and :meth:`record` to log the actual spend.
- :class:`ModelCatalog` — static table of eligible models with prices
  and per-task quality scores.
- :class:`BudgetLedger` — per-request / per-plan / per-user-per-day
  spend tracking with optional HelixDB persistence.
- :class:`ProviderHealth` — sliding-window provider health tracker.
- Types: :class:`RouteRequest`, :class:`RouteDecision`, :class:`CostRecord`,
  :class:`ModelSpec`, :class:`ModelTier`, :class:`ModelCapability`,
  :class:`TaskType`.
- Errors: :class:`BudgetExceededError`, :class:`NoRouteAvailableError`.
"""

from app.core.cost_router.catalog import ModelCatalog
from app.core.cost_router.health import HealthSnapshot, ProviderHealth
from app.core.cost_router.ledger import BudgetConfig, BudgetLedger, SpendSummary
from app.core.cost_router.router import CostRouter
from app.core.cost_router.types import (
    BudgetExceededError,
    CostRecord,
    ModelCapability,
    ModelSpec,
    ModelTier,
    NoRouteAvailableError,
    RouteDecision,
    RouteRequest,
    TaskType,
)

__all__ = [
    # Router
    "CostRouter",
    "ModelCatalog",
    "BudgetConfig",
    "BudgetLedger",
    "SpendSummary",
    "ProviderHealth",
    "HealthSnapshot",
    # Types
    "TaskType",
    "ModelCapability",
    "ModelTier",
    "ModelSpec",
    "RouteRequest",
    "RouteDecision",
    "CostRecord",
    # Errors
    "BudgetExceededError",
    "NoRouteAvailableError",
]
