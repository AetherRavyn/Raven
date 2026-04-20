"""Background routine for continuous internet topic tracking via Agent Reach."""

import logging
import asyncio
from datetime import datetime, timezone
from apscheduler.triggers.interval import IntervalTrigger

from agent_reach.core import AgentReach
from app.core.workspace_graph import WorkspaceGraph
from app.core.task_inbox import TaskInboxStore
from app.core.user_profile import UserProfileStore

logger = logging.getLogger(__name__)


class InternetWatcher:
    """Continuous topic monitoring and signal extraction layer."""

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config

        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.graph = WorkspaceGraph(self.workspace_dir)
        self.inbox = TaskInboxStore(self.workspace_dir)
        self.profile = UserProfileStore(self.workspace_dir)
        self.reach = AgentReach()
        logger.info(f"AgentReach Source Health:\n{self.reach.doctor_report()}")

    def _get_watched_topics(self, user_id: str) -> list[str]:
        """Extract topics the user cares about from profile, graph, and watchlists."""
        import json
        import os

        topics = set()

        # 0. Dedicated watchlists.json
        wl_path = os.path.join(self.workspace_dir, "watchlists.json")
        if os.path.exists(wl_path):
            try:
                with open(wl_path, "r") as f:
                    wl = json.load(f)
                    topics.update(wl.get("topics", []))
                    topics.update(wl.get("entities", []))
            except Exception:
                pass

        # 1. Profile facts/preferences
        try:
            prof = self.profile.load(user_id)
            for pref in prof.preferences:
                if (
                    "track" in pref.lower()
                    or "watch" in pref.lower()
                    or "monitor" in pref.lower()
                    or "interested in" in pref.lower()
                ):
                    topics.add(
                        pref.replace("Track", "").replace("Monitor", "").strip(" :.,")
                    )
        except Exception:
            pass

        # 2. Graph Nodes marked as "topic" or "interest"
        try:
            g = self.graph.build_for_user(user_id)
            for node in g.get("nodes", []):
                if node.get("kind") in ("topic", "interest", "project"):
                    topics.add(node.get("name"))
        except Exception:
            pass

        return list(topics)[:10]  # Allow up to 10 topics when explicitly provided

    async def run_sweep(self, user_id: str, platform: str, chat_id: str) -> None:
        """Run an internet sweep for watched topics and ingest new signals."""
        logger.info(f"Starting internet watcher sweep for user {user_id}...")

        topics = self._get_watched_topics(user_id)
        if not topics:
            logger.debug(f"No topics to watch for {user_id}")
            return

        logger.info(f"Watching topics for {user_id}: {topics}")

        for topic in topics:
            # 1. Search for latest intel
            logger.debug(f"Agent Reach discovering: {topic}")
            result = self.reach.discover(query=topic, limit=3, sources="all")

            if not result.get("success"):
                continue

            summary = result.get("summary", "")
            if not summary or summary.startswith("No discovery results"):
                continue

            # 2. Check if we already have this signal in the graph
            # This is a naive duplication check using the summary text
            existing_graph = self.graph.build_for_user(user_id, query=topic)
            existing_text = " ".join(
                [n.get("description", "") for n in existing_graph.get("nodes", [])]
            )

            # If the summary contains very new keywords not in the graph, it's a new signal
            # For simplicity in this lightweight version, we just add it to the Inbox as a "signal"
            # In a full model, we would embed it and check similarity.

            item_id = self.inbox.add_item(
                user_id=user_id,
                title=f"Intel on {topic}: {summary[:120]}...",
                kind="signal",
                source="internet_watcher",
                platform=platform,
                chat_id=chat_id,
                context={
                    "topic": topic,
                    "summary": summary,
                    "results": result.get("results", []),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Append evidence to evidence.jsonl for ForecastEngine
            from pathlib import Path
            import json

            memory_root = Path(self.workspace_dir)
            memory_root.mkdir(parents=True, exist_ok=True)
            evidence_path = memory_root / "evidence.jsonl"

            lower_summary = summary.lower()
            sentiment = "neutral"
            if any(
                w in lower_summary
                for w in ["crisis", "fail", "drop", "bad", "worse", "decline", "risk"]
            ):
                sentiment = "negative"
            elif any(
                w in lower_summary
                for w in ["growth", "success", "rise", "good", "better", "boom", "gain"]
            ):
                sentiment = "positive"

            results = result.get("results", [])
            source_url = results[0].get("url") if results else "AgentReach Discovery"

            evidence_record = {
                "topic_id": topic,
                "claims": [summary],
                "sentiment": sentiment,
                "source_url": source_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            try:
                with open(evidence_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(evidence_record) + "\n")
            except Exception as e:
                logger.error(f"Failed to write evidence: {e}")

            # 3. Add a node to the workspace graph
            try:
                # We run this sync inside the thread pool or synchronously since it's sqlite
                # Using the asyncio wrapper we need to be careful
                asyncio.create_task(
                    self.graph.sync_user(
                        user_id, query=f"Internet signal on {topic}: {summary}"
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to sync graph for internet watcher: {e}")

            logger.info(f"Added new internet signal for {topic} to inbox ({item_id})")


def register_internet_watcher(
    scheduler, user_id: str, platform: str, chat_id: str, interval_hours: int = 6
) -> None:
    """Register continuous internet monitoring routine."""

    async def _fire():
        try:
            watcher = InternetWatcher()
            await watcher.run_sweep(user_id, platform, chat_id)
        except Exception as e:
            logger.error(f"Error in internet watcher routine: {e}")

    job_id = f"internet_watcher_{user_id}"

    scheduler._scheduler.add_job(
        _fire,
        trigger=IntervalTrigger(hours=interval_hours),
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "Internet watcher registered for user %s every %d hours",
        user_id,
        interval_hours,
    )
