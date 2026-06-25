"""Habit tracker.

Tracks boolean habit completion and computes streaks so the
proactive loop can congratulate the user on milestone days
(7-day streak, 30-day streak, etc.) and gently remind them on
days at risk of breaking a streak.

Data shapes
-----------

Ledger (``habit_ledger.jsonl``) — append-only, one JSON
object per line::

    {"date": "2026-06-20", "habit": "morning_walk", "done": true}

A missing ``done`` field defaults to ``True`` (the line is
treated as "the user logged this habit, mark it done").  An
explicit ``false`` records that the user skipped the habit on
that day — useful for honesty about missed days vs. forgotten
logs.

The streak contract
-------------------

:meth:`HabitTracker.streak` returns the count of consecutive
days, ending at today (or ``ending=``), on which the habit
was either logged as ``done: true`` **or** simply logged
(``done`` absent).  A day with ``done: false`` breaks the
streak.  A day with no record at all does **not** break the
streak — we can't tell whether the user skipped the habit or
forgot to log it, and we err on the side of not punishing
the user for forgetting the tracker itself.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Tracker ────────────────────────────────────────────────────────────


class HabitTracker:
    """JSONL-backed daily habit scratchpad."""

    DEFAULT_LEDGER_FILENAME = "habit_ledger.jsonl"

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

    def mark_done(self, habit: str, *, date: str | None = None) -> None:
        """Record ``habit`` as completed on ``date`` (today by default)."""
        self._append(habit, date=date, done=True)

    def mark_skipped(self, habit: str, *, date: str | None = None) -> None:
        """Record ``habit`` as explicitly skipped on ``date``."""
        self._append(habit, date=date, done=False)

    def _append(
        self, habit: str, *, date: str | None, done: bool,
    ) -> None:
        active_date = date or _today(self._clock)
        entry = {"date": active_date, "habit": habit, "done": done}
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # ── Read API ────────────────────────────────────────────────────

    def streak(self, habit: str, *, ending: str | None = None) -> int:
        """Return the active streak of ``habit`` ending at ``ending``
        (today by default).  See module docstring for the contract.
        """
        anchor = (
            _dt.date.fromisoformat(ending)
            if ending is not None
            else _dt.date.fromtimestamp(self._clock())
        )
        # Build a per-day map of done / skipped / unknown.
        per_day: dict[_dt.date, bool | None] = {}
        for date_str, done in self._iter(habit):
            try:
                d = _dt.date.fromisoformat(date_str)
            except ValueError:
                continue
            if d > anchor:
                continue
            # Multiple writes on the same day — the last one wins.
            per_day[d] = done
        # Walk backwards from anchor, breaking on explicit False.
        streak = 0
        cursor = anchor
        while True:
            entry = per_day.get(cursor)
            if entry is False:
                break
            if entry is True:
                streak += 1
            elif entry is None:
                # No record — don't break; just don't add to the streak.
                pass
            cursor = cursor - _dt.timedelta(days=1)
            # Safety valve: don't walk past a year.
            if (anchor - cursor).days > 365:
                break
        return streak

    def completed_today(self, habit: str) -> bool:
        """``True`` iff ``habit`` was marked done (or logged without
        a flag) today."""
        today = _today(self._clock)
        for date_str, done in self._iter(habit):
            if date_str == today and done is not False:
                return True
        return False

    def habits(self) -> list[str]:
        """Return the sorted list of distinct habit names seen."""
        seen: set[str] = set()
        for _date, habit, _done in self._iter_any():
            seen.add(habit)
        return sorted(seen)

    # ── Internals ───────────────────────────────────────────────────

    def _iter(self, habit: str) -> Iterable[tuple[str, bool | None]]:
        for date_str, name, done in self._iter_any():
            if name == habit:
                yield date_str, done

    def _iter_any(self) -> Iterable[tuple[str, str, bool | None]]:
        if not self._ledger_path.is_file():
            return iter(())
        out: list[tuple[str, str, bool | None]] = []
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                date = str(raw.get("date", ""))
                name = str(raw.get("habit", ""))
                if "done" in raw:
                    done: bool | None = bool(raw["done"])
                else:
                    done = True
                out.append((date, name, done))
        return iter(out)


# ── Helpers ────────────────────────────────────────────────────────────


def _today(clock_fn: Any) -> str:
    return _dt.date.fromtimestamp(clock_fn()).isoformat()


# ── Singleton ──────────────────────────────────────────────────────────


_tracker_singleton: HabitTracker | None = None


def get_habit_tracker() -> HabitTracker:
    """Return the process-wide :class:`HabitTracker`."""
    global _tracker_singleton
    if _tracker_singleton is None:
        _tracker_singleton = HabitTracker()
    return _tracker_singleton


def reset_habit_tracker_for_tests() -> None:  # pragma: no cover - test seam
    """Drop the cached singleton."""
    global _tracker_singleton
    _tracker_singleton = None