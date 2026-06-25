"""Emotional voice tone — maps text sentiment to TTS parameters.

FRIDAY's signature: voice that matches the emotional context.

Sentiment detection is keyword-based (no LLM needed for speed).
Output is a set of TTS parameters that the pipeline applies.

Usage:
    from app.voice.emotion import detect_emotion, EmotionParams
    params = detect_emotion("Great news! You've been promoted!")
    # params.speed = 1.1, params.pitch = 1.05, params.energy = "high"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class EmotionParams:
    """TTS parameters derived from emotional tone."""
    emotion: str = "neutral"  # neutral, happy, sad, urgent, calm, excited, angry, concerned
    speed: float = 1.0  # 0.7 = slow, 1.0 = normal, 1.3 = fast
    pitch: float = 1.0  # 0.85 = low, 1.0 = normal, 1.15 = high
    energy: str = "normal"  # low, normal, high
    emphasis_words: list[str] = field(default_factory=list)  # words to stress
    pause_after: float = 0.0  # seconds of pause after this segment
    voice_variant: str | None = None  # override voice model if available


# ── Keyword lexicons ────────────────────────────────────────────

_HAPPY_WORDS = {
    "great", "excellent", "awesome", "fantastic", "wonderful", "perfect",
    "brilliant", "amazing", "love", "nice", "good", "well done",
    "congratulations", "success", "won", "achieved", "completed",
    "beautiful", "excited", "thrilled", "delighted", "celebrate",
}

_SAD_WORDS = {
    "sad", "sorry", "unfortunately", "failed", "lost", "missed",
    "cancelled", "denied", "rejected", "broken", "damaged", "regret",
    "apologize", "condolences", "disappointed", "grief", "pain",
}

_URGENT_WORDS = {
    "urgent", "immediately", "asap", "emergency", "critical", "alert",
    "warning", "danger", "help", "now", "hurry", "quick", "fast",
    "deadline", "overdue", "late", "rushing", "panic",
}

_ANGRY_WORDS = {
    "angry", "furious", "outraged", "unacceptable", "terrible",
    "horrible", "worst", "hate", "stupid", "incompetent", "fail",
    "frustrated", "annoyed", "irritated", "ridiculous",
}

_CONCERNED_WORDS = {
    "worried", "concerned", "afraid", "fear", "risk", "threat",
    "vulnerable", "exposed", "unsafe", "careful", "caution",
    "attention", "notice", "observed", "detected",
}

_CALM_WORDS = {
    "calm", "relax", "peace", "quiet", "gentle", "soft", "smooth",
    "easy", "simple", "comfortable", "rest", "breathe", "steady",
}

_EXCITED_WORDS = {
    "wow", "incredible", "unbelievable", "insane", "epic",
    "breakthrough", "revolutionary", "game changer", "milestone",
    "record", "first ever", "never before", "groundbreaking",
}

_EXCLAMATION_PATTERNS = [
    (r"!{2,}", "excited"),      # multiple exclamation marks
    (r"\?{2,}", "urgent"),      # multiple question marks
    (r"[A-Z]{3,}", "emphasis"),  # ALL CAPS words
]

_SENTENCE_PATTERNS = [
    (r"(?:^|\.)\s*Good (?:morning|afternoon|evening|night)", "happy"),
    (r"(?:^|\.)\s*Hey\b", "neutral"),
    (r"(?:^|\.)\s*Oh (?:no|dear|god)", "concerned"),
    (r"(?:^|\.)\s*Wait\b", "urgent"),
]


def detect_emotion(text: str) -> EmotionParams:
    """Detect emotional tone from text and return TTS parameters.

    Pure keyword/regex — no LLM, no dependencies, sub-millisecond.
    """
    lower = text.lower()
    words = set(lower.split())
    scores: dict[str, int] = {
        "happy": 0, "sad": 0, "urgent": 0, "angry": 0,
        "concerned": 0, "calm": 0, "excited": 0,
    }

    # Word matching
    scores["happy"] += len(words & _HAPPY_WORDS)
    scores["sad"] += len(words & _SAD_WORDS)
    scores["urgent"] += len(words & _URGENT_WORDS)
    scores["angry"] += len(words & _ANGRY_WORDS)
    scores["concerned"] += len(words & _CONCERNED_WORDS)
    scores["calm"] += len(words & _CALM_WORDS)
    scores["excited"] += len(words & _EXCITED_WORDS)

    # Pattern matching
    for pattern, emotion in _EXCLAMATION_PATTERNS:
        if re.search(pattern, text):
            scores[emotion] += 2

    for pattern, emotion in _SENTENCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            scores[emotion] += 2

    # Length-based signals
    if len(text) < 20:
        scores["calm"] += 1  # short = composed
    if len(text) > 200:
        scores["excited"] += 1  # long = passionate

    # Determine dominant emotion
    max_score = max(scores.values())
    if max_score == 0:
        emotion = "neutral"
    else:
        emotion = max(scores, key=scores.get)

    # Map emotion to TTS parameters
    params = _emotion_to_params(emotion)
    params.emphasis_words = list(words & (_URGENT_WORDS | _EXCITED_WORDS | _ANGRY_WORDS))

    return params


def _emotion_to_params(emotion: str) -> EmotionParams:
    """Map detected emotion to concrete TTS parameters."""
    if emotion == "happy":
        return EmotionParams(emotion="happy", speed=1.05, pitch=1.05, energy="high", pause_after=0.1)
    elif emotion == "sad":
        return EmotionParams(emotion="sad", speed=0.9, pitch=0.95, energy="low", pause_after=0.3)
    elif emotion == "urgent":
        return EmotionParams(emotion="urgent", speed=1.15, pitch=1.0, energy="high", pause_after=0.0)
    elif emotion == "angry":
        return EmotionParams(emotion="angry", speed=1.1, pitch=1.1, energy="high", pause_after=0.2)
    elif emotion == "concerned":
        return EmotionParams(emotion="concerned", speed=0.95, pitch=1.0, energy="normal", pause_after=0.2)
    elif emotion == "calm":
        return EmotionParams(emotion="calm", speed=0.92, pitch=0.98, energy="low", pause_after=0.4)
    elif emotion == "excited":
        return EmotionParams(emotion="excited", speed=1.12, pitch=1.08, energy="high", pause_after=0.1)
    else:
        return EmotionParams(emotion="neutral", speed=1.0, pitch=1.0, energy="normal")
