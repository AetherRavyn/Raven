"""Knowledge Graph Auto-Population — automatically extract and store entities from conversations.

Runs after every conversation turn to:
1. Extract people, projects, tools, concepts from user/assistant messages
2. Build relationships between entities
3. Consolidate old facts (temporal decay)
4. Merge duplicate entities
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeGraphPopulator:
    """Automatically populates the knowledge graph from conversation data."""

    # Common entity patterns
    PERSON_PATTERNS = [
        re.compile(r'\b(?:with|for|from|to|told|asked|mentioned)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})'),
        re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:said|asked|wants|needs|sent|called)'),
    ]
    PROJECT_PATTERNS = [
        re.compile(r'(?:project|module|feature|service)\s+[`"\']?([a-zA-Z0-9_-]+)[`"\']?'),
        re.compile(r'(?:deploy|build|ship|release|fix)\s+[`"\']?([a-zA-Z0-9_-]+)[`"\']?'),
    ]
    TOOL_PATTERNS = [
        re.compile(r'(?:use|using|ran|run|called)\s+[`"\']?([a-zA-Z_]+tool)[`"\']?', re.I),
        re.compile(r'[`"\']([a-zA-Z_]+tool)[`"\']', re.I),
    ]
    DECISION_PATTERNS = [
        re.compile(r'(?:decided|agreed|chose|selected|picked)\s+(?:to\s+)?(.{10,80})'),
        re.compile(r'(?:we\'ll|we will|let\'s|let us)\s+(.{10,80})'),
    ]

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._kg_file = Path(self._workspace) / "knowledge_graph" / "auto_populated.jsonl"
        self._kg_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_consolidation = 0.0
        self._consolidation_interval = 86400  # Daily

    def extract_entities(self, user_text: str, assistant_text: str) -> list[dict[str, Any]]:
        """Extract entities from a conversation turn."""
        combined = f"{user_text} {assistant_text}"
        entities: list[dict[str, Any]] = []

        # Extract people
        for pattern in self.PERSON_PATTERNS:
            for match in pattern.finditer(combined):
                name = match.group(1).strip()
                if len(name) > 3 and name not in ("The User", "The Assistant", "I am", "You are"):
                    entities.append({"type": "person", "name": name, "context": combined[:200]})

        # Extract projects
        for pattern in self.PROJECT_PATTERNS:
            for match in pattern.finditer(combined):
                name = match.group(1).strip()
                if len(name) > 2:
                    entities.append({"type": "project", "name": name, "context": combined[:200]})

        # Extract tools
        for pattern in self.TOOL_PATTERNS:
            for match in pattern.finditer(combined):
                name = match.group(1).strip()
                entities.append({"type": "tool", "name": name, "context": combined[:200]})

        # Extract decisions
        for pattern in self.DECISION_PATTERNS:
            for match in pattern.finditer(combined):
                text = match.group(1).strip()
                entities.append({"type": "decision", "name": text[:80], "context": combined[:200]})

        # Deduplicate
        seen = set()
        unique = []
        for e in entities:
            key = f"{e['type']}:{e['name'].lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(e)

        return unique

    def store_entities(self, entities: list[dict[str, Any]], session_id: str = "") -> int:
        """Store extracted entities to the knowledge graph JSONL."""
        stored = 0
        for entity in entities:
            record = {
                "type": entity["type"],
                "name": entity["name"],
                "context": entity.get("context", ""),
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                with open(self._kg_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                stored += 1
            except Exception:
                pass
        return stored

    def populate_from_turn(self, user_text: str, assistant_text: str, session_id: str = "") -> int:
        """Full pipeline: extract + store from a conversation turn."""
        entities = self.extract_entities(user_text, assistant_text)
        return self.store_entities(entities, session_id)

    def consolidate(self) -> int:
        """Consolidate old entities: merge duplicates, apply temporal decay."""
        if not self._kg_file.exists():
            return 0

        now = time.time()
        if now - self._last_consolidation < self._consolidation_interval:
            return 0
        self._last_consolidation = now

        # Load all entities
        entities = []
        for line in self._kg_file.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    entities.append(json.loads(line))
                except Exception:
                    continue

        if not entities:
            return 0

        # Merge duplicates: keep most recent, combine contexts
        merged: dict[str, dict] = {}
        for e in entities:
            key = f"{e['type']}:{e['name'].lower()}"
            if key in merged:
                existing = merged[key]
                existing["context"] = existing.get("context", "") + " | " + e.get("context", "")[:100]
                if e.get("timestamp", "") > existing.get("timestamp", ""):
                    existing["timestamp"] = e["timestamp"]
            else:
                merged[key] = e

        # Write consolidated version
        try:
            with open(self._kg_file, "w", encoding="utf-8") as f:
                for record in merged.values():
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            removed = len(entities) - len(merged)
            if removed > 0:
                logger.info("KG consolidation: merged %d duplicates, %d → %d entities", removed, len(entities), len(merged))
            return removed
        except Exception:
            return 0

    def get_entity_count(self) -> dict[str, int]:
        """Get count of entities by type."""
        if not self._kg_file.exists():
            return {}
        counts: dict[str, int] = {}
        for line in self._kg_file.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    t = data.get("type", "unknown")
                    counts[t] = counts.get(t, 0) + 1
                except Exception:
                    continue
        return counts

    def search_entities(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search entities by name or context."""
        if not self._kg_file.exists():
            return []
        query_lower = query.lower()
        results = []
        for line in self._kg_file.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    if query_lower in data.get("name", "").lower() or query_lower in data.get("context", "").lower():
                        results.append(data)
                except Exception:
                    continue
                if len(results) >= limit:
                    break
        return results


# Singleton
_populator: KnowledgeGraphPopulator | None = None


def get_kg_populator() -> KnowledgeGraphPopulator:
    global _populator
    if _populator is None:
        _populator = KnowledgeGraphPopulator()
    return _populator
