"""Eval grader + harness.

The grader is the pure function that scores a single (prompt, response)
pair against an :class:`EvalPrompt` expectation.  It is intentionally
deterministic and offline — no LLM, no I/O — so the nightly eval and
the regression gate can compare numbers without flakes.

The harness wraps the grader with timing + cost tracking + structured
:mod:`EvalResult` records.  Callers feed it a list of completed
``(prompt, response, latency_ms, cost_usd, tier, tool_called)`` tuples
and the harness returns the aggregate report.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

try:
    from tests.eval import EvalPrompt, ExpectKind, PROMPTS, all_prompts  # type: ignore[import-not-found]
except ModuleNotFoundError:
    # Loaded as a top-level module (e.g. when scripts/nightly_eval.py
    # adds tests/ to sys.path).
    from eval import EvalPrompt, ExpectKind, PROMPTS, all_prompts  # type: ignore[no-redef]


@dataclass(slots=True)
class EvalResult:
    """The score for one prompt."""

    id: str
    passed: bool
    score: float  # 0..1; 1.0 = full match, 0.5 = partial, 0.0 = miss
    reason: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    tier: str = ""
    tool_called: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "passed": self.passed,
            "score": self.score,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "tier": self.tier,
            "tool_called": self.tool_called,
        }


@dataclass(slots=True)
class EvalReport:
    """Aggregate report from running a set of prompts."""

    started_at: str = ""
    finished_at: str = ""
    pass_rate: float = 0.0
    total: int = 0
    passed: int = 0
    failed: int = 0
    p50_latency_ms: int = 0
    p95_latency_ms: int = 0
    total_cost_usd: float = 0.0
    avg_cost_usd: float = 0.0
    tool_call_count: int = 0
    escalations: int = 0
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pass_rate": self.pass_rate,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "total_cost_usd": self.total_cost_usd,
            "avg_cost_usd": self.avg_cost_usd,
            "tool_call_count": self.tool_call_count,
            "escalations": self.escalations,
            "by_category": dict(self.by_category),
            "results": [r.to_dict() for r in self.results],
        }


# ── Grading primitives ──────────────────────────────────────────────


def grade(prompt: EvalPrompt, response: str) -> EvalResult:
    """Score one (prompt, response) pair.

    Returns an :class:`EvalResult` with ``passed`` and ``score`` set.
    Latency / cost / tier are 0/empty; the harness fills them in.
    """
    if response is None:
        return EvalResult(
            id=prompt.id, passed=False, score=0.0, reason="no_response"
        )
    text = str(response)
    kind = prompt.expect

    if kind is ExpectKind.EXACT:
        passed = text.strip() == prompt.needle.strip()
        return EvalResult(
            id=prompt.id, passed=passed, score=1.0 if passed else 0.0,
            reason="exact_match" if passed else "exact_mismatch",
        )

    if kind is ExpectKind.SUBSTRING:
        hit = prompt.needle.lower() in text.lower()
        return EvalResult(
            id=prompt.id, passed=hit, score=1.0 if hit else 0.0,
            reason="substring_hit" if hit else "substring_miss",
        )

    if kind is ExpectKind.REGEX:
        try:
            m = re.search(prompt.needle, text, flags=re.MULTILINE)
        except re.error as e:
            return EvalResult(
                id=prompt.id, passed=False, score=0.0,
                reason=f"regex_error: {e}",
            )
        passed = m is not None
        return EvalResult(
            id=prompt.id, passed=passed,
            score=1.0 if passed else 0.0,
            reason="regex_hit" if passed else "regex_miss",
        )

    if kind is ExpectKind.JSON:
        # The response must parse as JSON and contain the required keys.
        try:
            obj = json.loads(text)
        except (ValueError, TypeError) as e:
            return EvalResult(
                id=prompt.id, passed=False, score=0.0,
                reason=f"json_parse_error: {e}",
            )
        if not isinstance(obj, dict):
            return EvalResult(
                id=prompt.id, passed=False, score=0.0,
                reason="json_not_object",
            )
        missing = [k for k in prompt.json_keys if k not in obj]
        if missing:
            return EvalResult(
                id=prompt.id, passed=False, score=0.5,
                reason=f"missing_keys: {missing}",
            )
        return EvalResult(
            id=prompt.id, passed=True, score=1.0,
            reason="json_valid",
        )

    return EvalResult(
        id=prompt.id, passed=False, score=0.0,
        reason=f"unknown_expect_kind: {kind}",
    )


# ── Harness ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class RunnerOutput:
    """The metadata the harness collects alongside the response."""

    response: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    tier: str = ""
    tool_called: str = ""


RunnerFn = Any  # callable: (EvalPrompt) -> RunnerOutput | str
"""A runner takes a prompt and returns either a string response or
a :class:`RunnerOutput` with timing + cost metadata.  Real runners
talk to the orchestrator; tests pass a stub."""


def run_eval(
    runner: RunnerFn,
    *,
    prompts: Optional[Iterable[EvalPrompt]] = None,
) -> EvalReport:
    """Run ``runner`` against every prompt and produce a report.

    ``runner`` is called once per prompt.  The harness grades the
    response, records latency/cost/tier/tool, and aggregates the
    results into an :class:`EvalReport`.

    A runner that raises is captured as a failed result with
    ``reason = "runner_error: ..."`` so a flaky LLM does not abort
    the whole eval.
    """
    prompts = list(prompts) if prompts is not None else list(PROMPTS)
    started = datetime.now(timezone.utc)
    results: list[EvalResult] = []
    for p in prompts:
        t0 = time.perf_counter()
        try:
            raw = runner(p)
        except Exception as e:  # noqa: BLE001
            elapsed = int((time.perf_counter() - t0) * 1000)
            results.append(EvalResult(
                id=p.id, passed=False, score=0.0,
                reason=f"runner_error: {e}",
                latency_ms=elapsed,
            ))
            continue
        elapsed = int((time.perf_counter() - t0) * 1000)
        if isinstance(raw, RunnerOutput):
            out = raw
            text = out.response
            latency = out.latency_ms or elapsed
            cost = out.cost_usd
            tier = out.tier
            tool_called = out.tool_called
        else:
            text = str(raw)
            latency = elapsed
            cost = 0.0
            tier = ""
            tool_called = ""
        result = grade(p, text)
        result.latency_ms = latency
        result.cost_usd = cost
        result.tier = tier
        result.tool_called = tool_called
        results.append(result)
    finished = datetime.now(timezone.utc)
    report = _aggregate(results, started, finished)
    return report


def _aggregate(
    results: list[EvalResult],
    started: datetime,
    finished: datetime,
) -> EvalReport:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    latencies = sorted(r.latency_ms for r in results)
    p50 = _percentile(latencies, 50) if latencies else 0
    p95 = _percentile(latencies, 95) if latencies else 0
    total_cost = sum(r.cost_usd for r in results)
    avg_cost = total_cost / total if total else 0.0
    tool_calls = sum(1 for r in results if r.tool_called)
    escalations = sum(
        1 for r in results if r.tier in {"large", "premium"}
    )
    by_cat: dict[str, dict[str, float]] = {}
    for r in results:
        # Find the category via PROMPTS lookup.
        cat = "unknown"
        for p in PROMPTS:
            if p.id == r.id:
                cat = p.category
                break
        b = by_cat.setdefault(cat, {"total": 0, "passed": 0})
        b["total"] += 1
        if r.passed:
            b["passed"] += 1
    for cat, b in by_cat.items():
        b["pass_rate"] = b["passed"] / b["total"] if b["total"] else 0.0
    return EvalReport(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        pass_rate=(passed / total) if total else 0.0,
        total=total,
        passed=passed,
        failed=failed,
        p50_latency_ms=int(p50),
        p95_latency_ms=int(p95),
        total_cost_usd=round(total_cost, 6),
        avg_cost_usd=round(avg_cost, 6),
        tool_call_count=tool_calls,
        escalations=escalations,
        by_category={k: dict(v) for k, v in by_cat.items()},
        results=results,
    )


def _percentile(sorted_values: list[int], pct: float) -> float:
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


# ── Diff / regression gate helpers ──────────────────────────────────


def compare_reports(
    baseline: EvalReport, current: EvalReport
) -> dict[str, Any]:
    """Compare two reports and return a regression verdict.

    Returns:
      {
        "pass_rate_delta":   current.pass_rate - baseline.pass_rate,
        "p95_latency_delta": current.p95_latency_ms - baseline.p95_latency_ms,
        "cost_delta":        current.total_cost_usd - baseline.total_cost_usd,
        "verdict":           "pass" | "fail",
        "reasons":           [...],
      }

    A regression is:
      * pass_rate drops > 5 percentage points (0.05)
      * p95 latency rises > 20% of the baseline p95
    """
    reasons: list[str] = []
    pr_delta = current.pass_rate - baseline.pass_rate
    p95_delta = current.p95_latency_ms - baseline.p95_latency_ms
    p95_ratio = (
        p95_delta / baseline.p95_latency_ms
        if baseline.p95_latency_ms > 0 else 0.0
    )
    cost_delta = current.total_cost_usd - baseline.total_cost_usd

    if pr_delta < -0.05:
        reasons.append(
            f"pass_rate_drop: {pr_delta:+.3f} (threshold -0.05)"
        )
    if p95_ratio > 0.20:
        reasons.append(
            f"p95_latency_spike: {p95_ratio:+.1%} (threshold +20%)"
        )

    return {
        "pass_rate_delta": round(pr_delta, 4),
        "p95_latency_delta": p95_delta,
        "p95_latency_ratio": round(p95_ratio, 4),
        "cost_delta": round(cost_delta, 6),
        "verdict": "fail" if reasons else "pass",
        "reasons": reasons,
    }


__all__ = [
    "EvalResult",
    "EvalReport",
    "RunnerOutput",
    "grade",
    "run_eval",
    "compare_reports",
]