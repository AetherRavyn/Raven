from __future__ import annotations

"""Context Awareness — Combines all context sources into a unified view.

Pulls from:
- LifeContextEngine (schedule, projects, tasks, preferences)
- ScheduleLearner (daily patterns)
- TaskDecomposer (active tasks)
- User profile (personal details)
- Conversation history (recent topics)

Provides:
- Unified context for prompt injection
- Context-aware response generation
- Proactive suggestion triggers
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ContextAwareness:
    """Combines all context sources into a unified view."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._workspace_dir = workspace_dir or Config.MEMORY_ROOT
        self._engine = None
        self._schedule = None
        self._decomposer = None

    def _get_engine(self):
        if self._engine is None:
            from app.core.life_context import get_life_context_engine
            self._engine = get_life_context_engine(self._workspace_dir)
        return self._engine

    def _get_schedule(self):
        if self._schedule is None:
            from app.core.schedule_learner import get_schedule_learner
            self._schedule = get_schedule_learner(self._workspace_dir)
        return self._schedule

    def _get_decomposer(self):
        if self._decomposer is None:
            from app.core.task_decomposer import get_task_decomposer
            self._decomposer = get_task_decomposer(self._workspace_dir)
        return self._decomposer

    def build_context_prompt(self, user_id: str = "default") -> str:
        """Build a context prompt to inject into the LLM system prompt.

        This gives the LLM awareness of the user's current state:
        - What they're working on
        - What their schedule looks like
        - What tasks they have
        - What their preferences are
        """
        engine = self._get_engine()
        ctx = engine.get_context(user_id)
        schedule = self._get_schedule()
        decomposer = self._get_decomposer()

        parts: list[str] = []

        # Current time context
        now = datetime.now(timezone.utc)
        parts.append(f"Current time: {now.strftime('%Y-%m-%d %H:%M UTC')}")

        # User identity
        if ctx.display_name:
            parts.append(f"User: {ctx.display_name}")

        # Current project
        if ctx.current_project:
            parts.append(f"Current project: {ctx.current_project}")

        # User mood (FRIDAY-style emotional awareness)
        if ctx.current_mood:
            parts.append(f"User mood: {ctx.current_mood}")

        # Location awareness (FRIDAY-style spatial awareness)
        try:
            from app.core.location_awareness import LocationAwareness
            loc = LocationAwareness(str(self._workspace_dir))
            loc_ctx = loc.get_location_context()
            if loc_ctx:
                parts.append(loc_ctx)
        except Exception:
            pass

        # Activity awareness (FRIDAY-style activity detection)
        try:
            from app.core.activity_detection import ActivityDetector
            detector = ActivityDetector(str(self._workspace_dir))
            act_ctx = detector.get_activity_context()
            if act_ctx:
                parts.append(act_ctx)
        except Exception:
            pass

        # Environmental awareness (FRIDAY-style physical environment)
        try:
            from raven_iot.sensors.environmental import EnvironmentalSensor
            from app.settings.config import Config
            env = EnvironmentalSensor(workspace_dir=Config.MEMORY_ROOT)
            env_ctx = env.get_context_string()
            if env_ctx:
                parts.append(env_ctx)
        except Exception:
            pass

        # Schedule
        schedule_dict = schedule.get_schedule()
        if schedule_dict:
            parts.append("User's schedule:")
            for k, v in schedule_dict.items():
                parts.append(f"  - {k}: {v}")

        # Active projects
        if ctx.active_projects:
            parts.append(f"Active projects: {', '.join(ctx.active_projects[:5])}")

        # Today's tasks
        if ctx.today_tasks:
            parts.append("Today's tasks:")
            for t in ctx.today_tasks[:5]:
                parts.append(f"  - {t}")

        # Pending tasks
        pending = decomposer.get_pending_tasks()
        if pending:
            parts.append(f"Pending tasks ({len(pending)} total):")
            for t in pending[:5]:
                parts.append(f"  - [{t.priority}] {t.title}")

        # Preferences
        if ctx.preferences:
            parts.append(f"User preferences: {', '.join(ctx.preferences[:3])}")

        # Recent topics
        if ctx.recent_topics:
            parts.append(f"Recent topics: {', '.join(ctx.recent_topics[:5])}")

        # Routines
        if ctx.daily_routines:
            parts.append("User's daily routines:")
            for r in ctx.daily_routines[:3]:
                parts.append(f"  - {r}")

        if not parts:
            return ""

        # FRIDAY: Add learned behavioral rules from pattern learner
        try:
            from app.core.pattern_learner import PatternLearner
            pl = PatternLearner(workspace_dir=str(self._workspace_dir))
            rules = pl.get_rules_for_prompt()
            if rules:
                parts.append(rules)
        except Exception:
            pass

        # FRIDAY: Add deep user model
        try:
            from app.core.user_model import get_user_model
            um = get_user_model()
            user_prompt = um.get_personality_prompt(user_id)
            if user_prompt:
                parts.append(user_prompt)
        except Exception:
            pass

        # FRIDAY: Add world model context
        try:
            from app.core.world_model import WorldModel
            wm_ctx = WorldModel(str(self._workspace_dir))
            world_text = wm_ctx.build_world_context()
            if world_text:
                parts.append(world_text)
        except Exception:
            pass

        # FRIDAY: Add adaptive personality
        try:
            from app.core.adaptive_personality import AdaptivePersonality
            ap = AdaptivePersonality(str(self._workspace_dir))
            ap_prompt = ap.get_personality_prompt()
            if ap_prompt:
                parts.append(ap_prompt)
        except Exception:
            pass

        # FRIDAY: Add working memory context
        try:
            from app.core.attention import WorkingMemory
            wm = WorkingMemory()
            wm_text = wm.get_context_text()
            if wm_text:
                parts.append(wm_text)
        except Exception:
            pass

        # FRIDAY: Add active goals
        try:
            from app.core.goal_manager import get_goal_manager
            gm = get_goal_manager()
            goals = gm.list_goals() if hasattr(gm, "list_goals") else []
            active = [g for g in goals if hasattr(g, "status") and "ACTIVE" in str(getattr(g, "status", ""))]
            if active:
                goal_lines = [f"- {getattr(g, 'title', str(g))}" for g in active[:5]]
                parts.append("Active Goals:\n" + "\n".join(goal_lines))
        except Exception:
            pass

        # FRIDAY: Add resilience status
        try:
            from app.core.resilient_recovery import get_resilience_manager
            rm = get_resilience_manager()
            if hasattr(rm, "get_status"):
                status = rm.get_status()
                if status and status != "healthy":
                    parts.append(f"System status: {status}")
        except Exception:
            pass

        return "\n".join(parts)

    def get_context_for_response(self, user_id: str = "default") -> dict[str, Any]:
        """Get context data for generating personalized responses."""
        engine = self._get_engine()
        ctx = engine.get_context(user_id)
        schedule = self._get_schedule()
        decomposer = self._get_decomposer()

        return {
            "user_id": user_id,
            "display_name": ctx.display_name,
            "current_project": ctx.current_project,
            "active_projects": ctx.active_projects,
            "schedule": schedule.get_schedule(),
            "pending_tasks": [t.title for t in decomposer.get_pending_tasks()[:10]],
            "today_tasks": ctx.today_tasks,
            "preferences": ctx.preferences,
            "recent_topics": ctx.recent_topics,
            "work_start": ctx.work_start,
            "wake_time": ctx.wake_time,
        }

    def should_send_proactive(self, user_id: str = "default") -> tuple[bool, str]:
        """Check if we should send a proactive message.

        Returns (should_send, message) tuple.
        """
        engine = self._get_engine()
        ctx = engine.get_context(user_id)
        decomposer = self._get_decomposer()

        # Check for overdue tasks
        if ctx.overdue_tasks:
            return True, f"You have {len(ctx.overdue_tasks)} overdue task(s)."

        # Check for pending tasks with high priority
        pending = decomposer.get_pending_tasks()
        high_priority = [t for t in pending if t.priority <= 2]
        if high_priority:
            return True, f"You have {len(high_priority)} high-priority task(s) pending."

        return False, ""

    def get_daily_briefing(self, user_id: str = "default") -> str:
        """Generate a daily briefing from all context sources."""
        engine = self._get_engine()
        ctx = engine.get_context(user_id)
        schedule = self._get_schedule()
        decomposer = self._get_decomposer()

        lines: list[str] = []
        name = ctx.display_name or user_id
        lines.append(f"Good morning, {name}. Here's your briefing:")
        lines.append("")

        # Schedule
        schedule_dict = schedule.get_schedule()
        if schedule_dict:
            lines.append("Today's Schedule:")
            for k, v in schedule_dict.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        # Tasks
        pending = decomposer.get_pending_tasks()
        if pending:
            lines.append(f"You have {len(pending)} pending task(s):")
            for t in pending[:5]:
                lines.append(f"  - [{t.priority}] {t.title}")
            lines.append("")

        # Projects
        if ctx.active_projects:
            lines.append("Active projects:")
            for p in ctx.active_projects:
                lines.append(f"  - {p}")
            lines.append("")

        return "\n".join(lines)

    def build_proactive_candidates(
        self,
        user_id: str = "default",
        *,
        channel: str = "telegram",
    ) -> list[Any]:
        """Return :class:`ProactiveCandidate` objects for the
        :class:`ProactiveIntelligence` engine to gate.

        Each candidate is sourced from the merged context snapshot
        — overdue tasks become ``"overdue_tasks"`` topic pushes;
        high-priority pending tasks become ``"pending_high_priority"``
        pushes.  The list is empty when there is nothing to say,
        which keeps the ambient loop cheap on idle turns.

        The lazy import keeps ``context_awareness`` usable when
        the proactive engine is unconfigured.
        """
        try:
            from app.core.proactive_intelligence import ProactiveCandidate
        except Exception:  # noqa: BLE001 - optional dependency
            return []
        engine = self._get_engine()
        ctx = engine.get_context(user_id)
        decomposer = self._get_decomposer()

        candidates: list[Any] = []
        if ctx.overdue_tasks:
            candidates.append(
                ProactiveCandidate(
                    channel=channel,
                    topic="overdue_tasks",
                    body=(
                        f"You have {len(ctx.overdue_tasks)} overdue task(s): "
                        + ", ".join(ctx.overdue_tasks[:3])
                    ),
                    priority="high",
                    metadata={"source": "context_awareness"},
                )
            )
        pending = decomposer.get_pending_tasks()
        high_priority = [t for t in pending if t.priority <= 2]
        if high_priority:
            candidates.append(
                ProactiveCandidate(
                    channel=channel,
                    topic="pending_high_priority",
                    body=(
                        f"{len(high_priority)} high-priority task(s) pending: "
                        + ", ".join(t.title for t in high_priority[:3])
                    ),
                    priority="normal",
                    metadata={"source": "context_awareness"},
                )
            )
        return candidates


# ── Singleton ───────────────────────────────────────────────────
_awareness: ContextAwareness | None = None


def get_context_awareness(workspace_dir: str | None = None) -> ContextAwareness:
    global _awareness
    if _awareness is None:
        _awareness = ContextAwareness(workspace_dir)
    return _awareness
