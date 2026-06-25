"""Background routine to periodically consolidate memory into profile and rules."""

import json
import logging
from typing import Any
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.triggers.interval import IntervalTrigger

from app.core.user_profile import UserProfileStore
from app.core.task_ledger import TaskLedger
from app.core.standing_orders import StandingOrderStore, StandingOrder
from app.core.model_router import AutoModelRouter
from app.provider.factory import create_provider
from app.settings.config import Config

logger = logging.getLogger(__name__)


class SessionConsolidator:
    """Consolidates recent sessions and tasks into facts, preferences, and rules.

    This is distinct from ``app.core.memory_consolidation.MemoryConsolidator``
    which handles low-level dedup/decay in the HelixDB vector store.
    This class uses an LLM to extract structured knowledge from conversation
    sessions and writes to UserProfileStore and StandingOrderStore.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.profile_store = UserProfileStore(self.workspace_dir)
        self.ledger = TaskLedger(self.workspace_dir)
        self.orders_store = StandingOrderStore(self.workspace_dir)
        try:
            provider_name, self.model_name = AutoModelRouter.get_best_model("agent")
            self.provider = create_provider(provider_name)
        except Exception:
            self.provider = None
            self.model_name = ""

    def _get_recent_sessions(self, hours: int = 24) -> str:
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
                        for line in lines[-50:]:  # Take last 50 messages
                            if not line.strip():
                                continue
                            msg = json.loads(line)
                            role = msg.get("role", "unknown")
                            content = msg.get("content", "")
                            if isinstance(content, str) and content.strip():
                                session_content.append(f"{role}: {content.strip()}")
                        if session_content:
                            recent_text.append(f"Session {file_path.stem}:")
                            recent_text.extend(session_content)
                            recent_text.append("---")
                    except Exception as e:
                        logger.warning("Error reading session %s: %s", file_path, e)
        except Exception as e:
            logger.warning("Error scanning sessions: %s", e)

        return "\n".join(recent_text)

    def _get_completed_tasks(self, hours: int = 24) -> str:
        tasks = self.ledger.list_tasks(status="done")
        recent_text = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        for task in tasks:
            updated_at_str = task.get("updated_at")
            if not updated_at_str:
                continue
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                if updated_at >= cutoff:
                    recent_text.append(f"Task: {task.get('title')}")
                    recent_text.append(f"Type: {task.get('task_type')}")
                    if task.get("metadata"):
                        recent_text.append(
                            f"Metadata: {json.dumps(task.get('metadata'))}"
                        )
                    recent_text.append("---")
            except Exception:
                pass

        return "\n".join(recent_text)

    async def run_consolidation(self, user_id: str, hours: int = 24) -> None:
        if not self.provider:
            logger.warning("No provider available for memory consolidation.")
            return

        logger.info(
            "Running memory consolidation for user %s over past %d hours...",
            user_id,
            hours,
        )

        sessions_text = self._get_recent_sessions(hours)
        tasks_text = self._get_completed_tasks(hours)

        if not sessions_text.strip() and not tasks_text.strip():
            logger.info("No recent activity to consolidate.")
            return

        prompt = f"""You are a memory consolidation AI.
Review the following recent activity (chat sessions and completed tasks) of the user and extract new enduring facts, preferences, and operational rules.

Activity Context:
{sessions_text}
{tasks_text}

Extract only what is new, meaningful, and long-term relevant. Do not include ephemeral state.
Return ONLY valid JSON in this exact format:
{{
  "facts": ["Objective fact 1", "Objective fact 2"],
  "preferences": ["User likes X", "User prefers Y formatting"],
  "rules": [
    {{"title": "Short title", "rule": "If X happens, do Y"}}
  ]
}}
"""
        try:
            resilient = getattr(self.provider, "chat_completion_resilient", None)
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
                result = await self.provider.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model_name or "google/gemini-2.5-flash:free",
                )

            if not isinstance(result, dict) or not result.get("success"):
                logger.warning(
                    "Consolidation LLM call failed: %s",
                    result.get("error")
                    if isinstance(result, dict)
                    else "unknown error",
                )
                return

            content = result.get("content", "").strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            extracted = json.loads(content)

            # Update Profile
            profile = self.profile_store.load(user_id)
            facts = extracted.get("facts", [])
            preferences = extracted.get("preferences", [])

            facts_added = 0
            for fact in facts:
                if isinstance(fact, str) and fact not in profile.facts:
                    profile.facts.append(fact)
                    facts_added += 1

            prefs_added = 0
            for pref in preferences:
                if isinstance(pref, str) and pref not in profile.preferences:
                    profile.preferences.append(pref)
                    prefs_added += 1

            if facts_added > 0 or prefs_added > 0:
                profile.updated_at = datetime.now(timezone.utc).isoformat()
                self.profile_store.save(profile)
                logger.info(
                    "Added %d facts and %d preferences for %s",
                    facts_added,
                    prefs_added,
                    user_id,
                )

            # Update Standing Orders
            rules = extracted.get("rules", [])
            if rules:
                orders = self.orders_store.parse()
                rules_added = 0
                existing_titles = {o.title for o in orders}
                for r in rules:
                    title = r.get("title")
                    rule = r.get("rule")
                    if title and rule and title not in existing_titles:
                        orders.append(StandingOrder(title=title, rule=rule))
                        existing_titles.add(title)
                        rules_added += 1

                if rules_added > 0:
                    new_content = self.orders_store.render(orders)
                    self.orders_store.save_raw(new_content)
                    logger.info("Added %d new rules to standing orders.", rules_added)

        except Exception as e:
            logger.error("Error during memory consolidation: %s", e)


def register_memory_consolidator(
    scheduler: Any, user_id: str, interval_hours: int = 12
) -> None:
    """Register the memory consolidation routine."""

    async def _fire() -> None:
        try:
            consolidator = SessionConsolidator()
            await consolidator.run_consolidation(user_id, interval_hours)
        except Exception as e:
            logger.error("Error in memory consolidation routine: %s", e)

    job_id = f"memory_consolidator_{user_id}"

    scheduler._scheduler.add_job(
        _fire,
        trigger=IntervalTrigger(hours=interval_hours),
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "Memory consolidator registered for user %s every %d hours",
        user_id,
        interval_hours,
    )
