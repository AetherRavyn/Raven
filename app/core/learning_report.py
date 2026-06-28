"""Learning Report — timestamped snapshots of Raven's learning state.

Generates structured reports from all learning stores and supports
comparing two reports to show "what changed" between them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_report(workspace_dir: str | None = None) -> dict[str, Any]:
    """Generate a snapshot report from all learning stores.

    Returns:
        Dict with timestamp, corrections, success patterns, prompt
        improvements, health metrics, and fact extraction summary.
    """
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Corrections
    try:
        from app.core.correction_learner import CorrectionStore

        store = CorrectionStore(workspace_dir)
        recents = store.get_recent(50)
        report["corrections"] = {
            "total": len(recents),
            "by_topic": _count_by(recents, "topic"),
            "recent": [
                {"topic": c.topic, "corrected": c.corrected_claim[:100]} for c in recents[-5:]
            ],
        }
    except Exception as exc:
        report["corrections"] = {"error": str(exc)}

    # 2. Success Patterns
    try:
        from app.core.success_patterns import get_success_pattern_learner

        sp = get_success_pattern_learner()
        prompt = sp.get_encouragement_prompt()
        report["success_patterns"] = {
            "active": [ln.strip("- ") for ln in prompt.splitlines() if ln.startswith("- ")],
        }
    except Exception as exc:
        report["success_patterns"] = {"error": str(exc)}

    # 3. Prompt Improvements
    try:
        from app.core.prompt_improver import PromptImprover

        improver = PromptImprover(workspace_dir)
        all_adjs = improver.get_all()
        report["prompt_improvements"] = {
            "total": len(all_adjs),
            "active": [{"category": a.category, "adjustment": a.adjustment[:80]} for a in all_adjs],
        }
    except Exception as exc:
        report["prompt_improvements"] = {"error": str(exc)}

    # 4. Health Metrics
    try:
        from app.core.learning_health import get_health_monitor

        monitor = get_health_monitor(workspace_dir)
        snap = monitor.snapshot()
        report["health"] = {
            "total_turns": snap.get("total_turns_recorded", 0),
            "success_rate": snap.get("success_rate", 0),
            "avg_confidence": snap.get("avg_confidence", 0),
            "correction_rate": snap.get("correction_rate", 0),
            "trends": snap.get("trends", {}),
            "alerts": snap.get("alerts", []),
        }
    except Exception as exc:
        report["health"] = {"error": str(exc)}

    return report


def save_report(report: dict[str, Any], workspace_dir: str | None = None) -> Path:
    """Save a report to disk and return the path."""
    from app.settings.config import Config

    reports_dir = Path(workspace_dir or Config.MEMORY_ROOT) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"report_{report['timestamp'][:19].replace(':', '-')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_latest_report(workspace_dir: str | None = None) -> dict[str, Any] | None:
    """Load the most recent saved report."""
    from app.settings.config import Config

    reports_dir = Path(workspace_dir or Config.MEMORY_ROOT) / "reports"
    if not reports_dir.exists():
        return None
    files = sorted(reports_dir.glob("report_*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def compare_reports(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compare two reports and return what changed.

    Returns a dict with categories of changes:
    - corrections: new count, topic shifts
    - success_patterns: new/removed patterns
    - prompt_improvements: new/removed adjustments
    - health: metric deltas
    """
    changes: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # Corrections delta
    old_c = old.get("corrections", {})
    new_c = new.get("corrections", {})
    old_total = old_c.get("total", 0) if isinstance(old_c, dict) else 0
    new_total = new_c.get("total", 0) if isinstance(new_c, dict) else 0
    delta = new_total - old_total
    if delta > 0:
        changes["new_corrections"] = delta
    if delta < 0:
        changes["corrections_pruned"] = -delta

    # Topic changes
    old_topics = old_c.get("by_topic", {}) if isinstance(old_c, dict) else {}
    new_topics = new_c.get("by_topic", {}) if isinstance(new_c, dict) else {}
    new_topics_set = set(new_topics.keys()) - set(old_topics.keys())
    if new_topics_set:
        changes["new_correction_topics"] = list(new_topics_set)

    # Success patterns delta
    old_sp = old.get("success_patterns", {})
    new_sp = new.get("success_patterns", {})
    old_patterns = set(old_sp.get("active", [])) if isinstance(old_sp, dict) else set()
    new_patterns = set(new_sp.get("active", [])) if isinstance(new_sp, dict) else set()
    added = new_patterns - old_patterns
    removed = old_patterns - new_patterns
    if added:
        changes["new_success_patterns"] = list(added)
    if removed:
        changes["removed_success_patterns"] = list(removed)

    # Prompt improvements delta
    old_adj = old.get("prompt_improvements", {})
    new_adj = new.get("prompt_improvements", {})
    old_count = old_adj.get("total", 0) if isinstance(old_adj, dict) else 0
    new_count = new_adj.get("total", 0) if isinstance(new_adj, dict) else 0
    adj_delta = new_count - old_count
    if adj_delta > 0:
        changes["new_improvements"] = adj_delta
    if adj_delta < 0:
        changes["improvements_pruned"] = -adj_delta

    # Health deltas
    old_h = old.get("health", {})
    new_h = new.get("health", {})
    health_deltas: dict[str, Any] = {}
    for metric in ("total_turns", "success_rate", "avg_confidence", "correction_rate"):
        old_val = old_h.get(metric, 0) if isinstance(old_h, dict) else 0
        new_val = new_h.get(metric, 0) if isinstance(new_h, dict) else 0
        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            diff = round(new_val - old_val, 3)
            if diff != 0:
                health_deltas[metric] = diff
    if health_deltas:
        changes["health_deltas"] = health_deltas

    # Alerts
    old_alerts = old_h.get("alerts", []) if isinstance(old_h, dict) else []
    new_alerts = new_h.get("alerts", []) if isinstance(new_h, dict) else []
    if new_alerts and not old_alerts:
        changes["new_alerts"] = new_alerts

    return changes


def format_change_summary(changes: dict[str, Any]) -> str:
    """Format a change comparison as human-readable text."""
    lines: list[str] = ["## Learning Progress Report\n"]

    if changes.get("new_corrections"):
        n = changes["new_corrections"]
        lines.append(f"📝 **{n} new correction{'s' if n != 1 else ''}**")
        if changes.get("new_correction_topics"):
            lines.append(f"   New topics: {', '.join(changes['new_correction_topics'])}")
        lines.append("")

    if changes.get("new_success_patterns"):
        for p in changes["new_success_patterns"]:
            lines.append(f"✓ **New success pattern:** {p}")
        lines.append("")

    if changes.get("new_improvements"):
        n = changes["new_improvements"]
        lines.append(f"🔧 **{n} new prompt improvement{'s' if n != 1 else ''}**")
        lines.append("")

    if changes.get("health_deltas"):
        lines.append("**Metric changes:**")
        deltas = changes["health_deltas"]
        if "success_rate" in deltas:
            val = deltas["success_rate"] * 100
            arrow = "↑" if val > 0 else "↓"
            lines.append(f"  {arrow} Success rate: {val:+.1f}%")
        if "avg_confidence" in deltas:
            val = deltas["avg_confidence"]
            arrow = "↑" if val > 0 else "↓"
            lines.append(f"  {arrow} Avg confidence: {val:+.2f}")
        if "correction_rate" in deltas:
            val = deltas["correction_rate"] * 100
            arrow = "↓" if val < 0 else "↑"
            lines.append(f"  {arrow} Correction rate: {val:+.1f}% (lower is better)")
        if "total_turns" in deltas:
            lines.append(f"  → {deltas['total_turns']} more turns processed")
        lines.append("")

    if changes.get("new_alerts"):
        lines.append("⚠ **New alerts:**")
        for a in changes["new_alerts"]:
            lines.append(f"  • [{a.get('type', '?')}] {a.get('message', '')[:100]}")
        lines.append("")

    return "\n".join(lines)


def _count_by(items: list[Any], key: str) -> dict[str, int]:
    """Count occurrences of a key across items."""
    from collections import Counter

    return dict(Counter(getattr(i, key, "unknown") for i in items))
