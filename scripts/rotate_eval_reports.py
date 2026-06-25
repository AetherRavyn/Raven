#!/usr/bin/env python3
"""Retention rotation for RAVEN nightly-eval reports.

The nightly-eval systemd timer drops a fresh ``nightly_report.json``
into ``workspace/eval/`` every morning.  That file is the *current*
half of the regression-gate comparison.  Older reports are useful
for trend analysis and post-mortems, but if we never prune them
``workspace/eval/`` grows without bound.

This script prunes reports older than a configurable retention window
(default: 14 days).  Two directory layouts are supported:

  1. **Flat** — a single directory of ``*.json`` files, each
     containing a top-level ``started_at`` ISO-8601 timestamp.  The
     script deletes any file whose ``started_at`` is older than
     ``--keep-days`` ago.
  2. **Archived** — the timer's recommended layout is to mirror
     finished reports into ``workspace/eval/archive/YYYY-MM-DD/`` so
     every night's bundle is in its own subdirectory.  The script
     recurses one level and deletes whole day-buckets whose newest
     ``*.json`` is older than the retention window.

The script is **pure stdlib** (no RAVEN imports) so the systemd unit
can invoke it before any venv activation.

Usage
-----
    python scripts/rotate_eval_reports.py --dir PATH [--keep-days N]
                                          [--dry-run] [--verbose]

Exit codes
----------
    0  rotation complete (some files may or may not have been pruned)
    2  bad input (missing directory, bad --keep-days)
    3  I/O error during prune (a partial run is still better than
       a hard failure that stops the timer)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Accepts both ``+00:00`` and trailing ``Z`` forms.  Returns
    ``None`` on any parse failure so the caller can decide whether
    a malformed report is prune-worthy or not (we never delete
    reports we can't read — we'd rather keep a corrupt one for
    a human to inspect than silently lose it).
    """
    if not isinstance(ts, str) or not ts:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Treat naive timestamps as UTC; the nightly_eval script
        # always emits aware timestamps, but if a hand-written
        # fixture used a naive one we'd rather guess than drop it.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _report_started_at(path: Path) -> datetime | None:
    """Read ``started_at`` from a nightly-report JSON file.

    Returns ``None`` if the file can't be read, isn't JSON, or
    lacks a parseable ``started_at``.  None is a *preserve*
    signal, not a *prune* signal — the caller keeps it.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    ts = data.get("started_at")
    return _parse_iso(ts) if isinstance(ts, str) else None


def _newest_report_mtime(dir_path: Path) -> tuple[datetime | None, list[Path]]:
    """Return the newest ``started_at`` across all JSON files in dir.

    Also returns the list of JSON files considered so the caller can
    report what would be removed.  Returns ``(None, [])`` for an
    empty / unreadable directory.
    """
    jsons = sorted(p for p in dir_path.glob("*.json") if p.is_file())
    newest: datetime | None = None
    for p in jsons:
        ts = _report_started_at(p)
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
    return newest, jsons


# ── Rotation logic ──────────────────────────────────────────────────


def _select_too_old_flat(
    files: Iterable[Path],
    *,
    cutoff: datetime,
    now: datetime,
) -> list[Path]:
    """Flat layout: prune files whose started_at < cutoff."""
    out: list[Path] = []
    for p in files:
        ts = _report_started_at(p)
        if ts is not None and ts < cutoff:
            out.append(p)
    return out


def _select_too_old_archived(
    root: Path,
    *,
    cutoff: datetime,
) -> list[Path]:
    """Archived layout: prune day-buckets whose newest report is old.

    ``root/archive/2026-06-12/nightly_report.json`` — the day-bucket
    is ``2026-06-12/``; we drop the whole bucket only when its
    newest report is older than the cutoff.
    """
    out: list[Path] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        newest, _ = _newest_report_mtime(sub)
        if newest is None:
            # Bucket has no parseable reports.  Preserve it; a
            # human can inspect later.
            continue
        if newest < cutoff:
            out.append(sub)
    return out


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune RAVEN nightly-eval reports older than N days.",
    )
    parser.add_argument(
        "--dir", required=True,
        help="Directory of nightly-report JSON files (flat or archive/YYYY-MM-DD/).",
    )
    parser.add_argument(
        "--keep-days", type=int, default=14,
        help="Retention window in days.  Default: 14.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be removed, but don't delete.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print every file considered, not just the ones pruned.",
    )
    args = parser.parse_args(argv)

    if args.keep_days < 0:
        print(f"rotate_eval_reports: --keep-days must be >= 0, got {args.keep_days}", file=sys.stderr)
        return 2

    root = Path(args.dir)
    if not root.is_dir():
        print(f"rotate_eval_reports: not a directory: {root}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.keep_days)

    # Decide layout.  An "archived" directory has only subdirectories
    # (no top-level JSONs); a "flat" directory has top-level JSONs.
    has_subdirs = any(p.is_dir() for p in root.iterdir())
    has_top_jsons = any(p.suffix == ".json" for p in root.iterdir() if p.is_file())

    to_prune: list[Path] = []
    layout = "flat"
    if has_subdirs and not has_top_jsons:
        layout = "archived"
        to_prune = _select_too_old_archived(root, cutoff=cutoff)
    else:
        flat_files = [p for p in root.glob("*.json") if p.is_file()]
        to_prune = _select_too_old_flat(flat_files, cutoff=cutoff, now=now)

    if args.verbose:
        print(f"rotate_eval_reports: layout={layout} cutoff={cutoff.isoformat()} now={now.isoformat()}")
        if layout == "flat":
            for p in sorted(root.glob("*.json")):
                print(f"  consider: {p}")
        else:
            for sub in sorted(root.iterdir()):
                if sub.is_dir():
                    print(f"  consider: {sub}/")

    if not to_prune:
        print(f"rotate_eval_reports: nothing to prune (cutoff={cutoff.date()}, layout={layout})")
        return 0

    print(f"rotate_eval_reports: pruning {len(to_prune)} item(s) older than {cutoff.date()} (layout={layout}):")
    for p in to_prune:
        print(f"  - {p}")

    if args.dry_run:
        print("rotate_eval_reports: dry-run, no files removed")
        return 0

    # Best-effort delete.  A single permission error shouldn't stop
    # the rotation; we log and continue.
    failures = 0
    for p in to_prune:
        try:
            if p.is_dir():
                # Recursive delete; for an archive day-bucket with
                # only a handful of JSONs the depth is shallow.
                for child in sorted(p.rglob("*")):
                    if child.is_file():
                        child.unlink()
                p.rmdir()
            else:
                p.unlink()
        except OSError as e:
            print(f"rotate_eval_reports: failed to remove {p}: {e}", file=sys.stderr)
            failures += 1

    if failures:
        # Partial run.  Exit 3 so the timer sees a non-zero but
        # doesn't silently swallow the issue.
        print(f"rotate_eval_reports: {failures} item(s) failed to remove", file=sys.stderr)
        return 3
    return 0


__all__ = [
    "_parse_iso",
    "_report_started_at",
    "_newest_report_mtime",
    "_select_too_old_flat",
    "_select_too_old_archived",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
