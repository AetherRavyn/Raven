"""Dashboard formatters for the audit log (A4 — closing out the
``audit/dashboard.py`` deliverable in PLAN_v3.md).

Three concerns live here:

1. **Timeline** — render an event list as a one-line-per-row table
   suitable for a CLI or a single-page UI.
2. **CSV export** — flatten an event list into a CSV string an
   analyst can open in a spreadsheet.
3. **Stats** — count events by ``kind``, ``risk_level``, ``success``
   so the dashboard can show "12 denies today" without a full
   scan on every page load.

All functions are pure: they take event lists (or an
:class:`AuditLog`) and return strings/dicts.  No I/O.  No globals.
That makes them easy to test, easy to embed in a CLI, and easy to
call from a FastAPI route.

The module also exposes a small registry hook so callers can add
custom columns to the timeline and CSV outputs without forking
the formatters.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from app.core.audit.types import AuditEvent


# Default columns for timeline + CSV.  Override via ``columns=`` arg.
DEFAULT_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "kind",
    "actor",
    "action",
    "target",
    "risk_level",
    "success",
    "detail",
)


# ---------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------


@dataclass(slots=True)
class AuditStats:
    """Aggregate counts for the dashboard summary tile."""

    total: int = 0
    by_kind: dict[str, int] = None  # type: ignore[assignment]
    by_risk: dict[str, int] = None  # type: ignore[assignment]
    by_success: dict[str, int] = None  # type: ignore[assignment]
    by_actor: dict[str, int] = None  # type: ignore[assignment]
    duration_total_ms: int = 0
    cost_total_usd: float = 0.0
    since: str | None = None
    until: str | None = None

    def __post_init__(self) -> None:
        if self.by_kind is None:
            self.by_kind = {}
        if self.by_risk is None:
            self.by_risk = {}
        if self.by_success is None:
            self.by_success = {}
        if self.by_actor is None:
            self.by_actor = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_kind": dict(self.by_kind),
            "by_risk": dict(self.by_risk),
            "by_success": dict(self.by_success),
            "by_actor": dict(self.by_actor),
            "duration_total_ms": self.duration_total_ms,
            "cost_total_usd": self.cost_total_usd,
            "since": self.since,
            "until": self.until,
        }


def compute_stats(
    events: Iterable[AuditEvent],
    *,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> AuditStats:
    """Aggregate ``events`` into an :class:`AuditStats` summary.

    ``since`` / ``until`` are optional ISO-8601 strings or
    :class:`datetime` objects.  Events outside the range are
    skipped, and the bounds are echoed back in the result so the
    dashboard can show "stats for the last 24h" precisely.
    """
    s = _coerce_ts(since)
    u = _coerce_ts(until)
    stats = AuditStats(
        since=s.isoformat() if s else None,
        until=u.isoformat() if u else None,
    )
    for ev in events:
        if s and ev.timestamp < s:
            continue
        if u and ev.timestamp > u:
            continue
        stats.total += 1
        kind_key = _enum_value(ev.kind)
        stats.by_kind[kind_key] = stats.by_kind.get(kind_key, 0) + 1
        risk_key = _enum_value(ev.risk_level)
        stats.by_risk[risk_key] = stats.by_risk.get(risk_key, 0) + 1
        success_key = "success" if ev.success else "failure"
        stats.by_success[success_key] = (
            stats.by_success.get(success_key, 0) + 1
        )
        stats.by_actor[ev.actor] = stats.by_actor.get(ev.actor, 0) + 1
        stats.duration_total_ms += int(getattr(ev, "duration_ms", 0) or 0)
        stats.cost_total_usd += float(getattr(ev, "cost_usd", 0.0) or 0.0)
    return stats


# ---------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------


def format_timeline(
    events: Sequence[AuditEvent] | Iterable[AuditEvent],
    *,
    columns: Sequence[str] = DEFAULT_COLUMNS,
    max_rows: int | None = None,
) -> str:
    """Format ``events`` as a human-readable text table.

    Output looks like::

        2026-06-15T18:31:02Z  tool_call   u1      list_files /tmp     low     ok    attempt
        2026-06-15T18:31:03Z  policy      u1      rm        /etc/..  high    fail   deny (legacy): ...

    The function never raises; an empty event list returns an
    empty string.  Set ``max_rows`` to truncate long lists.
    """
    rows: list[AuditEvent] = list(events)
    if max_rows is not None:
        rows = rows[:max_rows]
    if not rows:
        return ""

    # Build column data + widths
    rendered: list[list[str]] = []
    for ev in rows:
        d = ev.to_dict()
        rendered.append([_render_cell(col, d) for col in columns])
    widths = [
        max(len(row[i]) for row in rendered) for i in range(len(columns))
    ]

    # Header
    header_cells = [c.upper().ljust(widths[i]) for i, c in enumerate(columns)]
    sep = "-" * (sum(widths) + 2 * (len(widths) - 1))
    out_lines: list[str] = [" | ".join(header_cells).rstrip(), sep]
    for row in rendered:
        cells = [row[i].ljust(widths[i]) for i in range(len(columns))]
        out_lines.append(" | ".join(cells).rstrip())
    return "\n".join(out_lines)


def _render_cell(column: str, data: Mapping[str, Any]) -> str:
    """Resolve a column name to a short, table-safe string."""
    if column not in data:
        return ""
    v = data[column]
    if v is None:
        return ""
    if isinstance(v, bool):
        return "ok" if v else "fail"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    s = str(v)
    # Strip ISO-8601 down to "YYYY-MM-DDTHH:MM:SSZ" for table density.
    if column == "timestamp" and len(s) >= 19:
        s = s[:19] + "Z"
    return s


# ---------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------


def format_csv(
    events: Sequence[AuditEvent] | Iterable[AuditEvent],
    *,
    columns: Sequence[str] = DEFAULT_COLUMNS,
    include_header: bool = True,
) -> str:
    """Serialize ``events`` as a CSV string.

    Nested dicts (``context``, ``metadata``) are flattened to
    JSON strings so the CSV remains a flat grid — analysts can
    split them out in a spreadsheet if needed.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    if include_header:
        writer.writerow(list(columns))
    for ev in events:
        d = ev.to_dict()
        row: list[str] = []
        for col in columns:
            v = d.get(col)
            if v is None:
                row.append("")
            elif isinstance(v, (dict, list)):
                row.append(json.dumps(v, default=str))
            elif isinstance(v, bool):
                row.append("true" if v else "false")
            else:
                row.append(str(v))
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------
# JSON export (for the dashboard's "download as JSON" button)
# ---------------------------------------------------------------------


def format_json(
    events: Sequence[AuditEvent] | Iterable[AuditEvent],
    *,
    indent: int | None = 2,
) -> str:
    """Serialize ``events`` as a JSON array.

    The output is always a list, never a wrapping object, so it
    can be piped straight into ``jq``.
    """
    payload = [ev.to_dict() for ev in events]
    return json.dumps(payload, indent=indent, default=str)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _coerce_ts(v: str | datetime | None) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = v.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _enum_value(v: Any) -> str:
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


__all__ = [
    "AuditStats",
    "DEFAULT_COLUMNS",
    "compute_stats",
    "format_timeline",
    "format_csv",
    "format_json",
]
