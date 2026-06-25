from __future__ import annotations

"""Auto Memory Updater — Writes MEMORY.md automatically from observed behavior.

This is the CORE module that makes Ravyn self-evolving.
It reads the LifeContext and writes MEMORY.md without human touch,
using the LLM to generate memory sections when needed.

Rules:
1. Always update MEMORY.md when new facts are observed.
2. Ask user only when ambiguous (e.g., conflicting info).
3. Never overwrite security/ admin settings.
4. Use LLM to generate memory sections from conversation history.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_FILE = "MEMORY.md"


class AutoMemoryUpdater:
    """Automatically updates MEMORY.md based on observed user behavior.

    This is the brain that:
    1. Reads the current LifeContext (from life_context.py)
    2. Generates a memory section from the context
    3. Writes to MEMORY.md
    4. uses LLM to generate richer memory when available
    """

    def __init__(self, project_root: str | None = None) -> None:
        if project_root is not None:
            self.project_root = Path(project_root)
        else:
            # Walk up to the RAVEN project root (this file is at
            # RAVEN/app/core/auto_memory.py).
            self.project_root = Path(__file__).resolve().parents[2]
        self.memory_file = self.project_root / MEMORY_FILE
        self._last_update: str | None = None

    def update_memory_from_context(
        self,
        user_id: str,
        life_context,
    ) -> str:
        """Update MEMORY.md from the LifeContext.

        This is the main entry point. It:
        1. Gets the LifeContext
        2. Generates a memory section
        3. Writes it to MEMORY.md

        Returns the memory content that was written.
        """

        # Generate the memory content from context
        memory_content = self._generate_memory_content(user_id, life_context)

        # Write to MEMORY.md
        self._write_memory_file(memory_content)

        self._last_update = datetime.now(timezone.utc).isoformat()
        logger.info("MEMORY.md updated from LifeContext for user %s", user_id)

        return memory_content

    def update_memory_from_conversation(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str = "",
    ) -> str:
        """Update MEMORY.md from a conversation turn.

        This is called after every conversation to extract new memory
        from the user's words and update MEMORY.md.
        """
        from app.core.life_context import get_life_context_engine

        # Update the LifeContext from this conversation
        engine = get_life_context_engine()
        context = engine.update_from_conversation(user_id, user_message, assistant_response)

        # Generate and write memory
        return self.update_memory_from_context(user_id, context)

    def update_memory_with_llm(
        self,
        user_id: str,
        conversation_text: str,
        current_memory: str = "",
    ) -> str:
        """Use LLM to generate a memory update from conversation.

        This is a more advanced method that uses the LLM to:
        1. Extract facts from conversation
        2. Update existing memory with new facts
        3. Remove outdated information

        Returns the updated memory content.
        """
        try:
            from app.core.model_router import AutoModelRouter
            from app.provider.factory import create_provider

            provider_name, model_name = AutoModelRouter.get_best_model("agent")
            provider = create_provider(provider_name)

            # Build the prompt
            prompt = self._build_llm_prompt(conversation_text, current_memory)

            # Call LLM
            response = provider.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )

            if response and isinstance(response, str):
                return response.strip()
        except Exception as exc:
            logger.debug("LLM memory update failed: %s", exc)

        # Fallback to context-based update
        return self.update_memory_from_conversation(user_id, conversation_text)

    def get_memory_content(self) -> str:
        """Get current MEMORY.md content."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def _generate_memory_content(
        self,
        user_id: str,
        life_context,
    ) -> str:
        """Generate memory content from LifeContext."""

        # If context has data, use it
        if life_context and self._has_observations(life_context):
            sections = self._build_memory_sections(user_id, life_context)
            return "\n\n".join(sections)

        # If no context but file doesn't exist yet, seed an empty MEMORY.md
        # so downstream code (prompts, life_context reads) always finds it.
        if not self.memory_file.exists():
            return self._seed_empty_memory(user_id)
        # Otherwise keep whatever we already have — never clobber real
        # memory with an empty default context.
        return self.get_memory_content()

    def _has_observations(self, ctx) -> bool:
        """Return True if LifeContext has any non-default observations."""
        if ctx is None:
            return False
        # Any list field with content counts as an observation.
        list_fields = (
            "active_projects",
            "active_goals",
            "pending_tasks",
            "today_tasks",
            "overdue_tasks",
            "preferences",
            "known_people",
            "daily_routines",
            "recent_topics",
            "today_schedule",
        )
        for f in list_fields:
            v = getattr(ctx, f, None)
            if v:
                return True
        # Scalar fields that imply a real observation.
        scalar_fields = (
            "current_project",
            "current_task",
            "current_mood",
            "wake_time",
            "sleep_time",
            "work_start",
            "work_end",
            "display_name",
        )
        for f in scalar_fields:
            if getattr(ctx, f, None):
                return True
        return False

    def _build_memory_sections(
        self,
        user_id: str,
        ctx,
    ) -> list[str]:
        """Build memory sections from LifeContext."""
        sections: list[str] = []

        # Header
        sections.append("# AetherRavyn — Auto-Generated Memory")
        sections.append("")
        sections.append("> This file is automatically updated by Ravyn based on observed behavior.")
        sections.append(f"> Last updated: {ctx.last_updated if hasattr(ctx, 'last_updated') else 'unknown'}")
        sections.append(f"> User: {ctx.display_name or ctx.user_id}")
        sections.append("")

        # Identity
        sections.append("## Identity")
        if ctx.display_name:
            sections.append(f"- Name: {ctx.display_name}")
        sections.append(f"- User ID: {ctx.user_id}")
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

        # Current Project
        if ctx.current_project:
            sections.append("## Current Project")
            sections.append(f"- {ctx.current_project}")
            sections.append("")

        # Active Projects
        if ctx.active_projects:
            sections.append("## Active Projects")
            for p in ctx.active_projects:
                marker = " (current)" if p == ctx.current_project else ""
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

        if ctx.today_tasks:
            sections.append("## Today's Tasks")
            for t in ctx.today_tasks:
                sections.append(f"- [ ] {t}")
            sections.append("")

        if ctx.overdue_tasks:
            sections.append("## Overdue Tasks")
            for t in ctx.overdue_tasks:
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
        sections.append(f"Confidence: {ctx.confidence:.0%}")
        if ctx.sources:
            sections.append(f"Sources: {', '.join(ctx.sources[-5:])}")

        return sections

    def _write_memory_file(self, content: str) -> None:
        """Write content to MEMORY.md.

        Strategy: keep the header (lines before first ##) and append
        new sections. This preserves manual edits and history while
        updating auto-generated content.
        """
        try:
            if self.memory_file.exists():
                existing = self.memory_file.read_text(encoding="utf-8")
                # Find the first ## section — everything before it is header
                lines = existing.split("\n")
                header_lines = []
                for line in lines:
                    if line.startswith("## "):
                        break
                    header_lines.append(line)
                header = "\n".join(header_lines)

                # Extract just the auto-generated sections from new content
                new_sections = []
                for line in content.split("\n"):
                    if line.startswith("## ") or (new_sections and not line.startswith("#")):
                        new_sections.append(line)

                # Rebuild: header + new auto-generated sections
                if header.strip():
                    final = header.rstrip() + "\n\n" + "\n".join(new_sections).strip() + "\n"
                else:
                    final = content
            else:
                final = content

            self.memory_file.write_text(final, encoding="utf-8")
            logger.info("MEMORY.md updated successfully")
        except Exception as exc:
            logger.error("Failed to write MEMORY.md: %s", exc)

    def _seed_empty_memory(self, user_id: str) -> str:
        """Seed an empty MEMORY.md so downstream code always finds a file.

        Called when no LifeContext is available yet. Writes a minimal
        header + identity section so MEMORY.md is never empty.
        """
        now = datetime.now(timezone.utc).isoformat()
        content = (
            "# AetherRavyn — Auto-Generated Memory\n"
            "\n"
            "> This file is automatically updated by Ravyn based on observed behavior.\n"
            f"> Last updated: {now}\n"
            f"> User: {user_id}\n"
            "\n"
            "## Identity\n"
            f"- User ID: {user_id}\n"
            "\n"
            "_No observations recorded yet. This file will be enriched as the assistant "
            "learns about the user._\n"
        )
        return content

    def _build_llm_prompt(
        self,
        conversation_text: str,
        current_memory: str,
    ) -> str:
        """Build a prompt for the LLM to generate memory updates."""
        return f"""You are updating a user's memory file (MEMORY.md) for AetherRavyn, a personal AI assistant.

current MEMORY.md content:
---
{current_memory}
---

conversation to analyze:
---
{conversation_text[:3000]}
---

Instructions:
1. Extract facts, preferences, and tasks from the conversation
2. Update the MEMORY.md with new information
3. Keep existing information that is still relevant
4. Remove outdated information
5. Format as a clean markdown file
6. Include sections for: Identity, Daily Schedule, Active Projects, Pending Tasks, Preferences, Known People
7. Do NOT include any instructions or meta-commentary
8. Return ONLY the updated MEMORY.md content

Return the updated MEMORY.md:
"""


# ── Singleton ───────────────────────────────────────────────────
_updater: AutoMemoryUpdater | None = None


def get_auto_memory_updater(project_root: str | None = None) -> AutoMemoryUpdater:
    global _updater
    if _updater is None:
        _updater = AutoMemoryUpdater(project_root)
    return _updater
