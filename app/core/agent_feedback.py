"""Agent Feedback System — agents can critique and improve each other's work.

FRIDAY-style: when Agent A produces output, Agent B can review it
and suggest improvements before the final synthesis.

Architecture:
  WorkerAgent (produces) → FeedbackCollector (gathers critiques)
  → SynthesizerAgent (integrates feedback) → Final Output

This creates a quality loop where specialist agents cross-check
each other's work, catching errors and blind spots.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Feedback:
    """A piece of feedback from one agent about another's work."""
    source_agent: str
    target_agent: str
    original_output: str
    critique: str
    suggestions: list[str] = field(default_factory=list)
    severity: str = "info"  # info, warning, critical
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class FeedbackResult:
    """Aggregated feedback from multiple agents."""
    original_output: str
    feedbacks: list[Feedback] = field(default_factory=list)
    revised_output: str | None = None
    overall_quality: str = "unreviewed"  # unreviewed, reviewed, improved

    @property
    def has_critical(self) -> bool:
        return any(f.severity == "critical" for f in self.feedbacks)

    @property
    def suggestion_count(self) -> int:
        return sum(len(f.suggestions) for f in self.feedbacks)


class FeedbackCollector:
    """Gathers feedback from agents about each other's outputs.

    After parallel execution, each agent's output is circulated
    to other agents for cross-checking.
    """

    def __init__(self) -> None:
        self._feedbacks: dict[str, list[Feedback]] = {}  # output_id → feedbacks

    def submit(
        self,
        source_agent: str,
        target_agent: str,
        original_output: str,
        critique: str,
        suggestions: list[str] | None = None,
        severity: str = "info",
    ) -> Feedback:
        """Submit feedback about another agent's output."""
        fb = Feedback(
            source_agent=source_agent,
            target_agent=target_agent,
            original_output=original_output,
            critique=critique,
            suggestions=suggestions or [],
            severity=severity,
        )
        key = f"{target_agent}:{original_output[:50]}"
        self._feedbacks.setdefault(key, []).append(fb)
        logger.info(
            "Feedback: %s → %s [%s] %s",
            source_agent, target_agent, severity, critique[:80],
        )
        return fb

    def get_for_output(self, agent_name: str, output_prefix: str = "") -> list[Feedback]:
        """Get all feedback for a specific agent's output."""
        results = []
        for key, fbs in self._feedbacks.items():
            if key.startswith(agent_name):
                results.extend(fbs)
        return results

    def build_result(self, agent_name: str, original_output: str) -> FeedbackResult:
        """Build a FeedbackResult for an agent's output."""
        feedbacks = self.get_for_output(agent_name)
        result = FeedbackResult(
            original_output=original_output,
            feedbacks=feedbacks,
        )
        if feedbacks:
            result.overall_quality = "reviewed"
        if result.has_critical:
            result.overall_quality = "needs_revision"
        return result

    def clear(self) -> None:
        self._feedbacks.clear()


class FeedbackSynthesizer:
    """Integrates feedback into a revised output.

    Takes the original output + feedbacks and produces an
    improved version that addresses the critiques.
    """

    @staticmethod
    def build_revision_prompt(result: FeedbackResult) -> str:
        """Build a prompt for the LLM to revise the output based on feedback."""
        lines = [
            "You are reviewing and improving an output based on peer feedback.",
            f"\n## Original Output\n{result.original_output}",
            "\n## Peer Feedback",
        ]
        for i, fb in enumerate(result.feedbacks, 1):
            lines.append(f"\n### Feedback {i} (from {fb.source_agent}, {fb.severity})")
            lines.append(f"**Critique:** {fb.critique}")
            if fb.suggestions:
                lines.append("**Suggestions:**")
                for s in fb.suggestions:
                    lines.append(f"- {s}")

        lines.append(
            "\n## Task\n"
            "Revise the original output to address the feedback. "
            "Keep the strengths, fix the weaknesses, and incorporate "
            "the suggestions where they improve the output. "
            "Return ONLY the revised output."
        )
        return "\n".join(lines)

    @staticmethod
    def merge_feedbacks(feedbacks: list[Feedback]) -> str:
        """Merge multiple feedbacks into a single summary."""
        if not feedbacks:
            return "No feedback received."

        lines = ["## Feedback Summary"]
        by_severity = {"critical": [], "warning": [], "info": []}
        for fb in feedbacks:
            by_severity.get(fb.severity, by_severity["info"]).append(fb)

        for severity in ("critical", "warning", "info"):
            items = by_severity[severity]
            if items:
                lines.append(f"\n### {severity.upper()} ({len(items)})")
                for fb in items:
                    lines.append(f"- [{fb.source_agent}] {fb.critique}")
                    for s in fb.suggestions:
                        lines.append(f"  → {s}")

        return "\n".join(lines)
