"""Spend tracking with per-user / per-plan / per-day budgets.

The ledger is the source of truth for *how much we've actually spent*.
The router consults it before every decision to know how much budget
the current request has left.

Storage strategy:
- In-memory primary store — fast, ephemeral, fine for one process.
- Optional HelixDB KV fallback — durable across restarts, queryable
  for cost dashboards.  The ledger does not block on a Helix outage;
  if the KV write fails, we log and keep going.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.cost_router.types import CostRecord

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BudgetConfig:
    """Budget knobs.  Sensible defaults to prevent cost explosion."""

    per_request_usd: float | None = 0.50  # Max $0.50 per single LLM call
    per_plan_usd: float | None = 5.00  # Max $5.00 per plan execution
    per_user_per_day_usd: float | None = 10.00  # Max $10.00 per user per day
    daily_warn_pct: float = 0.8


@dataclass(slots=True)
class SpendSummary:
    """Aggregate view returned to callers and dashboards."""

    total_usd: float = 0.0
    total_tokens: int = 0
    by_model: dict[str, float] = field(default_factory=dict)
    by_task: dict[str, float] = field(default_factory=dict)
    by_user: dict[str, float] = field(default_factory=dict)
    record_count: int = 0


class BudgetLedger:
    """Thread-/asyncio-safe in-memory ledger with optional HelixDB persistence.

    Safety: all mutations are guarded by an asyncio lock when an event
    loop is running; the class is safe to share across coroutines.
    """

    def __init__(
        self,
        config: BudgetConfig | None = None,
        *,
        helix_client: Any | None = None,
        kv_namespace: str = "cost_ledger",
    ) -> None:
        self._config = config or BudgetConfig()
        self._records: list[CostRecord] = []
        # Keyed by (scope, key, date) → spend in USD.
        self._buckets: dict[tuple[str, str, str], float] = defaultdict(float)
        self._lock: Any | None = None  # lazy asyncio.Lock
        self._helix = helix_client
        self._kv_ns = kv_namespace

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def config(self) -> BudgetConfig:
        return self._config

    def set_config(self, config: BudgetConfig) -> None:
        self._config = config

    def attach_helix(self, client: Any) -> None:
        """Attach a HelixDB client for durable spend storage."""
        self._helix = client

    # ------------------------------------------------------------------
    # Budget gates
    # ------------------------------------------------------------------

    def _bucket_key(self, scope: str, key: str) -> tuple[str, str, str]:
        return (scope, key, datetime.now(timezone.utc).date().isoformat())

    def _get_lock(self) -> Any:
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    async def check_budget(
        self,
        *,
        user_id: str | None = None,
        plan_id: str | None = None,
        additional_usd: float = 0.0,
    ) -> tuple[bool, str | None]:
        """Return ``(allowed, reason)``.

        ``allowed=False`` means the *additional* cost would push us over
        a configured limit.  The router must then downshift tier or
        refuse.
        """
        cfg = self._config
        # Per-request check
        if cfg.per_request_usd is not None and additional_usd > cfg.per_request_usd:
            return False, f"per-request cap ${cfg.per_request_usd:.4f}"
        # Per-plan check
        if cfg.per_plan_usd is not None and plan_id:
            spent = self._buckets.get(self._bucket_key("plan", plan_id), 0.0)
            if spent + additional_usd > cfg.per_plan_usd:
                return False, f"per-plan cap ${cfg.per_plan_usd:.4f} for {plan_id}"
        # Per-user-per-day check
        if cfg.per_user_per_day_usd is not None and user_id:
            spent = self._buckets.get(self._bucket_key("user", user_id), 0.0)
            if spent + additional_usd > cfg.per_user_per_day_usd:
                return False, (f"per-user daily cap ${cfg.per_user_per_day_usd:.4f} for {user_id}")
        return True, None

    async def budget_remaining(
        self,
        *,
        user_id: str | None = None,
        plan_id: str | None = None,
    ) -> float | None:
        """Return USD remaining for the tightest applicable limit.

        ``None`` if no limit is configured for the relevant scope.
        """
        cfg = self._config
        candidates: list[float] = []
        if cfg.per_user_per_day_usd is not None and user_id:
            spent = self._buckets.get(self._bucket_key("user", user_id), 0.0)
            candidates.append(cfg.per_user_per_day_usd - spent)
        if cfg.per_plan_usd is not None and plan_id:
            spent = self._buckets.get(self._bucket_key("plan", plan_id), 0.0)
            candidates.append(cfg.per_plan_usd - spent)
        if cfg.per_request_usd is not None:
            candidates.append(cfg.per_request_usd)
        if not candidates:
            return None
        return min(candidates)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record(self, rec: CostRecord) -> None:
        """Append a spend record.  Updates all relevant buckets."""
        lock = self._get_lock()
        if lock is not None:
            async with lock:
                self._record_unlocked(rec)
        else:
            self._record_unlocked(rec)
        await self._persist(rec)

    def _record_unlocked(self, rec: CostRecord) -> None:
        # Keep all records (including free local calls) so the dashboard
        # can show call volume; the bucket update below is what enforces
        # the spend tracking.
        self._records.append(rec)
        if rec.cost_usd <= 0:
            return
        today = datetime.now(timezone.utc).date().isoformat()
        if rec.user_id:
            self._buckets[("user", rec.user_id, today)] += rec.cost_usd
        if rec.plan_id:
            self._buckets[("plan", rec.plan_id, today)] += rec.cost_usd
        model_key = f"{rec.provider}/{rec.model}"
        self._buckets[("model", model_key, today)] += rec.cost_usd
        self._buckets[("task", rec.task.value, today)] += rec.cost_usd
        self._buckets[("total", "all", today)] += rec.cost_usd

        cfg = self._config
        if cfg.per_user_per_day_usd is not None and rec.user_id and cfg.daily_warn_pct < 1.0:
            spent = self._buckets[("user", rec.user_id, today)]
            if spent >= cfg.daily_warn_pct * cfg.per_user_per_day_usd:
                logger.warning(
                    "user %s has spent $%.4f of $%.4f daily cap (%.0f%%)",
                    rec.user_id,
                    spent,
                    cfg.per_user_per_day_usd,
                    100 * spent / cfg.per_user_per_day_usd,
                )

    async def _persist(self, rec: CostRecord) -> None:
        if self._helix is None:
            return
        try:
            key = f"{self._kv_ns}:{rec.timestamp.isoformat()}:{rec.provider}:{rec.model}"
            await self._helix.kv_put(key, rec.to_dict())
        except Exception as e:  # noqa: BLE001
            logger.debug("helix KV write failed (non-fatal): %s", e)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def records(self) -> list[CostRecord]:
        return list(self._records)

    def summary(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> SpendSummary:
        s = SpendSummary()
        for r in self._records:
            if since and r.timestamp < since:
                continue
            if until and r.timestamp > until:
                continue
            s.total_usd += r.cost_usd
            s.total_tokens += r.input_tokens + r.output_tokens
            s.record_count += 1
            s.by_model[f"{r.provider}/{r.model}"] = (
                s.by_model.get(f"{r.provider}/{r.model}", 0.0) + r.cost_usd
            )
            s.by_task[r.task.value] = s.by_task.get(r.task.value, 0.0) + r.cost_usd
            if r.user_id:
                s.by_user[r.user_id] = s.by_user.get(r.user_id, 0.0) + r.cost_usd
        return s

    def spend_today(self, user_id: str | None = None) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        if user_id:
            return self._buckets.get(("user", user_id, today), 0.0)
        return self._buckets.get(("total", "all", today), 0.0)


__all__ = ["BudgetConfig", "SpendSummary", "BudgetLedger"]
