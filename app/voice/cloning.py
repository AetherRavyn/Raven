"""Voice Cloning — FRIDAY-style voice that adapts to the user.

Provides:
- Speaker enrollment (record voice samples)
- Speaker identification (who is talking)
- Voice profile management (per-user voice settings)
- Adaptive TTS (adjust voice to match user's preferences)

Uses the existing speaker_id.py for identification and
piper TTS models for synthesis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VoiceProfile:
    """A user's voice profile and preferences."""
    user_id: str
    display_name: str = ""
    voice_model: str = ""  # Piper model path
    speed: float = 1.0
    pitch: float = 1.0
    energy: str = "normal"  # low, normal, high
    language: str = "en"
    enrolled: bool = False
    enrollment_samples: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_used: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class VoiceProfileManager:
    """Manages per-user voice profiles and preferences."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "voice_profiles"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, user_id: str) -> Path:
        safe_id = user_id.replace("/", "_").replace("..", "_")
        return self._dir / f"{safe_id}.json"

    def get_profile(self, user_id: str) -> VoiceProfile | None:
        """Get a user's voice profile."""
        path = self._profile_path(user_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return VoiceProfile(**{k: v for k, v in data.items() if k in VoiceProfile.__dataclass_fields__})
        except Exception:
            return None

    def save_profile(self, profile: VoiceProfile) -> None:
        """Save a voice profile."""
        from dataclasses import asdict
        profile.last_used = datetime.now(timezone.utc).isoformat()
        path = self._profile_path(profile.user_id)
        path.write_text(
            json.dumps(asdict(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def create_profile(self, user_id: str, display_name: str = "") -> VoiceProfile:
        """Create a new voice profile for a user."""
        profile = VoiceProfile(user_id=user_id, display_name=display_name)
        self.save_profile(profile)
        return profile

    def update_preferences(
        self,
        user_id: str,
        speed: float | None = None,
        pitch: float | None = None,
        energy: str | None = None,
        language: str | None = None,
    ) -> VoiceProfile | None:
        """Update a user's voice preferences."""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)

        if speed is not None:
            profile.speed = max(0.5, min(2.0, speed))
        if pitch is not None:
            profile.pitch = max(0.5, min(2.0, pitch))
        if energy is not None:
            profile.energy = energy
        if language is not None:
            profile.language = language

        self.save_profile(profile)
        return profile

    def set_voice_model(self, user_id: str, model_path: str) -> None:
        """Set the TTS model for a user."""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)
        profile.voice_model = model_path
        self.save_profile(profile)

    def mark_enrolled(self, user_id: str, samples: int = 1) -> None:
        """Mark a user as enrolled for voice identification."""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)
        profile.enrolled = True
        profile.enrollment_samples = samples
        self.save_profile(profile)

    def list_profiles(self) -> list[VoiceProfile]:
        """List all voice profiles."""
        profiles = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                profiles.append(VoiceProfile(**{k: v for k, v in data.items() if k in VoiceProfile.__dataclass_fields__}))
            except Exception:
                continue
        return sorted(profiles, key=lambda p: p.last_used, reverse=True)

    def get_adaptive_voice(self, user_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Get adaptive voice settings based on user profile and context.

        FRIDAY-style: adjusts voice based on:
        - User's saved preferences
        - Time of day (morning = energetic, evening = calm)
        - Current activity (working = focused, relaxing = casual)
        - Emotional context (matches emotion detection)
        """
        profile = self.get_profile(user_id)
        if not profile:
            return {"speed": 1.0, "pitch": 1.0, "energy": "normal"}

        speed = profile.speed
        pitch = profile.pitch
        energy = profile.energy

        # Time-of-day adjustments
        if context:
            hour = context.get("hour", 12)
            if hour < 9:  # Morning
                speed = min(speed * 1.05, 1.3)  # Slightly faster
                energy = "high"
            elif hour > 21:  # Late night
                speed = max(speed * 0.9, 0.7)  # Slower, calmer
                energy = "low"

            # Activity adjustments
            activity = context.get("activity", "")
            if activity in ("working", "coding"):
                energy = "focused"
            elif activity in ("relaxing", "sleeping"):
                speed = max(speed * 0.85, 0.7)
                energy = "low"

            # Mood adjustments
            mood = context.get("mood", "")
            if mood in ("happy", "excited"):
                speed = min(speed * 1.05, 1.3)
                energy = "high"
            elif mood in ("sad", "tired"):
                speed = max(speed * 0.9, 0.7)
                energy = "low"
            elif mood in ("stressed", "anxious"):
                speed = max(speed * 0.85, 0.7)
                energy = "calm"

        return {"speed": speed, "pitch": pitch, "energy": energy}


# Singleton
_voice_manager: VoiceProfileManager | None = None


def get_voice_manager() -> VoiceProfileManager:
    global _voice_manager
    if _voice_manager is None:
        _voice_manager = VoiceProfileManager()
    return _voice_manager
