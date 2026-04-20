from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserProfile:
    user_id: str
    display_name: str | None = None
    timezone: str | None = None
    locale: str | None = None
    preferred_language: str | None = None
    communication_style: str | None = None
    preferences: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    updated_at: str | None = None
    expires_at: str | None = None
    confidence: float = 1.0
    pinned: bool = False


class UserProfileStore:
    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self.profiles_dir = Path(Config.STATE_DB_PATH).parent / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _profile_file(self, user_id: str) -> Path:
        safe = str(user_id).replace("/", "_").replace("..", "_")
        return self.profiles_dir / f"{safe}.json"

    def load(self, user_id: str) -> UserProfile:
        path = self._profile_file(user_id)
        if not path.exists():
            return UserProfile(user_id=user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return UserProfile(
                user_id=user_id,
                display_name=data.get("display_name"),
                timezone=data.get("timezone"),
                locale=data.get("locale"),
                preferred_language=data.get("preferred_language"),
                communication_style=data.get("communication_style"),
                preferences=list(data.get("preferences", []) or []),
                facts=list(data.get("facts", []) or []),
                tasks=list(data.get("tasks", []) or []),
                projects=list(data.get("projects", []) or []),
                files=list(data.get("files", []) or []),
                devices=list(data.get("devices", []) or []),
                decisions=list(data.get("decisions", []) or []),
                tools=list(data.get("tools", []) or []),
                updated_at=data.get("updated_at"),
                expires_at=data.get("expires_at"),
                confidence=float(data.get("confidence", 1.0) or 1.0),
                pinned=bool(data.get("pinned", False)),
            )
        except Exception as exc:
            logger.debug("Failed to load profile %s: %s", user_id, exc)
            return UserProfile(user_id=user_id)

    def save(self, profile: UserProfile) -> None:
        path = self._profile_file(profile.user_id)
        try:
            path.write_text(
                json.dumps(asdict(profile), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to save profile %s: %s", profile.user_id, exc)

    def update_from_text(self, user_id: str, text: str) -> UserProfile:
        profile = self.load(user_id)
        lowered = text.lower()

        def add_unique(target: list[str], value: str) -> None:
            cleaned = value.strip()
            if cleaned and cleaned not in target:
                target.append(cleaned)

        if "my name is" in lowered:
            add_unique(profile.facts, text.strip())
            try:
                after = text.lower().split("my name is", 1)[1]
                after = text[
                    text.lower().find("my name is") + len("my name is") :
                ].strip()
                if after:
                    profile.display_name = after.split()[0].strip(",.!? ")
            except Exception:
                pass

        if "i prefer" in lowered or "i like" in lowered or "please use" in lowered:
            add_unique(profile.preferences, text.strip())

        if "my timezone is" in lowered:
            try:
                after = text[
                    text.lower().find("my timezone is") + len("my timezone is") :
                ].strip()
                profile.timezone = after.split()[0].strip(",.!? ")
            except Exception:
                pass

        if "my language is" in lowered or "speak" in lowered:
            add_unique(profile.preferences, text.strip())

        if any(
            phrase in lowered
            for phrase in (
                "forget",
                "don't remember",
                "do not remember",
                "clear memory",
            )
        ):
            profile.preferences.clear()
            profile.facts.clear()
            profile.tasks.clear()
            profile.projects.clear()
            profile.files.clear()
            profile.devices.clear()
            profile.decisions.clear()

        if "remember" in lowered or "note that" in lowered:
            add_unique(profile.facts, text.strip())

        if any(
            phrase in lowered for phrase in ("project", "repo", "workspace", "roadmap")
        ):
            add_unique(profile.projects, text.strip())

        file_matches = re.findall(
            r"\b[\w./-]+\.(?:md|txt|py|json|yaml|yml|csv|xlsx|pdf|docx)\b", text
        )
        for match in file_matches:
            add_unique(profile.files, match)

        if any(
            phrase in lowered
            for phrase in (
                "laptop",
                "phone",
                "desktop",
                "server",
                "camera",
                "router",
                "device",
            )
        ):
            add_unique(profile.devices, text.strip())

        if any(
            phrase in lowered
            for phrase in ("decide", "decision", "approved", "choose", "selected")
        ):
            add_unique(profile.decisions, text.strip())

        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(profile)
        return profile

    def resolve_conflict(
        self,
        user_id: str,
        category: str,
        old_value: str,
        new_value: str,
        *,
        prefer_new: bool = True,
    ) -> UserProfile:
        profile = self.load(user_id)
        target = getattr(profile, category, None)
        if isinstance(target, list):
            if old_value in target:
                target.remove(old_value)
            if prefer_new and new_value not in target:
                target.append(new_value)
        elif hasattr(profile, category):
            setattr(profile, category, new_value if prefer_new else old_value)
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(profile)
        return profile

    def pin_profile(self, user_id: str, pinned: bool = True) -> UserProfile:
        profile = self.load(user_id)
        profile.pinned = pinned
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(profile)
        return profile

    def set_expiry(self, user_id: str, expires_at: str | None) -> UserProfile:
        profile = self.load(user_id)
        profile.expires_at = expires_at
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(profile)
        return profile

    def prune_expired(self, user_id: str) -> UserProfile:
        profile = self.load(user_id)
        if profile.pinned or not profile.expires_at:
            return profile
        try:
            expires = datetime.fromisoformat(profile.expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < expires:
                return profile
        except Exception:
            return profile
        profile.preferences.clear()
        profile.facts.clear()
        profile.tasks.clear()
        profile.projects.clear()
        profile.files.clear()
        profile.devices.clear()
        profile.decisions.clear()
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(profile)
        return profile

    def append_turn(
        self, user_id: str, *, request_text: str, response_text: str
    ) -> UserProfile:
        profile = self.update_from_text(user_id, request_text)
        self.update_from_text(user_id, response_text)
        if "concise" in response_text.lower():
            if "concise" not in profile.preferences:
                profile.preferences.append("concise")
        self.save(profile)
        return profile

    @staticmethod
    def render(profile: UserProfile) -> str:
        lines: list[str] = ["--- [User Profile] ---"]
        if profile.display_name:
            lines.append(f"name: {profile.display_name}")
        if profile.timezone:
            lines.append(f"timezone: {profile.timezone}")
        if profile.locale:
            lines.append(f"locale: {profile.locale}")
        if profile.preferred_language:
            lines.append(f"preferred_language: {profile.preferred_language}")
        if profile.communication_style:
            lines.append(f"communication_style: {profile.communication_style}")
        if profile.preferences:
            lines.append("preferences:")
            lines.extend(f"- {item}" for item in profile.preferences[:8])
        if profile.facts:
            lines.append("facts:")
            lines.extend(f"- {item}" for item in profile.facts[:8])
        if profile.tasks:
            lines.append("tasks:")
            lines.extend(f"- {item}" for item in profile.tasks[:8])
        if profile.projects:
            lines.append("projects:")
            lines.extend(f"- {item}" for item in profile.projects[:8])
        if profile.files:
            lines.append("files:")
            lines.extend(f"- {item}" for item in profile.files[:8])
        if profile.devices:
            lines.append("devices:")
            lines.extend(f"- {item}" for item in profile.devices[:8])
        if profile.decisions:
            lines.append("decisions:")
            lines.extend(f"- {item}" for item in profile.decisions[:8])
        if profile.tools:
            lines.append("tools:")
            lines.extend(f"- {item}" for item in profile.tools[:8])
        return "\n".join(lines)
