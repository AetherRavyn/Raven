from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.learning_db import get_learning_store

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """You are a reflection engine analyzing an interaction between a user and an AI assistant.

Determine if the user's message contains a **correction** — that is, the user is telling the assistant that
something it said or did was wrong. This could be:
- Factual correction ("Actually, the capital is Paris, not London")
- Preference correction ("I asked for JSON, not XML")
- Naming correction ("The file is called config.yaml, not settings.yaml")
- Procedural correction ("You should have used the search tool, not the file tool")

If the message IS a correction, respond with a JSON object:
{{"is_correction": true, "topic": "the topic", "corrected_claim": "the corrected fact", "wrong_segment": "what was wrong", "confidence": 0.95}}

If the message is NOT a correction, respond with:
{{"is_correction": false}}

User message: {user_message}
Assistant response: {assistant_response}

Return ONLY valid JSON, no other text.
"""


@dataclass
class ReflectionResult:
    is_correction: bool = False
    topic: str = ""
    corrected_claim: str = ""
    wrong_segment: str = ""
    confidence: float = 0.0
    raw_response: str = ""


class LearnedReflector:
    """LLM-based reflection engine for detecting corrections.

    Replaces the regex-based ``CorrectionDetector`` with a learned
    classifier that improves over time via feedback tracking.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider
        self._store = get_learning_store()
        self._correction_count = 0

    # ── public API ──────────────────────────────────────────────────────

    async def reflect(
        self,
        user_message: str,
        assistant_response: str = "",
    ) -> ReflectionResult:
        """Analyze a user message for corrections using the LLM provider."""
        return (
            self._sync_reflect(user_message, assistant_response)
            if self._provider is None
            else await self._llm_reflect(user_message, assistant_response)
        )

    def _sync_reflect(self, user_message: str, assistant_response: str = "") -> ReflectionResult:
        """Synchronous reflection path (heuristic fallback)."""
        if not user_message or not user_message.strip():
            return ReflectionResult()

        trivial = self._quick_check(user_message)
        if trivial is not None:
            return trivial

        return self._fallback_reflect(user_message, assistant_response)

    def record_and_store(self, result: ReflectionResult, source: str = "reflection") -> int | None:
        """Store a confirmed reflection in the learning store. Returns learning id."""
        if not result.is_correction or not result.corrected_claim:
            return None

        id_ = self._store.add(
            type_="correction",
            content=result.corrected_claim,
            topic=result.topic,
            confidence=result.confidence,
            metadata={
                "wrong_segment": result.wrong_segment,
                "raw_response": result.raw_response,
                "source": source,
            },
            source=source,
        )
        self._correction_count += 1
        logger.info(
            "Reflection stored: [%s] %s (confidence=%.2f)",
            result.topic,
            result.corrected_claim[:60],
            result.confidence,
        )
        return id_

    @property
    def total_corrections(self) -> int:
        return self._correction_count

    # ── internal ────────────────────────────────────────────────────────

    async def _llm_reflect(self, user_message: str, assistant_response: str) -> ReflectionResult:
        prompt = REFLECTION_PROMPT.format(
            user_message=user_message[:2000],
            assistant_response=assistant_response[:1000],
        )

        try:
            response = await self._provider.chat_completion(
                model="",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise reflection engine. Output only JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=300,
            )

            content = ""
            if isinstance(response, dict):
                content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

            result = self._parse_response(content)
            result.raw_response = content
            if not result.is_correction and content.strip():
                return self._fallback_reflect(user_message, assistant_response)
            return result

        except Exception as exc:
            logger.debug("LLM reflection failed: %s", exc)
            return self._fallback_reflect(user_message, assistant_response)

    def _parse_response(self, content: str) -> ReflectionResult:
        result = ReflectionResult(raw_response=content)
        try:
            # Extract JSON from response (handle markdown fences)
            json_str = content.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)
            result.is_correction = data.get("is_correction", False)
            if result.is_correction:
                result.topic = data.get("topic", "")
                result.corrected_claim = data.get("corrected_claim", "")
                result.wrong_segment = data.get("wrong_segment", "")
                result.confidence = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("Failed to parse reflection JSON: %s", exc)
            result.is_correction = False

        return result

    def _quick_check(self, message: str) -> ReflectionResult | None:
        """Quick regex-based pre-check for obvious non-corrections."""
        msg = message.strip().lower()
        greetings = {
            "hello",
            "hi",
            "hey",
            "thanks",
            "thank you",
            "ok",
            "okay",
            "yes",
            "no",
            "goodbye",
            "bye",
        }
        if msg.rstrip("!.,?") in greetings:
            return ReflectionResult()
        return None

    def _fallback_reflect(self, user_message: str, assistant_response: str) -> ReflectionResult:
        """Fallback heuristic when LLM is unavailable."""
        from app.core.correction_learner import CorrectionDetector

        is_corr = CorrectionDetector.is_correction(user_message)
        if not is_corr:
            return ReflectionResult()

        corr = CorrectionDetector.extract_correction(user_message)
        if not corr:
            return ReflectionResult()

        return ReflectionResult(
            is_correction=True,
            topic=corr.topic,
            corrected_claim=corr.corrected_claim,
            wrong_segment=corr.wrong_segment or "",
            confidence=corr.confidence * 0.8,  # discount heuristic
        )


# Singleton
_reflector: LearnedReflector | None = None


def get_reflector(provider: Any | None = None) -> LearnedReflector:
    global _reflector
    if _reflector is None:
        _reflector = LearnedReflector(provider=provider)
    return _reflector
