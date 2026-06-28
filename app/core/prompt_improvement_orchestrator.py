"""Prompt Improvement Orchestrator — Raven's self-improvement loop.

Connects feedback sources (corrections, uncertainty, self-review) to the
PromptImprover system.  Generates targeted LLM-powered prompt adjustments
that are injected into the system prompt on future turns.

Flow:
  1. Collect signals from CorrectionLearner, UncertaintyEstimator,
     SelfReviewCycle, and InteractionTracker
  2. Build a compact summary of recent failure patterns
  3. Use the LLM to generate specific, actionable prompt adjustments
  4. Feed adjustments into PromptImprover so they appear in every
     subsequent system prompt
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PromptImprovementOrchestrator:
    """Orchestrates closed-loop prompt improvement from feedback signals.

    Designed to be called periodically (e.g., every N turns or on a
    schedule) to keep the system prompt evolving with the user's needs.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        self._last_review_path = (
            Path(workspace_dir or ".") / "memory" / "prompt_improvements" / "last_review.json"
        )

    async def review_and_improve(
        self,
        turn_result: dict[str, Any] | None = None,
        query: str = "",
        provider: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Run one review cycle: collect signals → generate improvements.

        Args:
            turn_result: The most recent turn result (optional).
            query: The most recent user query (optional).
            provider: LLM provider for generating improvements.  If
                None, falls back to rule-based analysis.

        Returns:
            A list of improvement dicts generated (empty if none).
        """
        # 1. Collect signals from all feedback sources
        corrections = self._collect_corrections()
        suggestions = self._collect_self_review_suggestions()
        interactions = self._collect_interactions()
        confidence = self._get_confidence(turn_result, query)

        # 2. Check if any new signals exist since last review
        if not self._has_new_signals(corrections, suggestions, interactions):
            return []

        # 3. Generate improvements
        if provider is not None:
            improvements = await self._generate_llm_improvements(
                provider=provider,
                corrections=corrections,
                suggestions=suggestions,
                interactions=interactions,
                confidence=confidence,
                query=query,
            )
        else:
            improvements = self._generate_rule_improvements(
                corrections=corrections,
                suggestions=suggestions,
                interactions=interactions,
            )

        # 4. Feed into PromptImprover
        if improvements:
            self._apply_improvements(improvements)

        # 5. Record this review
        self._record_review(improvements)

        return improvements

    # ── Signal Collection ───────────────────────────────────────────

    def _collect_corrections(self) -> list[dict[str, Any]]:
        """Fetch recent corrections from CorrectionLearner."""
        try:
            from app.core.correction_learner import CorrectionStore

            store = CorrectionStore(self._workspace_dir)
            recents = store.get_recent(20)
            return [
                {
                    "topic": c.topic,
                    "original": c.original_claim[:120],
                    "corrected": c.corrected_claim[:120],
                }
                for c in recents
            ]
        except Exception as exc:
            logger.debug("Failed to collect corrections: %s", exc)
            return []

    def _collect_self_review_suggestions(self) -> list[dict[str, Any]]:
        """Fetch pending suggestions from SelfReviewCycle."""
        try:
            from app.core.self_review import get_self_reviewer

            reviewer = get_self_reviewer(self._workspace_dir)
            return reviewer.get_pending_suggestions()
        except Exception as exc:
            logger.debug("Failed to collect self-review suggestions: %s", exc)
            return []

    def _collect_interactions(self) -> list[dict[str, Any]]:
        """Fetch recent interactions from InteractionTracker."""
        try:
            from app.core.prompt_improver import InteractionTracker

            tracker = InteractionTracker(self._workspace_dir)
            recents = tracker.get_recent(50)
            return [
                {
                    "success": r.success,
                    "failure_reason": r.failure_reason[:100],
                    "query": r.query[:100],
                    "duration_ms": r.duration_ms,
                    "user_feedback": r.user_feedback,
                }
                for r in recents
            ]
        except Exception as exc:
            logger.debug("Failed to collect interactions: %s", exc)
            return []

    @staticmethod
    def _get_confidence(turn_result: dict[str, Any] | None, query: str) -> float | None:
        """Get the confidence score from UncertaintyEstimator."""
        if not turn_result:
            return None
        try:
            from app.core.uncertainty import get_uncertainty_estimator

            estimator = get_uncertainty_estimator()
            return estimator.estimate(turn_result, query)
        except Exception as exc:
            logger.debug("Failed to get confidence: %s", exc)
            return None

    # ── Review State ───────────────────────────────────────────────

    def _has_new_signals(
        self,
        corrections: list,
        suggestions: list,
        interactions: list,
    ) -> bool:
        """Check if there are new signals since the last review."""
        if not self._last_review_path.exists():
            return bool(corrections or suggestions or interactions)

        try:
            last = json.loads(self._last_review_path.read_text(encoding="utf-8"))
            last_count = last.get("signal_counts", {})
            current = {
                "corrections": len(corrections),
                "suggestions": len(suggestions),
                "interactions": len(interactions),
            }
            return any(current[k] > last_count.get(k, 0) for k in current)
        except Exception:
            return True

    def _record_review(self, improvements: list[dict[str, Any]]) -> None:
        """Save the review state for next comparison."""
        try:
            self._last_review_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "timestamp": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
                "signal_counts": {
                    "corrections": len(self._collect_corrections()),
                    "suggestions": len(self._collect_self_review_suggestions()),
                    "interactions": len(self._collect_interactions()),
                },
                "improvements_generated": len(improvements),
            }
            self._last_review_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Failed to record review: %s", exc)

    # ── Improvement Generation ─────────────────────────────────────

    async def _generate_llm_improvements(
        self,
        provider: Any,
        corrections: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        interactions: list[dict[str, Any]],
        confidence: float | None,
        query: str,
    ) -> list[dict[str, Any]]:
        """Use the LLM to analyze signals and generate adjustments."""
        # Build a compact summary for the LLM
        summary_parts = ["## Current State"]

        if corrections:
            topics = {}
            for c in corrections:
                topics[c["topic"]] = topics.get(c["topic"], 0) + 1
            topic_summary = ", ".join(f"{k}: {v}" for k, v in topics.items())
            summary_parts.append(f"Recent corrections by topic: {topic_summary}")
            summary_parts.append(
                "Latest correction: "
                + corrections[-1]["original"]
                + " → "
                + corrections[-1]["corrected"]
            )

        if suggestions:
            types = {}
            for s in suggestions:
                t = s.get("type", "unknown")
                types[t] = types.get(t, 0) + 1
            summary_parts.append(
                "Pending suggestions: " + ", ".join(f"{k}: {v}" for k, v in types.items())
            )

        if interactions:
            failures = [i for i in interactions if not i["success"]]
            feedback_issues = [i for i in interactions if i.get("user_feedback") == "bad"]
            if failures:
                reasons = {}
                for f in failures:
                    r = f.get("failure_reason", "unknown") or "unknown"
                    reasons[r] = reasons.get(r, 0) + 1
                top_reason = max(reasons, key=lambda r: reasons[r])
                summary_parts.append(
                    f"Recent failures: {len(failures)}/{len(interactions)} turns "
                    f"(top reason: {top_reason})"
                )
            if feedback_issues:
                summary_parts.append(f"Negative feedback on {len(feedback_issues)} recent turns")

        if confidence is not None:
            summary_parts.append(f"Last-turn confidence: {confidence:.2f}")

        summary = "\n".join(summary_parts)
        last_query = f"\nLast query: {query[:200]}" if query else ""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Raven's self-improvement engine. "
                    "Analyze the following signal summary and generate "
                    "specific, actionable improvements to the system prompt. "
                    "Each improvement must be a concise instruction that Raven "
                    "can follow on every subsequent response.\n\n"
                    "Respond with a JSON array of objects, each with:\n"
                    "- category: one of (tone, detail_level, tool_usage, "
                    "response_format, efficiency, memory, reasoning, safety)\n"
                    "- adjustment: the specific instruction (1-2 sentences)\n"
                    "- reason: why this improvement is needed\n"
                    "- confidence: float 0.0-1.0\n\n"
                    "Return [] if no improvements are warranted."
                ),
            },
            {
                "role": "user",
                "content": summary + last_query,
            },
        ]

        try:
            result = await provider.chat_completion_resilient(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
            raw = (result or {}).get("content", "[]")
            improvements = json.loads(raw)
            if isinstance(improvements, list):
                return improvements
            return []
        except Exception as exc:
            logger.debug("LLM prompt improvement failed: %s", exc)
            return self._generate_rule_improvements(corrections, suggestions, interactions)

    def _generate_rule_improvements(
        self,
        corrections: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        interactions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fallback rule-based improvement generation."""
        improvements: list[dict[str, Any]] = []

        # From corrections: detect top correction topics
        if corrections:
            topics = {}
            for c in corrections:
                topics[c["topic"]] = topics.get(c["topic"], 0) + 1
            top_topic = max(topics, key=lambda t: topics[t])
            improvements.append(
                {
                    "category": "memory",
                    "adjustment": (
                        f"Pay extra attention to {top_topic}-related details. "
                        "Users have corrected these frequently."
                    ),
                    "reason": f"{topics[top_topic]} recent corrections in '{top_topic}' category",
                    "confidence": 0.7,
                }
            )

        # From self-review suggestions: tool failures
        if suggestions:
            tool_suggestions = [s for s in suggestions if s.get("type") == "tool_fix"]
            if tool_suggestions:
                tools = {s.get("tool", "?") for s in tool_suggestions}
                improvements.append(
                    {
                        "category": "tool_usage",
                        "adjustment": (
                            f"Be more careful with tools: {', '.join(tools)}. "
                            "Verify inputs before calling."
                        ),
                        "reason": f"{len(tool_suggestions)} tool failure suggestions",
                        "confidence": 0.6,
                    }
                )

        # From interactions: high failure rate
        if interactions:
            failures = [i for i in interactions if not i["success"]]
            if len(failures) > max(3, len(interactions) * 0.2):
                improvements.append(
                    {
                        "category": "efficiency",
                        "adjustment": (
                            "When a tool fails, immediately try an alternative "
                            "approach rather than retrying the same tool."
                        ),
                        "reason": f"High failure rate: {len(failures)}/{len(interactions)}",
                        "confidence": 0.8,
                    }
                )

            feedback_issues = [i for i in interactions if i.get("user_feedback") == "bad"]
            if feedback_issues:
                long_responses = [i for i in feedback_issues if len(i.get("query", "")) > 0]
                if len(long_responses) > len(feedback_issues) * 0.3:
                    improvements.append(
                        {
                            "category": "detail_level",
                            "adjustment": (
                                "Keep responses concise. Lead with the key "
                                "information, add details only if relevant."
                            ),
                            "reason": f"{len(feedback_issues)} negative feedback items",
                            "confidence": 0.6,
                        }
                    )

        return improvements

    # ── Apply to PromptImprover ────────────────────────────────────

    def _apply_improvements(self, improvements: list[dict[str, Any]]) -> None:
        """Feed generated improvements into the PromptImprover."""
        try:
            from app.core.prompt_improver import PromptAdjustment, PromptImprover

            improver = PromptImprover(self._workspace_dir)
            for imp in improvements:
                adjustment = PromptAdjustment(
                    category=imp.get("category", "general"),
                    adjustment=imp.get("adjustment", ""),
                    reason=imp.get("reason", ""),
                    confidence=imp.get("confidence", 0.5),
                )
                improver.add_adjustment(adjustment)

            logger.info("Applied %d prompt improvements", len(improvements))
        except Exception as exc:
            logger.debug("Failed to apply improvements: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_ORCHESTRATOR: PromptImprovementOrchestrator | None = None


def get_prompt_improvement_orchestrator(
    workspace_dir: str | None = None,
) -> PromptImprovementOrchestrator:
    global _GLOBAL_ORCHESTRATOR
    if _GLOBAL_ORCHESTRATOR is None:
        _GLOBAL_ORCHESTRATOR = PromptImprovementOrchestrator(workspace_dir=workspace_dir)
    return _GLOBAL_ORCHESTRATOR
