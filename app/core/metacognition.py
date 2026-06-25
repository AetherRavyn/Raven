"""Meta-Cognitive Monitor — Tracks reasoning quality and adapts strategy.

Enables AetherRavyn to reflect on its own performance, learn which
reasoning strategies work best for different problem types, and
dynamically adjust its approach.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReasoningStrategy:
    """Available reasoning strategies."""

    ANALYTICAL = "analytical"    # Step-by-step logical decomposition
    CREATIVE = "creative"       # Lateral thinking, brainstorming
    SYSTEMATIC = "systematic"   # Exhaustive, methodical approach
    RAPID = "rapid"             # Quick pattern matching, heuristics
    COLLABORATIVE = "collaborative"  # Delegate to specialist agents

    ALL = [ANALYTICAL, CREATIVE, SYSTEMATIC, RAPID, COLLABORATIVE]


@dataclass(slots=True)
class PerformanceRecord:
    """A single reasoning performance observation."""

    query_hash: str
    query_category: str
    strategy_used: str
    tools_used: list[str]
    success: bool
    confidence: float  # 0.0 to 1.0
    duration_ms: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class StrategyStats:
    """Aggregated stats for a reasoning strategy in a category."""

    strategy: str
    category: str
    attempts: int = 0
    successes: int = 0
    total_confidence: float = 0.0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

    @property
    def avg_confidence(self) -> float:
        return self.total_confidence / self.attempts if self.attempts > 0 else 0.5

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.attempts if self.attempts > 0 else 0.0

    @property
    def score(self) -> float:
        """Combined score balancing success rate, confidence, and speed."""
        if self.attempts == 0:
            return 0.5  # Neutral prior for unexplored strategies
        speed_bonus = max(0, 1.0 - (self.avg_duration_ms / 30000))  # Faster = better
        return (self.success_rate * 0.5) + (self.avg_confidence * 0.3) + (speed_bonus * 0.2)


class MetaCognitiveMonitor:
    """Monitors reasoning performance and adapts strategy selection.

    Tracks which strategies work best for different problem categories,
    building an internal model of its own strengths and weaknesses.
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            from app.settings.config import Config
            store_dir = Path(Config.MEMORY_ROOT) / "metacognition"
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        # category → strategy → StrategyStats
        self._stats: dict[str, dict[str, StrategyStats]] = defaultdict(dict)
        self._recent_records: list[PerformanceRecord] = []
        self._max_recent = 100
        self._load()

    # ── Recording ───────────────────────────────────────────────────

    def record(
        self,
        query: str,
        category: str,
        strategy: str,
        tools_used: list[str],
        success: bool,
        confidence: float = 0.5,
        duration_ms: float = 0.0,
    ) -> None:
        """Record a reasoning performance observation."""
        record = PerformanceRecord(
            query_hash=str(hash(query) % 10**8),
            query_category=category,
            strategy_used=strategy,
            tools_used=tools_used,
            success=success,
            confidence=max(0.0, min(1.0, confidence)),
            duration_ms=duration_ms,
        )

        self._recent_records.append(record)
        if len(self._recent_records) > self._max_recent:
            self._recent_records = self._recent_records[-self._max_recent:]

        # Update aggregated stats
        if strategy not in self._stats[category]:
            self._stats[category][strategy] = StrategyStats(
                strategy=strategy, category=category
            )
        stats = self._stats[category][strategy]
        stats.attempts += 1
        if success:
            stats.successes += 1
        stats.total_confidence += confidence
        stats.total_duration_ms += duration_ms

        self._save()

    # ── Strategy Selection ──────────────────────────────────────────

    def select_strategy(self, query: str, category: str = "general") -> str:
        """Choose the best reasoning strategy for a query category.

        Uses Thompson sampling-inspired exploration/exploitation:
        - Mostly picks the best-performing strategy (exploit)
        - Occasionally tries underexplored strategies (explore)
        """
        cat_stats = self._stats.get(category, {})

        if not cat_stats:
            # No data — use analytical as default
            return ReasoningStrategy.ANALYTICAL

        # Score each strategy
        scores: list[tuple[str, float]] = []
        for strategy in ReasoningStrategy.ALL:
            if strategy in cat_stats:
                stats = cat_stats[strategy]
                score = stats.score
                # Exploration bonus for underexplored strategies
                exploration = 1.0 / math.sqrt(max(1, stats.attempts))
                scores.append((strategy, score + exploration * 0.1))
            else:
                # Unexplored strategy gets moderate exploration bonus
                scores.append((strategy, 0.6))

        scores.sort(key=lambda x: -x[1])
        best = scores[0][0]

        logger.debug(
            "Strategy selection for '%s': %s (scores: %s)",
            category, best,
            {s: f"{sc:.2f}" for s, sc in scores[:3]},
        )
        return best

    # ── Confidence & Reflection ─────────────────────────────────────

    def get_confidence(self, window: int = 10) -> float:
        """Current confidence level based on recent performance."""
        recent = self._recent_records[-window:]
        if not recent:
            return 0.5
        return sum(r.confidence for r in recent) / len(recent)

    def get_success_rate(self, window: int = 20) -> float:
        """Recent success rate."""
        recent = self._recent_records[-window:]
        if not recent:
            return 0.5
        return sum(1 for r in recent if r.success) / len(recent)

    def get_strengths(self, top_k: int = 3) -> list[tuple[str, float]]:
        """Return top-performing categories."""
        category_scores: dict[str, float] = {}
        for cat, strategies in self._stats.items():
            scores = [s.score for s in strategies.values() if s.attempts >= 3]
            if scores:
                category_scores[cat] = max(scores)
        ranked = sorted(category_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]

    def get_weaknesses(self, top_k: int = 3) -> list[tuple[str, float]]:
        """Return worst-performing categories."""
        category_scores: dict[str, float] = {}
        for cat, strategies in self._stats.items():
            scores = [s.score for s in strategies.values() if s.attempts >= 3]
            if scores:
                category_scores[cat] = max(scores)
        ranked = sorted(category_scores.items(), key=lambda x: x[1])
        return ranked[:top_k]

    def reflect(self) -> str:
        """Generate a self-reflection report."""
        lines: list[str] = ["## 🧠 Meta-Cognitive Reflection\n"]
        lines.append(f"**Confidence**: {self.get_confidence():.0%}")
        lines.append(f"**Recent Success Rate**: {self.get_success_rate():.0%}")
        lines.append(f"**Total Observations**: {len(self._recent_records)}")

        strengths = self.get_strengths()
        if strengths:
            lines.append("\n**Strengths:**")
            for cat, score in strengths:
                lines.append(f"  ✅ {cat}: {score:.0%}")

        weaknesses = self.get_weaknesses()
        if weaknesses:
            lines.append("\n**Areas for Improvement:**")
            for cat, score in weaknesses:
                lines.append(f"  📈 {cat}: {score:.0%}")

        return "\n".join(lines)

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data: dict[str, Any] = {"stats": {}, "recent": []}
            for cat, strategies in self._stats.items():
                data["stats"][cat] = {}
                for strat, stats in strategies.items():
                    data["stats"][cat][strat] = {
                        "attempts": stats.attempts,
                        "successes": stats.successes,
                        "total_confidence": stats.total_confidence,
                        "total_duration_ms": stats.total_duration_ms,
                    }
            path = self._store_dir / "metacog.json"
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save metacognition data: %s", exc)

    def _load(self) -> None:
        path = self._store_dir / "metacog.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for cat, strategies in data.get("stats", {}).items():
                for strat, vals in strategies.items():
                    self._stats[cat][strat] = StrategyStats(
                        strategy=strat,
                        category=cat,
                        attempts=vals.get("attempts", 0),
                        successes=vals.get("successes", 0),
                        total_confidence=vals.get("total_confidence", 0.0),
                        total_duration_ms=vals.get("total_duration_ms", 0.0),
                    )
        except Exception as exc:
            logger.warning("Failed to load metacognition data: %s", exc)


_GLOBAL_METACOG: MetaCognitiveMonitor | None = None


def get_metacognitive_monitor() -> MetaCognitiveMonitor:
    global _GLOBAL_METACOG
    if _GLOBAL_METACOG is None:
        _GLOBAL_METACOG = MetaCognitiveMonitor()
    return _GLOBAL_METACOG
