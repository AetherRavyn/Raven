# app/core/self_improvement.py
"""Self-Improvement Loop — RAVEN learns from its own performance.

Components:
  1. Interaction Feedback Tracker — records success/failure per tool + model combo
  2. Model Router Optimizer — adjusts System1/System2 routing thresholds based on
     historical success rates
  3. Skill Auto-Discovery — scans workspace for new .py files matching tool patterns
     and suggests registration

Data stored in: workspace/memory/self_improvement/
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InteractionFeedback:
    """Tracks per-interaction quality signals for continuous improvement."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        base = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self._dir = base / "self_improvement"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._feedback_file = self._dir / "feedback.jsonl"
        self._stats_file = self._dir / "tool_stats.json"
        self._model_stats_file = self._dir / "model_stats.json"

    # ── Record Feedback ────────────────────────────────────────────────

    def record(
        self,
        interaction_id: str,
        tool_name: str | None = None,
        model_used: str | None = None,
        success: bool = True,
        latency_ms: float = 0,
        user_rating: int | None = None,
        system_1_handled: bool = False,
        error: str | None = None,
    ) -> None:
        """Log a single interaction outcome."""
        entry = {
            "id": interaction_id,
            "tool": tool_name,
            "model": model_used,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "user_rating": user_rating,
            "system_1": system_1_handled,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._feedback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("Feedback write failed: %s", exc)

        # Update aggregated stats
        self._update_tool_stats(tool_name, success, latency_ms)
        self._update_model_stats(model_used, success, latency_ms, system_1_handled)

    # ── Tool Stats ─────────────────────────────────────────────────────

    def _update_tool_stats(
        self, tool_name: str | None, success: bool, latency_ms: float
    ) -> None:
        if not tool_name:
            return
        stats = self._load_json(self._stats_file) or {}
        tool = stats.setdefault(tool_name, {
            "calls": 0, "successes": 0, "failures": 0,
            "avg_latency_ms": 0, "total_latency_ms": 0,
        })
        tool["calls"] += 1
        if success:
            tool["successes"] += 1
        else:
            tool["failures"] += 1
        tool["total_latency_ms"] += latency_ms
        tool["avg_latency_ms"] = round(tool["total_latency_ms"] / tool["calls"], 1)
        tool["success_rate"] = round(tool["successes"] / tool["calls"], 3)
        self._save_json(self._stats_file, stats)

    def get_tool_stats(self) -> Dict[str, Any]:
        return self._load_json(self._stats_file) or {}

    # ── Model Stats ────────────────────────────────────────────────────

    def _update_model_stats(
        self,
        model: str | None,
        success: bool,
        latency_ms: float,
        system_1: bool,
    ) -> None:
        stats = self._load_json(self._model_stats_file) or {}
        routing = "system_1" if system_1 else "system_2"
        key = f"{routing}:{model or 'unknown'}"
        entry = stats.setdefault(key, {
            "calls": 0, "successes": 0, "avg_latency_ms": 0, "total_latency_ms": 0,
        })
        entry["calls"] += 1
        if success:
            entry["successes"] += 1
        entry["total_latency_ms"] += latency_ms
        entry["avg_latency_ms"] = round(entry["total_latency_ms"] / entry["calls"], 1)
        entry["success_rate"] = round(entry["successes"] / entry["calls"], 3)
        self._save_json(self._model_stats_file, stats)

    def get_model_stats(self) -> Dict[str, Any]:
        return self._load_json(self._model_stats_file) or {}

    # ── Model Router Optimizer ─────────────────────────────────────────

    def get_routing_recommendations(self) -> Dict[str, Any]:
        """Analyze model performance and recommend routing changes."""
        model_stats = self.get_model_stats()
        tool_stats = self.get_tool_stats()

        recommendations = []

        # Find underperforming tools
        for tool, stats in tool_stats.items():
            if stats.get("calls", 0) >= 10 and stats.get("success_rate", 1.0) < 0.7:
                recommendations.append({
                    "type": "tool_reliability",
                    "tool": tool,
                    "success_rate": stats["success_rate"],
                    "suggestion": f"Tool '{tool}' has {stats['success_rate']:.0%} success rate. "
                                  f"Consider adding error handling or fallback.",
                })

        # Find slow tools
        for tool, stats in tool_stats.items():
            if stats.get("calls", 0) >= 5 and stats.get("avg_latency_ms", 0) > 5000:
                recommendations.append({
                    "type": "performance",
                    "tool": tool,
                    "avg_latency_ms": stats["avg_latency_ms"],
                    "suggestion": f"Tool '{tool}' averages {stats['avg_latency_ms']:.0f}ms. "
                                  f"Consider caching or async optimization.",
                })

        # System 1 vs System 2 efficiency
        s1_stats = {k: v for k, v in model_stats.items() if k.startswith("system_1:")}
        s2_stats = {k: v for k, v in model_stats.items() if k.startswith("system_2:")}

        s1_total = sum(v.get("calls", 0) for v in s1_stats.values())
        s2_total = sum(v.get("calls", 0) for v in s2_stats.values())
        total = s1_total + s2_total

        if total > 20:
            s1_ratio = s1_total / total
            if s1_ratio < 0.3:
                recommendations.append({
                    "type": "routing_balance",
                    "s1_ratio": round(s1_ratio, 2),
                    "suggestion": "Only {:.0%} of queries use System 1. "
                                  "Consider expanding the fast-path patterns to reduce latency.".format(s1_ratio),
                })
            elif s1_ratio > 0.85:
                recommendations.append({
                    "type": "routing_balance",
                    "s1_ratio": round(s1_ratio, 2),
                    "suggestion": "System 1 handles {:.0%} of queries — may be under-escalating. "
                                  "Check if complex queries are being answered shallowly.".format(s1_ratio),
                })

        return {
            "recommendations": recommendations,
            "summary": {
                "total_interactions": total,
                "system_1_ratio": round(s1_total / total, 2) if total else 0,
                "tools_tracked": len(tool_stats),
                "models_tracked": len(model_stats),
            },
        }

    # ── Skill Discovery ────────────────────────────────────────────────

    def discover_unregistered_tools(self, registered_tools: List[str]) -> List[Dict[str, str]]:
        """Scan app/tools/ for Python files that define BaseTool subclasses but aren't registered."""
        tools_dir = Path("app/tools")
        if not tools_dir.exists():
            return []

        discovered = []
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                # Look for BaseTool subclasses
                if "BaseTool" in content and "class " in content:
                    # Extract class name
                    import re
                    for match in re.finditer(r"class\s+(\w+)\s*\(\s*BaseTool\s*\)", content):
                        cls_name = match.group(1)
                        # Check if any tool name from this class is registered
                        # Simple heuristic: check if the module was imported
                        module_name = py_file.stem
                        is_registered = any(
                            module_name.lower() in t.lower() or cls_name.lower().replace("tool", "") in t.lower()
                            for t in registered_tools
                        )
                        if not is_registered:
                            discovered.append({
                                "file": str(py_file),
                                "class": cls_name,
                                "module": f"app.tools.{module_name}",
                            })
            except Exception:
                continue

        return discovered

    # ── Helpers ─────────────────────────────────────────────────────────

    def _load_json(self, path: Path) -> Optional[Dict]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_json(self, path: Path, data: Any) -> None:
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save %s: %s", path, exc)


# ── Module singleton ───────────────────────────────────────────────────

_FEEDBACK: InteractionFeedback | None = None


def get_feedback_tracker() -> InteractionFeedback:
    global _FEEDBACK
    if _FEEDBACK is None:
        _FEEDBACK = InteractionFeedback()
    return _FEEDBACK
