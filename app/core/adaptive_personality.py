"""Adaptive Personality Evolution — Raven's personality adapts over time.

Unlike static personality (SOUL.md), this system:
1. Tracks which communication styles work best
2. Adjusts humor level based on user responses
3. Adapts formality based on context
4. Evolves vocabulary based on user's language
5. Learns when to be verbose vs concise

The personality evolves slowly — changes are gradual and
validated against user feedback before being permanent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PersonalityTrait:
    """A personality trait that can evolve over time."""
    name: str
    value: float  # 0.0 to 1.0
    description: str
    history: list[tuple[str, float]] = field(default_factory=list)  # (timestamp, value)

    def adjust(self, delta: float, reason: str) -> None:
        """Adjust the trait value, bounded to [0, 1]."""
        old = self.value
        self.value = max(0.0, min(1.0, self.value + delta))
        self.history.append((datetime.now(timezone.utc).isoformat(), self.value))

    @property
    def trend(self) -> str:
        """Get the trend direction."""
        if len(self.history) < 2:
            return "stable"
        recent = self.history[-1][1]
        previous = self.history[-2][1]
        if recent > previous + 0.05:
            return "increasing"
        elif recent < previous - 0.05:
            return "decreasing"
        return "stable"


@dataclass(slots=True)
class PersonalityProfile:
    """Raven's evolving personality profile."""
    traits: dict[str, PersonalityTrait] = field(default_factory=dict)
    vocabulary: dict[str, int] = field(default_factory=dict)  # word → usage count
    response_styles: dict[str, int] = field(default_factory=dict)  # style → success count
    last_evolution: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AdaptivePersonality:
    """FRIDAY-style adaptive personality system.

    Learns from interactions how to communicate best with
    each user, and slowly evolves personality traits.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "personality"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._profile_file = self._dir / "profile.json"

    def get_profile(self) -> PersonalityProfile:
        """Get the current personality profile."""
        if not self._profile_file.exists():
            return self._create_default_profile()
        try:
            data = json.loads(self._profile_file.read_text(encoding="utf-8"))
            traits = {
                name: PersonalityTrait(**t) for name, t in data.get("traits", {}).items()
            }
            return PersonalityProfile(
                traits=traits,
                vocabulary=data.get("vocabulary", {}),
                response_styles=data.get("response_styles", {}),
                last_evolution=data.get("last_evolution", ""),
            )
        except Exception:
            return self._create_default_profile()

    def save_profile(self, profile: PersonalityProfile) -> None:
        """Save the personality profile."""
        from dataclasses import asdict
        self._profile_file.write_text(
            json.dumps(asdict(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _create_default_profile(self) -> PersonalityProfile:
        """Create a default personality profile."""
        return PersonalityProfile(
            traits={
                "humor": PersonalityTrait("humor", 0.5, "How funny/witty Raven is"),
                "formality": PersonalityTrait("formality", 0.5, "How formal vs casual"),
                "verbosity": PersonalityTrait("verbosity", 0.5, "How detailed responses are"),
                "proactivity": PersonalityTrait("proactivity", 0.6, "How much Raven takes initiative"),
                "empathy": PersonalityTrait("empathy", 0.6, "How much Raven shows emotional understanding"),
                "confidence": PersonalityTrait("confidence", 0.7, "How confident Raven sounds"),
            },
        )

    def learn_from_interaction(
        self,
        user_message: str,
        assistant_response: str,
        user_feedback: str | None = None,
    ) -> None:
        """Learn from an interaction to evolve personality."""
        profile = self.get_profile()

        # Track vocabulary usage
        for word in assistant_response.lower().split():
            if len(word) > 4:  # Only track meaningful words
                profile.vocabulary[word] = profile.vocabulary.get(word, 0) + 1

        # Track response style effectiveness
        style = self._detect_response_style(assistant_response)
        profile.response_styles[style] = profile.response_styles.get(style, 0) + 1

        # Adjust traits based on feedback
        if user_feedback:
            if user_feedback == "positive":
                profile.traits["confidence"].adjust(0.02, "positive feedback")
                profile.traits["empathy"].adjust(0.01, "positive feedback")
            elif user_feedback == "negative":
                profile.traits["verbosity"].adjust(-0.02, "negative feedback")
                profile.traits["confidence"].adjust(-0.01, "negative feedback")

        # Adjust based on message patterns
        if len(user_message) < 20:
            # User likes short messages
            profile.traits["verbosity"].adjust(-0.005, "short user message")
        elif len(user_message) > 200:
            # User sends long messages — match their style
            profile.traits["verbosity"].adjust(0.005, "long user message")

        if any(w in user_message.lower() for w in ("lol", "haha", "funny")):
            profile.traits["humor"].adjust(0.01, "user enjoyed humor")

        profile.last_evolution = datetime.now(timezone.utc).isoformat()
        self.save_profile(profile)

    def _detect_response_style(self, response: str) -> str:
        """Detect the style of a response."""
        if len(response) < 50:
            return "concise"
        elif len(response) > 300:
            return "verbose"
        elif response.count("!" or "?.") > 2:
            return "enthusiastic"
        elif any(w in response.lower() for w in ("however", "furthermore", "moreover")):
            return "formal"
        return "balanced"

    def get_personality_prompt(self) -> str:
        """Generate a personality section for the system prompt.

        This adapts the base SOUL.md personality with learned
        adjustments.
        """
        profile = self.get_profile()
        lines = ["## Adaptive Personality (learned from interactions)"]

        for name, trait in profile.traits.items():
            if trait.trend != "stable":
                direction = "increasing" if trait.trend == "increasing" else "decreasing"
                lines.append(f"- {name}: {trait.value:.2f} (trending {direction})")

        # Top vocabulary
        top_words = sorted(profile.vocabulary.items(), key=lambda x: x[1], reverse=True)[:10]
        if top_words:
            lines.append("\nFrequently used words: " + ", ".join(w for w, _ in top_words))

        # Best response styles
        top_styles = sorted(profile.response_styles.items(), key=lambda x: x[1], reverse=True)[:3]
        if top_styles:
            lines.append("Most effective styles: " + ", ".join(f"{s} ({c}x)" for s, c in top_styles))

        return "\n".join(lines) if len(lines) > 1 else ""
