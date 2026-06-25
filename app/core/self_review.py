"""Self-Improvement Review Cycle — Hermes Agent-style after-turn reflection.

Runs after each turn completes. The reviewer:
1. Records the interaction for later analysis
2. Identifies improvement opportunities (missing skills, memory gaps)
3. Queues actionable items for the agent to address in future turns

This is the core of the autonomous self-evolution loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SelfReviewCycle:
    """Post-turn self-improvement reviewer.

    Records every turn, identifies patterns, and queues improvement
    suggestions for the agent to act on.
    """

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        if workspace_dir is None:
            from app.settings.config import Config
            workspace_dir = Path(getattr(Config, "MEMORY_ROOT", "workspace"))
        self._workspace_dir = Path(workspace_dir)
        self._log_dir = self._workspace_dir / "memory" / "self_review"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._suggestions_file = self._log_dir / "suggestions.jsonl"

    async def review_turn(
        self,
        user_message: str,
        response: str,
        tool_calls: list[dict[str, Any]],
        success: bool,
        latency_ms: float,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Analyze a completed turn and record improvement opportunities.

        Returns a review record with any suggestions generated.
        """
        review = self._build_review(
            user_message=user_message,
            response=response,
            tool_calls=tool_calls,
            success=success,
            latency_ms=latency_ms,
            session_id=session_id,
        )
        self._log_review(review)

        suggestions = self._generate_suggestions(review)
        if suggestions:
            for suggestion in suggestions:
                self._queue_suggestion(suggestion)
            review["suggestions"] = suggestions

        return review

    def _build_review(
        self,
        user_message: str,
        response: str,
        tool_calls: list[dict[str, Any]],
        success: bool,
        latency_ms: float,
        session_id: str | None,
    ) -> dict[str, Any]:
        tool_count = len(tool_calls)
        failed_tools = [
            tc.get("tool", "unknown") for tc in tool_calls if not tc.get("success", False)
        ]
        response_length = len(response)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "",
            "user_message_length": len(user_message),
            "response_length": response_length,
            "tool_calls_count": tool_count,
            "failed_tools": failed_tools,
            "success": success,
            "latency_ms": latency_ms,
            "quality_signals": {
                "has_failures": len(failed_tools) > 0,
                "very_short_response": response_length < 20 and tool_count > 0,
                "no_tools_used": tool_count == 0,
                "high_latency": latency_ms > 30000,
            },
        }

    def _generate_suggestions(self, review: dict[str, Any]) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        signals = review.get("quality_signals", {})

        if signals.get("has_failures"):
            for tool in review.get("failed_tools", []):
                suggestions.append({
                    "type": "tool_fix",
                    "priority": "high",
                    "message": f"Tool '{tool}' failed during this turn. Consider adding a fallback or checking configuration.",
                    "tool": tool,
                })

        if signals.get("very_short_response"):
            suggestions.append({
                "type": "response_quality",
                "priority": "medium",
                "message": "Response was very short relative to tool usage. Consider providing more context in the result.",
            })

        if signals.get("no_tools_used"):
            suggestions.append({
                "type": "tool_discovery",
                "priority": "low",
                "message": "No tools were used in this turn. Consider if any tool could have helped.",
            })

        return suggestions

    def _log_review(self, review: dict[str, Any]) -> None:
        day_dir = self._log_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        log_file = day_dir / "reviews.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(review, ensure_ascii=True) + "\n")
        except Exception as e:
            logger.debug("Failed to log self-review: %s", e)

    def _queue_suggestion(self, suggestion: dict[str, Any]) -> None:
        try:
            with open(self._suggestions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(suggestion, ensure_ascii=True) + "\n")
        except Exception as e:
            logger.debug("Failed to queue suggestion: %s", e)

    def get_pending_suggestions(self) -> list[dict[str, Any]]:
        if not self._suggestions_file.exists():
            return []
        suggestions: list[dict[str, Any]] = []
        try:
            for line in self._suggestions_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    suggestions.append(json.loads(line))
        except Exception as e:
            logger.error("Failed to load suggestions: %s", e)
        return suggestions

    def clear_suggestions(self) -> None:
        try:
            self._suggestions_file.write_text("", encoding="utf-8")
        except Exception as e:
            logger.error("Failed to clear suggestions: %s", e)

    def get_review_summary(self, days: int = 7) -> dict[str, Any]:
        total_reviews = 0
        total_suggestions = 0
        tool_failures: dict[str, int] = {}
        quality_issues = 0

        start_date = datetime.now(timezone.utc)
        for i in range(days):
            day_dir = self._log_dir / (start_date - __import__("datetime").timedelta(days=i)).strftime("%Y-%m-%d")
            if not day_dir.exists():
                continue
            log_file = day_dir / "reviews.jsonl"
            if not log_file.exists():
                continue
            try:
                for line in log_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    total_reviews += 1
                    review = json.loads(line)
                    for tool in review.get("failed_tools", []):
                        tool_failures[tool] = tool_failures.get(tool, 0) + 1
                    if any(review.get("quality_signals", {}).values()):
                        quality_issues += 1
            except Exception:
                continue

        suggestions = self.get_pending_suggestions()
        total_suggestions = len(suggestions)

        return {
            "period_days": days,
            "total_reviews": total_reviews,
            "total_suggestions": total_suggestions,
            "quality_issues": quality_issues,
            "tool_failures": dict(sorted(tool_failures.items(), key=lambda x: -x[1])[:10]),
            "success_rate": round(
                (total_reviews - quality_issues) / max(total_reviews, 1) * 100, 1
            ),
        }


# Module-level singleton
_reviewer: SelfReviewCycle | None = None


def get_self_reviewer(workspace_dir: str | Path | None = None) -> SelfReviewCycle:
    global _reviewer
    if _reviewer is None:
        _reviewer = SelfReviewCycle(workspace_dir=workspace_dir)
    return _reviewer
