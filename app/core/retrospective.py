"""Retrospective Analyzer — periodic deep reflection on Raven's performance.

Runs on a schedule (every N turns or via cron).  Analyzes a batch of
recent interactions to identify systemic patterns and generates
concrete improvements that feed into the PromptImprover.

Unlike the per-turn PromptImprovementOrchestrator, this looks at the
*big picture* — clusters of related corrections, tool failures that
share a root cause, response-style mismatches that recur across
sessions.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RetrospectiveAnalyzer:
    """Batch analyzer that finds systemic patterns across many turns.

    Call ``analyze()`` periodically (every 50-100 turns, or via a
    daily cron) to generate improvement insights that might not be
    visible in any single turn.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        self._insights: list[dict[str, Any]] = []

    async def analyze(self) -> list[dict[str, Any]]:
        """Run a full retrospective analysis.

        Returns a list of improvement suggestions, each with:
        - ``category``: improvement category
        - ``insight``: what pattern was found
        - ``recommendation``: what to do about it
        - ``confidence``: 0.0-1.0
        - ``evidence``: supporting data summary
        """
        insights: list[dict[str, Any]] = []

        # 1. Correction cluster analysis
        insights.extend(self._analyze_correction_clusters())

        # 2. Tool failure pattern analysis
        insights.extend(self._analyze_tool_failures())

        # 3. Response quality trends
        insights.append(self._analyze_response_trends())

        # 4. Skill gap detection
        insights.append(self._detect_skill_gaps())

        # 5. Improvement effectiveness
        insights.append(self._evaluate_improvement_effectiveness())

        self._insights = [i for i in insights if i]
        self._save_insights()
        return self._insights

    # ── Correction Cluster Analysis ───────────────────────────────

    def _analyze_correction_clusters(self) -> list[dict[str, Any]]:
        """Detect clusters of related corrections.

        If the same topic gets corrected repeatedly, the system prompt
        needs a more targeted instruction rather than a single fact fix.
        """
        corrections = self._load_corrections()
        if len(corrections) < 3:
            return []

        topics = Counter(c["topic"] for c in corrections)
        # Find topics with unusually high correction counts
        avg = sum(topics.values()) / max(len(topics), 1)
        clusters = []

        for topic, count in topics.most_common(3):
            if count > avg * 1.5 and count >= 3:
                examples = [c for c in corrections if c["topic"] == topic][:3]
                sample = "; ".join(
                    f"'{e['original'][:60]}' → '{e['corrected'][:60]}'" for e in examples
                )
                clusters.append(
                    {
                        "category": f"correction_cluster_{topic}",
                        "insight": (
                            f"Repeated corrections in '{topic}': {count} instances. "
                            f"This suggests a systemic misunderstanding rather than "
                            f"isolated errors."
                        ),
                        "recommendation": (
                            f"Add a dedicated system-prompt instruction about "
                            f"{topic} handling. Review the correction patterns:\n"
                            f"{sample}"
                        ),
                        "confidence": min(0.5 + count * 0.08, 0.95),
                        "evidence": (
                            f"{count} corrections in '{topic}' topic "
                            f"({count / max(len(corrections), 1) * 100:.0f}% of all corrections)"
                        ),
                    }
                )

        return clusters

    # ── Tool Failure Pattern Analysis ──────────────────────────────

    def _analyze_tool_failures(self) -> list[dict[str, Any]]:
        """Detect tools that fail more than expected."""
        interactions = self._load_interactions()
        if len(interactions) < 10:
            return []

        tool_stats: dict[str, list[bool]] = {}
        for i in interactions:
            tool = i.get("tool_used", "")
            if tool:
                tool_stats.setdefault(tool, []).append(i["success"])

        insights = []
        for tool, outcomes in tool_stats.items():
            if len(outcomes) < 3:
                continue
            fail_rate = 1 - (sum(outcomes) / len(outcomes))
            if fail_rate > 0.4:
                insights.append(
                    {
                        "category": "tool_failure",
                        "insight": (
                            f"Tool '{tool}' fails {fail_rate * 100:.0f}% of the time "
                            f"({len(outcomes)} uses)."
                        ),
                        "recommendation": (
                            f"Review '{tool}' configuration or consider a fallback. "
                            f"Add pre-flight validation before calling this tool."
                        ),
                        "confidence": min(0.3 + fail_rate, 0.9),
                        "evidence": (
                            f"{fail_rate * 100:.0f}% failure rate over {len(outcomes)} uses"
                        ),
                    }
                )

        return insights

    # ── Response Quality Trends ────────────────────────────────────

    def _analyze_response_trends(self) -> dict[str, Any]:
        """Check if response quality is improving or degrading over time."""
        interactions = self._load_interactions()
        if len(interactions) < 10:
            return {}

        # Split into first half and second half
        mid = len(interactions) // 2
        first_half = interactions[:mid]
        second_half = interactions[mid:]

        first_success = sum(1 for i in first_half if i["success"])
        second_success = sum(1 for i in second_half if i["success"])

        first_rate = first_success / max(len(first_half), 1)
        second_rate = second_success / max(len(second_half), 1)

        trend = second_rate - first_rate

        if abs(trend) < 0.05:
            return {}

        direction = "improving" if trend > 0 else "degrading"
        return {
            "category": "quality_trend",
            "insight": (
                f"Response quality is {direction}: "
                f"{first_rate * 100:.0f}% → {second_rate * 100:.0f}% success rate."
            ),
            "recommendation": (
                "Review recent changes to system prompt or tool configuration."
                if direction == "degrading"
                else "Current approach is working — continue monitoring."
            ),
            "confidence": min(abs(trend) * 3, 0.8),
            "evidence": (
                f"Success rate went from {first_rate * 100:.0f}% to "
                f"{second_rate * 100:.0f}% ({len(interactions)} total interactions)"
            ),
        }

    # ── Skill Gap Detection ────────────────────────────────────────

    def _detect_skill_gaps(self) -> dict[str, Any]:
        """Detect recurring query types that have no dedicated skill."""
        corrections = self._load_corrections()
        if len(corrections) < 5:
            return {}

        # If corrections cluster heavily in one topic AND that topic
        # isn't covered by a skill, suggest creating one.
        topics = Counter(c["topic"] for c in corrections)
        top_topic, top_count = topics.most_common(1)[0]

        if top_count >= 5 and top_count > len(corrections) * 0.3:
            return {
                "category": "skill_gap",
                "insight": (
                    f"'{top_topic}' is responsible for "
                    f"{top_count}/{len(corrections)} corrections. "
                    f"No dedicated skill handles this domain well."
                ),
                "recommendation": (
                    f"Consider creating a '{top_topic}' skill that teaches "
                    f"Raven the proper conventions for this domain."
                ),
                "confidence": 0.65,
                "evidence": (
                    f"{top_count} corrections in '{top_topic}' "
                    f"({top_count / len(corrections) * 100:.0f}% of total)"
                ),
            }

        return {}

    # ── Improvement Effectiveness ──────────────────────────────────

    def _evaluate_improvement_effectiveness(self) -> dict[str, Any]:
        """Check if prompt improvements are actually reducing corrections."""
        prompt_adjustments = self._load_prompt_adjustments()
        if not prompt_adjustments:
            return {}

        corrections = self._load_corrections()

        # Compare correction rate before vs after the latest adjustment
        if len(corrections) < 6:
            return {}

        # Use a simple heuristic: look at the oldest 1/3 vs newest 1/3
        third = len(corrections) // 3
        old = corrections[:third]
        recent = corrections[third:]

        old_topics = Counter(c["topic"] for c in old)
        recent_topics = Counter(c["topic"] for c in recent)

        # Check if any topic has fewer corrections recently
        improvements = []
        for topic in old_topics:
            old_count = old_topics.get(topic, 0)
            new_count = recent_topics.get(topic, 0)
            if old_count > 2 and new_count < old_count * 0.5:
                improvements.append(f"{topic}: {old_count} → {new_count}")

        if improvements:
            return {
                "category": "improvement_effectiveness",
                "insight": "Prompt improvements seem to be working.",
                "recommendation": (
                    "Continue with the current improvement strategy. "
                    "Positive trend in: " + ", ".join(improvements)
                ),
                "confidence": 0.6,
                "evidence": "; ".join(improvements),
            }

        return {}

    # ── Loaders ─────────────────────────────────────────────────────

    def _load_corrections(self) -> list[dict[str, Any]]:
        try:
            from app.core.correction_learner import CorrectionStore

            store = CorrectionStore(self._workspace_dir)
            recents = store.get_recent(100)
            return [
                {
                    "topic": c.topic,
                    "original": c.original_claim[:120],
                    "corrected": c.corrected_claim[:120],
                }
                for c in recents
            ]
        except Exception as exc:
            logger.debug("Failed to load corrections: %s", exc)
            return []

    def _load_interactions(self) -> list[dict[str, Any]]:
        try:
            from app.core.prompt_improver import InteractionTracker

            tracker = InteractionTracker(self._workspace_dir)
            recents = tracker.get_recent(200)
            return [
                {
                    "success": r.success,
                    "tool_used": r.tool_used,
                    "failure_reason": r.failure_reason[:100],
                    "duration_ms": r.duration_ms,
                }
                for r in recents
            ]
        except Exception as exc:
            logger.debug("Failed to load interactions: %s", exc)
            return []

    def _load_prompt_adjustments(self) -> list[dict[str, Any]]:
        try:
            from app.core.prompt_improver import PromptImprover

            improver = PromptImprover(self._workspace_dir)
            return [
                {
                    "category": a.category,
                    "adjustment": a.adjustment,
                    "confidence": a.confidence,
                    "applied": a.applied,
                }
                for a in improver.get_all()
            ]
        except Exception as exc:
            logger.debug("Failed to load adjustments: %s", exc)
            return []

    # ── Persistence ───────────────────────────────────────────────

    def _insights_dir(self) -> Path:
        from app.settings.config import Config

        base = Path(self._workspace_dir or Config.MEMORY_ROOT)
        path = base / "retrospective"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_insights(self) -> None:
        import json

        try:
            path = self._insights_dir() / "insights.json"
            path.write_text(
                json.dumps(self._insights, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to save retrospective insights: %s", exc)

    def load_insights(self) -> list[dict[str, Any]]:
        import json

        try:
            path = self._insights_dir() / "insights.json"
            if path.exists():
                self._insights = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to load retrospective insights: %s", exc)
        return list(self._insights)

    def latest_insights(self, n: int = 5) -> list[dict[str, Any]]:
        """Return the most recent / highest-confidence insights."""
        sorted_insights = sorted(self._insights, key=lambda i: i.get("confidence", 0), reverse=True)
        return sorted_insights[:n]


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_ANALYZER: RetrospectiveAnalyzer | None = None


def get_retrospective_analyzer(
    workspace_dir: str | None = None,
) -> RetrospectiveAnalyzer:
    global _GLOBAL_ANALYZER
    if _GLOBAL_ANALYZER is None:
        _GLOBAL_ANALYZER = RetrospectiveAnalyzer(workspace_dir=workspace_dir)
        _GLOBAL_ANALYZER.load_insights()
    return _GLOBAL_ANALYZER
