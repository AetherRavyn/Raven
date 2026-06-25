"""A/B Testing Framework — compare two approaches and learn which is better.

FRIDAY-style: when uncertain between two approaches, run both
on a small sample and pick the winner based on outcomes.

Usage:
    from app.core.ab_testing import ABTest
    test = ABTest("prompt_style", "concise vs verbose")
    variant_a = await test.run("concise", prompt_fn_a, query)
    variant_b = await test.run("verbose", prompt_fn_b, query)
    winner = test.evaluate()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VariantResult:
    """Result of running one variant."""
    variant_name: str
    output: str
    latency_ms: float
    success: bool
    quality_score: float = 0.5  # 0.0 to 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ABTestResult:
    """Final result of an A/B test."""
    test_name: str
    description: str
    variant_a: VariantResult
    variant_b: VariantResult
    winner: str  # "a", "b", or "tie"
    confidence: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ABTest:
    """Runs and evaluates A/B tests between two approaches."""

    def __init__(self, test_name: str, description: str = "") -> None:
        self.test_name = test_name
        self.description = description
        self._results_dir = Path("workspace/ab_tests")
        self._results_dir.mkdir(parents=True, exist_ok=True)

    async def run_variant(
        self,
        variant_name: str,
        fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> VariantResult:
        """Run a single variant and measure its performance."""
        start = time.time()
        try:
            output = await fn(*args, **kwargs)
            latency_ms = (time.time() - start) * 1000
            return VariantResult(
                variant_name=variant_name,
                output=str(output),
                latency_ms=latency_ms,
                success=True,
                quality_score=self._estimate_quality(str(output)),
            )
        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            return VariantResult(
                variant_name=variant_name,
                output=str(exc),
                latency_ms=latency_ms,
                success=False,
                quality_score=0.0,
            )

    def evaluate(self, result_a: VariantResult, result_b: VariantResult) -> ABTestResult:
        """Evaluate which variant performed better."""
        score_a = self._compute_score(result_a)
        score_b = self._compute_score(result_b)

        diff = abs(score_a - score_b)
        if diff < 0.05:
            winner = "tie"
            confidence = 0.5
        elif score_a > score_b:
            winner = "a"
            confidence = min(0.5 + diff, 0.95)
        else:
            winner = "b"
            confidence = min(0.5 + diff, 0.95)

        ab_result = ABTestResult(
            test_name=self.test_name,
            description=self.description,
            variant_a=result_a,
            variant_b=result_b,
            winner=winner,
            confidence=confidence,
        )

        # Save result
        self._save_result(ab_result)
        return ab_result

    def _compute_score(self, result: VariantResult) -> float:
        """Compute a composite score for a variant."""
        if not result.success:
            return 0.0

        # Weight: quality (60%) + speed (20%) + success (20%)
        speed_score = max(0, 1.0 - (result.latency_ms / 10000))  # 10s = 0
        return result.quality_score * 0.6 + speed_score * 0.2 + 0.2

    def _estimate_quality(self, output: str) -> float:
        """Estimate output quality based on heuristics."""
        if not output:
            return 0.0
        score = 0.5  # base
        if len(output) > 50:
            score += 0.1  # substantive
        if len(output) > 200:
            score += 0.1  # detailed
        if any(w in output.lower() for w in ("because", "therefore", "however", "analysis")):
            score += 0.1  # analytical
        if output.count("\n") > 3:
            score += 0.1  # well-structured
        return min(score, 1.0)

    def _save_result(self, result: ABTestResult) -> None:
        """Save test result to disk."""
        from dataclasses import asdict
        path = self._results_dir / f"{self.test_name}_{int(time.time())}.json"
        try:
            path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save A/B test result: %s", exc)

    def get_history(self, limit: int = 10) -> list[ABTestResult]:
        """Get recent test results."""
        results = []
        for path in sorted(self._results_dir.glob(f"{self.test_name}_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["variant_a"] = VariantResult(**data["variant_a"])
                data["variant_b"] = VariantResult(**data["variant_b"])
                results.append(ABTestResult(**data))
            except Exception:
                continue
        return results
