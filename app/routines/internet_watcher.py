"""Background routine for continuous internet topic tracking via Agent Reach.

Day 22: Adds :func:`generate_signals` that returns a
:class:`Signal` per topic discovered, and a
:func:`register_internet_watcher_v2` entry point that wires
the watcher to a v2 :class:`Scheduler`.  The legacy
``APScheduler`` path is preserved for backward compatibility.
"""

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from agent_reach.core import AgentReach
from app.core.workspace_graph import WorkspaceGraph
from app.core.task_inbox import TaskInboxStore
from app.core.user_profile import UserProfileStore

logger = logging.getLogger(__name__)


# Sentiment word lists (kept tiny — the inbox payload still
# carries the raw summary for richer downstream processing).
_NEGATIVE_WORDS = (
    "crisis", "fail", "drop", "bad", "worse", "decline", "risk",
)
_POSITIVE_WORDS = (
    "growth", "success", "rise", "good", "better", "boom", "gain",
)


def _classify_sentiment(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in _NEGATIVE_WORDS):
        return "negative"
    if any(w in lower for w in _POSITIVE_WORDS):
        return "positive"
    return "neutral"


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
        """Run an internet sweep for watched topics and ingest new signals.

        v1 API: side-effecting (writes to inbox + evidence).
        v2 code should use :meth:`generate_signals` and let the
        :class:`SignalRouter` handle delivery.  This method is
        kept for the legacy ``APScheduler`` path.
        """
        signals = await self.generate_signals(
            user_id=user_id, platform=platform, chat_id=chat_id,
        )
        # The v2 path already published through the router;
        # here we only do the persistence side-effects.
        for sig in signals:
            topic = sig.payload.get("topic", "?")
            logger.info("internet_sweep persisted signal %s for topic %s", sig.id, topic)

    async def generate_signals(
        self,
        *,
        user_id: str,
        platform: str,
        chat_id: str,
    ) -> list:
        """Discover intel on watched topics and return :class:`Signal` objects.

        Side effects (per signal):
        * appends a row to ``evidence.jsonl`` (for
          :class:`ForecastEngine` and any future analytics)
        * queues a graph-sync task for the topic
        * stores an inbox item so the user can review in
          their task inbox

        The returned signals are typed ``INTERNET`` so
        subscribers (botsignal, anticipation, dashboard) can
        filter on ``kind``.
        """
        from app.core.scheduling import Signal, SignalKind, SignalSeverity
        from pathlib import Path

        logger.info("Starting internet watcher sweep for user %s...", user_id)

        topics = self._get_watched_topics(user_id)
        if not topics:
            logger.debug("No topics to watch for %s", user_id)
            return []

        logger.info("Watching topics for %s: %s", user_id, topics)
        out: list[Signal] = []

        for topic in topics:
            try:
                result = self.reach.discover(query=topic, limit=3, sources="all")
            except Exception as exc:
                logger.warning("AgentReach discover failed for %r: %s", topic, exc)
                continue

            if not result.get("success"):
                continue

            summary = result.get("summary", "")
            if not summary or summary.startswith("No discovery results"):
                continue

            sentiment = _classify_sentiment(summary)
            results = result.get("results", [])
            source_url = results[0].get("url") if results else "AgentReach Discovery"
            ts = datetime.now(timezone.utc).isoformat()

            # Persist inbox + evidence
            try:
                self.inbox.add_item(
                    user_id=user_id,
                    title=f"Intel on {topic}: {summary[:120]}...",
                    kind="signal",
                    source="internet_watcher",
                    platform=platform,
                    chat_id=chat_id,
                    context={
                        "topic": topic,
                        "summary": summary,
                        "results": results,
                        "timestamp": ts,
                    },
                )
            except Exception as exc:
                logger.warning("inbox.add_item failed: %s", exc)

            try:
                memory_root = Path(self.workspace_dir)
                memory_root.mkdir(parents=True, exist_ok=True)
                evidence_path = memory_root / "evidence.jsonl"
                with evidence_path.open("a", encoding="utf-8") as f:
                    import json
                    f.write(
                        json.dumps(
                            {
                                "topic_id": topic,
                                "claims": [summary],
                                "sentiment": sentiment,
                                "source_url": source_url,
                                "timestamp": ts,
                            }
                        )
                        + "\n"
                    )
            except Exception as exc:
                logger.error("Failed to write evidence: %s", exc)

            try:
                asyncio.create_task(
                    self.graph.sync_user(
                        user_id, query=f"Internet signal on {topic}: {summary}"
                    )
                )
            except Exception as exc:
                logger.warning("Failed to sync graph for internet watcher: %s", exc)

            severity = (
                SignalSeverity.WARNING
                if sentiment == "negative"
                else SignalSeverity.NOTICE
                if sentiment == "positive"
                else SignalSeverity.INFO
            )

            out.append(
                Signal.make(
                    kind=SignalKind.INTERNET,
                    source="internet_watcher",
                    user_id=user_id,
                    title=f"Intel on {topic}",
                    severity=severity,
                    body=summary,
                    payload={
                        "topic": topic,
                        "summary": summary,
                        "sentiment": sentiment,
                        "source_url": source_url,
                        "results": results,
                        "platform": platform,
                        "chat_id": chat_id,
                    },
                )
            )

        return out


def register_internet_watcher(
    scheduler, user_id: str, platform: str, chat_id: str, interval_hours: int = 6
) -> str | None:
    """Register continuous internet monitoring routine.

    Returns the schedule id when registered on a v2
    :class:`~app.core.scheduling.Scheduler`, or ``None`` when
    the legacy APScheduler path is used.
    """
    from app.core.scheduling import Scheduler

    if isinstance(scheduler, Scheduler):
        return register_internet_watcher_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            interval_hours=interval_hours,
        )

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
    return None


def register_internet_watcher_v2(
    scheduler,
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    interval_hours: int = 6,
    signal_router: Any = None,
    schedule_id: str | None = None,
) -> str:
    """Register the internet watcher on a v2 :class:`Scheduler`."""
    from app.core.scheduling import (
        IntervalTrigger,
        Scheduler,
        get_default_signal_router,
    )

    if not isinstance(scheduler, Scheduler):
        raise TypeError(
            "register_internet_watcher_v2 requires a v2 Scheduler; "
            f"got {type(scheduler).__name__}"
        )

    routine_id = f"internet_watcher::{user_id}"
    watcher = InternetWatcher()
    router = signal_router or getattr(scheduler, "signal_router", None) or get_default_signal_router()

    async def _fire(uid: str, *args: Any, triggered_at: datetime | None = None, **kwargs: Any) -> list:
        signals = await watcher.generate_signals(
            user_id=uid,
            platform=platform,
            chat_id=chat_id,
        )
        for sig in signals:
            await router.publish(sig)
        return signals

    if scheduler.routine_registry.get(routine_id) is None:
        scheduler.routine_registry.register_fn(
            routine_id,
            _fire,
            name="internet_watcher",
            kind="watcher",
            metadata={
                "user_id": user_id,
                "platform": platform,
                "chat_id": chat_id,
                "interval_hours": interval_hours,
            },
        )

    sid = schedule_id or f"internet_watcher_{user_id}"
    scheduler.add(
        routine_id=routine_id,
        trigger=IntervalTrigger(every=timedelta(hours=interval_hours)),
        user_id=user_id,
        schedule_id=sid,
    )
    logger.info(
        "InternetWatcher v2 registered for user %s every %d hours (schedule=%s)",
        user_id,
        interval_hours,
        sid,
    )
    return sid
