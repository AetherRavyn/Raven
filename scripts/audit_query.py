#!/usr/bin/env python3
"""Audit query CLI — Phase 5.3.

Tiny CLI over :class:`app.core.audit.AuditLog`.  Lets the operator
search the audit log from the shell:

    python scripts/audit_query.py --kind tool_call --since 1h
    python scripts/audit_query.py --actor orchestrator --risk high --limit 20
    python scripts/audit_query.py --failed-only --since 2024-01-01T00:00:00
    python scripts/audit_query.py --user u_abc123
    python scripts/audit_query.py --format json

The CLI is **read-only** and **side-effect free**.  It never modifies
the audit log.  All filters compose; missing filters mean "any".

Exit codes
----------
- 0  : query succeeded (even if 0 events matched)
- 1  : bad arguments
- 2  : audit log could not be opened / parsed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_since(s: str) -> datetime:
    """Parse a ``--since`` argument.

    Accepts:
      - ISO-8601 absolute (``2024-01-01T00:00:00``, with or without TZ)
      - Relative duration (``1h``, ``30m``, ``2d``, ``45s``)
    """
    s = s.strip()
    # Relative form
    if s and s[-1] in "smhd":
        try:
            n = int(s[:-1])
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"bad relative duration: {s!r}") from exc
        unit = s[-1]
        delta_args = {"s": n, "m": n * 60, "h": n * 3600, "d": n * 86400}
        return datetime.now(timezone.utc) - timedelta(seconds=delta_args[unit])
    # ISO form
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad ISO timestamp: {s!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="audit_query",
        description="Query the RAVEN audit log.",
    )
    p.add_argument("--kind", help="Filter by event kind (e.g. tool_call).")
    p.add_argument("--actor", help="Filter by actor (e.g. orchestrator).")
    p.add_argument("--action", help="Filter by action substring.")
    p.add_argument("--target", help="Filter by target.")
    p.add_argument("--user", help="Filter by user id (matches actor + context).")
    p.add_argument("--risk", help="Filter by risk level (low|medium|high|critical).")
    p.add_argument("--since", type=_parse_since, help="ISO-8601 or relative (1h, 30m, 2d).")
    p.add_argument("--until", type=_parse_since, help="ISO-8601 or relative.")
    p.add_argument("--search", help="Free-text search across actor/action/target/detail/context.")
    p.add_argument("--failed-only", action="store_true", help="Only events with success=False.")
    p.add_argument("--limit", type=int, default=50, help="Max events to return (default 50).")
    p.add_argument("--offset", type=int, default=0, help="Skip the first N events.")
    p.add_argument(
        "--format",
        choices=("json", "table", "ids"),
        default="table",
        help="Output format (default: table).",
    )
    p.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Override the audit log path (default: workspace/audit.log).",
    )
    return p.parse_args(argv)


def _format_row(e: Any) -> dict[str, Any]:
    return {
        "id": e.id,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "kind": e.kind.value if hasattr(e.kind, "value") else e.kind,
        "actor": e.actor,
        "action": e.action,
        "target": e.target,
        "risk": e.risk_level.value if hasattr(e.risk_level, "value") else e.risk_level,
        "success": e.success,
        "detail": e.detail,
    }


def _print_table(rows: list[dict[str, Any]], out) -> None:
    if not rows:
        print("(no events)", file=out)
        return
    cols = ("timestamp", "kind", "actor", "action", "risk", "success")
    widths = {c: max(len(c), *(len(str(r.get(c, "") or "")) for r in rows)) for c in cols}
    line = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    print(line, file=out)
    print(sep, file=out)
    for r in rows:
        print(
            " | ".join(str(r.get(c, "") or "").ljust(widths[c]) for c in cols),
            file=out,
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        from app.core.audit import AuditLog
    except Exception as exc:
        print(f"audit log module unavailable: {exc}", file=sys.stderr)
        return 2

    try:
        log = (
            AuditLog(jsonl_path=args.log_path)
            if args.log_path is not None
            else AuditLog()
        )
    except Exception as exc:
        print(f"could not open audit log: {exc}", file=sys.stderr)
        return 2

    # Resolve --user by ORing actor + free-text on context.user_id.
    actor = args.actor or args.user
    search = args.search
    if args.user and search is None:
        search = f'"user_id": "{args.user}"'

    success = False if args.failed_only else None

    try:
        events = log.query(
            kind=args.kind,
            actor=actor,
            action=args.action,
            target=args.target,
            risk_level=args.risk,
            since=args.since,
            until=args.until,
            search=search,
            success=success,
            limit=args.limit,
            offset=args.offset,
        )
    except Exception as exc:
        print(f"query failed: {exc}", file=sys.stderr)
        return 2

    rows = [_format_row(e) for e in events]

    if args.format == "json":
        print(json.dumps(rows, indent=2, default=str))
    elif args.format == "ids":
        for r in rows:
            print(r["id"])
    else:
        _print_table(rows, sys.stdout)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
