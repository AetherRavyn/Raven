"""World Model Building — Raven builds a mental model of the user's life.

Beyond simple facts and preferences, this system builds:
- Relationship maps (who knows whom, who works with whom)
- Project timelines (what happened when, what's coming next)
- Habit patterns (daily routines, weekly cycles)
- Knowledge graph of the user's world
- Temporal understanding (what's past, present, future)

This creates a "living document" of the user's world that
Raven can reason about and predict from.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Entity:
    """An entity in the user's world."""
    entity_id: str
    entity_type: str  # person, project, device, location, concept
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)  # [{type, target_id, properties}]
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class TimelineEvent:
    """An event in the user's world timeline."""
    event_id: str
    event_type: str  # meeting, deadline, milestone, conversation
    title: str
    description: str
    timestamp: str
    entities: list[str] = field(default_factory=list)  # related entity IDs
    metadata: dict[str, Any] = field(default_factory=dict)


class WorldModel:
    """FRIDAY-style world model builder.

    Builds and maintains a mental model of the user's world:
    - People, projects, devices, locations
    - Relationships between entities
    - Timeline of events
    - Habit patterns
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "world_model"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entities_file = self._dir / "entities.json"
        self._timeline_file = self._dir / "timeline.jsonl"
        self._habits_file = self._dir / "habits.json"

    # ── Entity Management ─────────────────────────────────────────

    def upsert_entity(self, entity: Entity) -> None:
        """Add or update an entity."""
        entities = self._load_entities()
        entities[entity.entity_id] = entity
        self._save_entities(entities)

    def get_entity(self, entity_id: str) -> Entity | None:
        entities = self._load_entities()
        return entities.get(entity_id)

    def find_entities(self, entity_type: str | None = None, name_contains: str = "") -> list[Entity]:
        """Find entities by type or name."""
        entities = self._load_entities()
        results = list(entities.values())
        if entity_type:
            results = [e for e in results if e.entity_type == entity_type]
        if name_contains:
            lower = name_contains.lower()
            results = [e for e in results if lower in e.name.lower()]
        return results

    def add_relationship(self, source_id: str, relation_type: str, target_id: str, properties: dict[str, Any] | None = None) -> None:
        """Add a relationship between two entities."""
        entities = self._load_entities()
        source = entities.get(source_id)
        if source:
            source.relationships.append({
                "type": relation_type,
                "target_id": target_id,
                "properties": properties or {},
            })
            self._save_entities(entities)

    def get_related(self, entity_id: str, relation_type: str | None = None) -> list[Entity]:
        """Get all entities related to a given entity."""
        entities = self._load_entities()
        source = entities.get(entity_id)
        if not source:
            return []

        related_ids = []
        for rel in source.relationships:
            if relation_type is None or rel.get("type") == relation_type:
                related_ids.append(rel.get("target_id", ""))

        return [entities[rid] for rid in related_ids if rid in entities]

    def _load_entities(self) -> dict[str, Entity]:
        if not self._entities_file.exists():
            return {}
        try:
            data = json.loads(self._entities_file.read_text(encoding="utf-8"))
            return {eid: Entity(**e) for eid, e in data.items()}
        except Exception:
            return {}

    def _save_entities(self, entities: dict[str, Entity]) -> None:
        from dataclasses import asdict
        self._entities_file.write_text(
            json.dumps({eid: asdict(e) for eid, e in entities.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Timeline ──────────────────────────────────────────────────

    def add_event(self, event: TimelineEvent) -> None:
        """Add an event to the timeline."""
        with open(self._timeline_file, "a", encoding="utf-8") as f:
            from dataclasses import asdict
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def get_recent_events(self, n: int = 20) -> list[TimelineEvent]:
        """Get recent timeline events."""
        if not self._timeline_file.exists():
            return []
        events = []
        for line in self._timeline_file.read_text(encoding="utf-8").strip().splitlines()[-n:]:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                events.append(TimelineEvent(**data))
            except Exception:
                continue
        return events

    # ── Habit Tracking ────────────────────────────────────────────

    def record_habit(self, habit_name: str, timestamp: str | None = None) -> None:
        """Record that a habit was performed."""
        habits = self._load_habits()
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        habits.setdefault(habit_name, []).append(ts)
        # Keep last 100 entries per habit
        if len(habits[habit_name]) > 100:
            habits[habit_name] = habits[habit_name][-100:]
        self._save_habits(habits)

    def get_habit_frequency(self, habit_name: str, days: int = 30) -> float:
        """Get the frequency of a habit (times per day) over the last N days."""
        habits = self._load_habits()
        timestamps = habits.get(habit_name, [])
        if not timestamps:
            return 0.0

        cutoff = datetime.now(timezone.utc).isoformat()[:10]  # Simple day cutoff
        recent = [t for t in timestamps if t[:10] >= cutoff[:10]]
        return len(recent) / max(days, 1)

    def _load_habits(self) -> dict[str, list[str]]:
        if not self._habits_file.exists():
            return {}
        try:
            return json.loads(self._habits_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_habits(self, habits: dict[str, list[str]]) -> None:
        self._habits_file.write_text(
            json.dumps(habits, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Entity Extraction from Conversations ──────────────────────

    def extract_entities_from_conversation(self, user_text: str, assistant_text: str) -> list[Entity]:
        """Extract entities (people, projects, concepts) from conversation text.

        Uses simple heuristics: capitalized phrases for people/projects,
        explicit mentions for concepts.  Can be upgraded to LLM-based
        NER for higher accuracy.
        """
        import re
        entities: list[Entity] = []
        text = f"{user_text} {assistant_text}"

        # People: "my colleague Alice", "my friend Bob", "with Sarah"
        people_patterns = [
            r"my\s+(?:colleague|friend|boss|manager|teammate|partner|wife|husband|brother|sister|mom|dad|mother|father)\s+([A-Z][a-z]+)",
            r"(?:with|from|to|ask)\s+([A-Z][a-z]+)",
            r"([A-Z][a-z]+)\s+(?:said|asked|mentioned|told|wants|needs|requested)",
        ]
        seen_names: set[str] = set()
        for pattern in people_patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                if name.lower() not in {"the", "this", "that", "what", "how", "when", "where", "why", "please", "thanks"} and name not in seen_names:
                    seen_names.add(name)
                    entity_id = f"person_{name.lower()}"
                    entity = Entity(
                        entity_id=entity_id,
                        entity_type="person",
                        name=name,
                        properties={"source": "conversation_extraction"},
                    )
                    self.upsert_entity(entity)
                    entities.append(entity)

        # Projects: "the X project", "working on Y"
        project_patterns = [
            r"(?:the|our|my)\s+(.+?)\s+project",
            r"working\s+on\s+(.+?)(?:\.|,|!|\?|$)",
            r"(?:project|repo|codebase)\s+(.+?)(?:\.|,|!|\?|$)",
        ]
        seen_projects: set[str] = set()
        for pattern in project_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                project_name = match.group(1).strip()[:50]
                if len(project_name) > 3 and project_name not in seen_projects:
                    seen_projects.add(project_name)
                    entity_id = f"project_{project_name.lower().replace(' ', '_')[:30]}"
                    entity = Entity(
                        entity_id=entity_id,
                        entity_type="project",
                        name=project_name,
                        properties={"source": "conversation_extraction"},
                    )
                    self.upsert_entity(entity)
                    entities.append(entity)

        return entities

    # ── Context Building ──────────────────────────────────────────

    def build_world_context(self) -> str:
        """Build a world model context string for LLM prompts."""
        lines = ["## World Model\n"]

        # People
        people = self.find_entities(entity_type="person")
        if people:
            lines.append("### People")
            for p in people[:10]:
                relations = [r.get("type", "") for r in p.relationships[:3]]
                lines.append(f"- {p.name}: {', '.join(relations) if relations else 'no relationships recorded'}")

        # Projects
        projects = self.find_entities(entity_type="project")
        if projects:
            lines.append("\n### Projects")
            for p in projects[:10]:
                status = p.properties.get("status", "unknown")
                lines.append(f"- {p.name}: {status}")

        # Recent events
        events = self.get_recent_events(5)
        if events:
            lines.append("\n### Recent Events")
            for e in events:
                lines.append(f"- {e.title}")

        # Habits
        habits = self._load_habits()
        if habits:
            lines.append("\n### Habits")
            for name, timestamps in list(habits.items())[:5]:
                freq = self.get_habit_frequency(name)
                lines.append(f"- {name}: ~{freq:.1f}x/day")

        return "\n".join(lines) if len(lines) > 1 else ""
