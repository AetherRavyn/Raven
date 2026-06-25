"""Health tracker.

Records daily health metrics (steps, sleep hours, water
glasses, custom metrics) and exposes rolling averages so the
proactive loop can prompt the user when they fall behind their
personal baseline.  Like :class:`FinanceTracker`, the tracker
is a thin JSONL scratchpad — not a medical device.

Data shapes
-----------

Ledger (``health_ledger.jsonl``) — append-only, one JSON
object per line::

    {"date": "2026-06-20", "metric": "steps", "value": 8421.0}

The ``date`` field is an ISO ``YYYY-MM-DD``; the ``metric``
field is free-form (``"steps"``, ``"sleep_hours"``,
``"water_glasses"``, etc.).  Values are numeric; booleans are
recorded as ``1.0`` / ``0.0``.

Rolling averages
----------------

:meth:`HealthTracker.rolling_average` returns the arithmetic
mean of a metric over the last ``window_days`` days, defaulting
to 7.  Days with no record are treated as missing (skipped,
not zero-filled) so the user isn't penalised for forgetting to
log a metric.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Tracker ────────────────────────────────────────────────────────────


class HealthTracker:
    """JSONL-backed daily-metrics scratchpad."""

    DEFAULT_LEDGER_FILENAME = "health_ledger.jsonl"

    def __init__(
        self,
        *,
        workspace_dir: str | Path | None = None,
        ledger_filename: str = DEFAULT_LEDGER_FILENAME,
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
        self._clock = clock or time.time

    # ── Mutators ────────────────────────────────────────────────────

    def record(self, metric: str, value: float, *, date: str | None = None) -> None:
        """Append a daily metric reading."""
        active_date = date or _today(self._clock)
        entry = {
            "date": active_date,
            "metric": metric,
            "value": float(value),
        }
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # ── Read API ────────────────────────────────────────────────────

    def values_for(
        self,
        metric: str,
        *,
        window_days: int = 7,
        ending: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return ``[(date, value), ...]`` for ``metric`` over the
        last ``window_days`` days, ending at ``ending`` (defaults
        to today).  Days with no record are omitted.
        """
        if window_days <= 0:
            return []
        anchor = (
            _dt.date.fromisoformat(ending)
            if ending is not None
            else _dt.date.fromtimestamp(self._clock())
        )
        start = anchor - _dt.timedelta(days=window_days - 1)
        out: list[tuple[str, float]] = []
        for date_str, value in self._iter_metric(metric):
            try:
                d = _dt.date.fromisoformat(date_str)
            except ValueError:
                continue
            if d < start or d > anchor:
                continue
            out.append((date_str, value))
        out.sort(key=lambda pair: pair[0])
        return out

    def rolling_average(
        self,
        metric: str,
        *,
        window_days: int = 7,
        ending: str | None = None,
    ) -> float | None:
        """Arithmetic mean of ``metric`` over the last
        ``window_days`` days.  Returns ``None`` if no records
        fall in the window — callers should treat ``None`` as
        "no signal", not "0.0"."""
        pairs = self.values_for(metric, window_days=window_days, ending=ending)
        if not pairs:
            return None
        return sum(v for _d, v in pairs) / len(pairs)

    def today_total(self, metric: str) -> float:
        """Sum of all ``metric`` readings recorded for today.

        Useful for "water glasses today" style queries where the
        user logs each glass as a separate entry.
        """
        today = _today(self._clock)
        total = 0.0
        for date_str, value in self._iter_metric(metric):
            if date_str == today:
                total += value
        return total

    # ── Internals ───────────────────────────────────────────────────

    def _iter_metric(self, metric: str) -> Iterable[tuple[str, float]]:
        if not self._ledger_path.is_file():
            return iter(())
        out: list[tuple[str, float]] = []
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if raw.get("metric") != metric:
                    continue
                out.append(
                    (str(raw.get("date", "")), float(raw.get("value", 0.0))),
                )
        return iter(out)


# ── Helpers ────────────────────────────────────────────────────────────


def _today(clock_fn: Any) -> str:
    return _dt.date.fromtimestamp(clock_fn()).isoformat()


# ── Singleton ──────────────────────────────────────────────────────────


_tracker_singleton: HealthTracker | None = None


def get_health_tracker() -> HealthTracker:
    """Return the process-wide :class:`HealthTracker`."""
    global _tracker_singleton
    if _tracker_singleton is None:
        _tracker_singleton = HealthTracker()
    return _tracker_singleton


def reset_health_tracker_for_tests() -> None:  # pragma: no cover - test seam
    """Drop the cached singleton."""
    global _tracker_singleton
    _tracker_singleton = None
