"""User Correction Learning — Raven learns from user corrections.

When a user says "no", "wrong", "that's incorrect", etc., Raven
extracts the correction, updates its memory, and adapts future
responses to avoid the same mistake.

Flow:
  1. Detect correction intent in user message
  2. Extract what was wrong and what's correct
  3. Update memory with the correction
  4. Store correction pattern for future avoidance
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Correction:
    """A user correction of Raven's output."""
    original_claim: str  # What Raven said
    corrected_claim: str  # What the user says is correct
    topic: str  # What category this falls under
    confidence: float = 1.0  # How confident we are in the correction
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Correction detection patterns
_CORRECTION_PATTERNS = [
    # Direct negation
    (r"(?:no|nope|wrong|incorrect|that'?s not right|that'?s wrong|actually[,.])", "negation"),
    # Correction with "it's" / "it is"
    (r"(?:it'?s|it is)\s+(?:actually|really|in fact)\s+(.+?)(?:\.|$)", "correction"),
    # "I said" / "I mean" / "I meant"
    (r"(?:i said|i mean|i meant|i was trying to say)\s+(.+?)(?:\.|$)", "repetition"),
    # "The correct" / "The right"
    (r"(?:the correct|the right|the actual)\s+(?:answer|value|name|is)\s+(?:is\s+)?(.+?)(?:\.|$)", "explicit"),
    # "Don't" / "Don't use"
    (r"(?:don'?t|do not)\s+(?:use|say|write|call|name)\s+(.+?)(?:\.|$)", "negative"),
]


class CorrectionDetector:
    """Detects when a user is correcting Raven's output."""

    @staticmethod
    def is_correction(user_message: str) -> bool:
        """Check if the user message contains a correction."""
        lower = user_message.lower()
        return any(re.search(pat, lower) for pat, _ in _CORRECTION_PATTERNS)

    @staticmethod
    def extract_correction(user_message: str, previous_output: str = "") -> Correction | None:
        """Extract the correction from a user message.

        Uses the previous output as context for what was wrong.
        """
        lower = user_message.lower()

        for pattern, kind in _CORRECTION_PATTERNS:
            m = re.search(pattern, lower)
            if m:
                corrected = m.group(1) if m.lastindex else ""
                # Determine topic from keywords
                topic = _detect_topic(lower)

                return Correction(
                    original_claim=previous_output[:200] if previous_output else "(unknown)",
                    corrected_claim=corrected or user_message.strip(),
                    topic=topic,
                )

        return None


def _detect_topic(text: str) -> str:
    """Detect the topic category of a correction."""
    if any(w in text for w in ("name", "called", "labeled")):
        return "naming"
    if any(w in text for w in ("date", "time", "when", "schedule")):
        return "temporal"
    if any(w in text for w in ("file", "path", "directory")):
        return "filesystem"
    if any(w in text for w in ("code", "function", "variable", "class")):
        return "code"
    if any(w in text for w in ("fact", "number", "data", "statistic")):
        return "factual"
    if any(w in text for w in ("preference", "style", "format")):
        return "preference"
    return "general"


class CorrectionStore:
    """Stores user corrections for future reference."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "corrections"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "corrections.jsonl"

    def save(self, correction: Correction) -> None:
        """Append a correction to the store."""
        import json
        data = {
            "original": correction.original_claim,
            "corrected": correction.corrected_claim,
            "topic": correction.topic,
            "confidence": correction.confidence,
            "timestamp": correction.timestamp,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def get_recent(self, n: int = 20) -> list[Correction]:
        """Get the last N corrections."""
        import json
        if not self._file.exists():
            return []
        lines = self._file.read_text(encoding="utf-8").strip().splitlines()
        corrections = []
        for line in lines[-n:]:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                corrections.append(Correction(
                    original_claim=d.get("original", ""),
                    corrected_claim=d.get("corrected", ""),
                    topic=d.get("topic", "general"),
                    confidence=d.get("confidence", 1.0),
                    timestamp=d.get("timestamp", ""),
                ))
            except Exception:
                continue
        return corrections

    def get_by_topic(self, topic: str) -> list[Correction]:
        """Get corrections for a specific topic."""
        return [c for c in self.get_recent(100) if c.topic == topic]

    def count(self) -> int:
        if not self._file.exists():
            return 0
        return sum(1 for line in self._file.read_text(encoding="utf-8").strip().splitlines() if line.strip())


class CorrectionLearner:
    """Processes user corrections and updates Raven's knowledge.

    Uses corrections to:
    1. Update memory with correct information
    2. Store patterns for future avoidance
    3. Adjust response style for the user
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.detector = CorrectionDetector()
        self.store = CorrectionStore(workspace_dir)

    async def process_correction(
        self,
        user_message: str,
        previous_output: str = "",
        user_id: str | None = None,
    ) -> Correction | None:
        """Detect and process a user correction.

        Returns the Correction if one was detected, None otherwise.
        """
        if not self.detector.is_correction(user_message):
            return None

        correction = self.detector.extract_correction(user_message, previous_output)
        if correction is None:
            return None

        # Save to store
        self.store.save(correction)

        # Update memory with the correction
        try:
            from app.core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            facade.remember(
                f"[Correction] {correction.topic}: {correction.corrected_claim}",
                user_id=user_id,
                category="RULE",
            )
        except Exception as exc:
            logger.debug("Failed to save correction to memory: %s", exc)

        logger.info(
            "Learned correction [%s]: %s → %s",
            correction.topic, correction.original_claim[:50], correction.corrected_claim[:50],
        )
        return correction

    def get_correction_context(self, user_id: str | None = None) -> str:
        """Build a context string from recent corrections.

        Injected into prompts to help Raven avoid past mistakes.
        """
        recent = self.store.get_recent(10)
        if not recent:
            return ""

        lines = ["## Past Corrections (learn from these)"]
        for c in recent:
            lines.append(f"- [{c.topic}] Wrong: {c.original_claim[:60]} → Correct: {c.corrected_claim[:60]}")

        return "\n".join(lines)
