import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class Bootstrapper:
    """Handles File-Injected Context Strategy for Dynamic System Prompts."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        # Create default template files if they don't exist
        self._ensure_file_exists(
            "SOUL.md",
            "You are SARAS, an advanced, highly capable AI assistant. Be helpful, concise, and professional.",
        )
        self._ensure_file_exists(
            "AGENTS.md",
            "Core Operating Instructions:\n- You have access to various tools.\n- Analyze context before acting.",
        )
        self._ensure_file_exists(
            "TOOLS.md",
            "Tool Guidance:\n- Prefer specific tools for the job.\n- Output tool names precisely.",
        )

    def _ensure_file_exists(self, filename: str, default_content: str):
        filepath = self.workspace_dir / filename
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            try:
                filepath.write_text(default_content, encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to create default {filename}: {e}")

    def _read_and_truncate(self, filename: str, max_chars: int = 5000) -> str:
        filepath = self.workspace_dir / filename
        if not filepath.exists():
            return f"\n--- [Missing File: {filename}] ---\n"

        try:
            content = filepath.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = (
                    content[:max_chars]
                    + f"\n...[Content Truncated due to size limit]..."
                )
            return f"\n--- [{filename}] ---\n{content}\n"
        except Exception as e:
            logger.error(f"Failed to read {filename}: {e}")
            return f"\n--- [Error reading {filename}] ---\n"

    def build_dynamic_context(self, user_id: str | None = None) -> str:
        """Return a short string describing the current date/time context.

        Injected into every system prompt so SARAS is always temporally aware.
        Zero compute cost — pure datetime math.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        hour = now.hour
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        elif 17 <= hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        return (
            f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M')} ({time_of_day})\n"
            f"Day of week: {now.strftime('%A')}"
        )

    def build_system_prompt(
        self, query: str | None = None, user_id: str | None = None
    ) -> str:
        """Injects SOUL, AGENTS, TOOLS, live context, and relevant memories."""
        soul = self._read_and_truncate("SOUL.md")
        agents = self._read_and_truncate("AGENTS.md", max_chars=1000)
        tools = self._read_and_truncate("TOOLS.md", max_chars=1000)

        # Dynamic context — always injected, zero cost
        dynamic = self.build_dynamic_context(user_id)
        dynamic_section = f"\n--- [Current Context] ---\n{dynamic}\n"

        memory_section = ""
        if query:
            try:
                from app.core.memory import get_memory_store

                store = get_memory_store()
                memories = store.retrieve(query, top_k=5, user_id=user_id)
                if memories:
                    bullets = "\n".join(f"- {m}" for m in memories)
                    memory_section = f"\n--- [Relevant Memories] ---\n{bullets}\n"
            except Exception as exc:
                logger.warning("Memory retrieval failed: %s", exc)

        return (
            f"System Bootstrapped Context:\n"
            f"{soul}{dynamic_section}{agents}{tools}{memory_section}"
        )
