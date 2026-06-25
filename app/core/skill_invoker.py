"""Skill Invoker — Auto-invokes skills matching user queries.

When a user message matches a skill's trigger patterns with high confidence,
the SkillInvoker can:
1. Inject the skill's instructions into the system prompt
2. Log the invocation for learning
3. Track success/failure for skill improvement

This is the runtime component that makes skills "active" rather than passive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillInvocation:
    """Record of a skill being invoked."""

    skill_id: str
    skill_name: str
    query: str
    match_confidence: float
    success: bool = True
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    feedback: str = ""


class SkillInvoker:
    """Checks for matching skills and manages invocations.

    Usage:
        invoker = SkillInvoker()
        matches = invoker.check_matches("review my code")
        if matches:
            skill_text = invoker.get_skill_text(matches[0])
            # Inject into system prompt
    """

    def __init__(self, min_confidence: float = 0.6, max_skills: int = 3) -> None:
        self._min_confidence = min_confidence
        self._max_skills = max_skills
        self._invocation_history: list[SkillInvocation] = []
        self._max_history = 100

    def check_matches(self, query: str) -> list[dict[str, Any]]:
        """Check if any skills match the query.

        Returns list of matching skill records with match_confidence.
        """
        try:
            from app.core.skill_registry import SkillRegistry

            registry = SkillRegistry()
            return registry.match_skills(query, self._min_confidence)[:self._max_skills]
        except Exception as exc:
            logger.debug("Skill matching failed: %s", exc)
            return []

    def get_skill_text(self, skill_record: dict[str, Any]) -> str:
        """Get the instruction text for a skill record."""
        body = skill_record.get("body", "").strip()
        name = skill_record.get("display_name", "Unknown Skill")
        confidence = skill_record.get("match_confidence", 0)
        if body:
            return f"### {name} (match: {confidence:.0%})\n{body}"
        return ""

    def get_matched_skills_text(self, query: str) -> str:
        """Get concatenated skill texts for all matching skills."""
        try:
            from app.core.skill_registry import SkillRegistry

            registry = SkillRegistry()
            return registry.get_matched_skill_texts(
                query, self._min_confidence, self._max_skills
            )
        except Exception as exc:
            logger.debug("Skill text retrieval failed: %s", exc)
            return ""

    def record_invocation(
        self,
        skill_id: str,
        skill_name: str,
        query: str,
        confidence: float,
        success: bool = True,
        feedback: str = "",
    ) -> None:
        """Record a skill invocation for learning and improvement."""
        invocation = SkillInvocation(
            skill_id=skill_id,
            skill_name=skill_name,
            query=query,
            match_confidence=confidence,
            success=success,
            feedback=feedback,
        )
        self._invocation_history.append(invocation)
        if len(self._invocation_history) > self._max_history:
            self._invocation_history = self._invocation_history[-self._max_history:]

        # Also record in the skill learner for long-term tracking
        try:
            import asyncio
            from app.core.skill_learner import get_skill_learner

            learner = get_skill_learner()

            async def _record():
                await learner.record_invocation(skill_id, success, feedback)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_record())
            except RuntimeError:
                pass
        except Exception as exc:
            logger.debug("Skill learner recording failed: %s", exc)

    def get_invocation_stats(self) -> dict[str, Any]:
        """Get statistics about skill invocations."""
        if not self._invocation_history:
            return {"total": 0, "success_rate": 0, "skills_used": {}}

        total = len(self._invocation_history)
        successes = sum(1 for i in self._invocation_history if i.success)

        skills_used: dict[str, int] = {}
        for inv in self._invocation_history:
            skills_used[inv.skill_name] = skills_used.get(inv.skill_name, 0) + 1

        return {
            "total": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": successes / total if total > 0 else 0,
            "skills_used": skills_used,
            "recent": [
                {
                    "skill": i.skill_name,
                    "query": i.query[:50],
                    "confidence": i.match_confidence,
                    "success": i.success,
                    "timestamp": i.timestamp,
                }
                for i in self._invocation_history[-10:]
            ],
        }


# Module singleton
_INVOKER: SkillInvoker | None = None


def get_skill_invoker() -> SkillInvoker:
    """Get or create the global SkillInvoker instance."""
    global _INVOKER
    if _INVOKER is None:
        _INVOKER = SkillInvoker()
    return _INVOKER


def reset_skill_invoker_for_tests() -> None:
    """Drop the cached singleton.  Tests use this between
    cases so the module state doesn't leak across tests."""
    global _INVOKER
    _INVOKER = None
