"""Learning Tracker — Phase 4 (v10) — aggregate user learning profile.

A read-only analytics facade that joins two existing data sources:

1. **Skill inventory** — :class:`SkillLearner` writes one
   ``module.yaml`` per learned skill in ``skills/learned/<slug>/``.
   Each manifest records the skill's confidence, the count of
   invocations, and the rolling success rate.

2. **Tool-call history** — :class:`AuditLog` records every
   tool call with ``kind="tool_call"``, an ``action`` that names
   the tool, ``success``, ``duration_ms``, and a ``risk_level``.

The tracker does **no writes**.  It is a pure analytics layer
that the ambient loop and the orchestrator's ``/learned``
slash command both read from to surface a single coherent
view of "what the user has learned" and "what tools fail most
often" without each caller re-implementing the join.

API surface
-----------

* :meth:`compute_skill_profile` — per-skill
  (name, invocations, success_rate, confidence, last_invoked)
* :meth:`compute_tool_profile` — per-tool
  (name, call_count, success_rate, avg_duration_ms, failure_count)
* :meth:`compute_learning_velocity` — count of skills learned
  in the trailing ``window_days`` (default 30)
* :meth:`top_failure_modes` — most common
  ``(action, risk_level)`` combinations where ``success=False``
* :meth:`summary` — one :class:`LearningSummary` that composes
  the four above plus a generation timestamp

Failure modes are silent.  The audit log may be empty, the
skills directory may not exist, the project root may be
misconfigured.  None of these should ever raise — the tracker
is on the read path of the ambient loop and the slash-command
handler, and a crash would break both.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Result dataclasses ───────────────────────────────────────────────


@dataclass(slots=True)
class SkillRow:
    """One row in the skill profile."""

    name: str
    module_id: str
    confidence: float
    invocation_count: int
    success_rate: float
    last_invoked: str | None
    origin: str = "learned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module_id": self.module_id,
            "confidence": round(self.confidence, 3),
            "invocation_count": self.invocation_count,
            "success_rate": round(self.success_rate, 3),
            "last_invoked": self.last_invoked,
            "origin": self.origin,
        }


@dataclass(slots=True)
class ToolRow:
    """One row in the tool-call profile."""

    name: str
    call_count: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "call_count": self.call_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
        }


@dataclass(slots=True)
class FailurePattern:
    """One row in the top-failure-modes list."""

    action: str
    risk_level: str
    count: int
    last_seen: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "risk_level": self.risk_level,
            "count": self.count,
            "last_seen": self.last_seen,
        }


@dataclass(slots=True)
class LearningSummary:
    """Composite view returned by :meth:`LearningTracker.summary`."""

    generated_at: str
    project_root: str
    skill_count: int
    total_tool_calls: int
    overall_success_rate: float
    velocity_30d: int
    skills: list[SkillRow] = field(default_factory=list)
    tools: list[ToolRow] = field(default_factory=list)
    failure_modes: list[FailurePattern] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "project_root": self.project_root,
            "skill_count": self.skill_count,
            "total_tool_calls": self.total_tool_calls,
            "overall_success_rate": round(self.overall_success_rate, 3),
            "velocity_30d": self.velocity_30d,
            "skills": [s.to_dict() for s in self.skills],
            "tools": [t.to_dict() for t in self.tools],
            "failure_modes": [f.to_dict() for f in self.failure_modes],
        }

    def format_text(self) -> str:
        """One-screen, human-readable render for the /learned
        slash command and the ambient-loop audit log entry."""
        lines: list[str] = []
        lines.append(
            f"Learning summary ({self.skill_count} skills, "
            f"{self.total_tool_calls} tool calls, "
            f"{self.overall_success_rate * 100:.1f}% success)"
        )
        if self.skills:
            lines.append("")
            lines.append("Top skills:")
            for s in self.skills[:5]:
                lines.append(
                    f"  • {s.name} — invocations={s.invocation_count}, "
                    f"success={s.success_rate * 100:.0f}%, "
                    f"confidence={s.confidence:.2f}"
                )
        if self.tools:
            lines.append("")
            lines.append("Top tools:")
            for t in self.tools[:5]:
                lines.append(
                    f"  • {t.name} — calls={t.call_count}, "
                    f"success={t.success_rate * 100:.0f}%, "
                    f"avg={t.avg_duration_ms:.0f}ms"
                )
        if self.failure_modes:
            lines.append("")
            lines.append("Top failure modes:")
            for f in self.failure_modes[:3]:
                lines.append(
                    f"  • {f.action} ({f.risk_level}) — {f.count} failure(s)"
                )
        if not (self.skills or self.tools or self.failure_modes):
            lines.append("(no learning signals recorded yet)")
        return "\n".join(lines)


# ── Tracker ──────────────────────────────────────────────────────────


class LearningTracker:
    """Read-only analytics over the skill inventory and the
    audit log.

    The class is **stateless beyond configuration** — every
    compute method walks the underlying sources on demand.  This
    keeps the tracker cheap to construct and impossible to get
    "stale" — a real-time view is always returned.

    The audit log and skill learner are injected; the tracker
    tolerates ``None`` for either (in which case that source is
    treated as empty).
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        audit_log: Any = None,
        skill_learner: Any = None,
    ) -> None:
        if project_root is None:
            project_root = os.environ.get("RAVEN_PROJECT_ROOT")
        self._project_root = (
            Path(project_root).resolve() if project_root else _find_project_root()
        )
        self._learned_dir = self._project_root / "skills" / "learned"
        self._audit_log = audit_log
        self._skill_learner = skill_learner

    # ── Skill profile ────────────────────────────────────────────

    def compute_skill_profile(
        self, *, sort_by: str = "invocation_count",
    ) -> list[SkillRow]:
        """Return one row per learned skill.

        Reads ``skills/learned/<slug>/module.yaml`` directly so
        the tracker does not need a live :class:`SkillLearner`
        (the manifest is the canonical record).  Skills with
        ``invocation_count == 0`` and zero recorded invocations
        in their ``history.jsonl`` are filtered out — the user
        never used them, so they pollute the leaderboard.
        """
        rows: list[SkillRow] = []
        if not self._learned_dir.exists():
            return rows
        for skill_dir in sorted(self._learned_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "module.yaml"
            if not manifest_path.exists():
                continue
            try:
                import yaml

                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "LearningTracker: manifest read failed for %s — %s",
                    skill_dir, exc,
                )
                continue
            invocation_count = int(data.get("invocation_count", 0) or 0)
            success_rate = float(data.get("success_rate", 0.0) or 0.0)
            if invocation_count == 0:
                # Skip skills that have never been used — they
                # would otherwise dominate "by confidence" sorts
                # and look like progress the user hasn't felt.
                continue
            rows.append(
                SkillRow(
                    name=str(
                        data.get("display_name")
                        or data.get("name")
                        or skill_dir.name
                    ),
                    module_id=str(data.get("module_id") or skill_dir.name),
                    confidence=float(data.get("confidence", 0.0) or 0.0),
                    invocation_count=invocation_count,
                    success_rate=success_rate,
                    last_invoked=data.get("last_invoked"),
                    origin=str(data.get("origin", "learned")),
                )
            )
        rows.sort(
            key=lambda r: (
                -getattr(r, sort_by, r.invocation_count) if sort_by != "name"
                else r.name.lower()
            ),
        )
        return rows

    def compute_learning_velocity(self, *, window_days: int = 30) -> int:
        """Count skills whose manifest is newer than
        ``now - window_days``.

        Heuristic: a skill is "learned" within the window if its
        manifest has a ``learned_from`` field that parses as a
        timestamp and falls inside the window.  We do not rely
        on a separate registry file (none exists), and we do
        not look at file mtime because manifest writes
        (e.g. invocation counter updates) move mtime forward
        and would over-count.
        """
        if not self._learned_dir.exists():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        count = 0
        for skill_dir in self._learned_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "module.yaml"
            if not manifest_path.exists():
                continue
            try:
                import yaml

                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                continue
            learned_from = str(data.get("learned_from") or "")
            # The ``learned_from`` convention is
            # ``"<iso-timestamp> — <user-message-fragment>"``
            # per SkillLearner.save().
            ts_str = learned_from.split("—", 1)[0].strip()
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                count += 1
        return count

    # ── Tool profile ─────────────────────────────────────────────

    def compute_tool_profile(self) -> list[ToolRow]:
        """Aggregate audit events with ``kind="tool_call"`` into
        a per-tool leaderboard.

        The audit log is injected.  When it is ``None`` (or
        raises) we return an empty list — the tracker never
        breaks the caller on a missing source.
        """
        events = self._safe_tool_events()
        if not events:
            return []
        by_tool: dict[str, list[Any]] = {}
        for ev in events:
            name = _audit_event_name(ev)
            if not name:
                continue
            by_tool.setdefault(name, []).append(ev)

        rows: list[ToolRow] = []
        for name, evs in by_tool.items():
            total = len(evs)
            successes = sum(1 for e in evs if bool(getattr(e, "success", True)))
            failures = total - successes
            durations = [int(getattr(e, "duration_ms", 0) or 0) for e in evs]
            avg = sum(durations) / total if total else 0.0
            rows.append(
                ToolRow(
                    name=name,
                    call_count=total,
                    success_count=successes,
                    failure_count=failures,
                    success_rate=(successes / total) if total else 0.0,
                    avg_duration_ms=avg,
                )
            )
        rows.sort(key=lambda r: -r.call_count)
        return rows

    def top_failure_modes(self, *, top_n: int = 5) -> list[FailurePattern]:
        """Return the most common ``(action, risk_level)`` pairs
        among failing tool calls.

        The ``action`` field on a tool_call audit event names
        the tool.  We group by ``(action, risk_level)`` and
        order by descending count, breaking ties by most-recent
        timestamp.
        """
        events = self._safe_tool_events(success_only=False)
        if not events:
            return []
        # Group: (action, risk_level) -> list[timestamps]
        groups: dict[tuple[str, str], list[Any]] = {}
        for ev in events:
            if bool(getattr(ev, "success", True)):
                continue
            action = str(getattr(ev, "action", "") or "").strip()
            if not action:
                continue
            risk = _enum_str(getattr(ev, "risk_level", "low"))
            groups.setdefault((action, risk), []).append(ev)

        rows: list[FailurePattern] = []
        for (action, risk), evs in groups.items():
            ts_values: list[datetime] = []
            for e in evs:
                ts = getattr(e, "timestamp", None)
                if isinstance(ts, datetime):
                    ts_values.append(ts)
            last_seen = max(ts_values).isoformat() if ts_values else None
            rows.append(
                FailurePattern(
                    action=action,
                    risk_level=risk,
                    count=len(evs),
                    last_seen=last_seen,
                )
            )
        rows.sort(key=lambda r: (-r.count, r.last_seen or ""))
        return rows[:top_n]

    # ── Composite ────────────────────────────────────────────────

    def summary(
        self,
        *,
        top_skills: int = 10,
        top_tools: int = 10,
        top_failure_n: int = 5,
    ) -> LearningSummary:
        """Compose all four views into one :class:`LearningSummary`.

        ``overall_success_rate`` is the success rate across
        **all** tool-call audit events, not the mean of the
        per-tool rates (so a tool called once doesn't pull the
        average toward 1.0).
        """
        skills = self.compute_skill_profile()[:top_skills]
        tools = self.compute_tool_profile()[:top_tools]
        failure_modes = self.top_failure_modes(top_n=top_failure_n)
        events = self._safe_tool_events()
        total = len(events)
        successes = sum(1 for e in events if bool(getattr(e, "success", True)))
        overall_rate = (successes / total) if total else 0.0
        return LearningSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            project_root=str(self._project_root),
            skill_count=len(self.compute_skill_profile()),
            total_tool_calls=total,
            overall_success_rate=overall_rate,
            velocity_30d=self.compute_learning_velocity(window_days=30),
            skills=skills,
            tools=tools,
            failure_modes=failure_modes,
        )

    # ── Internals ────────────────────────────────────────────────

    def _safe_tool_events(self, *, success_only: bool = False) -> list[Any]:
        """Return audit events of kind ``tool_call``.

        Tolerates a missing or broken audit log by returning
        an empty list.  This is the one place the tracker is
        allowed to be defensive — the rest of the file is
        straightforward data munging.
        """
        if self._audit_log is None:
            return []
        try:
            events = self._audit_log.query(
                kind="tool_call",
                limit=10_000,
                newest_first=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LearningTracker: audit query failed — %s", exc)
            return []
        if not isinstance(events, list):
            return []
        return events


# ── Helpers ──────────────────────────────────────────────────────────


def _find_project_root() -> Path:
    """Walk up from this file looking for a directory that
    contains a ``skills/`` subdirectory.  Fall back to the
    current working directory."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "skills").is_dir():
            return parent
    return Path.cwd()


def _audit_event_name(ev: Any) -> str:
    """Pull a stable tool name out of an :class:`AuditEvent`.

    AuditEvent uses ``action`` for the tool name.  Some legacy
    events put the tool in ``target`` or ``metadata["tool"]``;
    we try those fallbacks in order.
    """
    action = str(getattr(ev, "action", "") or "").strip()
    if action:
        return action
    target = getattr(ev, "target", None)
    if target:
        return str(target).strip()
    metadata = getattr(ev, "metadata", None) or {}
    tool = metadata.get("tool")
    if tool:
        return str(tool).strip()
    return ""


def _enum_str(value: Any) -> str:
    """Best-effort string form for an enum-typed field."""
    if value is None:
        return "low"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


# ── Singleton ────────────────────────────────────────────────────────


_learning_tracker: LearningTracker | None = None


def get_learning_tracker(
    *,
    project_root: str | Path | None = None,
    audit_log: Any = None,
    skill_learner: Any = None,
) -> LearningTracker:
    """Return the process-wide :class:`LearningTracker`.

    The first call constructs the tracker.  Subsequent calls
    ignore the kwargs and return the cached instance.  Tests
    that need a fresh tracker call
    :func:`reset_learning_tracker_for_tests` between cases and
    patch the module-level ``get_learning_tracker`` to return
    their own instance.
    """
    global _learning_tracker
    if _learning_tracker is None:
        _learning_tracker = LearningTracker(
            project_root=project_root,
            audit_log=audit_log,
            skill_learner=skill_learner,
        )
    return _learning_tracker


def reset_learning_tracker_for_tests() -> None:  # pragma: no cover - seam
    """Drop the cached singleton."""
    global _learning_tracker
    _learning_tracker = None


__all__ = [
    "SkillRow",
    "ToolRow",
    "FailurePattern",
    "LearningSummary",
    "LearningTracker",
    "get_learning_tracker",
    "reset_learning_tracker_for_tests",
]
