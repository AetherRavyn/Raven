#!/usr/bin/env python3
"""Regression gate for the RAVEN nightly eval.

Compares a current eval report against a baseline and fails if:
  * pass rate drops more than 5 percentage points (0.05), or
  * p95 latency rises more than 20% of the baseline.

Usage:
    python scripts/regression_gate.py --baseline PATH --current PATH
                                       [--markdown-output PATH]

Exit codes:
    0  no regression
    1  regression detected
    2  bad input (missing file, malformed JSON)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from eval.grader import compare_reports  # noqa: E402


def _load_report(path: Path) -> dict:
    if not path.exists():
        print(f"regression_gate: file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"regression_gate: bad JSON in {path}: {e}", file=sys.stderr)
        raise SystemExit(2)


def _report_from_dict(d: dict):
    # ``compare_reports`` expects EvalReport objects but only reads
    # the four scalar fields (pass_rate, p95_latency_ms, total_cost_usd).
    # A small shim saves us the round-trip through the dataclass.
    class _Shim:
        pass
    s = _Shim()
    s.pass_rate = d.get("pass_rate", 0.0)
    s.p95_latency_ms = d.get("p95_latency_ms", 0)
    s.total_cost_usd = d.get("total_cost_usd", 0.0)
    s.total = d.get("total", 0)
    s.passed = d.get("passed", 0)
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAVEN eval regression gate"
    )
    parser.add_argument(
        "--baseline", required=True,
        help="Path to the baseline JSON report.",
    )
    parser.add_argument(
        "--current", required=True,
        help="Path to the current JSON report.",
    )
    parser.add_argument(
        "--markdown-output", default=None,
        help="If set, write a markdown summary to this path.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Also fail on cost increase > 50% (default: cost is advisory).",
    )
    args = parser.parse_args(argv)

    base = _load_report(Path(args.baseline))
    curr = _load_report(Path(args.current))
    base_obj = _report_from_dict(base)
    curr_obj = _report_from_dict(curr)
    verdict = compare_reports(base_obj, curr_obj)

    # Optionally add a cost-spike rule.
    cost_ratio = (
        verdict["cost_delta"] / base["total_cost_usd"]
        if base["total_cost_usd"] > 0 else 0.0
    )
    if args.strict and cost_ratio > 0.50:
        verdict["reasons"].append(
            f"cost_spike: {cost_ratio:+.1%} (strict threshold +50%)"
        )
        verdict["verdict"] = "fail"

    # Console summary.
    print(f"Regression gate: {verdict['verdict'].upper()}")
    print(f"  baseline: {base['passed']}/{base['total']} passed "
          f"({base['pass_rate']:.1%}), p95={base['p95_latency_ms']}ms, "
          f"${base['total_cost_usd']:.4f}")
    print(f"  current : {curr['passed']}/{curr['total']} passed "
          f"({curr['pass_rate']:.1%}), p95={curr['p95_latency_ms']}ms, "
          f"${curr['total_cost_usd']:.4f}")
    print(f"  Δ pass  : {verdict['pass_rate_delta']:+.3f}")
    print(f"  Δ p95   : {verdict['p95_latency_ratio']:+.1%} "
          f"({verdict['p95_latency_delta']:+d}ms)")
    print(f"  Δ cost  : {verdict['cost_delta']:+.4f} ({cost_ratio:+.1%})")
    if verdict["reasons"]:
        print("  reasons :")
        for r in verdict["reasons"]:
            print(f"    - {r}")

    if args.markdown_output:
        md_path = Path(args.markdown_output)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(_render_markdown(base, curr, verdict, cost_ratio))

    return 1 if verdict["verdict"] == "fail" else 0


def _render_markdown(base: dict, curr: dict, verdict: dict, cost_ratio: float) -> str:
    badge = "🟢 PASS" if verdict["verdict"] == "pass" else "🔴 FAIL"
    lines = [
        f"# Regression gate — {badge}",
        "",
        f"- Baseline: **{base['passed']}/{base['total']}** passed "
        f"({base['pass_rate']:.1%}), p95 {base['p95_latency_ms']}ms, "
        f"${base['total_cost_usd']:.4f}",
        f"- Current:  **{curr['passed']}/{curr['total']}** passed "
        f"({curr['pass_rate']:.1%}), p95 {curr['p95_latency_ms']}ms, "
        f"${curr['total_cost_usd']:.4f}",
        "",
        "| Metric       | Δ                |",
        "|--------------|------------------|",
        f"| Pass rate    | {verdict['pass_rate_delta']:+.3f}        |",
        f"| p95 latency  | {verdict['p95_latency_ratio']:+.1%} "
        f"({verdict['p95_latency_delta']:+d}ms) |",
        f"| Cost         | {cost_ratio:+.1%}           |",
        "",
    ]
    if verdict["reasons"]:
        lines.append("## Reasons")
        lines.append("")
        for r in verdict["reasons"]:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
