"""Quiet hours / DND logic.

A :class:`QuietHoursResolver` answers one question: *given a
signal and a time, should the engine mute it?*

It supports four sources of quiet:

* **User-set windows** — "no notifications 10pm–7am"
* **Learned windows** — auto-detected by the schedule learner
  ("user never replies after 11pm on weekdays")
* **Focus mode** — explicit "do not disturb" toggle
* **Calendar** — "user is in a meeting" (checked externally)

CRITICAL signals always pass through unless ``block_critical`` is
set on the user-set window.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Protocol

from app.core.proactive_core.types import (
    DecisionVerdict,
    ProactiveDecision,
    ProactiveSignal,
    QuietWindow,
    Urgency,
)

logger = logging.getLogger(__name__)


class CalendarProvider(Protocol):
    """Minimal interface the resolver needs from the calendar.

    The real implementation lives elsewhere (Google Calendar, CalDAV,
    etc.).  The protocol keeps this module testable.
    """

    def is_user_busy(self, user_id: str, at: datetime) -> bool:  # pragma: no cover
        ...


def _parse_window(window: QuietWindow) -> tuple[time, time]:
    return (
        time(window.start_hour, window.start_minute),
        time(window.end_hour, window.end_minute),
    )


def _time_in_window(now: time, start: time, end: time) -> bool:
    """True if ``now`` falls inside [start, end), supporting wraps past midnight."""
    if start <= end:
        return start <= now < end
    return now >= start or now < end


class QuietHoursResolver:
    """Decide whether a signal should be muted by quiet hours.

    The resolver is purely functional — no I/O.  Pass calendar state
    in via ``is_user_busy``; everything else is computed from the
    signal itself and the configured windows.
    """

    def __init__(
        self,
        *,
        user_windows: Iterable[QuietWindow] | None = None,
        learned_windows: Iterable[QuietWindow] | None = None,
        focus_mode: bool = False,
    ) -> None:
        self._user_windows: list[QuietWindow] = list(user_windows or [])
        self._learned_windows: list[QuietWindow] = list(learned_windows or [])
        self._focus_mode: bool = focus_mode

    def set_focus_mode(self, on: bool) -> None:
        self._focus_mode = on

    def add_user_window(self, window: QuietWindow) -> None:
        self._user_windows.append(window)

    def add_learned_window(self, window: QuietWindow) -> None:
        self._learned_windows.append(window)

    def is_in_quiet_window(self, now: datetime) -> tuple[bool, str]:
        """Return ``(in_quiet, label)``.

        ``label`` describes the first matching window (for audit).
        ``in_quiet`` is True if the user should be considered
        unavailable.
        """
        if self._focus_mode:
            return True, "focus_mode"

        local = now.timetz().replace(second=0, microsecond=0)
        now_t = time(local.hour, local.minute)

        for window in self._user_windows:
            start, end = _parse_window(window)
            if _time_in_window(now_t, start, end):
                return True, f"user:{window.label}"
        for window in self._learned_windows:
            start, end = _parse_window(window)
            if _time_in_window(now_t, start, end):
                return True, f"learned:{window.label}"
        return False, ""

    def evaluate(
        self,
        signal: ProactiveSignal,
        *,
        now: datetime | None = None,
        calendar: CalendarProvider | None = None,
    ) -> ProactiveDecision | None:
        """Return a DEFER decision if the signal should be muted, else None.

        CRITICAL signals always pass unless every active window
        explicitly blocks them with ``allow_critical=False``.
        """
        moment = now or datetime.now(tz=signal.created_at.tzinfo)

        # CRITICAL signals bypass quiet hours by default.
        if signal.urgency == Urgency.CRITICAL:
            all_block_critical = all(
                not w.allow_critical for w in (*self._user_windows, *self._learned_windows)
            )
            if not (all_block_critical and (self._user_windows or self._learned_windows)):
                return None

        in_quiet, label = self.is_in_quiet_window(moment)
        if not in_quiet and calendar is not None:
            try:
                if calendar.is_user_busy(signal.user_id, moment):
                    in_quiet = True
                    label = "calendar:busy"
            except Exception as exc:  # noqa: BLE001
                logger.debug("Calendar provider failed: %s", exc)

        if not in_quiet:
            return None

        # Defer until the next non-quiet moment.
        defer_until = self._next_awake(moment)
        return ProactiveDecision(
            signal=signal,
            verdict=DecisionVerdict.DEFER,
            stage="dnd",
            reason=f"quiet_hours:{label}",
            defer_until=defer_until,
        )

    def _next_awake(self, now: datetime) -> datetime:
        """Best-effort next moment when the user is awake.

        Walks forward in 15-minute steps (up to 24h) and returns the
        first time the user is *not* in any quiet window.  If we
        can't find one (e.g., permanent focus mode), returns
        ``now + 4h`` as a sensible fallback.
        """
        candidate = now
        for _ in range(96):  # 24h / 15min
            candidate = candidate + timedelta(minutes=15)
            in_quiet, _ = self.is_in_quiet_window(candidate)
            if not in_quiet:
                return candidate
        return now + timedelta(hours=4)
