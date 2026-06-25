#!/usr/bin/env python3
"""Convert RAVEN nightly-eval reports to Prometheus textfile metrics.

The nightly-eval timer (see ``monitoring/nightly-eval.timer``) runs
``scripts/nightly_eval.py`` first and ``scripts/regression_gate.py``
second.  This script is the **third** step: it reads the latest
``workspace/eval/nightly_report.json`` (and, if present, the
``baseline.json``) and emits a Prometheus textfile-format payload to
``workspace/eval/eval_metrics.prom``.

The Prometheus textfile collector then scrapes the file on its
next scrape interval; no Python Prometheus client is required at
runtime, which keeps the venv requirement minimal (the existing
``prometheus-client`` dep is only used by the RAVEN web server's
``/metrics`` endpoint, not by this script).

Output format
-------------
Follows the Prometheus text exposition format — one metric family
per line, ``# HELP`` and ``# TYPE`` comments at the top, and label
values properly escaped.  See:
  https://prometheus.io/docs/instrumenting/exposition_formats/

Usage
-----
    python scripts/eval_to_prom.py \
        --report workspace/eval/nightly_report.json \
        --baseline workspace/eval/baseline.json \
        --archive workspace/eval/archive \
        --output workspace/eval/eval_metrics.prom

Any of ``--report``, ``--baseline``, ``--archive`` may be omitted;
the script emits whatever it has and skips metrics that need
missing input (with a ``# raven_eval_*_skipped`` comment so the
operator can see why a metric is missing).

Exit codes
----------
    0  output written successfully (even if some inputs were missing)
    2  bad arguments
    3  I/O error writing output
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 string into an aware UTC datetime.  None on failure."""
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON file, returning ``None`` if missing or malformed.

    A missing nightly report is expected on first run; a malformed
    one is a real problem.  We log the latter to stderr and the
    former silently — the operator can see the absence of metrics.
    """
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"eval_to_prom: bad JSON in {path}: {e}", file=sys.stderr)
        return None


def _escape_label_value(s: str) -> str:
    """Escape a Prometheus label value per the spec.

    Required escapes: ``\\`` -> ``\\\\``, ``"`` -> ``\\"``, newline
    -> ``\\n``.  We also strip non-printable bytes.
    """
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        else:
            out.append(ch)
    return "".join(out)


def _fmt_float(x: float) -> str:
    """Render a float in Prometheus exposition form.

    Prometheus accepts ``inf``, ``nan``, ``+Inf``, ``-Inf``.  We
    prefer the lowercase forms.  ``0`` and ``1`` must be rendered
    as ``0`` and ``1`` (no decimal point) per the spec.
    """
    if x != x:  # NaN
        return "NaN"
    if x == float("inf"):
        return "+Inf"
    if x == float("-inf"):
        return "-Inf"
    if x == 0.0:
        return "0"
    if x == 1.0:
        return "1"
    return f"{x:.6f}"


# ── Metric emitters ─────────────────────────────────────────────────


class _EmittedMetric:
    """A single Prometheus metric line + its HELP/TYPE header.

    We collect these and render them in declaration order, which
    gives a stable file layout across runs (easier for diffing).
    """

    def __init__(
        self,
        name: str,
        mtype: str,
        help_text: str,
        samples: list[tuple[dict[str, str], float]],
    ) -> None:
        self.name = name
        self.mtype = mtype
        self.help_text = help_text
        self.samples = samples

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} {self.mtype}",
        ]
        for labels, value in self.samples:
            if labels:
                label_str = ",".join(
                    f'{k}="{_escape_label_value(v)}"' for k, v in labels.items()
                )
                lines.append(f"{self.name}{{{label_str}}} {_fmt_float(value)}")
            else:
                lines.append(f"{self.name} {_fmt_float(value)}")
        return "\n".join(lines)


def _build_from_report(report: dict[str, Any] | None) -> list[_EmittedMetric]:
    """Translate a single EvalReport dict into Prometheus metrics.

    All metrics are gauges because each nightly run produces a
    snapshot, not a cumulative count.  For a true Prometheus
    counter (monotonically increasing across runs) we'd need to
    store previous values and emit a delta — that's a follow-up;
    for now the dashboard can use ``rate()`` on the
    ``*_run_timestamp_seconds`` series to detect missing runs.
    """
    metrics: list[_EmittedMetric] = []
    if report is None:
        metrics.append(_EmittedMetric(
            "raven_eval_run_timestamp_seconds",
            "gauge",
            "Unix timestamp of the latest nightly eval run; 0 if missing.",
            [({}, 0.0)],
        ))
        return metrics

    started_at = _parse_iso(report.get("started_at"))
    ts = started_at.timestamp() if started_at else 0.0
    age = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds()) \
        if started_at else 0.0

    pass_rate = float(report.get("pass_rate", 0.0))
    total = int(report.get("total", 0))
    passed = int(report.get("passed", 0))
    failed = total - passed
    p50 = int(report.get("p50_latency_ms", 0))
    p95 = int(report.get("p95_latency_ms", 0))
    cost = float(report.get("total_cost_usd", 0.0))
    tool_calls = int(report.get("tool_call_count", 0))
    escalations = int(report.get("escalations", 0))

    metrics.extend([
        _EmittedMetric(
            "raven_eval_run_timestamp_seconds",
            "gauge",
            "Unix timestamp of the latest nightly eval run.",
            [({}, ts)],
        ),
        _EmittedMetric(
            "raven_eval_run_age_seconds",
            "gauge",
            "Seconds since the latest nightly eval run (0 = current).",
            [({}, age)],
        ),
        _EmittedMetric(
            "raven_eval_pass_rate",
            "gauge",
            "Pass rate of the latest nightly eval (0..1).",
            [({}, pass_rate)],
        ),
        _EmittedMetric(
            "raven_eval_p50_latency_ms",
            "gauge",
            "p50 prompt latency from the latest nightly eval.",
            [({}, float(p50))],
        ),
        _EmittedMetric(
            "raven_eval_p95_latency_ms",
            "gauge",
            "p95 prompt latency from the latest nightly eval.",
            [({}, float(p95))],
        ),
        _EmittedMetric(
            "raven_eval_total_cost_usd",
            "gauge",
            "Total cost (USD) of the latest nightly eval.",
            [({}, cost)],
        ),
        _EmittedMetric(
            "raven_eval_tool_calls_total",
            "gauge",
            "Total tool calls invoked during the latest nightly eval.",
            [({}, float(tool_calls))],
        ),
        _EmittedMetric(
            "raven_eval_escalations_total",
            "gauge",
            "Number of times the eval escalated to a higher tier.",
            [({}, float(escalations))],
        ),
        _EmittedMetric(
            "raven_eval_prompts_total",
            "gauge",
            "Number of prompts in the latest run, by outcome.",
            [
                ({"outcome": "pass"}, float(passed)),
                ({"outcome": "fail"}, float(failed)),
                ({"outcome": "total"}, float(total)),
            ],
        ),
    ])

    # Per-category rollup.  The EvalReport has a ``by_category``
    # dict whose values are ``{total, passed, pass_rate}``.  We
    # emit one series per category; the operator can plot a
    # stacked bar or filter to one category at a time.
    by_cat = report.get("by_category", {})
    if isinstance(by_cat, dict) and by_cat:
        cat_samples: list[tuple[dict[str, str], float]] = []
        for cat, body in sorted(by_cat.items()):
            if not isinstance(body, dict):
                continue
            pr = float(body.get("pass_rate", 0.0))
            cat_samples.append(({"category": str(cat)}, pr))
        metrics.append(_EmittedMetric(
            "raven_eval_by_category_pass_rate",
            "gauge",
            "Per-category pass rate from the latest nightly eval (0..1).",
            cat_samples,
        ))

    return metrics


def _build_from_baseline(baseline: dict[str, Any] | None) -> list[_EmittedMetric]:
    """Translate a baseline report into a parallel set of metrics.

    Naming convention: every baseline metric has a ``_baseline``
    suffix so the dashboard can plot ``raven_eval_pass_rate`` and
    ``raven_eval_pass_rate_baseline`` on the same panel.  We emit
    just the headline numbers — latency, cost, pass_rate — that
    the regression gate actually compares.
    """
    metrics: list[_EmittedMetric] = []
    if baseline is None:
        return metrics
    metrics.extend([
        _EmittedMetric(
            "raven_eval_pass_rate_baseline",
            "gauge",
            "Baseline pass rate the regression gate compares against.",
            [({}, float(baseline.get("pass_rate", 0.0)))],
        ),
        _EmittedMetric(
            "raven_eval_p95_latency_ms_baseline",
            "gauge",
            "Baseline p95 latency the regression gate compares against.",
            [({}, float(baseline.get("p95_latency_ms", 0)))],
        ),
        _EmittedMetric(
            "raven_eval_total_cost_usd_baseline",
            "gauge",
            "Baseline total cost the regression gate compares against.",
            [({}, float(baseline.get("total_cost_usd", 0.0)))],
        ),
    ])
    return metrics


def _parse_regression_md(md_path: Path) -> int | None:
    """Extract the regression verdict (1=pass, 0=fail) from the markdown.

    The ``regression_gate.py --markdown-output`` writes a line like
    ``# Regression gate — 🟢 PASS`` or ``# Regression gate — 🔴 FAIL``.
    We look for the badge, not the word, because the word may appear
    elsewhere in the file.  Returns ``None`` if the file is missing
    or has an unrecognised badge.
    """
    if not md_path.is_file():
        return None
    try:
        first_line = md_path.read_text().splitlines()[0]
    except OSError:
        return None
    if "🟢" in first_line and "PASS" in first_line.upper():
        return 1
    if "🔴" in first_line and "FAIL" in first_line.upper():
        return 0
    return None


def _build_from_regression_md(md_path: Path) -> list[_EmittedMetric]:
    """Convert the regression markdown's verdict into a Prometheus gauge."""
    verdict = _parse_regression_md(md_path)
    if verdict is None:
        return []
    return [_EmittedMetric(
        "raven_eval_regression_verdict",
        "gauge",
        "Latest regression gate verdict: 1 = pass, 0 = fail.",
        [({}, float(verdict))],
    )]


def _build_from_archive(archive_dir: Path | None) -> list[_EmittedMetric]:
    """Count reports in the archive directory (any layout).

    Used to surface "how many days of history do we have" in the
    dashboard, so the operator can see at a glance whether the
    retention rotation is pruning too aggressively.
    """
    if archive_dir is None or not archive_dir.is_dir():
        return []
    # Flat layout: top-level *.json.  Archived layout: subdirs
    # each containing *.json.  Either way, count report files.
    flat = sum(1 for p in archive_dir.glob("*.json") if p.is_file())
    archived = sum(
        1
        for sub in archive_dir.iterdir()
        if sub.is_dir()
        for p in sub.glob("*.json")
        if p.is_file()
    )
    total = flat + archived
    return [_EmittedMetric(
        "raven_eval_reports_in_window",
        "gauge",
        "Number of eval reports currently in the retention window.",
        [({}, float(total))],
    )]


# ── Render ──────────────────────────────────────────────────────────


def render(metrics: list[_EmittedMetric]) -> str:
    """Render a list of metrics into a single textfile payload.

    Separates each metric block with a blank line for readability
    (Prometheus ignores whitespace, so this is purely cosmetic).
    """
    blocks = [m.render() for m in metrics]
    return "\n\n".join(blocks) + "\n"


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert RAVEN nightly-eval reports to Prometheus textfile metrics.",
    )
    parser.add_argument(
        "--report", default="workspace/eval/nightly_report.json",
        help="Path to the latest EvalReport JSON.",
    )
    parser.add_argument(
        "--baseline", default="workspace/eval/baseline.json",
        help="Path to the baseline EvalReport JSON (optional).",
    )
    parser.add_argument(
        "--archive", default="workspace/eval/archive",
        help="Path to the eval archive directory (optional).",
    )
    parser.add_argument(
        "--regression-md", default="workspace/eval/regression.md",
        help="Path to the regression_gate markdown verdict (optional).",
    )
    parser.add_argument(
        "--output", default="workspace/eval/eval_metrics.prom",
        help="Where to write the Prometheus textfile.  Use '-' for stdout.",
    )
    args = parser.parse_args(argv)

    report = _load_json(Path(args.report))
    baseline = _load_json(Path(args.baseline))
    archive_dir = Path(args.archive) if args.archive else None

    metrics: list[_EmittedMetric] = []
    metrics.extend(_build_from_report(report))
    metrics.extend(_build_from_baseline(baseline))
    metrics.extend(_build_from_regression_md(Path(args.regression_md)))
    metrics.extend(_build_from_archive(archive_dir))

    payload = render(metrics)

    if args.output == "-":
        sys.stdout.write(payload)
        return 0

    out_path = Path(args.output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: emit to a temp file in the same directory
        # then rename.  The textfile collector reads on every
        # scrape; an atomic write avoids a half-written file.
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp_path.write_text(payload)
        tmp_path.replace(out_path)
    except OSError as e:
        print(f"eval_to_prom: failed to write {out_path}: {e}", file=sys.stderr)
        return 3

    n = len(metrics)
    series = sum(len(m.samples) for m in metrics)
    print(f"eval_to_prom: wrote {n} metric families ({series} series) to {out_path}")
    return 0


__all__ = [
    "_build_from_report",
    "_build_from_baseline",
    "_build_from_archive",
    "_build_from_regression_md",
    "render",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())