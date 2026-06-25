"""Finance tracker.

Tracks day-to-day spending + monthly budget burn so the
proactive loop can warn the user when they are approaching
budget caps.  The tracker is intentionally **stateless across
processes**: every call reads / writes a JSONL ledger on disk
and a small JSON config file for the active budget.

Data shapes
-----------

Ledger (``finance_ledger.jsonl``) — append-only, one JSON
object per line::

    {"ts": 1700000000.0, "amount": 12.50, "currency": "USD",
     "category": "groceries", "note": "weekly shop"}

Budget (``finance_budget.json``) — single object::

    {"monthly_cap": 1500.0, "currency": "USD",
     "category_caps": {"groceries": 400.0}}

The tracker is intentionally **not** a ledger of record.  It is
a thin personal-finance scratchpad that lets the agent answer
"how much have I spent this month?" without an external
banking integration.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Records ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Expense:
    """One row in the ledger."""

    amount: float
    category: str
    currency: str = "USD"
    note: str = ""
    ts: float = 0.0

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(slots=True)
class Budget:
    """Monthly spend caps."""

    monthly_cap: float = 0.0
    currency: str = "USD"
    category_caps: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class MonthlySummary:
    """The tracker's read API: a snapshot of the current month."""

    month: str  # "YYYY-MM"
    total: float
    by_category: dict[str, float]
    cap: float
    over_cap: bool
    over_category_caps: dict[str, float]


# ── Tracker ────────────────────────────────────────────────────────────


class FinanceTracker:
    """JSONL-backed personal-finance scratchpad."""

    DEFAULT_LEDGER_FILENAME = "finance_ledger.jsonl"
    DEFAULT_BUDGET_FILENAME = "finance_budget.json"

    def __init__(
        self,
        *,
        workspace_dir: str | Path | None = None,
        ledger_filename: str = DEFAULT_LEDGER_FILENAME,
        budget_filename: str = DEFAULT_BUDGET_FILENAME,
        clock: Any = None,
    ) -> None:
        base = (
            Path(workspace_dir)
            if workspace_dir is not None
            else Path(
                os.environ.get("MEMORY_ROOT", "workspace/memory"),
            )
        )
        base.mkdir(parents=True, exist_ok=True)
        self._ledger_path = base / ledger_filename
        self._budget_path = base / budget_filename
        self._clock = clock or time.time

    # ── Mutators ────────────────────────────────────────────────────

    def record(self, expense: Expense) -> None:
        """Append ``expense`` to the ledger."""
        if expense.ts == 0.0:
            expense = Expense(
                amount=expense.amount,
                category=expense.category,
                currency=expense.currency,
                note=expense.note,
                ts=self._clock(),
            )
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(expense.to_jsonl() + "\n")
        logger.info(
            "FinanceTracker recorded %.2f %s in %s",
            expense.amount, expense.currency, expense.category,
        )

    def set_budget(self, budget: Budget) -> None:
        """Persist ``budget`` to disk."""
        self._budget_path.write_text(
            json.dumps(asdict(budget), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # ── Read API ────────────────────────────────────────────────────

    def get_budget(self) -> Budget:
        """Read the active budget, returning a zero-budget default
        if the file is missing or unreadable."""
        if not self._budget_path.is_file():
            return Budget()
        try:
            raw = json.loads(self._budget_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("FinanceTracker budget read failed: %s", e)
            return Budget()
        return Budget(
            monthly_cap=float(raw.get("monthly_cap", 0.0)),
            currency=str(raw.get("currency", "USD")),
            category_caps=dict(raw.get("category_caps", {})),
        )

    def iter_expenses(self, *, month: str | None = None) -> Iterable[Expense]:
        """Yield expenses in chronological order, optionally
        filtered to ``month`` (``"YYYY-MM"``)."""
        if not self._ledger_path.is_file():
            return iter(())
        out: list[Expense] = []
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if month is not None:
                    ts = float(raw.get("ts", 0.0))
                    if _month_key(ts) != month:
                        continue
                out.append(
                    Expense(
                        amount=float(raw["amount"]),
                        category=str(raw.get("category", "uncategorised")),
                        currency=str(raw.get("currency", "USD")),
                        note=str(raw.get("note", "")),
                        ts=float(raw.get("ts", 0.0)),
                    ),
                )
        return iter(out)

    def summary(self, *, month: str | None = None) -> MonthlySummary:
        """Return a monthly summary.  ``month`` defaults to the
        current month in the tracker's clock."""
        active_month = month or _month_key(self._clock())
        budget = self.get_budget()
        by_cat: dict[str, float] = defaultdict(float)
        total = 0.0
        for expense in self.iter_expenses(month=active_month):
            by_cat[expense.category] += expense.amount
            total += expense.amount
        over_caps: dict[str, float] = {}
        for cat, cap in budget.category_caps.items():
            spent = by_cat.get(cat, 0.0)
            if spent > cap:
                over_caps[cat] = round(spent - cap, 2)
        return MonthlySummary(
            month=active_month,
            total=round(total, 2),
            by_category={k: round(v, 2) for k, v in by_cat.items()},
            cap=budget.monthly_cap,
            over_cap=total > budget.monthly_cap > 0,
            over_category_caps=over_caps,
        )


# ── Helpers ────────────────────────────────────────────────────────────


def _month_key(ts: float) -> str:
    import datetime as _dt

    d = _dt.datetime.fromtimestamp(ts)
    return f"{d.year:04d}-{d.month:02d}"


# ── Singleton ──────────────────────────────────────────────────────────


_tracker_singleton: FinanceTracker | None = None


def get_finance_tracker() -> FinanceTracker:
    """Return the process-wide :class:`FinanceTracker`."""
    global _tracker_singleton
    if _tracker_singleton is None:
        _tracker_singleton = FinanceTracker()
    return _tracker_singleton


def reset_finance_tracker_for_tests() -> None:  # pragma: no cover - test seam
    """Drop the cached singleton."""
    global _tracker_singleton
    _tracker_singleton = None
