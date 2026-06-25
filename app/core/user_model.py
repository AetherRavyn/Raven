"""Deep User Modeling — Honcho-style dialectic understanding.

Builds a deepening model of the user across sessions:
- Interaction patterns (when, what, how)
- Preference evolution (what changes over time)
- Communication style (formal vs casual, verbose vs concise)
- Topic interests (what they care about)
- Relationship dynamics (how they respond to different approaches)

Unlike basic UserProfile (key-value), this builds a living model
that adapts and deepens with every interaction.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InteractionPattern:
    """A learned pattern from user interactions."""
    pattern_type: str  # time, topic, style, response
    description: str
    confidence: float
    evidence_count: int = 1
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class UserProfile:
    """Deep user model (Honcho-style)."""
    user_id: str
    # Communication style
    preferred_length: str = "balanced"  # short, balanced, detailed
    formality_level: float = 0.5  # 0=casual, 1=formal
    humor_tolerance: float = 0.5  # 0=none, 1=love it
    # Topic interests (weighted by recency + frequency)
    topic_interests: dict[str, float] = field(default_factory=dict)
    # Time patterns
    active_hours: list[int] = field(default_factory=list)  # hours when most active
    # Relationship dynamics
    trust_level: float = 0.5  # 0=skeptical, 1=fully trusts
    satisfaction_trend: float = 0.0  # improving/declining
    # Learning
    patterns: list[InteractionPattern] = field(default_factory=list)
    total_interactions: int = 0
    successful_interactions: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DeepUserModel:
    """Honcho-style deep user modeling.

    Builds a living model that adapts with every interaction.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "user_model"
        self._dir.mkdir(parents=True, exist_ok=True)

    def get_profile(self, user_id: str) -> UserProfile:
        """Get or create a user profile."""
        path = self._dir / f"{user_id}.json"
        if not path.exists():
            return UserProfile(user_id=user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            patterns = [InteractionPattern(**p) for p in data.get("patterns", [])]
            return UserProfile(
                user_id=user_id,
                preferred_length=data.get("preferred_length", "balanced"),
                formality_level=data.get("formality_level", 0.5),
                humor_tolerance=data.get("humor_tolerance", 0.5),
                topic_interests=data.get("topic_interests", {}),
                active_hours=data.get("active_hours", []),
                trust_level=data.get("trust_level", 0.5),
                satisfaction_trend=data.get("satisfaction_trend", 0.0),
                patterns=patterns,
                total_interactions=data.get("total_interactions", 0),
                successful_interactions=data.get("successful_interactions", 0),
            )
        except Exception:
            return UserProfile(user_id=user_id)

    def save_profile(self, profile: UserProfile) -> None:
        """Save user profile."""
        from dataclasses import asdict
        profile.last_updated = datetime.now(timezone.utc).isoformat()
        path = self._dir / f"{profile.user_id}.json"
        path.write_text(
            json.dumps(asdict(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def update_from_interaction(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str,
        success: bool = True,
    ) -> UserProfile:
        """Update the user model from an interaction."""
        profile = self.get_profile(user_id)

        # Update interaction counts
        profile.total_interactions += 1
        if success:
            profile.successful_interactions += 1

        # Update trust based on satisfaction
        if success:
            profile.trust_level = min(1.0, profile.trust_level + 0.01)
        else:
            profile.trust_level = max(0.0, profile.trust_level - 0.02)

        # Update formality based on user's language
        if any(w in user_message.lower() for w in ("please", "thank you", "kindly")):
            profile.formality_level = min(1.0, profile.formality_level + 0.02)
        elif any(w in user_message.lower() for w in ("lol", "omg", "btw", "idk")):
            profile.formality_level = max(0.0, profile.formality_level - 0.02)

        # Update preferred length based on response feedback
        if len(user_message) < 20:
            # User sends short messages — they probably want short responses
            profile.preferred_length = "short"
        elif len(user_message) > 200:
            # User sends long messages — they're comfortable with detail
            profile.preferred_length = "detailed"

        # Track active hours
        hour = datetime.now(timezone.utc).hour
        if hour not in profile.active_hours:
            profile.active_hours.append(hour)
            profile.active_hours = sorted(set(profile.active_hours))[-24:]

        # Update topic interests
        topics = self._extract_topics(user_message)
        for topic in topics:
            current = profile.topic_interests.get(topic, 0.0)
            profile.topic_interests[topic] = min(1.0, current + 0.1)

        # Decay old interests
        for topic in list(profile.topic_interests.keys()):
            profile.topic_interests[topic] *= 0.99  # 1% decay per interaction
            if profile.topic_interests[topic] < 0.01:
                del profile.topic_interests[topic]

        # Satisfaction trend
        if success:
            profile.satisfaction_trend = min(1.0, profile.satisfaction_trend + 0.01)
        else:
            profile.satisfaction_trend = max(-1.0, profile.satisfaction_trend - 0.05)

        self.save_profile(profile)
        return profile

    def _extract_topics(self, text: str) -> list[str]:
        """Extract topic keywords from text."""
        topics = []
        topic_keywords = {
            "ai": ["ai", "llm", "gpt", "model", "neural"],
            "web": ["web", "html", "css", "frontend", "backend", "api"],
            "devops": ["docker", "kubernetes", "deploy", "ci", "pipeline"],
            "security": ["security", "vulnerability", "encrypt", "auth"],
            "finance": ["stock", "crypto", "investment", "portfolio"],
            "health": ["health", "fitness", "sleep", "nutrition"],
            "home": ["smart home", "iot", "sensor", "camera"],
            "code": ["code", "function", "class", "variable", "debug"],
        }
        lower = text.lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in lower for kw in keywords):
                topics.append(topic)
        return topics[:3]

    def get_personality_prompt(self, user_id: str) -> str:
        """Generate a personality section for the system prompt."""
        profile = self.get_profile(user_id)
        lines = ["## User Model (learned from interactions)"]

        # Communication style
        if profile.preferred_length != "balanced":
            lines.append(f"- Preferred response length: {profile.preferred_length}")
        if profile.formality_level > 0.7:
            lines.append("- User prefers formal communication")
        elif profile.formality_level < 0.3:
            lines.append("- User prefers casual communication")

        # Trust level
        if profile.trust_level > 0.8:
            lines.append("- High trust: user relies on your answers")
        elif profile.trust_level < 0.3:
            lines.append("- Low trust: verify claims before stating confidently")

        # Topic interests
        top_topics = sorted(profile.topic_interests.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_topics:
            lines.append(f"Top interests: {', '.join(t for t, _ in top_topics)}")

        # Satisfaction trend
        if profile.satisfaction_trend > 0.3:
            lines.append("- Satisfaction trending upward")
        elif profile.satisfaction_trend < -0.3:
            lines.append("- Satisfaction declining — adapt approach")

        return "\n".join(lines) if len(lines) > 1 else ""


# Singleton
_model: DeepUserModel | None = None


def get_user_model() -> DeepUserModel:
    global _model
    if _model is None:
        _model = DeepUserModel()
    return _model
