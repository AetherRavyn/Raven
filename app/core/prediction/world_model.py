"""World Model — Core entity and relationship modeling for predictive intelligence.

This module provides the foundational world model that tracks entities (people, projects,
devices, locations, concepts), their relationships, and timeline events. This forms the
basis for causal reasoning and scenario simulation.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Entity:
    """An entity in the user's world."""
    entity_id: str
    entity_type: str  # person, project, device, location, concept, organization
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 1.0
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entity:
        return cls(**data)


@dataclass(slots=True)
class TimelineEvent:
    """An event in the user's world timeline."""
    event_id: str
    event_type: str  # meeting, deadline, milestone, conversation, observation, alert
    title: str
    description: str
    timestamp: str
    entities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelineEvent:
        return cls(**data)


@dataclass(slots=True)
class HabitPattern:
    """A detected habit or routine pattern."""
    pattern_id: str
    name: str
    entity_ids: list[str]
    frequency: str  # daily, weekly, monthly, irregular
    typical_time: str | None = None  # HH:MM or cron-like
    duration_minutes: int | None = None
    confidence: float = 0.5
    evidence_count: int = 0
    last_observed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorldModel:
    """FRIDAY-style world model builder.

    Builds and maintains a mental model of the user's world:
    - People, projects, devices, locations, organizations, concepts
    - Relationships between entities (works_with, owns, located_at, member_of, etc.)
    - Timeline of events
    - Habit patterns
    - Entity properties and state
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "world_model"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entities_file = self._dir / "entities.json"
        self._timeline_file = self._dir / "timeline.jsonl"
        self._habits_file = self._dir / "habits.json"
        self._index_file = self._dir / "entity_index.json"

    # ── Entity Management ─────────────────────────────────────────

    def upsert_entity(self, entity: Entity) -> None:
        """Add or update an entity."""
        entities = self._load_entities()
        entity.last_seen = datetime.now(timezone.utc).isoformat()
        entities[entity.entity_id] = entity
        self._save_entities(entities)
        self._update_index(entity)

    def get_entity(self, entity_id: str) -> Entity | None:
        entities = self._load_entities()
        return entities.get(entity_id)

    def find_entities(
        self,
        entity_type: str | None = None,
        name_contains: str = "",
        property_filter: dict[str, Any] | None = None
    ) -> list[Entity]:
        """Find entities by type, name, or properties."""
        entities = self._load_entities()
        results = list(entities.values())
        if entity_type:
            results = [e for e in results if e.entity_type == entity_type]
        if name_contains:
            lower = name_contains.lower()
            results = [e for e in results if lower in e.name.lower()]
        if property_filter:
            for key, value in property_filter.items():
                results = [e for e in results if e.properties.get(key) == value]
        return results

    def add_relationship(
        self,
        source_id: str,
        relation_type: str,
        target_id: str,
        properties: dict[str, Any] | None = None,
        confidence: float = 1.0
    ) -> None:
        """Add a relationship between two entities."""
        entities = self._load_entities()
        source = entities.get(source_id)
        target = entities.get(target_id)
        if not source or not target:
            logger.warning(f"Cannot add relationship: source={source_id} or target={target_id} not found")
            return
        source.relationships.append({
            "type": relation_type,
            "target_id": target_id,
            "properties": properties or {},
            "confidence": confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Add reverse relationship for bidirectional queries
        reverse_type = self._get_reverse_relation(relation_type)
        if reverse_type:
            target.relationships.append({
                "type": reverse_type,
                "target_id": source_id,
                "properties": properties or {},
                "confidence": confidence,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        self._save_entities(entities)

    def get_related(
        self,
        entity_id: str,
        relation_type: str | None = None,
        min_confidence: float = 0.0
    ) -> list[Entity]:
        """Get all entities related to a given entity."""
        entities = self._load_entities()
        source = entities.get(entity_id)
        if not source:
            return []

        related_ids = []
        for rel in source.relationships:
            if rel.get("confidence", 1.0) < min_confidence:
                continue
            if relation_type is None or rel.get("type") == relation_type:
                related_ids.append(rel.get("target_id", ""))

        return [entities[rid] for rid in related_ids if rid in entities]

    def _get_reverse_relation(self, relation_type: str) -> str | None:
        """Get the reverse of a relationship type."""
        reverse_map = {
            "works_with": "works_with",
            "manages": "managed_by",
            "managed_by": "manages",
            "owns": "owned_by",
            "owned_by": "owns",
            "located_at": "location_of",
            "location_of": "located_at",
            "member_of": "has_member",
            "has_member": "member_of",
            "knows": "knows",
            "reports_to": "supervises",
            "supervises": "reports_to",
            "collaborates_with": "collaborates_with",
            "depends_on": "required_by",
            "required_by": "depends_on",
        }
        return reverse_map.get(relation_type)

    def _load_entities(self) -> dict[str, Entity]:
        if not self._entities_file.exists():
            return {}
        try:
            data = json.loads(self._entities_file.read_text(encoding="utf-8"))
            return {eid: Entity.from_dict(e) for eid, e in data.items()}
        except Exception as e:
            logger.error(f"Failed to load entities: {e}")
            return {}

    def _save_entities(self, entities: dict[str, Entity]) -> None:
        self._entities_file.write_text(
            json.dumps({eid: asdict(e) for eid, e in entities.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _update_index(self, entity: Entity) -> None:
        """Update the search index for fast lookups."""
        index = self._load_index()
        index.setdefault("by_type", defaultdict(list))
        index.setdefault("by_name", {})
        index["by_type"][entity.entity_type].append(entity.entity_id)
        index["by_name"][entity.name.lower()] = entity.entity_id
        self._save_index(index)

    def _load_index(self) -> dict[str, Any]:
        if not self._index_file.exists():
            return {"by_type": defaultdict(list), "by_name": {}}
        try:
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        except Exception:
            return {"by_type": defaultdict(list), "by_name": {}}

    def _save_index(self, index: dict[str, Any]) -> None:
        # Convert defaultdict to dict for JSON serialization
        if isinstance(index.get("by_type"), defaultdict):
            index["by_type"] = dict(index["by_type"])
        self._index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Timeline ──────────────────────────────────────────────────

    def add_event(self, event: TimelineEvent) -> None:
        """Add an event to the timeline."""
        with open(self._timeline_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        # Update entity last_seen
        for entity_id in event.entities:
            entity = self.get_entity(entity_id)
            if entity:
                entity.last_seen = datetime.now(timezone.utc).isoformat()
                self.upsert_entity(entity)

    def get_recent_events(self, n: int = 20) -> list[TimelineEvent]:
        """Get recent timeline events."""
        if not self._timeline_file.exists():
            return []
        events = []
        try:
            lines = self._timeline_file.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-n:]:
                if not line.strip():
                    continue
                data = json.loads(line)
                events.append(TimelineEvent.from_dict(data))
        except Exception as e:
            logger.error(f"Failed to load timeline events: {e}")
        return events

    def get_events_for_entity(self, entity_id: str, n: int = 50) -> list[TimelineEvent]:
        """Get timeline events involving a specific entity."""
        if not self._timeline_file.exists():
            return []
        events = []
        try:
            lines = self._timeline_file.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                data = json.loads(line)
                if entity_id in data.get("entities", []):
                    events.append(TimelineEvent.from_dict(data))
                    if len(events) >= n:
                        break
        except Exception as e:
            logger.error(f"Failed to load entity events: {e}")
        return list(reversed(events))

    def get_events_in_range(self, start: str, end: str) -> list[TimelineEvent]:
        """Get events within a time range (ISO format)."""
        if not self._timeline_file.exists():
            return []
        events = []
        try:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            lines = self._timeline_file.read_text(encoding="utf-8").strip().splitlines()
            for line in lines:
                if not line.strip():
                    continue
                data = json.loads(line)
                event_dt = datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00'))
                if start_dt <= event_dt <= end_dt:
                    events.append(TimelineEvent.from_dict(data))
        except Exception as e:
            logger.error(f"Failed to load events in range: {e}")
        return events

    # ── Habit Patterns ────────────────────────────────────────────

    def add_habit(self, habit: HabitPattern) -> None:
        """Add or update a habit pattern."""
        habits = self._load_habits()
        habits[habit.pattern_id] = habit
        self._save_habits(habits)

    def get_habits(self, entity_id: str | None = None) -> list[HabitPattern]:
        """Get all habits, optionally filtered by entity."""
        habits = list(self._load_habits().values())
        if entity_id:
            habits = [h for h in habits if entity_id in h.entity_ids]
        return habits

    def _load_habits(self) -> dict[str, HabitPattern]:
        if not self._habits_file.exists():
            return {}
        try:
            data = json.loads(self._habits_file.read_text(encoding="utf-8"))
            return {pid: HabitPattern(**h) for pid, h in data.items()}
        except Exception:
            return {}

    def _save_habits(self, habits: dict[str, HabitPattern]) -> None:
        self._habits_file.write_text(
            json.dumps({pid: asdict(h) for pid, h in habits.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Query Helpers ─────────────────────────────────────────────

    def get_entity_graph(self, entity_id: str, depth: int = 2) -> dict[str, Any]:
        """Get a subgraph of entities around a given entity."""
        visited = set()
        nodes = []
        edges = []

        def traverse(eid: str, current_depth: int):
            if eid in visited or current_depth > depth:
                return
            visited.add(eid)
            entity = self.get_entity(eid)
            if not entity:
                return
            nodes.append({
                "id": entity.entity_id,
                "type": entity.entity_type,
                "name": entity.name,
                "properties": entity.properties,
            })
            for rel in entity.relationships:
                target_id = rel.get("target_id")
                if target_id and target_id not in visited:
                    edges.append({
                        "source": eid,
                        "target": target_id,
                        "type": rel.get("type"),
                        "confidence": rel.get("confidence", 1.0),
                    })
                    traverse(target_id, current_depth + 1)

        traverse(entity_id, 0)
        return {"nodes": nodes, "edges": edges}

    def get_timeline_summary(self, days: int = 7) -> dict[str, Any]:
        """Get a summary of recent timeline activity."""
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        events = self.get_events_in_range(start.isoformat(), end.isoformat())

        by_type = defaultdict(int)
        by_entity = defaultdict(int)
        for event in events:
            by_type[event.event_type] += 1
            for eid in event.entities:
                by_entity[eid] += 1

        top_entities = sorted(by_entity.items(), key=lambda x: x[1], reverse=True)[:10]
        top_entities_detail = [
            {"entity_id": eid, "count": count, "entity": self.get_entity(eid).to_dict() if self.get_entity(eid) else None}
            for eid, count in top_entities
        ]

        return {
            "period_days": days,
            "total_events": len(events),
            "by_type": dict(by_type),
            "top_entities": top_entities_detail,
        }

    # ── Factory Methods ───────────────────────────────────────────

    @classmethod
    def create_person(
        cls,
        model: "WorldModel",
        name: str,
        properties: dict[str, Any] | None = None
    ) -> Entity:
        entity = Entity(
            entity_id=str(uuid.uuid4())[:8],
            entity_type="person",
            name=name,
            properties=properties or {},
        )
        model.upsert_entity(entity)
        return entity

    @classmethod
    def create_project(
        cls,
        model: "WorldModel",
        name: str,
        properties: dict[str, Any] | None = None
    ) -> Entity:
        entity = Entity(
            entity_id=str(uuid.uuid4())[:8],
            entity_type="project",
            name=name,
            properties=properties or {},
        )
        model.upsert_entity(entity)
        return entity

    @classmethod
    def create_device(
        cls,
        model: "WorldModel",
        name: str,
        properties: dict[str, Any] | None = None
    ) -> Entity:
        entity = Entity(
            entity_id=str(uuid.uuid4())[:8],
            entity_type="device",
            name=name,
            properties=properties or {},
        )
        model.upsert_entity(entity)
        return entity

    @classmethod
    def create_location(
        cls,
        model: "WorldModel",
        name: str,
        properties: dict[str, Any] | None = None
    ) -> Entity:
        entity = Entity(
            entity_id=str(uuid.uuid4())[:8],
            entity_type="location",
            name=name,
            properties=properties or {},
        )
        model.upsert_entity(entity)
        return entity

    @classmethod
    def create_concept(
        cls,
        model: "WorldModel",
        name: str,
        properties: dict[str, Any] | None = None
    ) -> Entity:
        entity = Entity(
            entity_id=str(uuid.uuid4())[:8],
            entity_type="concept",
            name=name,
            properties=properties or {},
        )
        model.upsert_entity(entity)
        return entity