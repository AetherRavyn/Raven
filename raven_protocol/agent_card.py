"""Agent Card — describes a module's capabilities (A2A-inspired).

Each module exposes an Agent Card that tells the system:
- What it can do (skills/capabilities)
- How to talk to it (transport endpoint)
- What data it accepts/produces
- Its version and metadata

This is the "business card" of a module — the system discovers
and routes to modules based on their Agent Cards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class Skill:
    """A single capability exposed by a module."""
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentCard:
    """A2A-style Agent Card describing a module.

    Every module in Raven exposes one of these. The system
    discovers modules by their cards and routes requests
    based on skill matching.
    """
    name: str
    description: str
    version: str = "1.0.0"
    skills: list[Skill] = field(default_factory=list)
    transport: str = "in-process"  # "in-process", "http", "websocket"
    endpoint: str = ""  # URL for http/websocket transport
    auth: dict[str, str] = field(default_factory=dict)  # auth config
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        skills = [Skill(**s) for s in data.get("skills", [])]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            skills=skills,
            transport=data.get("transport", "in-process"),
            endpoint=data.get("endpoint", ""),
            auth=data.get("auth", {}),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> AgentCard:
        return cls.from_dict(json.loads(json_str))

    def has_skill(self, skill_name: str) -> bool:
        return any(s.name == skill_name for s in self.skills)

    def find_skill(self, tags: list[str]) -> Skill | None:
        """Find a skill matching the given tags."""
        for skill in self.skills:
            if any(tag in skill.tags for tag in tags):
                return skill
        return None
