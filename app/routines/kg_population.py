"""Background routine to auto-populate knowledge graph from conversations.

Extracts entities (people, places, things, concepts) and relationships
from recent conversations and adds them to the knowledge graph for
Graph-RAG deductive reasoning.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from app.settings.config import Config

logger = logging.getLogger(__name__)


class KnowledgeGraphPopulator:
    """Extracts entities and relationships from conversations and populates the knowledge graph."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self._kg_tool = None

    def _get_kg_tool(self):
        """Lazy-load the knowledge graph tool."""
        if self._kg_tool is None:
            try:
                from app.tools.kgtool import KnowledgeGraphTool
                self._kg_tool = KnowledgeGraphTool()
            except Exception as exc:
                logger.warning("KnowledgeGraphPopulator: KG tool unavailable — %s", exc)
        return self._kg_tool

    def _get_recent_sessions(self, hours: int = 24) -> str:
        """Get recent session content for entity extraction."""
        sessions_dir = Path(self.workspace_dir) / "sessions"
        if not sessions_dir.exists():
            return ""

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent_text = []

        try:
            for file_path in sessions_dir.glob("*.jsonl"):
                stat = file_path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if mtime >= cutoff:
                    try:
                        lines = file_path.read_text(encoding="utf-8").splitlines()
                        session_content = []
                        for line in lines[-30:]:  # Last 30 messages
                            if not line.strip():
                                continue
                            msg = json.loads(line)
                            role = msg.get("role", "unknown")
                            content = msg.get("content", "")
                            if isinstance(content, str) and content.strip():
                                # Skip system messages
                                if role in ("user", "assistant"):
                                    session_content.append(f"{role}: {content.strip()[:500]}")
                        if session_content:
                            recent_text.append(f"=== Session {file_path.stem} ===")
                            recent_text.extend(session_content)
                    except Exception as e:
                        logger.warning("Error reading session %s: %s", file_path, e)
        except Exception as e:
            logger.warning("Error scanning sessions: %s", e)

        return "\n".join(recent_text)

    async def extract_entities_with_llm(self, text: str) -> list[dict[str, str]]:
        """Use LLM to extract entities and relationships from text."""
        from app.core.model_router import AutoModelRouter
        from app.provider.factory import create_provider

        try:
            provider_name, model_name = AutoModelRouter.get_best_model("agent")
            provider = create_provider(provider_name)
        except Exception:
            logger.warning("No provider available for entity extraction")
            return []

        prompt = f"""You are an entity extraction AI. Analyze the following conversation and extract meaningful entities and their relationships.

Focus on:
- People (names, roles)
- Places (locations, servers, devices)
- Things (projects, tools, technologies)
- Concepts (ideas, plans, goals)
- Relationships between entities (owns, uses, works on, located at, etc.)

Return ONLY valid JSON in this exact format:
{{
  "entities": [
    {{"name": "Entity Name", "type": "person|place|thing|concept"}},
    ...
  ],
  "relationships": [
    {{"from": "Entity1", "relation": "VERB", "to": "Entity2"}},
    ...
  ]
}}

If no meaningful entities are found, return {{"entities": [], "relationships": []}}.

Conversation:
{text[:4000]}
"""

        try:
            resilient = getattr(provider, "chat_completion_resilient", None)
            if resilient:
                result = await resilient(
                    messages=[{"role": "user", "content": prompt}],
                    preferred_models=[
                        "big-pickle",
                        "deepseek-v4-flash-free",
                    ],
                    free_only_guard=True,
                )
            else:
                result = await provider.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=model_name or "google/gemini-2.5-flash:free",
                )

            if not isinstance(result, dict) or not result.get("success"):
                return []

            content = result.get("content", "").strip()
            # Strip markdown code blocks if present
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            extracted = json.loads(content)
            return extracted.get("relationships", [])

        except Exception as e:
            logger.debug("Entity extraction failed: %s", e)
            return []

    async def populate_graph(self, hours: int = 24) -> int:
        """Extract entities from recent sessions and populate the knowledge graph.

        Returns the number of relationships added.
        """
        kg_tool = self._get_kg_tool()
        if not kg_tool:
            logger.warning("Knowledge graph tool not available")
            return 0

        sessions_text = self._get_recent_sessions(hours)
        if not sessions_text.strip():
            logger.info("No recent sessions to process for KG population")
            return 0

        logger.info("Extracting entities from %d chars of session data", len(sessions_text))

        # Extract entities and relationships using LLM
        relationships = await self.extract_entities_with_llm(sessions_text)

        if not relationships:
            logger.info("No entities/relationships extracted")
            return 0

        # Add relationships to Neo4j
        added_count = 0
        for rel in relationships:
            try:
                entity1 = rel.get("from", "").strip()
                relation = rel.get("relation", "RELATED_TO").strip().upper().replace(" ", "_")
                entity2 = rel.get("to", "").strip()

                if not entity1 or not entity2:
                    continue

                # Sanitize relation name for Cypher
                relation = re.sub(r"[^A-Z0-9_]", "_", relation)
                if not relation:
                    relation = "RELATED_TO"

                result = await kg_tool.execute(
                    operation="add_relationship",
                    entity1=entity1,
                    relation=relation,
                    entity2=entity2,
                )

                if result.get("success"):
                    added_count += 1
                    logger.debug("Added KG relationship: [%s] -[%s]-> [%s]", entity1, relation, entity2)

            except Exception as e:
                logger.debug("Failed to add relationship: %s", e)

        logger.info("Knowledge graph population: added %d relationships", added_count)
        return added_count


def register_kg_populator(
    scheduler: Any, interval_hours: int = 6
) -> None:
    """Register the knowledge graph population routine."""

    async def _fire() -> None:
        try:
            populator = KnowledgeGraphPopulator()
            await populator.populate_graph(interval_hours)
        except Exception as e:
            logger.error("Error in KG population routine: %s", e)

    job_id = "kg_populator"

    scheduler._scheduler.add_job(
        _fire,
        trigger=IntervalTrigger(hours=interval_hours),
        id=job_id,
        replace_existing=True,
    )
    logger.info("Knowledge graph populator registered every %d hours", interval_hours)
