from __future__ import annotations

"""Life Context Engine — The brain that watches the user's life.

Collects context from conversation, sessions, calendar, tasks, memory.
Produces a unified LifeContext used to:
1. Auto-update MEMORY.md (without human touch)
2. Generate proactive suggestions
3. Personalize responses (voice + text)
4. Define user's work based on observed data
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LifeContext:
    """Unified context about the user's life."""
    user_id: str = ""
    display_name: str | None = None
    timezone: str = "Asia/Kolkata"
    current_project: str | None = None
    current_task: str | None = None
    current_mood: str | None = None
    wake_time: str | None = None
    sleep_time: str | None = None
    work_start: str | None = None
    work_end: str | None = None
    today_schedule: list[str] = field(default_factory=list)
    active_projects: list[str] = field(default_factory=list)
    active_goals: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    overdue_tasks: list[str] = field(default_factory=list)
    today_tasks: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    communication_style: str = "adaptive"
    known_people: list[str] = field(default_factory=list)
    daily_routines: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    confidence: float = 0.5
    sources: list[str] = field(default_factory=list)


class LifeContextEngine:
    """Collects and maintains a unified context about the user's life.

    Core brain that watches daily patterns and produces a LifeContext
    used to personalize responses, generate proactive suggestions,
    and auto-update MEMORY.md.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self.workspace_dir = Path(workspace_dir or Config.MEMORY_ROOT)
        self.context_dir = self.workspace_dir / "life_context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self.context_dir / "context_history.jsonl"

    def _context_file_for(self, user_id: str) -> Path:
        """Per-user context file for multi-user isolation."""
        safe_id = user_id.replace("/", "_").replace("..", "_")
        return self.context_dir / f"{safe_id}.json"

    def get_context(self, user_id: str = "default") -> LifeContext:
        """Get the current life context for the user."""
        cached = self._load_cached_context(user_id)
        if cached:
            return cached
        return LifeContext(user_id=user_id)

    def update_from_conversation(
        self, user_id: str, user_message: str, assistant_response: str = "",
    ) -> LifeContext:
        """Update life context from a conversation turn.

        Now includes mood detection from message sentiment.
        """
        context = self.get_context(user_id)
        changes: list[dict[str, Any]] = []

        # Detect mood from user message
        mood = self._detect_mood(user_message)
        if mood and mood != context.current_mood:
            context.current_mood = mood
            changes.append({"type": "mood", "field": "current_mood", "value": mood})

        schedule_changes = self._extract_schedule_info(user_message)
        if schedule_changes:
            changes.extend(schedule_changes)
            self._apply_schedule_changes(context, schedule_changes)

        project_changes = self._extract_project_info(user_message)
        if project_changes:
            changes.extend(project_changes)
            self._apply_project_changes(context, project_changes)

        task_changes = self._extract_task_info(user_message)
        if task_changes:
            changes.extend(task_changes)
            self._apply_task_changes(context, task_changes)

        pref_changes = self._extract_preferences(user_message)
        if pref_changes:
            changes.extend(pref_changes)
            self._apply_preference_changes(context, pref_changes)

        people_changes = self._extract_people_info(user_message)
        if people_changes:
            changes.extend(people_changes)
            for ch in people_changes:
                val = ch.get("value", "")
                if val and val not in context.known_people:
                    context.known_people.append(val)

        routine_changes = self._extract_routine_info(user_message)
        if routine_changes:
            changes.extend(routine_changes)
            for ch in routine_changes:
                val = ch.get("value", "")
                if val and val not in context.daily_routines:
                    context.daily_routines.append(val)

        context.last_updated = datetime.now(timezone.utc).isoformat()
        if changes:
            context.sources.append("conversation")
            context.confidence = min(1.0, context.confidence + 0.1)
        else:
            # Natural confidence decay when no new info
            context.confidence = max(0.1, context.confidence - 0.02)

        # Deduplicate and cap sources
        context.sources = list(dict.fromkeys(context.sources))[-10:]

        # Cap all lists to prevent unbounded growth
        for attr in ("active_projects", "pending_tasks", "overdue_tasks",
                      "today_tasks", "preferences", "known_people",
                      "daily_routines", "recent_topics", "today_schedule"):
            lst = getattr(context, attr, [])
            if len(lst) > 20:
                setattr(context, attr, lst[-20:])

        self._save_context(user_id, context)
        self._log_history(user_id, user_message, changes)

        if changes:
            logger.info("LifeContext: %d changes from conversation", len(changes))
        return context

    def update_from_session(
        self, user_id: str, session_path: Path
    ) -> LifeContext:
        """Update context from a session log file."""
        context = self.get_context(user_id)
        try:
            lines = session_path.read_text(encoding="utf-8").strip().splitlines()
            topics: list[str] = []
            for line in lines[-50:]:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                        topics.extend(self._extract_topics(msg["content"]))
                except json.JSONDecodeError:
                    continue
            if topics:
                context.recent_topics = list(dict.fromkeys(topics))[:10]
                context.sources.append("session")
                context.sources = list(dict.fromkeys(context.sources))[-10:]
            self._save_context(user_id, context)
        except Exception as exc:
            logger.debug("Failed to update context from session: %s", exc)
        return context

    # ── Summary Methods ──────────────────────────────────────────

    def get_schedule_summary(self, user_id: str = "default") -> str:
        """Get human-readable summary of today's schedule."""
        ctx = self.get_context(user_id)
        lines = []
        if ctx.wake_time:
            lines.append(f"Wake up: {ctx.wake_time}")
        if ctx.work_start:
            lines.append(f"Work starts: {ctx.work_start}")
        if ctx.today_schedule:
            lines.append("Today's schedule:")
            for item in ctx.today_schedule:
                lines.append(f"  - {item}")
        if ctx.today_tasks:
            lines.append("Today's tasks:")
            for task in ctx.today_tasks:
                lines.append(f"  - {task}")
        return "\n".join(lines) if lines else "No schedule information available."

    def get_all_work(self, user_id: str = "default") -> str:
        """Get summary of ALL the user's current work."""
        ctx = self.get_context(user_id)
        lines = [f"=== {ctx.display_name or user_id}'s Current Work ===", ""]
        if ctx.current_project:
            lines.append(f"Current project: {ctx.current_project}")
        if ctx.active_projects:
            lines.append("Active projects:")
            for p in ctx.active_projects:
                lines.append(f"  - {p}")
        if ctx.active_goals:
            lines.append("Active goals:")
            for g in ctx.active_goals:
                lines.append(f"  - {g}")
        if ctx.pending_tasks:
            lines.append("Pending tasks:")
            for t in ctx.pending_tasks:
                lines.append(f"  - {t}")
        if ctx.today_tasks:
            lines.append("Today's tasks:")
            for t in ctx.today_tasks:
                lines.append(f"  - {t}")
        if ctx.overdue_tasks:
            lines.append("Overdue tasks:")
            for t in ctx.overdue_tasks:
                lines.append(f"  - {t}")
        if ctx.daily_routines:
            lines.append("Daily routines:")
            for r in ctx.daily_routines:
                lines.append(f"  - {r}")
        if ctx.preferences:
            lines.append("Preferences:")
            for p in ctx.preferences:
                lines.append(f"  - {p}")
        return "\n".join(lines)

    def to_memory_section(self, user_id: str = "default") -> str:
        """Generate a MEMORY.md section from the current context."""
        ctx = self.get_context(user_id)
        sections: list[str] = []

        if ctx.display_name or ctx.user_id:
            name = ctx.display_name or ctx.user_id
            sections.append(f"# Life Context for {name}")
        else:
            sections.append("# Life Context")
        sections.append("")

        # Identity
        sections.append("## Identity")
        sections.append(f"- User ID: {ctx.user_id}")
        if ctx.display_name:
            sections.append(f"- Name: {ctx.display_name}")
        sections.append(f"- Timezone: {ctx.timezone}")
        sections.append("")

        # Schedule
        schedule_items = []
        if ctx.wake_time:
            schedule_items.append(f"- Wake time: {ctx.wake_time}")
        if ctx.sleep_time:
            schedule_items.append(f"- Sleep time: {ctx.sleep_time}")
        if ctx.work_start:
            schedule_items.append(f"- Work start: {ctx.work_start}")
        if ctx.work_end:
            schedule_items.append(f"- Work end: {ctx.work_end}")
        if schedule_items:
            sections.append("## Daily Schedule")
            sections.extend(schedule_items)
            sections.append("")

        # Projects
        if ctx.active_projects:
            sections.append("## Active Projects")
            for p in ctx.active_projects:
                marker = " **(current)**" if p == ctx.current_project else ""
                sections.append(f"- {p}{marker}")
            sections.append("")

        # Goals
        if ctx.active_goals:
            sections.append("## Active Goals")
            for g in ctx.active_goals:
                sections.append(f"- {g}")
            sections.append("")

        # Tasks
        if ctx.pending_tasks:
            sections.append("## Pending Tasks")
            for t in ctx.pending_tasks:
                sections.append(f"- [ ] {t}")
            sections.append("")

        # Routines
        if ctx.daily_routines:
            sections.append("## Daily Routines")
            for r in ctx.daily_routines:
                sections.append(f"- {r}")
            sections.append("")

        # People
        if ctx.known_people:
            sections.append("## Known People")
            for p in ctx.known_people:
                sections.append(f"- {p}")
            sections.append("")

        # Preferences
        if ctx.preferences:
            sections.append("## Preferences")
            for p in ctx.preferences:
                sections.append(f"- {p}")
            sections.append("")

        # Recent Topics
        if ctx.recent_topics:
            sections.append("## Recent Topics")
            for t in ctx.recent_topics:
                sections.append(f"- {t}")
            sections.append("")

        # Meta
        sections.append("---")
        sections.append(f"Last updated: {ctx.last_updated}")
        sections.append(f"Confidence: {ctx.confidence:.0%}")
        if ctx.sources:
            sections.append(f"Sources: {', '.join(ctx.sources[-5:])}")

        return "\n".join(sections)

    # ── Extraction Methods ──────────────────────────────────────

    def _extract_schedule_info(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"wake.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"i (?:usually |typically )?wake.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                changes.append({"type": "schedule", "field": "wake_time", "value": m.group(1)})
                break
        for pat in [
            r"sleep.*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"bed.*?by\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                changes.append({"type": "schedule", "field": "sleep_time", "value": m.group(1)})
                break
        for pat in [
            r"work.*?(?:from|starts?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            r"office.*?(?:from|starts?).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        ]:
            m = re.search(pat, low)
            if m:
                changes.append({"type": "schedule", "field": "work_start", "value": m.group(1)})
                break
        return changes

    def _extract_project_info(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"(?:working on|project is|focus is|current project is)\s+(.+?)(?:\.|$)",
            r"(?:i'm|currently)\s+(?:focused on|working on)\s+(.+?)(?:\.|$)",
            r"(?:started|beginning|starting)\s+(?:the\s+)?(.+?)(?:\s+project)?(?:\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                proj = m.group(1).strip()
                if 3 < len(proj) < 100:
                    changes.append({"type": "project", "field": "active_project", "value": proj})
                break
        return changes

    def _extract_task_info(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"(?:need to|have to|must|should)\s+(.+?)(?:\.|$)",
            r"(?:todo|task|to do|to-do):\s*(.+?)(?:\.|$)",
            r"(?:remind me to|don't forget to)\s+(.+?)(?:\.|$)",
            r"(?:i need to|i have to|i must|i should)\s+(.+?)(?:\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                task = m.group(1).strip()
                if 3 < len(task) < 200:
                    changes.append({"type": "task", "field": "pending_task", "value": task})
                break
        return changes

    def _extract_preferences(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"(?:i prefer|i like|i want|i love|i hate|i don't like)\s+(.+?)(?:\.|$)",
            r"(?:please use|always use|never use)\s+(.+?)(?:\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                pref = m.group(1).strip()
                if 2 < len(pref) < 200:
                    changes.append({"type": "preference", "field": "preference", "value": pref})
                break
        return changes

    def _extract_people_info(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"my (?:boss|manager|colleague|friend|wife|husband|partner|mom|dad|brother|sister)\s+(?:is|says?|told me)\s+(.+?)(?:\.|$)",
            r"(?:talked to|spoke with|met with)\s+(.+?)(?:\s+today|\s+yesterday|\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                person = m.group(1).strip()
                if 2 < len(person) < 50:
                    changes.append({"type": "person", "field": "known_person", "value": person})
                break
        return changes

    def _extract_routine_info(self, text: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        low = text.lower()
        for pat in [
            r"i (?:usually|always|typically)\s+(.+?)(?:\.|$)",
            r"my routine is\s+(.+?)(?:\.|$)",
        ]:
            m = re.search(pat, low)
            if m:
                routine = m.group(1).strip()
                if 5 < len(routine) < 200:
                    changes.append({"type": "routine", "field": "daily_routine", "value": routine})
                break
        return changes

    def _extract_topics(self, text: str) -> list[str]:
        topics: list[str] = []
        low = text.lower()
        for kw in ["project", "meeting", "deadline", "report", "code",
                   "design", "review", "deploy", "test", "debug",
                   "email", "call", "presentation", "document", "plan",
                   "budget", "invoice", "client", "server", "database"]:
            if kw in low:
                topics.append(kw)
        return topics

    # ── Apply Changes ───────────────────────────────────────────

    def _detect_mood(self, text: str) -> str | None:
        """Detect user mood from message text.

        Uses keyword/emoji heuristics — fast, no LLM needed.
        Returns None if mood is ambiguous (no change needed).
        """
        lower = text.lower()
        words = set(lower.split())

        # Strong signals
        if any(w in lower for w in ("i'm so happy", "i'm excited", "this is amazing", "i love")):
            return "happy"
        if any(w in lower for w in ("i'm sad", "i'm upset", "this is terrible", "i hate")):
            return "sad"
        if any(w in lower for w in ("urgent", "emergency", "asap", "help me", "i need help")):
            return "stressed"
        if any(w in lower for w in ("i'm tired", "exhausted", "sleepy", "can't sleep")):
            return "tired"
        if any(w in lower for w in ("i'm bored", "nothing to do", "boring")):
            return "bored"
        if any(w in lower for w in ("thank you", "thanks", "appreciate", "grateful")):
            return "grateful"
        if any(w in lower for w in ("i'm angry", "furious", "this is unacceptable")):
            return "frustrated"
        if any(w in lower for w in ("i'm worried", "concerned", "afraid", "scared")):
            return "anxious"

        # Weak signals from punctuation/style
        if "!!" in text:
            return "excited"
        if text.endswith("...") or text.endswith("…"):
            return "thoughtful"

        # Emoji signals
        if any(e in text for e in ("😊", "😄", "🎉", "❤️", "👍")):
            return "happy"
        if any(e in text for e in ("😢", "😞", "💔", "😔")):
            return "sad"
        if any(e in text for e in ("😡", "🤬", "😤")):
            return "frustrated"
        if any(e in text for e in ("😰", "😨", "😱")):
            return "anxious"

        return None  # No clear mood signal

    def _apply_schedule_changes(self, ctx: LifeContext, changes: list[dict[str, Any]]) -> None:
        for ch in changes:
            f = ch.get("field", "")
            v = ch.get("value", "")
            if f == "wake_time":
                ctx.wake_time = v
            elif f == "sleep_time":
                ctx.sleep_time = v
            elif f == "work_start":
                ctx.work_start = v

    def _apply_project_changes(self, ctx: LifeContext, changes: list[dict[str, Any]]) -> None:
        for ch in changes:
            v = ch.get("value", "")
            if v and v not in ctx.active_projects:
                ctx.active_projects.append(v)
                ctx.current_project = v

    def _apply_task_changes(self, ctx: LifeContext, changes: list[dict[str, Any]]) -> None:
        for ch in changes:
            v = ch.get("value", "")
            if v and v not in ctx.pending_tasks:
                ctx.pending_tasks.append(v)

    def _apply_preference_changes(self, ctx: LifeContext, changes: list[dict[str, Any]]) -> None:
        for ch in changes:
            v = ch.get("value", "")
            if v and v not in ctx.preferences:
                ctx.preferences.append(v)

    # ── Persistence ─────────────────────────────────────────────

    def _save_context(self, user_id: str, ctx: LifeContext) -> None:
        try:
            data = {
                "user_id": ctx.user_id, "display_name": ctx.display_name,
                "timezone": ctx.timezone, "current_project": ctx.current_project,
                "current_task": ctx.current_task, "current_mood": ctx.current_mood,
                "wake_time": ctx.wake_time, "sleep_time": ctx.sleep_time,
                "work_start": ctx.work_start, "work_end": ctx.work_end,
                "today_schedule": ctx.today_schedule,
                "active_projects": ctx.active_projects,
                "active_goals": ctx.active_goals,
                "pending_tasks": ctx.pending_tasks,
                "overdue_tasks": ctx.overdue_tasks, "today_tasks": ctx.today_tasks,
                "preferences": ctx.preferences,
                "communication_style": ctx.communication_style,
                "known_people": ctx.known_people,
                "daily_routines": ctx.daily_routines,
                "recent_topics": ctx.recent_topics,
                "last_updated": ctx.last_updated,
                "confidence": ctx.confidence,
                "sources": ctx.sources[-10:],
            }
            context_file = self._context_file_for(user_id)
            context_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Failed to save context: %s", exc)

    def _load_cached_context(self, user_id: str) -> LifeContext | None:
        context_file = self._context_file_for(user_id)
        if not context_file.exists():
            return None
        try:
            d = json.loads(context_file.read_text(encoding="utf-8"))
            return LifeContext(
                user_id=d.get("user_id", user_id),
                display_name=d.get("display_name"),
                timezone=d.get("timezone", "Asia/Kolkata"),
                current_project=d.get("current_project"),
                current_task=d.get("current_task"),
                current_mood=d.get("current_mood"),
                wake_time=d.get("wake_time"), sleep_time=d.get("sleep_time"),
                work_start=d.get("work_start"), work_end=d.get("work_end"),
                today_schedule=d.get("today_schedule", []),
                active_projects=d.get("active_projects", []),
                active_goals=d.get("active_goals", []),
                pending_tasks=d.get("pending_tasks", []),
                overdue_tasks=d.get("overdue_tasks", []),
                today_tasks=d.get("today_tasks", []),
                preferences=d.get("preferences", []),
                communication_style=d.get("communication_style", "adaptive"),
                known_people=d.get("known_people", []),
                daily_routines=d.get("daily_routines", []),
                recent_topics=d.get("recent_topics", []),
                last_updated=d.get("last_updated", ""),
                confidence=d.get("confidence", 0.5),
                sources=d.get("sources", []),
            )
        except Exception as exc:
            logger.debug("Failed to load cached context: %s", exc)
            return None

    def _log_history(self, user_id: str, msg: str, changes: list[dict[str, Any]]) -> None:
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "message_preview": msg[:200],
                "changes": changes,
            }
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def clear_context(self, user_id: str = "default") -> None:
        context_file = self._context_file_for(user_id)
        if context_file.exists():
            context_file.unlink()
        logger.info("Cleared life context for user: %s", user_id)


# ── Singleton ───────────────────────────────────────────────────
_ENGINE: LifeContextEngine | None = None


def get_life_context_engine(workspace_dir: str | None = None) -> LifeContextEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = LifeContextEngine(workspace_dir)
    return _ENGINE
