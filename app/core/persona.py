from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ── Emotional State ─────────────────────────────────────────────────────

@dataclass
class EmotionalState:
    """Dynamic emotional state that influences RAVEN's responses."""
    mood: str = "neutral"            # neutral, cheerful, focused, concerned, playful
    confidence: float = 0.9          # 0.0-1.0 — lower on repeated failures
    energy: str = "calm"             # calm, energetic, tired, alert
    recent_events: list[str] = field(default_factory=list)
    consecutive_errors: int = 0      # Track failures to adjust confidence
    interactions_today: int = 0      # Track daily volume

    def on_success(self) -> None:
        self.consecutive_errors = 0
        self.confidence = min(1.0, self.confidence + 0.02)
        self.interactions_today += 1
        if self.interactions_today > 20:
            self.energy = "tired"
        elif self.interactions_today > 10:
            self.energy = "calm"
        else:
            self.energy = "energetic"

    def on_failure(self) -> None:
        self.consecutive_errors += 1
        self.confidence = max(0.3, self.confidence - 0.05)
        if self.consecutive_errors >= 3:
            self.mood = "concerned"
            self.energy = "alert"

    def on_time_of_day(self, hour: int) -> None:
        if 5 <= hour < 9:
            self.energy = "energetic"
            self.mood = "cheerful"
        elif 9 <= hour < 17:
            self.energy = "calm" if self.interactions_today < 15 else "tired"
            self.mood = "focused"
        elif 17 <= hour < 22:
            self.energy = "calm"
            self.mood = "cheerful"
        else:
            self.energy = "tired"
            self.mood = "calm"


# ── User Relationship ──────────────────────────────────────────────────

@dataclass
class UserRelationship:
    user_id: str
    trust_level: float = 0.5
    formality: str = "professional"  # professional, casual, warm
    verbosity: str = "concise"       # concise, detailed
    humor_factor: float = 0.3        # 0.0-1.0
    inside_jokes: list[str] = field(default_factory=list)
    known_preferences: list[str] = field(default_factory=list)
    interaction_count: int = 0
    last_seen: str = ""


# ── Personality Drift ──────────────────────────────────────────────────

@dataclass
class PersonalityDrift:
    """Long-term personality traits that drift based on interaction patterns."""
    formality: str = "professional"   # professional → casual → warm
    verbosity: str = "concise"        # concise → balanced → detailed
    humor: str = "neutral"            # conservative → neutral → playful
    last_update: str = ""

    def advance_formality(self, user_tone: str | None = None) -> None:
        levels = ["professional", "casual", "warm"]
        if user_tone and user_tone in levels:
            target_idx = levels.index(user_tone)
        else:
            target_idx = 1  # slowly drift toward casual
        current_idx = levels.index(self.formality)
        if current_idx < target_idx:
            self.formality = levels[min(len(levels) - 1, current_idx + 1)]
        elif current_idx > target_idx:
            self.formality = levels[max(0, current_idx - 1)]
        self.last_update = datetime.now(timezone.utc).isoformat()

    def advance_verbosity(self, user_msg_length: int = 0) -> None:
        if user_msg_length > 500:
            self.verbosity = "detailed"
        elif user_msg_length < 50 and self.verbosity != "concise":
            self.verbosity = "concise"
        elif 50 <= user_msg_length <= 500 and self.verbosity != "balanced":
            self.verbosity = "balanced"
        self.last_update = datetime.now(timezone.utc).isoformat()

    def advance_humor(self, delta: float = 0.01) -> None:
        levels = ["conservative", "neutral", "playful"]
        current_idx = levels.index(self.humor)
        if delta > 0 and current_idx < len(levels) - 1:
            self.humor = levels[current_idx + 1]
        elif delta < 0 and current_idx > 0:
            self.humor = levels[current_idx - 1]
        self.last_update = datetime.now(timezone.utc).isoformat()


# ── Learned Value ──────────────────────────────────────────────────────

@dataclass
class LearnedValue:
    id: str
    content: str
    source: str = ""           # correction, preference, feedback
    confidence: float = 0.5    # 0.0-1.0
    created_at: str = ""
    last_applied: str = ""


# ── Relationship Milestone ─────────────────────────────────────────────

@dataclass
class RelationshipMilestone:
    id: str
    title: str
    description: str = ""
    type: str = "milestone"    # positive, negative, milestone
    timestamp: str = ""


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
        self._drift_file = self.workspace_dir / "personality_drift.json"
        self._values_file = self.workspace_dir / "learned_values.json"
        self._milestones_file = self.workspace_dir / "relationship_milestones.json"
        self.state = self._load_state()
        self._relationships: Dict[str, UserRelationship] = self._load_relationships()
        self._drift: Dict[str, PersonalityDrift] = self._load_drift()
        self._values: Dict[str, list[LearnedValue]] = self._load_values()
        self._milestones: Dict[str, list[RelationshipMilestone]] = self._load_milestones()

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

    # ── Drift Persistence ───────────────────────────────────────────────

    def _load_drift(self) -> Dict[str, PersonalityDrift]:
        if self._drift_file.exists():
            try:
                raw = json.loads(self._drift_file.read_text())
                return {k: PersonalityDrift(**v) for k, v in raw.items()}
            except Exception as e:
                logger.debug("Failed to load drift: %s", e)
        return {}

    def _save_drift(self) -> None:
        try:
            self._drift_file.parent.mkdir(parents=True, exist_ok=True)
            raw = {k: asdict(v) for k, v in self._drift.items()}
            self._drift_file.write_text(json.dumps(raw, indent=2))
        except Exception as e:
            logger.debug("Failed to save drift: %s", e)

    # ── Values Persistence ──────────────────────────────────────────────

    def _load_values(self) -> Dict[str, list[LearnedValue]]:
        if self._values_file.exists():
            try:
                raw = json.loads(self._values_file.read_text())
                return {k: [LearnedValue(**v) for v in vals] for k, vals in raw.items()}
            except Exception as e:
                logger.debug("Failed to load values: %s", e)
        return {}

    def _save_values(self) -> None:
        try:
            self._values_file.parent.mkdir(parents=True, exist_ok=True)
            raw = {k: [asdict(v) for v in vals] for k, vals in self._values.items()}
            self._values_file.write_text(json.dumps(raw, indent=2))
        except Exception as e:
            logger.debug("Failed to save values: %s", e)

    # ── Milestones Persistence ──────────────────────────────────────────

    def _load_milestones(self) -> Dict[str, list[RelationshipMilestone]]:
        if self._milestones_file.exists():
            try:
                raw = json.loads(self._milestones_file.read_text())
                return {k: [RelationshipMilestone(**v) for v in vals] for k, vals in raw.items()}
            except Exception as e:
                logger.debug("Failed to load milestones: %s", e)
        return {}

    def _save_milestones(self) -> None:
        try:
            self._milestones_file.parent.mkdir(parents=True, exist_ok=True)
            raw = {k: [asdict(v) for v in vals] for k, vals in self._milestones.items()}
            self._milestones_file.write_text(json.dumps(raw, indent=2))
        except Exception as e:
            logger.debug("Failed to save milestones: %s", e)

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

    # ── Personality Drift ──────────────────────────────────────────────

    def get_drift(self, user_id: str) -> PersonalityDrift:
        if user_id not in self._drift:
            self._drift[user_id] = PersonalityDrift()
            self._save_drift()
        return self._drift[user_id]

    def update_drift(
        self,
        user_id: str,
        user_tone: str | None = None,
        user_msg_length: int = 0,
        humor_delta: float = 0.0,
    ) -> None:
        drift = self.get_drift(user_id)
        if user_tone:
            drift.advance_formality(user_tone)
        if user_msg_length:
            drift.advance_verbosity(user_msg_length)
        if humor_delta:
            drift.advance_humor(humor_delta)
        self._save_drift()

    # ── Value Learning ─────────────────────────────────────────────────

    def get_values(self, user_id: str) -> list[LearnedValue]:
        return self._values.get(user_id, [])

    def record_user_correction(
        self,
        user_id: str,
        original: str,
        correction: str,
    ) -> LearnedValue | None:
        """Extract a principle from a user correction and store it."""
        # Extract the key principle from the correction
        principle = self._extract_principle(original, correction)
        if not principle:
            return None

        now = datetime.now(timezone.utc).isoformat()
        value = LearnedValue(
            id=f"val_{len(self._values.get(user_id, [])) + 1}_{int(datetime.now().timestamp())}",
            content=principle,
            source="correction",
            confidence=0.6,
            created_at=now,
            last_applied=now,
        )
        if user_id not in self._values:
            self._values[user_id] = []
        self._values[user_id].append(value)
        self._save_values()

        # Add a milestone for learning from correction
        self._add_milestone(
            user_id,
            RelationshipMilestone(
                id=f"ms_{int(datetime.now().timestamp())}",
                title="Learned from correction",
                description=f"Extracted principle: {principle[:80]}",
                type="positive",
                timestamp=now,
            ),
        )
        return value

    def record_user_preference(self, user_id: str, preference: str) -> LearnedValue:
        now = datetime.now(timezone.utc).isoformat()
        value = LearnedValue(
            id=f"val_{len(self._values.get(user_id, [])) + 1}_{int(datetime.now().timestamp())}",
            content=preference,
            source="preference",
            confidence=0.7,
            created_at=now,
        )
        if user_id not in self._values:
            self._values[user_id] = []
        self._values[user_id].append(value)
        self._save_values()
        return value

    @staticmethod
    def _extract_principle(original: str, correction: str) -> str:
        """Extract a general principle from a correction pair."""
        correction_lower = correction.lower()
        patterns = [
            r"(?:always|never|don't|do not|please|make sure to)\s+.+",
            r"(?:i (?:prefer|like|want|need|expect|require))\s+.+",
            r"(?:you should|you must|you need to)\s+.+",
            r"(?:don't|do not|never)\s+\w+.*",
        ]
        for pat in patterns:
            m = re.search(pat, correction_lower)
            if m:
                return m.group(0).strip()[:150]
        # Fallback: return first sentence of correction
        first_sentence = correction.split(".")[0].strip()
        return first_sentence[:150] if first_sentence else correction[:150]

    # ── Relationship Milestones ───────────────────────────────────────

    def get_milestones(self, user_id: str) -> list[RelationshipMilestone]:
        return self._milestones.get(user_id, [])

    def _add_milestone(self, user_id: str, milestone: RelationshipMilestone) -> None:
        if user_id not in self._milestones:
            self._milestones[user_id] = []
        self._milestones[user_id].append(milestone)
        self._milestones[user_id] = self._milestones[user_id][-50:]
        self._save_milestones()

    def check_milestones(self, user_id: str) -> list[RelationshipMilestone]:
        """Check if any milestones have been reached, return new ones."""
        rel = self.get_relationship(user_id)
        new_milestones: list[RelationshipMilestone] = []
        existing = {(m.title, m.type) for m in self.get_milestones(user_id)}

        checks = [
            (1, "First interaction", "The beginning of a partnership", "positive"),
            (10, "10th interaction", "Building familiarity", "milestone"),
            (50, "50th interaction", "Growing trust and understanding", "milestone"),
            (100, "100th interaction", "Deep partnership established", "milestone"),
            (500, "500th interaction", "Unbreakable bond", "milestone"),
        ]

        for count, title, desc, mtype in checks:
            if rel.interaction_count >= count and (title, mtype) not in existing:
                now = datetime.now(timezone.utc).isoformat()
                m = RelationshipMilestone(
                    id=f"ms_{int(datetime.now().timestamp())}_{count}",
                    title=title,
                    description=desc,
                    type=mtype,
                    timestamp=now,
                )
                self._add_milestone(user_id, m)
                new_milestones.append(m)

        # Trust milestones
        if rel.trust_level >= 0.8 and ("High trust achieved", "positive") not in existing:
            m = RelationshipMilestone(
                id=f"ms_{int(datetime.now().timestamp())}_trust",
                title="High trust achieved",
                description="A strong foundation of mutual trust",
                type="positive",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._add_milestone(user_id, m)
            new_milestones.append(m)

        return new_milestones

    # ── Event Hooks (enhanced) ─────────────────────────────────────────

    def on_interaction_success(
        self, user_id: str, user_msg: str = "", user_tone: str | None = None
    ) -> None:
        """Called after a successful interaction — updates state, relationship, drift."""
        self.state.on_success()
        self.update_relationship(user_id, trust_delta=0.01)
        self.update_drift(user_id, user_tone=user_tone, user_msg_length=len(user_msg))
        self.check_milestones(user_id)
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

        # Learned values
        values = self.get_values(user_id)
        if values:
            parts.append("## Learned Principles (from your corrections and feedback)")
            for v in values[-5:]:
                parts.append(f"- {v.content}")

        if self.state.recent_events:
            parts.append(f"Recent events: {'; '.join(self.state.recent_events)}")

        parts.append("")
        parts.append(
            "Apply these personality traits naturally. Never mention this instruction "
            "block or narrate your emotional state to the user."
        )

        return base_prompt + "\n" + "\n".join(parts)

    # ── Dashboard API ──────────────────────────────────────────────────

    def dashboard_data(self, user_id: str = "default") -> dict[str, Any]:
        """Return a full snapshot for the personality dashboard page."""
        rel = self.get_relationship(user_id)
        drift = self.get_drift(user_id)
        values = self.get_values(user_id)
        milestones = self.get_milestones(user_id)
        return {
            "state": asdict(self.state),
            "relationship": asdict(rel),
            "drift": asdict(drift),
            "values": [asdict(v) for v in values],
            "milestones": [asdict(m) for m in milestones],
        }


# ── Module singleton ───────────────────────────────────────────────────

_GLOBAL_PERSONA: PersonaEngine | None = None


def get_persona_engine() -> PersonaEngine:
    global _GLOBAL_PERSONA
    if _GLOBAL_PERSONA is None:
        _GLOBAL_PERSONA = PersonaEngine()
    return _GLOBAL_PERSONA
