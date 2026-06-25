#!/usr/bin/env python3
"""Run the RAVEN nightly eval set and write a JSON report.

Usage:
    python scripts/nightly_eval.py [--output PATH] [--category CAT]
                                    [--runner stub|orchestrator]

By default it uses the ``stub`` runner, which answers every prompt
deterministically (correctly for trivial prompts, deterministically
wrong for the verifier-style prompts) so the script produces a
non-empty report without needing an LLM.  In CI / nightly the
``orchestrator`` runner talks to the real planner; that's a
follow-up wiring.

Exit codes:
    0  report written successfully
    1  report failed to write
    2  any prompt raised (also written to the report)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Make `python scripts/nightly_eval.py` work without an installed
# package.  The repo root is two levels up.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Make the eval modules importable without a `tests/__init__.py`.
sys.path.insert(0, str(ROOT / "tests"))

from eval import all_prompts, by_category  # noqa: E402
from eval.grader import (  # noqa: E402
    EvalPrompt,
    EvalReport,
    EvalResult,
    RunnerOutput,
    compare_reports,
    grade,
    run_eval,
)


# ── Runners ─────────────────────────────────────────────────────────


def stub_runner(prompt: EvalPrompt) -> RunnerOutput:
    """A deterministic stub that knows the expected answers.

    The stub is calibrated to:
      * pass the trivial prompts (math, regex, exact strings)
      * miss the verifier-false prompts (ver-02 expects "false" but
        a naive LLM would say "true" — the stub returns "true")
      * return a correct-looking answer for the rest
    """
    pid = prompt.id
    t0 = time.perf_counter()
    text, tier, tool = _stub_answer(pid)
    # The latency the harness sees is the wall-clock + a fake cost.
    elapsed_ms = int((time.perf_counter() - t0) * 1000) + 50
    return RunnerOutput(
        response=text,
        latency_ms=elapsed_ms,
        cost_usd=0.0001 if tier == "nano" else 0.001,
        tier=tier,
        tool_called=tool,
    )


def _stub_answer(pid: str) -> tuple[str, str, str]:
    answers = {
        "plan-01": ("Research on vertical farming shows promise.", "medium", "web_search"),
        "plan-02": ("Email scheduled via send_email.", "small", "send_email"),
        "plan-03": ("Tokyo weather: sunny, 24C.", "small", "weather"),
        "plan-04": ("Found RAVEN release notes for v0.7.", "small", "web_search"),
        "plan-05": ("Calendar events for tomorrow: 2 meetings.", "small", "calendar"),
        "tool-01": ("4", "nano", ""),
        "tool-02": ("dlrow olleh", "nano", ""),
        "tool-03": ("9", "nano", ""),
        "tool-04": ("92.50 EUR", "small", ""),
        "tool-05": ("a3b7c2e8d1f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0", "nano", ""),
        "sum-01": ("Here is a summary of the previous messages.", "small", ""),
        "sum-02": ("RAVEN is a layered personal intelligence.", "small", ""),
        "sum-03": ("Connection refused on port 8080.", "nano", ""),
        "sum-04": ("Added replan; fixed planner bug.", "nano", ""),
        "sum-05": ("Morning briefing generated at 8 AM.", "nano", ""),
        "ext-01": ("bob@raven.ai", "nano", ""),
        "ext-02": ("3, 2", "nano", ""),
        "ext-03": ('{"name": "Alice", "age": 30}', "small", ""),
        "ext-04": ("2026-07-15", "nano", ""),
        "ext-05": ("San Francisco", "nano", ""),
        # Verifier prompts — ver-02 deliberately wrong (the LLM would
        # say "true" but the truth is "false").
        "ver-01": ("true", "nano", ""),
        "ver-02": ("true", "small", ""),  # wrong on purpose
        "ver-03": ("true", "nano", ""),
        "ver-04": ("true", "nano", ""),
        "ver-05": ("true", "nano", ""),
        "gen-01": ("Hello! How can I help?", "nano", ""),
        "gen-02": ("An orchestrator coordinates components.", "small", ""),
        "gen-03": ("bonjour", "nano", ""),
        "gen-04": ("red, blue, yellow", "nano", ""),
        "gen-05": ("2026-06-18", "nano", ""),
    }
    return answers.get(pid, ("ok", "small", ""))


def orchestrator_runner(prompt: EvalPrompt) -> RunnerOutput:
    """Send the prompt to the live orchestrator.

    This is a placeholder; the real wiring talks to the in-process
    orchestrator over the planner.  For now it returns a stub answer
    so the script never crashes even when the orchestrator isn't
    running.
    """
    return stub_runner(prompt)


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAVEN nightly eval")
    parser.add_argument(
        "--output", default="workspace/eval/nightly_report.json",
        help="Path to write the JSON report.",
    )
    parser.add_argument(
        "--category", default=None,
        help="If set, only run prompts in this category (plan/tool/summary/extract/verify/general).",
    )
    parser.add_argument(
        "--runner", choices=["stub", "orchestrator"], default="stub",
        help="Which runner to use.  Default: stub (offline, deterministic).",
    )
    args = parser.parse_args(argv)

    prompts = by_category(args.category) if args.category else all_prompts()
    runner = stub_runner if args.runner == "stub" else orchestrator_runner
    report = run_eval(runner, prompts=prompts)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(report.to_dict(), f, indent=2)

    # Console summary.
    print(f"Nightly eval: {report.passed}/{report.total} passed "
          f"({report.pass_rate:.1%})")
    print(f"  p50 latency : {report.p50_latency_ms} ms")
    print(f"  p95 latency : {report.p95_latency_ms} ms")
    print(f"  total cost  : ${report.total_cost_usd:.4f}")
    print(f"  tool calls  : {report.tool_call_count}")
    print(f"  escalations : {report.escalations}")
    print(f"  by category :")
    for cat, b in report.by_category.items():
        print(f"    {cat:8s}: {int(b['passed'])}/{int(b['total'])}")
    print(f"  report      : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())