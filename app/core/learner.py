"""Learner Agent — Tracks agent performance and enables cross-training.

The LearnerAgent monitors which specialist agents succeed at which task types,
building a performance model that helps route future tasks to the best agent.
It also identifies successful patterns that can be shared across agents.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentPerformanceRecord:
    """A single performance observation for an agent."""

    agent_name: str
    task_category: str
    success: bool
    duration_ms: float
    tools_used: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class AgentStats:
    """Aggregated performance stats for an agent in a category."""

    agent_name: str
    category: str
    attempts: int = 0
    successes: int = 0
    total_duration_ms: float = 0.0
    common_tools: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.attempts if self.attempts > 0 else 0.0

    @property
    def score(self) -> float:
        """Combined score: success rate weighted by speed."""
        if self.attempts == 0:
            return 0.5
        speed_factor = max(0.5, 1.0 - (self.avg_duration_ms / 60000))
        return self.success_rate * speed_factor


class LearnerAgent:
    """Tracks agent performance and enables cross-training.

    The LearnerAgent:
    1. Records which agents succeed at which task types
    2. Identifies the best agent for each category
    3. Extracts successful patterns for sharing
    4. Provides recommendations for task routing
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            from app.settings.config import Config
            store_dir = Path(Config.MEMORY_ROOT) / "learner"
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        # category → agent_name → AgentStats
        self._stats: dict[str, dict[str, AgentStats]] = defaultdict(dict)
        self._recent_records: list[AgentPerformanceRecord] = []
        self._max_recent = 200
        self._cross_training_patterns: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # ── Recording ───────────────────────────────────────────────────

    def record(
        self,
        agent_name: str,
        task_category: str,
        success: bool,
        duration_ms: float = 0.0,
        tools_used: list[str] | None = None,
    ) -> None:
        """Record an agent's performance on a task."""
        record = AgentPerformanceRecord(
            agent_name=agent_name,
            task_category=task_category,
            success=success,
            duration_ms=duration_ms,
            tools_used=tools_used or [],
        )

        self._recent_records.append(record)
        if len(self._recent_records) > self._max_recent:
            self._recent_records = self._recent_records[-self._max_recent:]

        # Update aggregated stats
        if agent_name not in self._stats[task_category]:
            self._stats[task_category][agent_name] = AgentStats(
                agent_name=agent_name, category=task_category
            )
        stats = self._stats[task_category][agent_name]
        stats.attempts += 1
        if success:
            stats.successes += 1
        stats.total_duration_ms += duration_ms

        # Track common tools
        for tool in (tools_used or []):
            if tool not in stats.common_tools:
                stats.common_tools.append(tool)

        self._save()

    # ── Agent Selection ─────────────────────────────────────────────

    def get_best_agent(self, task_category: str) -> str | None:
        """Get the best-performing agent for a task category."""
        cat_stats = self._stats.get(task_category, {})
        if not cat_stats:
            return None

        # Find agent with highest score (min 3 attempts for reliability)
        candidates = [
            (name, stats)
            for name, stats in cat_stats.items()
            if stats.attempts >= 3
        ]

        if not candidates:
            # Fall back to any agent with attempts
            candidates = list(cat_stats.items())

        if not candidates:
            return None

        candidates.sort(key=lambda x: -x[1].score)
        return candidates[0][0]

    def get_agent_ranking(self, task_category: str) -> list[tuple[str, float]]:
        """Get all agents ranked by performance for a category."""
        cat_stats = self._stats.get(task_category, {})
        rankings = [
            (name, stats.score)
            for name, stats in cat_stats.items()
            if stats.attempts >= 1
        ]
        rankings.sort(key=lambda x: -x[1])
        return rankings

    # ── Cross-Training ──────────────────────────────────────────────

    def extract_successful_patterns(self, min_successes: int = 3) -> list[dict[str, Any]]:
        """Extract patterns from successful agent runs for cross-training.

        Returns a list of patterns like:
        {
            "category": "code_review",
            "agent": "DeveloperAgent",
            "tools": ["file_ops", "git_ops"],
            "success_rate": 0.9,
            "pattern": "Use file_ops to read, then git_ops to check history"
        }
        """
        patterns = []

        for category, agents in self._stats.items():
            for agent_name, stats in agents.items():
                if stats.successes >= min_successes and stats.common_tools:
                    pattern = {
                        "category": category,
                        "agent": agent_name,
                        "tools": stats.common_tools[:5],
                        "success_rate": stats.success_rate,
                        "avg_duration_ms": stats.avg_duration_ms,
                        "pattern": f"Use {', '.join(stats.common_tools[:3])} for {category} tasks",
                    }
                    patterns.append(pattern)

        # Sort by success rate
        patterns.sort(key=lambda x: -x["success_rate"])
        self._cross_training_patterns = {
            p["category"]: [pat for pat in patterns if pat["category"] == p["category"]]
            for p in patterns
        }
        return patterns

    def get_cross_training_advice(
        self, agent_name: str, task_category: str
    ) -> str | None:
        """Get advice for an agent based on what works for other agents.

        Returns a string with recommendations, or None if no advice available.
        """
        cat_stats = self._stats.get(task_category, {})
        if not cat_stats or agent_name not in cat_stats:
            return None

        # Find the best agent in this category
        best_agent = self.get_best_agent(task_category)
        if not best_agent or best_agent == agent_name:
            return None

        best_stats = cat_stats[best_agent]
        current_stats = cat_stats[agent_name]

        # Only give advice if best agent is significantly better
        if best_stats.score - current_stats.score < 0.2:
            return None

        advice_parts = [
            f"For {task_category} tasks, {best_agent} performs better.",
        ]

        if best_stats.common_tools:
            tools_str = ", ".join(best_stats.common_tools[:3])
            advice_parts.append(f"Consider using: {tools_str}")

        if best_stats.success_rate > current_stats.success_rate + 0.1:
            advice_parts.append(
                f"{best_agent} has {best_stats.success_rate:.0%} success rate "
                f"vs your {current_stats.success_rate:.0%}."
            )

        return " ".join(advice_parts)

    # ── Reporting ───────────────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a performance report across all agents and categories."""
        lines: list[str] = ["## 📊 Agent Performance Report\n"]

        if not self._stats:
            lines.append("No performance data recorded yet.")
            return "\n".join(lines)

        for category in sorted(self._stats.keys()):
            lines.append(f"### {category}")
            rankings = self.get_agent_ranking(category)
            for agent_name, score in rankings[:5]:
                stats = self._stats[category][agent_name]
                lines.append(
                    f"  - **{agent_name}**: {score:.0%} "
                    f"(success: {stats.success_rate:.0%}, "
                    f"attempts: {stats.attempts})"
                )
            lines.append("")

        # Add cross-training patterns
        patterns = self.extract_successful_patterns()
        if patterns:
            lines.append("### 🔄 Cross-Training Patterns")
            for p in patterns[:5]:
                lines.append(
                    f"  - **{p['category']}**: {p['agent']} "
                    f"({p['success_rate']:.0%} success) — {p['pattern']}"
                )

        return "\n".join(lines)

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data: dict[str, Any] = {"stats": {}, "recent_count": len(self._recent_records)}
            for cat, agents in self._stats.items():
                data["stats"][cat] = {}
                for agent, stats in agents.items():
                    data["stats"][cat][agent] = {
                        "attempts": stats.attempts,
                        "successes": stats.successes,
                        "total_duration_ms": stats.total_duration_ms,
                        "common_tools": stats.common_tools,
                    }
            path = self._store_dir / "learner.json"
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save learner data: %s", exc)

    def _load(self) -> None:
        path = self._store_dir / "learner.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for cat, agents in data.get("stats", {}).items():
                for agent, vals in agents.items():
                    self._stats[cat][agent] = AgentStats(
                        agent_name=agent,
                        category=cat,
                        attempts=vals.get("attempts", 0),
                        successes=vals.get("successes", 0),
                        total_duration_ms=vals.get("total_duration_ms", 0.0),
                        common_tools=vals.get("common_tools", []),
                    )
        except Exception as exc:
            logger.warning("Failed to load learner data: %s", exc)


# ── Module singleton ────────────────────────────────────────────────────

_GLOBAL_LEARNER: LearnerAgent | None = None


def get_learner_agent() -> LearnerAgent:
    """Get or create the global LearnerAgent instance."""
    global _GLOBAL_LEARNER
    if _GLOBAL_LEARNER is None:
        _GLOBAL_LEARNER = LearnerAgent()
    return _GLOBAL_LEARNER
