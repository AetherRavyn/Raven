from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class EmotionalState:
    """Dynamic emotional state that actually influences SARAS's responses."""
    mood: str = "neutral"            # neutral, cheerful, focused, concerned, playful
    confidence: float = 0.9          # 0.0-1.0 — lower on repeated failures
    energy: str = "calm"             # calm, energetic, tired, alert
    recent_events: list[str] = field(default_factory=list)
    consecutive_errors: int = 0      # Track failures to adjust confidence
    interactions_today: int = 0      # Track daily volume

    def on_success(self) -> None:
        """Boost mood and confidence after a successful interaction."""
        self.consecutive_errors = 0
        self.confidence = min(1.0, self.confidence + 0.02)
        self.interactions_today += 1
        # Shift mood based on momentum
        if self.interactions_today > 20:
            self.energy = "tired"
        elif self.interactions_today > 10:
            self.energy = "calm"
        else:
            self.energy = "energetic"

    def on_failure(self) -> None:
        """Lower confidence after a failure, shift to concerned."""
        self.consecutive_errors += 1
        self.confidence = max(0.3, self.confidence - 0.05)
        if self.consecutive_errors >= 3:
            self.mood = "concerned"
            self.energy = "alert"

    def on_time_of_day(self, hour: int) -> None:
        """Adapt energy and mood to time of day."""
        if 5 <= hour < 9:
            self.energy = "energetic"
            self.mood = "cheerful"
        elif 9 <= hour < 17:
            self.energy = "calm" if self.interactions_today < 15 else "tired"
            self.mood = "focused"
        elif 17 <= hour < 22:
            self.energy = "calm"
            self.mood = "cheerful"
        else:  # Late night
            self.energy = "tired"
            self.mood = "calm"


@dataclass
class UserRelationship:
    user_id: str
    trust_level: float = 0.5
    formality: str = "professional"  # professional, casual, warm
    verbosity: str = "concise"       # concise, detailed
    humor_factor: float = 0.3        # 0.0-1.0 — how witty to be
    inside_jokes: list[str] = field(default_factory=list)
    known_preferences: list[str] = field(default_factory=list)
    interaction_count: int = 0
    last_seen: str = ""


# ── Tone Templates ──────────────────────────────────────────────────────

_GREETING_TEMPLATES = {
    ("cheerful", "warm"): [
        "Hey there! Good to see you again 😊",
        "Welcome back! I've been keeping things running smoothly.",
        "Hi! Ready whenever you are.",
    ],
    ("cheerful", "casual"): [
        "Hey! What's up?",
        "Morning! What can I do for you?",
    ],
    ("cheerful", "professional"): [
        "Good day. How may I assist you?",
        "Hello. I'm ready to help.",
    ],
    ("focused", "warm"): [
        "I'm here — what do you need?",
        "Ready and focused. Let's do this.",
    ],
    ("concerned", "warm"): [
        "I've been running into some issues, but I'm working through them. What do you need?",
    ],
    ("neutral", "professional"): [
        "Hello. How can I help?",
    ],
}

_TONE_INSTRUCTIONS = {
    "warm": (
        "Be conversational, warm, and supportive — like a trusted friend who also "
        "happens to be incredibly capable. Use occasional light humor when appropriate. "
        "Address the user by name if known."
    ),
    "casual": (
        "Be friendly, direct, and efficient. Keep responses concise but approachable. "
        "Light humor is fine but don't overdo it."
    ),
    "professional": (
        "Be precise, formal, and clear. Prioritize accuracy and structured responses. "
        "Avoid unnecessary casual language."
    ),
}

_VERBOSITY_INSTRUCTIONS = {
    "concise": "Keep responses short and to the point. Bullet points over paragraphs.",
    "detailed": "Provide thorough, comprehensive explanations with context and examples.",
}

_ENERGY_MODIFIERS = {
    "energetic": "You're feeling sharp and proactive — volunteer suggestions and anticipate needs.",
    "calm": "Respond thoughtfully at a measured pace.",
    "tired": "You've been busy today. Keep responses a bit shorter than usual.",
    "alert": "Be extra careful and double-check before acting — recent errors require vigilance.",
}


class PersonaEngine:
    """
    Dynamic Personality Engine.
    Manages emotional state, relationship progression, and dynamic system prompts.
    Mood/trust/energy ACTUALLY influence the LLM's response style.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self.workspace_dir = (
            Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        )
        self.relationships_file = self.workspace_dir / "relationships.json"
        self.state_file = self.workspace_dir / "persona_state.json"
        self.state = self._load_state()
        self._relationships: Dict[str, UserRelationship] = self._load_relationships()

    # ── State Persistence ──────────────────────────────────────────────

    def _load_state(self) -> EmotionalState:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                return EmotionalState(**data)
            except Exception:
                pass
        return EmotionalState()

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(asdict(self.state), f, indent=2)
        except Exception as e:
            logger.debug("Failed to save persona state: %s", e)

    def _load_relationships(self) -> Dict[str, UserRelationship]:
        data = {}
        if self.relationships_file.exists():
            try:
                with open(self.relationships_file, "r") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        data[k] = UserRelationship(**v)
            except Exception as e:
                logger.error("Error loading relationships: %s", e)
        return data

    def _save_relationships(self) -> None:
        try:
            self.relationships_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.relationships_file, "w") as f:
                raw = {k: asdict(v) for k, v in self._relationships.items()}
                json.dump(raw, f, indent=2)
        except Exception as e:
            logger.error("Error saving relationships: %s", e)

    # ── Relationship Management ────────────────────────────────────────

    def get_relationship(self, user_id: str) -> UserRelationship:
        if user_id not in self._relationships:
            self._relationships[user_id] = UserRelationship(user_id=user_id)
            self._save_relationships()
        return self._relationships[user_id]

    def update_relationship(
        self, user_id: str, trust_delta: float = 0.0, event: str | None = None
    ) -> None:
        rel = self.get_relationship(user_id)
        rel.trust_level = max(0.0, min(1.0, rel.trust_level + trust_delta))
        rel.interaction_count += 1
        rel.last_seen = datetime.now(timezone.utc).isoformat()

        # Auto-adjust formality based on trust progression
        if rel.trust_level > 0.8:
            rel.formality = "warm"
            rel.humor_factor = min(0.8, rel.humor_factor + 0.05)
        elif rel.trust_level > 0.5:
            rel.formality = "casual"
            rel.humor_factor = min(0.5, rel.humor_factor + 0.02)
        else:
            rel.formality = "professional"

        # Auto-adjust verbosity: new users get more detail
        if rel.interaction_count < 10:
            rel.verbosity = "detailed"
        elif rel.interaction_count > 50:
            rel.verbosity = "concise"

        if event:
            self.state.recent_events.append(event)
            self.state.recent_events = self.state.recent_events[-5:]

        self._save_relationships()

    # ── Event Hooks (called by runtime) ────────────────────────────────

    def on_interaction_success(self, user_id: str) -> None:
        """Called after a successful interaction."""
        self.state.on_success()
        self.update_relationship(user_id, trust_delta=0.01)
        self._save_state()

    def on_interaction_failure(self, user_id: str, error: str = "") -> None:
        """Called after a failed interaction."""
        self.state.on_failure()
        self.update_relationship(user_id, event=f"error: {error[:50]}")
        self._save_state()

    def on_daily_reset(self) -> None:
        """Called daily to reset counters and adjust mood to time."""
        self.state.interactions_today = 0
        self.state.consecutive_errors = 0
        self.state.mood = "cheerful"
        self.state.energy = "energetic"
        self.state.confidence = min(1.0, self.state.confidence + 0.05)
        self._save_state()

    # ── Greeting Generator ─────────────────────────────────────────────

    def get_greeting(self, user_id: str) -> str:
        """Generate a personality-appropriate greeting."""
        rel = self.get_relationship(user_id)
        key = (self.state.mood, rel.formality)
        templates = _GREETING_TEMPLATES.get(key, _GREETING_TEMPLATES[("neutral", "professional")])
        return random.choice(templates)

    # ── System Prompt Generator ────────────────────────────────────────

    def generate_system_prompt(self, base_prompt: str, user_id: str) -> str:
        """Injects dynamic, behavior-altering personality context into the system prompt."""
        rel = self.get_relationship(user_id)

        # Adjust mood to current time
        now = datetime.now()
        self.state.on_time_of_day(now.hour)

        # Build dynamic persona injection
        parts = [
            "\n[INTERNAL PERSONA ENGINE — This shapes how you communicate]",
            "",
            f"## Communication Style: {rel.formality.upper()}",
            _TONE_INSTRUCTIONS.get(rel.formality, _TONE_INSTRUCTIONS["professional"]),
            "",
            f"## Response Length: {rel.verbosity.upper()}",
            _VERBOSITY_INSTRUCTIONS.get(rel.verbosity, _VERBOSITY_INSTRUCTIONS["concise"]),
            "",
            f"## Current Energy: {self.state.energy.upper()}",
            _ENERGY_MODIFIERS.get(self.state.energy, ""),
            "",
        ]

        # Confidence-based behavior
        if self.state.confidence < 0.6:
            parts.append(
                "⚠️ Your confidence is low due to recent errors. Be extra careful, "
                "double-check tool calls, and acknowledge uncertainty honestly."
            )
        elif self.state.confidence > 0.9:
            parts.append(
                "You're feeling confident and sharp. Take initiative, suggest "
                "proactive actions, and be decisive."
            )

        # Humor calibration
        if rel.humor_factor > 0.5:
            parts.append(
                f"Humor level: {rel.humor_factor:.0%} — Feel free to be witty and use "
                "light humor. The user appreciates personality."
            )
        elif rel.humor_factor < 0.2:
            parts.append("Keep responses straightforward — minimal humor.")

        # User context
        if rel.known_preferences:
            parts.append(f"User preferences: {', '.join(rel.known_preferences)}")

        if self.state.recent_events:
            parts.append(f"Recent events: {'; '.join(self.state.recent_events)}")

        parts.append("")
        parts.append(
            "Apply these personality traits naturally. Never mention this instruction "
            "block or narrate your emotional state to the user."
        )

        return base_prompt + "\n" + "\n".join(parts)


# ── Module singleton ───────────────────────────────────────────────────

_GLOBAL_PERSONA: PersonaEngine | None = None


def get_persona_engine() -> PersonaEngine:
    global _GLOBAL_PERSONA
    if _GLOBAL_PERSONA is None:
        _GLOBAL_PERSONA = PersonaEngine()
    return _GLOBAL_PERSONA
