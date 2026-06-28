"""Curiosity Module — intrinsic motivation for self-driven exploration.

Identifies knowledge gaps Raven can autonomously fill during
ambient-loop idle cycles.  Gaps come from three sources:

1. **Sparse KG entities** — entities with few relationships
   (Raven knows they exist but little else).
2. **Unanswered questions** — topics the user asked about where
   the KG had no matching facts at query time.
3. **Domain curiosity** — domains the user engages with frequently
   that have thin KG coverage.

Each gap is scored by importance and optionally promoted to a
``GoalManager`` goal for autonomous pursuit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KnowledgeGap:
    """A topic or entity Raven knows little about."""

    domain: str
    question: str
    importance: float  # 0.0 – 1.0
    confidence: float  # 0.0 – 1.0 (how sure this is a real gap)
    source: str = "unknown"  # "sparse_entity" | "unanswered" | "domain_thin"
    entity_name: str = ""


@dataclass(slots=True)
class ExplorationResult:
    """Result of filling a knowledge gap."""

    gap: KnowledgeGap
    facts_written: int
    summary: str
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CuriosityModule:
    """Identifies knowledge gaps and drives autonomous exploration.

    Designed to be called periodically (e.g. every 30 min from the
    ambient loop).  Each tick scans for gaps, picks the most
    important one, and either creates a goal for it or explores
    it directly.
    """

    def __init__(
        self,
        workspace_dir: str = "workspace",
        goal_manager: Any | None = None,
        kg_manager: Any | None = None,
        memory_facade: Any | None = None,
    ) -> None:
        self._workspace = Path(workspace_dir)
        self._exploration_log = self._workspace / "curiosity" / "explorations.jsonl"
        self._exploration_log.parent.mkdir(parents=True, exist_ok=True)

        self._goal_manager = goal_manager
        self._kg_manager = kg_manager
        self._memory_facade = memory_facade

        # Track which gaps we've already explored (dedup)
        self._explored_domains: set[str] = set()

    # ── Public API ───────────────────────────────────────────────────

    async def identify_gaps(
        self, recent_user_queries: list[str] | None = None
    ) -> list[KnowledgeGap]:
        """Scan all gap sources and return scored candidates."""
        gaps: list[KnowledgeGap] = []

        # 1. Sparse entities from KG
        try:
            kg_gaps = await self._scan_sparse_entities()
            gaps.extend(kg_gaps)
        except Exception as exc:
            logger.debug("Curiosity: sparse-entity scan failed — %s", exc)

        # 2. Unanswered questions from recent queries
        if recent_user_queries:
            try:
                query_gaps = await self._scan_unanswered_queries(recent_user_queries)
                gaps.extend(query_gaps)
            except Exception as exc:
                logger.debug("Curiosity: unanswered-query scan failed — %s", exc)

        # 3. Domain curiosity from interaction patterns
        try:
            domain_gaps = await self._scan_domain_coverage()
            gaps.extend(domain_gaps)
        except Exception as exc:
            logger.debug("Curiosity: domain-coverage scan failed — %s", exc)

        # Deduplicate and sort by importance
        seen: set[str] = set()
        unique: list[KnowledgeGap] = []
        for g in sorted(gaps, key=lambda x: -x.importance):
            key = f"{g.domain}:{g.question}"
            if key not in seen and g.domain not in self._explored_domains:
                seen.add(key)
                unique.append(g)

        return unique

    async def execute_exploration(self, gap: KnowledgeGap) -> ExplorationResult:
        """Fill a knowledge gap by researching and recording facts.

        Uses web search to find information about the gap topic,
        then records discovered facts into the knowledge graph.
        """
        logger.info("Curiosity: exploring gap — %s: %s", gap.domain, gap.question)

        facts_written = 0
        summary = ""

        try:
            # Use web search to research the gap
            search_results = await self._research_topic(gap)
            if not search_results:
                return ExplorationResult(
                    gap=gap,
                    facts_written=0,
                    summary="No information found.",
                    success=False,
                )

            # Extract facts from search results and record them
            facts_written = await self._record_discoveries(gap, search_results)
            summary = self._summarize_discoveries(gap, search_results)

            self._explored_domains.add(gap.domain)
            self._log_exploration(gap, facts_written, summary, success=True)
            logger.info("Curiosity: explored %s — %d facts written", gap.domain, facts_written)
            return ExplorationResult(
                gap=gap,
                facts_written=facts_written,
                summary=summary,
                success=True,
            )

        except Exception as exc:
            logger.debug("Curiosity: exploration failed for %s — %s", gap.domain, exc)
            self._log_exploration(gap, 0, str(exc), success=False)
            return ExplorationResult(
                gap=gap,
                facts_written=0,
                summary=str(exc),
                success=False,
            )

    async def promote_to_goal(self, gap: KnowledgeGap) -> str | None:
        """Promote a knowledge gap to a GoalManager goal.

        Returns the goal ID if created, None otherwise.
        """
        if self._goal_manager is None:
            return None

        try:
            goal = self._goal_manager.create_goal(
                title=f"Explore: {gap.domain}",
                description=gap.question,
                priority=2 if gap.importance > 0.7 else 3,
                tags=["curiosity", "knowledge", gap.domain],
            )
            self._goal_manager.add_subtask(
                goal.id,
                title=f"Research {gap.domain}",
                description=gap.question,
            )
            self._goal_manager.add_subtask(
                goal.id,
                title=f"Record findings about {gap.domain}",
                depends_on=[goal.subtasks[0].id],
            )
            logger.info("Curiosity: promoted gap to goal %s", goal.id)
            return goal.id
        except Exception as exc:
            logger.debug("Curiosity: promote_to_goal failed — %s", exc)
            return None

    # ── Gap Sources ──────────────────────────────────────────────────

    async def _scan_sparse_entities(self) -> list[KnowledgeGap]:
        """Find KG entities that have few relationships.

        An entity that's mentioned but has <3 relationships is a
        knowledge gap — we know it exists but little else.
        """
        gaps: list[KnowledgeGap] = []
        if self._kg_manager is None:
            return gaps

        # Query recent entities from the KG
        # We look for entities the manager has recorded facts about
        # and check how many relationships each has.
        try:
            # Get a sample of entity names from the KG by querying
            # common categories the user has asked about
            candidate_entities = await self._get_candidate_entities()
            for entity in candidate_entities:
                facts = self._kg_manager.query(entity)
                if facts is None:
                    continue
                # If the entity has 1-2 facts, it's sparse
                if 1 <= len(facts) <= 2:
                    domain = self._classify_entity(entity)
                    gaps.append(
                        KnowledgeGap(
                            domain=domain,
                            question=f"What else should I know about {entity}?",
                            importance=0.6,
                            confidence=0.7,
                            source="sparse_entity",
                            entity_name=entity,
                        )
                    )
        except Exception as exc:
            logger.debug("Curiosity: sparse entity scan error — %s", exc)

        return gaps

    async def _scan_unanswered_queries(self, recent_queries: list[str]) -> list[KnowledgeGap]:
        """Find user queries that the KG couldn't answer."""
        gaps: list[KnowledgeGap] = []
        if self._kg_manager is None:
            return gaps

        for query in recent_queries:
            # Extract potential entity names from the query
            entities = self._extract_entities(query)
            for entity in entities:
                facts = self._kg_manager.query(entity)
                if facts is None or len(facts) == 0:
                    # The user asked about something we know nothing about
                    domain = self._classify_entity(entity)
                    gaps.append(
                        KnowledgeGap(
                            domain=domain,
                            question=f"User asked about '{entity}' but KG has no facts",
                            importance=0.8,
                            confidence=0.6,
                            source="unanswered",
                            entity_name=entity,
                        )
                    )
        return gaps

    async def _scan_domain_coverage(self) -> list[KnowledgeGap]:
        """Identify thin domains — broad topics with few KG facts."""
        gaps: list[KnowledgeGap] = []
        if self._kg_manager is None:
            return gaps

        # Known broad domains we should have coverage on
        core_domains = [
            ("computer_science", "programming"),
            ("science", "physics"),
            ("mathematics", "mathematics"),
            ("history", "world_history"),
            ("geography", "geography"),
            ("biology", "life_sciences"),
            ("astronomy", "space"),
            ("technology", "technology"),
            ("philosophy", "philosophy"),
            ("economics", "economics"),
        ]

        for domain, tag in core_domains:
            facts = self._kg_manager.query(tag)
            if facts is None or len(facts) < 3:
                gaps.append(
                    KnowledgeGap(
                        domain=domain,
                        question=f"KG has limited coverage of {domain} ({len(facts) if facts else 0} facts)",
                        importance=0.4,
                        confidence=0.5,
                        source="domain_thin",
                        entity_name=tag,
                    )
                )

        return gaps

    # ── Helpers ──────────────────────────────────────────────────────

    async def _research_topic(self, gap: KnowledgeGap) -> list[dict[str, str]]:
        """Search the web for information about a gap topic.

        Returns a list of result dicts with 'title', 'snippet', 'url' keys.
        """
        # Try to use the orchestrator's web search via tool registry
        # For ambient use, import and use the WebOperationTool directly
        results: list[dict[str, str]] = []

        try:
            from app.tools.websearch import WebOperationTool

            tool = WebOperationTool()
            search_result = await tool.execute(
                operation="search",
                query=f"what is {gap.entity_name or gap.domain}",
                max_results=5,
            )
            if isinstance(search_result, dict):
                entries = search_result.get("results", []) or search_result.get("entries", [])
                for entry in entries[:5]:
                    if isinstance(entry, dict):
                        results.append(
                            {
                                "title": str(entry.get("title", "")),
                                "snippet": str(
                                    entry.get("snippet")
                                    or entry.get("content", "")
                                    or entry.get("description", "")
                                ),
                                "url": str(entry.get("url", "")),
                            }
                        )
        except Exception as exc:
            logger.debug("Curiosity: web search failed — %s", exc)

        return results

    async def _record_discoveries(
        self, gap: KnowledgeGap, search_results: list[dict[str, str]]
    ) -> int:
        """Extract facts from search results and record them in the KG."""
        if self._kg_manager is None:
            return 0

        count = 0
        entity = gap.entity_name or gap.domain

        for result in search_results:
            snippet = result.get("snippet", "")
            if not snippet or len(snippet) < 20:
                continue

            # Try to extract predicate-object pairs from snippets
            # This is a simple heuristic — in production, use the LLM
            facts = self._extract_facts_from_snippet(entity, snippet)
            for predicate, obj in facts:
                try:
                    self._kg_manager.record_fact(entity, predicate, obj, source="curiosity")
                    count += 1
                except Exception:
                    continue

        return count

    def _extract_facts_from_snippet(self, entity: str, snippet: str) -> list[tuple[str, str]]:
        """Heuristic fact extraction from a text snippet.

        Returns list of (predicate, object) pairs.
        """
        facts: list[tuple[str, str]] = []
        lower = snippet.lower()

        # "X is a Y" → is_a
        m = re.search(
            rf"{re.escape(entity)}\s+is\s+a(?:n)?\s+([\w\s]+?)(?:[,.]|\s+that|\s+which|\s+who)",
            lower,
        )
        if m:
            facts.append(("is_a", m.group(1).strip()))

        # "X is known for Y" → known_for
        m = re.search(rf"{re.escape(entity)}\s+is\s+known\s+for\s+([\w\s]+?)(?:[,.]|$)", lower)
        if m:
            facts.append(("known_for", m.group(1).strip()))

        # "X was born in Y" → born_in
        m = re.search(
            rf"{re.escape(entity)}\s+was\s+born\s+(?:in|on)\s+([\w\s]+?)(?:[,.]|$)", lower
        )
        if m:
            facts.append(("born_in", m.group(1).strip()))

        # "X is located in Y" → located_in
        m = re.search(rf"{re.escape(entity)}\s+is\s+located\s+in\s+([\w\s]+?)(?:[,.]|$)", lower)
        if m:
            facts.append(("located_in", m.group(1).strip()))

        # "X developed Y" → developed
        m = re.search(
            rf"{re.escape(entity)}\s+(?:developed|created|invented|founded)\s+([\w\s]+?)(?:[,.]|$)",
            lower,
        )
        if m:
            facts.append(("developed", m.group(1).strip()))

        return facts

    def _summarize_discoveries(
        self, gap: KnowledgeGap, search_results: list[dict[str, str]]
    ) -> str:
        """Build a short summary of what was discovered."""
        titles = [r.get("title", "") for r in search_results if r.get("title")]
        if titles:
            domain = gap.domain.replace("_", " ").title()
            return f"Learned about {domain}: " + "; ".join(titles[:3])
        return f"Gathered information about {gap.domain}"

    async def _get_candidate_entities(self) -> list[str]:
        """Get entity names from the KG to check for sparsity.

        Queries common categories that the user might have
        mentioned.
        """
        if self._kg_manager is None:
            return []

        candidates: set[str] = set()

        # Query some broad categories that the KG might have
        for category in ["user", "project", "person", "technology", "tool", "location"]:
            try:
                facts = self._kg_manager.query(category)
                if facts:
                    for fact in facts:
                        # Collect subject and object as potential entities
                        if hasattr(fact, "subject"):
                            candidates.add(fact.subject)
                        if hasattr(fact, "object"):
                            candidates.add(str(fact.object))
            except Exception:
                continue

        return list(candidates)[:50]  # limit to 50 candidates

    @staticmethod
    def _classify_entity(entity: str) -> str:
        """Guess a domain for an entity name."""
        entity_lower = entity.lower()

        # Technology
        if any(
            kw in entity_lower
            for kw in (
                "python",
                "javascript",
                "rust",
                "docker",
                "kubernetes",
                "linux",
                "git",
                "api",
                "framework",
                "library",
                "database",
                "algorithm",
                "protocol",
            )
        ):
            return "technology"

        # People
        if any(kw in entity_lower for kw in ("dr.", "prof.", "albert", "elon", "swadhin")):
            return "people"

        # Science
        if any(
            kw in entity_lower
            for kw in ("physics", "chemistry", "biology", "quantum", "neural", "genome")
        ):
            return "science"

        # Projects
        if any(kw in entity_lower for kw in ("project", "raven", "aether", "agent", "module")):
            return "projects"

        # Locations
        if any(
            kw in entity_lower for kw in ("city", "country", "river", "mountain", "ocean", "planet")
        ):
            return "geography"

        return "general_knowledge"

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Simple noun-phrase extraction to find entity candidates.

        In production, replace with an NER model or LLM call.
        """
        words = text.split()
        entities: list[str] = []
        i = 0
        while i < len(words):
            word = words[i]
            # Capitalized words (potential named entities)
            if (
                word[0].isupper()
                and len(word) > 1
                and word.lower()
                not in {
                    "i",
                    "my",
                    "the",
                    "this",
                    "that",
                    "what",
                    "how",
                    "why",
                }
            ):
                entity = word
                # Check for multi-word entities
                j = i + 1
                while j < len(words) and words[j][0].isupper():
                    entity += " " + words[j]
                    j += 1
                entities.append(entity)
                i = j
                continue
            i += 1
        return entities[:5]  # limit to top 5

    def _log_exploration(
        self, gap: KnowledgeGap, facts_written: int, summary: str, success: bool
    ) -> None:
        """Append an exploration record to the JSONL log."""
        import json

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": gap.domain,
            "question": gap.question,
            "source": gap.source,
            "entity": gap.entity_name,
            "facts_written": facts_written,
            "summary": summary,
            "success": success,
        }
        try:
            with open(self._exploration_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("Curiosity: failed to log exploration — %s", exc)

    def get_exploration_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent exploration records."""
        import json

        if not self._exploration_log.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in self._exploration_log.read_text(encoding="utf-8").strip().splitlines():
                if line.strip():
                    records.append(json.loads(line))
        except Exception:
            pass
        return records[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about curiosity-driven exploration."""
        history = self.get_exploration_history(limit=1000)
        total = len(history)
        successes = sum(1 for r in history if r.get("success"))
        total_facts = sum(r.get("facts_written", 0) for r in history)
        domains = set(r.get("domain", "") for r in history)
        return {
            "total_explorations": total,
            "successful_explorations": successes,
            "total_facts_written": total_facts,
            "unique_domains_explored": len(domains),
            "domains": sorted(domains),
            "success_rate": successes / total if total > 0 else 0.0,
        }


# ── Singleton ─────────────────────────────────────────────────────

_GLOBAL_CURIOSITY: CuriosityModule | None = None


def get_curiosity_module(
    workspace_dir: str = "workspace",
) -> CuriosityModule:
    global _GLOBAL_CURIOSITY
    if _GLOBAL_CURIOSITY is None:
        _GLOBAL_CURIOSITY = CuriosityModule(workspace_dir=workspace_dir)
    return _GLOBAL_CURIOSITY
