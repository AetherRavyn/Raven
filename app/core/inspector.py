"""Self-Improvement Inspector — CLI dashboard for Raven's learning state.

Usage:
    uv run python -m app.core.inspector

Shows a unified view of:
  - Corrections by topic
  - Active prompt improvements
  - Recent fact-check findings
  - Confidence trends
  - Retrospective insights
  - Interaction statistics
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Inspector:
    """Aggregates state from all self-improvement subsystems."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir

    def report(self) -> dict[str, Any]:
        """Build a comprehensive report as a structured dict."""
        return {
            "corrections": self._corrections_summary(),
            "prompt_improvements": self._prompt_improvements_summary(),
            "interactions": self._interactions_summary(),
            "retrospective": self._retrospective_summary(),
            "success_patterns": self._success_patterns_summary(),
            "knowledge_graph": self._kg_summary(),
            "health": self._health_summary(),
            "system": self._system_info(),
        }

    def format_report(self) -> str:
        """Format the report as human-readable text."""
        data = self.report()
        lines: list[str] = []
        sep = "─" * 60

        # ── Header ──
        lines.append(" Raven Self-Improvement Inspector")
        lines.append(sep)

        # ── System Info ──
        sys_info = data.get("system", {})
        lines.append(f" Workspace: {sys_info.get('workspace', '?')}")
        lines.append(f" Turn count: {sys_info.get('turn_count', '?')}")
        lines.append("")

        # ── Corrections ──
        corr = data.get("corrections", {})
        lines.append(f" Corrections (total: {corr.get('total', 0)})")
        lines.append(sep)
        if corr.get("by_topic"):
            for topic, count in corr["by_topic"].items():
                bar = "█" * min(count * 2, 20)
                lines.append(f"  {topic:12s} {bar} {count}")
        else:
            lines.append("  (none)")
        if corr.get("recent"):
            lines.append("")
            lines.append("  Latest corrections:")
            for c in corr["recent"][:3]:
                lines.append(f"    • [{c['topic']}] {c['corrected'][:80]}")
        lines.append("")

        # ── Prompt Improvements ──
        imp = data.get("prompt_improvements", {})
        lines.append(f" Prompt Improvements (total: {imp.get('total', 0)})")
        lines.append(sep)
        if imp.get("active"):
            for a in imp["active"]:
                badge = "✓" if a.get("applied") else " "
                lines.append(f"  [{badge}] [{a['category']}] {a['adjustment'][:90]}")
        else:
            lines.append("  (none)")
        lines.append("")

        # ── Interactions ──
        ix = data.get("interactions", {})
        total = ix.get("total", 0)
        successes = ix.get("successful", 0)
        rate = successes / max(total, 1) * 100
        lines.append(f" Interactions (total: {total})")
        lines.append(sep)
        lines.append(f"  Success rate: {rate:.0f}% ({successes}/{total})")
        if ix.get("top_tool_issues"):
            lines.append("  Tools with issues:")
            for t, c in ix["top_tool_issues"]:
                lines.append(f"    • {t}: {c} failures")
        lines.append("")

        # ── Success Patterns ──
        sp = data.get("success_patterns", {})
        if sp.get("active"):
            lines.append(" Success Patterns")
            lines.append(sep)
            for p in sp["active"]:
                lines.append(f"  ✓ {p}")
            lines.append("")

        # ── Knowledge Graph (fact-check data) ──
        kg = data.get("knowledge_graph", {})
        if kg.get("recent_facts"):
            lines.append(" Knowledge Graph Facts")
            lines.append(sep)
            for f in kg["recent_facts"][:5]:
                lines.append(f"  • {f['entity1']} --({f['relation']})--> {f['entity2']}")
            lines.append("")

        # ── Health Monitor ──
        health = data.get("health", {})
        if health:
            lines.append(" Learning Health")
            lines.append(sep)
            lines.append(f"  Turns tracked: {health.get('total_turns_recorded', 0)}")
            trends = health.get("trends", {})
            sr = health.get("success_rate", 0) * 100
            sr_t = trends.get("success_rate", "")
            lines.append(f"  Success rate:  {sr:.0f}%  {sr_t}")
            ac = health.get("avg_confidence", 0)
            ac_t = trends.get("confidence", "")
            lines.append(f"  Avg confidence: {ac:.2f}  {ac_t}")
            cr = health.get("correction_rate", 0) * 100
            cr_t = trends.get("correction_rate", "")
            lines.append(f"  Correction rate: {cr:.0f}%  {cr_t}")
            if health.get("alerts"):
                for a in health["alerts"]:
                    lines.append(f"  ⚠ [{a['type']}] {a.get('message', '')[:80]}")
            lines.append("")

        # ── Retrospective ──
        retro = data.get("retrospective", {})
        lines.append(" Retrospective (last run)" if retro.get("last_run") else " Retrospective")
        lines.append(sep)
        if retro.get("insights"):
            for ins in retro["insights"]:
                lines.append(f"  • [{ins['category']}] {ins['insight'][:100]}")
        else:
            lines.append("  (no insights yet)")
        lines.append("")

        return "\n".join(lines)

    # ── Data Sources ───────────────────────────────────────────────

    def _corrections_summary(self) -> dict[str, Any]:
        try:
            from app.core.correction_learner import CorrectionStore

            store = CorrectionStore(self._workspace_dir)
            recents = store.get_recent(100)
            topics = Counter(c.topic for c in recents)
            return {
                "total": len(recents),
                "by_topic": dict(topics.most_common()),
                "recent": [
                    {"topic": c.topic, "corrected": c.corrected_claim} for c in recents[-5:]
                ],
            }
        except Exception as exc:
            logger.debug("Failed to load corrections: %s", exc)
            return {"total": 0, "by_topic": {}, "recent": []}

    def _prompt_improvements_summary(self) -> dict[str, Any]:
        try:
            from app.core.prompt_improver import PromptImprover

            improver = PromptImprover(self._workspace_dir)
            all_adjs = improver.get_all()
            return {
                "total": len(all_adjs),
                "active": [
                    {
                        "category": a.category,
                        "adjustment": a.adjustment,
                        "reason": a.reason,
                        "confidence": a.confidence,
                        "applied": a.applied,
                    }
                    for a in all_adjs
                ],
            }
        except Exception as exc:
            logger.debug("Failed to load improvements: %s", exc)
            return {"total": 0, "active": []}

    def _interactions_summary(self) -> dict[str, Any]:
        try:
            from app.core.prompt_improver import InteractionTracker

            tracker = InteractionTracker(self._workspace_dir)
            recents = tracker.get_recent(200)
            tool_failures: Counter = Counter()
            successes = 0
            for r in recents:
                if r.success:
                    successes += 1
                if r.tool_used and not r.success:
                    tool_failures[r.tool_used] += 1
            return {
                "total": len(recents),
                "successful": successes,
                "top_tool_issues": tool_failures.most_common(5),
            }
        except Exception as exc:
            logger.debug("Failed to load interactions: %s", exc)
            return {"total": 0, "successful": 0, "top_tool_issues": []}

    def _retrospective_summary(self) -> dict[str, Any]:
        path = Path(self._workspace_dir or "workspace") / "memory" / ".retro_counter"
        turn_count = 0
        try:
            turn_count = int(path.read_text(encoding="utf-8").strip())
        except Exception:
            pass
        try:
            from app.core.retrospective import get_retrospective_analyzer

            analyzer = get_retrospective_analyzer(self._workspace_dir)
            insights = analyzer.latest_insights(5)
            return {"last_run": turn_count, "insights": insights}
        except Exception:
            return {"last_run": turn_count, "insights": []}

    def _success_patterns_summary(self) -> dict[str, Any]:
        try:
            from app.core.success_patterns import get_success_pattern_learner

            learner = get_success_pattern_learner()
            prompt = learner.get_encouragement_prompt()
            patterns = [line.strip("- ") for line in prompt.splitlines() if line.startswith("- ")]
            return {"active": patterns}
        except Exception:
            return {"active": []}

    def _kg_summary(self) -> dict[str, Any]:
        return {"recent_facts": []}

    def _health_summary(self) -> dict[str, Any]:
        try:
            from app.core.learning_health import get_health_monitor

            monitor = get_health_monitor(self._workspace_dir)
            return monitor.snapshot()
        except Exception:
            return {}

    @staticmethod
    def _system_info() -> dict[str, Any]:
        try:
            from app.settings.config import Config

            return {
                "workspace": str(getattr(Config, "MEMORY_ROOT", "workspace")),
                "turn_count": 0,
            }
        except Exception:
            return {"workspace": "?", "turn_count": 0}


# ── CLI Entry Point ───────────────────────────────────────────────


def main() -> None:
    """Print the inspection report to stdout."""

    inspector = Inspector()
    report = inspector.format_report()
    print(report)


if __name__ == "__main__":
    main()
