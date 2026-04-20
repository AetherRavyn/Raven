import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent_reach.core import AgentReach

logger = logging.getLogger(__name__)


class WatchedTopic(BaseModel):
    id: str
    query: str
    interval_seconds: int = 3600
    last_checked: float = 0.0
    status: str = "active"


class EvidenceItem(BaseModel):
    id: str
    topic_id: str
    source_url: str
    title: str
    snippet: str
    timestamp: float
    sentiment: str = "neutral"
    claims: List[str] = Field(default_factory=list)


class PerceptionEngine:
    """
    Background engine that continuously monitors the internet for watched topics.
    It extracts claims, updates the evidence database, and feeds into the world graph.
    """

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.topics_file = os.path.join(self.workspace_dir, "watched_topics.json")
        self.evidence_file = os.path.join(self.workspace_dir, "evidence.jsonl")
        self.reach = AgentReach()
        self._ensure_files()

    def _ensure_files(self):
        if not os.path.exists(self.workspace_dir):
            os.makedirs(self.workspace_dir)
        if not os.path.exists(self.topics_file):
            with open(self.topics_file, "w") as f:
                json.dump([], f)
        if not os.path.exists(self.evidence_file):
            open(self.evidence_file, "w").close()

    def list_topics(self) -> List[WatchedTopic]:
        with open(self.topics_file, "r") as f:
            data = json.load(f)
        return [WatchedTopic(**item) for item in data]

    def add_topic(self, query: str, interval_seconds: int = 3600) -> WatchedTopic:
        import uuid

        topics = self.list_topics()
        # Check if exists
        for t in topics:
            if t.query.lower() == query.lower():
                return t

        new_topic = WatchedTopic(
            id=f"topic_{uuid.uuid4().hex[:8]}",
            query=query,
            interval_seconds=interval_seconds,
        )
        topics.append(new_topic)
        self._save_topics(topics)
        return new_topic

    def remove_topic(self, topic_id: str) -> bool:
        topics = self.list_topics()
        filtered = [t for t in topics if t.id != topic_id]
        if len(filtered) < len(topics):
            self._save_topics(filtered)
            return True
        return False

    def _save_topics(self, topics: List[WatchedTopic]):
        with open(self.topics_file, "w") as f:
            json.dump([t.dict() for t in topics], f, indent=2)

    def save_evidence(self, evidence: EvidenceItem):
        with open(self.evidence_file, "a") as f:
            f.write(json.dumps(evidence.dict()) + "\n")

        # Optional: Feed into knowledge graph
        # For a low-compute setup, we just append to the evidence stream.
        # The Orchestrator's Forecast engine can consume this .jsonl later.

    async def run_cycle(self):
        """Run one sweep of perception. Check topics that are due."""
        topics = self.list_topics()
        now = time.time()
        updated = False

        for topic in topics:
            if topic.status != "active":
                continue
            if now - topic.last_checked >= topic.interval_seconds:
                logger.info(f"PerceptionEngine: Sweeping topic '{topic.query}'")
                await self._sweep_topic(topic)
                topic.last_checked = time.time()
                updated = True

        if updated:
            self._save_topics(topics)

    async def _sweep_topic(self, topic: WatchedTopic):
        import uuid

        try:
            # We use AgentReach discover to get multi-source results
            # The discover method automatically fetches from DuckDuckGo, Reddit, YouTube, etc.
            res = self.reach.discover(topic.query, limit=5, max_chars=1000)

            if not res.get("success"):
                logger.warning(f"Failed to sweep '{topic.query}': {res.get('error')}")
                return

            results = res.get("results", [])
            for item in results:
                if not isinstance(item, dict):
                    continue

                url = item.get("url") or item.get("source_url") or "unknown"
                title = item.get("title") or item.get("name") or "untitled"
                snippet = item.get("snippet") or item.get("content") or ""

                if not snippet:
                    continue

                # Light heuristics for sentiment/claims.
                # In Tier 3 mode, we'd use an LLM here. In Tier 1, simple keyword match.
                sentiment = "neutral"
                lower_snippet = snippet.lower()
                if any(
                    w in lower_snippet
                    for w in ["good", "great", "excellent", "positive", "growth", "win"]
                ):
                    sentiment = "positive"
                elif any(
                    w in lower_snippet
                    for w in [
                        "bad",
                        "terrible",
                        "negative",
                        "loss",
                        "decline",
                        "fail",
                        "crisis",
                    ]
                ):
                    sentiment = "negative"

                ev = EvidenceItem(
                    id=f"ev_{uuid.uuid4().hex[:8]}",
                    topic_id=topic.id,
                    source_url=url,
                    title=title,
                    snippet=snippet[:500],
                    timestamp=time.time(),
                    sentiment=sentiment,
                    claims=[title],  # Treat title as main claim
                )
                self.save_evidence(ev)

            logger.info(
                f"PerceptionEngine: Saved {len(results)} evidence items for '{topic.query}'"
            )
        except Exception as e:
            logger.error(f"Error sweeping topic {topic.query}: {e}")
