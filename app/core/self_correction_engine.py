"""Self-Correction Engine — acknowledges and confirms user corrections.

When a user corrects Raven, this module generates a brief acknowledgment
message that confirms the correction was understood and will be applied
in future responses.

Flow:
  1. Detect correction in user message (via CorrectionLearner)
  2. Extract the corrected claim
  3. Generate a natural acknowledgment
  4. Send as follow-up
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SelfCorrectionEngine:
    """Generates acknowledgment responses to user corrections.

    Runs after ``execute_turn()`` in the orchestrator.  If the user's
    message is a correction, the engine crafts a brief confirmation and
    sends it as a follow-up, so the user knows the correction stuck.
    """

    async def process(
        self,
        user_message: str,
        turn_result: dict[str, Any] | None,
        provider: Any | None = None,
    ) -> str | None:
        """Check if the message is a correction and return an acknowledgment.

        Args:
            user_message: The raw user message.
            turn_result: Dict from ``execute_turn()``.
            provider: Optional LLM provider for generating a natural
                acknowledgment.  Falls back to a template if ``None``.

        Returns:
            An acknowledgment string to send, or ``None`` if the
            message is not a correction.
        """
        correction = self._detect_correction(user_message)
        if correction is None:
            return None

        corrected_claim = correction.get("corrected", "") or correction.get("claim", "")
        topic = correction.get("topic", "general")

        if provider is not None:
            try:
                return await self._llm_acknowledgment(provider, corrected_claim, topic)
            except Exception as exc:
                logger.debug("LLM acknowledgment failed: %s", exc)

        return self._template_acknowledgment(corrected_claim, topic)

    @staticmethod
    def _detect_correction(
        user_message: str,
    ) -> dict[str, str] | None:
        """Detect a correction using CorrectionLearner."""
        try:
            from app.core.correction_learner import CorrectionDetector

            detector = CorrectionDetector()
            if not detector.is_correction(user_message):
                return None

            correction = detector.extract_correction(user_message)
            if correction is None:
                return None

            return {
                "original": correction.original_claim,
                "corrected": correction.corrected_claim,
                "topic": correction.topic,
            }
        except Exception as exc:
            logger.debug("Correction detection failed: %s", exc)
            return None

    @staticmethod
    async def _llm_acknowledgment(
        provider: Any,
        corrected_claim: str,
        topic: str,
    ) -> str:
        """Generate a natural acknowledgment using the LLM."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Raven. A user just corrected you. "
                    "Respond with a brief, natural acknowledgment "
                    "(1-2 sentences) that confirms the correction "
                    "and shows you've learned from it. "
                    "Do not apologize excessively. Be warm and precise."
                ),
            },
            {
                "role": "user",
                "content": f"Correction ({topic}): {corrected_claim}",
            },
        ]

        result = await provider.chat_completion_resilient(
            messages=messages,
            temperature=0.5,
            max_tokens=150,
        )
        return (result or {}).get("content", "").strip()

    @staticmethod
    def _template_acknowledgment(corrected_claim: str, topic: str) -> str:
        """Fallback template-based acknowledgment."""
        templates = {
            "naming": f'Got it — I\'ll use "{corrected_claim}" going forward.',
            "temporal": f'Thanks, I\'ve updated the time/date to "{corrected_claim}".',
            "filesystem": f'Noted — I\'ll use "{corrected_claim}" for that path.',
            "code": f"Fixed — I'll remember that {corrected_claim}.",
            "factual": f"Thanks for the correction — I've updated my knowledge: {corrected_claim}.",
            "preference": f"Got it, I'll keep that preference in mind: {corrected_claim}.",
        }
        return templates.get(
            topic,
            f"Thanks for the correction — I'll remember: {corrected_claim}.",
        )


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_ENGINE: SelfCorrectionEngine | None = None


def get_self_correction_engine() -> SelfCorrectionEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = SelfCorrectionEngine()
    return _GLOBAL_ENGINE
