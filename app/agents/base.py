from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path("workspace") / "agents"


class BaseAgent(ABC):
    """
    Enhanced base class for all RAVEN agents.

    Every agent now has:
    - **soul**        – immutable core purpose (who they *are*)
    - **personality** – communication style
    - **goals**       – current objectives (mutable at runtime)
    - **perfectness** – 0.0 (creative/loose) … 1.0 (strict/precise)
    - **heartbeat**   – periodic background task interval (0 = disabled)
    - **markdown memory** – per-agent workspace with soul.md, goals.md,
      memory.md, journal.md, skill.md
    - **HelixDB** semantic retrieval for memory and skills

    All new properties have safe defaults so existing agents continue to work
    without modification.
    """

    # ------------------------------------------------------------------
    # Abstract (must be overridden)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the agent (e.g. 'FinanceAnalyst')."""
        raise NotImplementedError

    @property
    @abstractmethod
    def role_prompt(self) -> str:
        """Legacy system prompt defining the agent's persona."""
        raise NotImplementedError

    @property
    @abstractmethod
    def tools(self) -> List[BaseTool]:
        """Instantiated tools this agent may use."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Concrete defaults (override per-agent as desired)
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        # Default to "auto" so :class:`SwarmManager` always asks
        # :class:`AutoModelRouter` for the best model based on
        # the *current* set of API keys (which may have been
        # pasted on the /page/providers dashboard).  Subclasses
        # may override to pin a specific provider.
        return "auto"

    @property
    def model_name(self) -> str:
        # Empty string means "let AutoModelRouter pick the model
        # for the chosen provider".  Subclasses may override.
        return ""

    # --- Identity & Personality -----------------------------------------

    @property
    def soul(self) -> str:
        """Immutable core purpose. Override per agent."""
        return ""

    @property
    def personality(self) -> str:
        """Communication style. Override per agent."""
        return ""

    @property
    def goals(self) -> List[str]:
        """Current high-level objectives. Override per agent."""
        return []

    @property
    def perfectness(self) -> float:
        """0.0 = creative / free-form … 1.0 = strict / by-the-book."""
        return 0.5

    # --- Heartbeat ------------------------------------------------------

    @property
    def heartbeat_interval(self) -> int:
        """Seconds between heartbeat calls. 0 disables heartbeat."""
        return 0

    async def heartbeat(self) -> Optional[str]:
        """
        Override to perform periodic background work.
        Return an optional status string (logged / stored in journal).
        """
        return None

    # ------------------------------------------------------------------
    # Markdown Memory (file-backed)
    # ------------------------------------------------------------------

    @property
    def memory_dir(self) -> Path:
        """Per-agent workspace directory: workspace/agents/{name_lower}/"""
        return _WORKSPACE_ROOT / self.name.lower().replace(" ", "_")

    def _ensure_memory_files(self) -> None:
        """Lazily creates the per-agent memory directory and seed files."""
        d = self.memory_dir
        d.mkdir(parents=True, exist_ok=True)

        soul_path = d / "soul.md"
        if not soul_path.exists():
            soul_path.write_text(
                f"# Soul — {self.name}\n\n{self.soul or '(No soul defined yet.)'}\n",
                encoding="utf-8",
            )

        goals_path = d / "goals.md"
        if not goals_path.exists():
            goals_lines = (
                "\n".join(f"- {g}" for g in self.goals)
                if self.goals
                else "(No goals set yet.)"
            )
            goals_path.write_text(
                f"# Goals — {self.name}\n\n{goals_lines}\n",
                encoding="utf-8",
            )

        # skill.md — learned capabilities, patterns, and tool usage tips
        skill_path = d / "skill.md"
        if not skill_path.exists():
            skill_path.write_text(
                f"# Skills — {self.name}\n\n"
                "Learned capabilities, tool-usage patterns, and domain expertise.\n\n",
                encoding="utf-8",
            )

        for fname in ("memory.md", "journal.md"):
            p = d / fname
            if not p.exists():
                p.write_text(
                    f"# {fname.replace('.md', '').title()} — {self.name}\n\n",
                    encoding="utf-8",
                )

    # --- File-based read / write ----------------------------------------

    def load_memory(self) -> str:
        """Reads the agent's memory.md (returns empty string on first use)."""
        self._ensure_memory_files()
        p = self.memory_dir / "memory.md"
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""

    def load_skills(self) -> str:
        """Reads the agent's skill.md."""
        self._ensure_memory_files()
        p = self.memory_dir / "skill.md"
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""

    def save_to_memory(self, category: str, content: str) -> None:
        """Appends a categorised entry to memory.md and HelixDB.

        File is capped at 50KB — oldest entries are trimmed when exceeded.
        """
        self._ensure_memory_files()
        p = self.memory_dir / "memory.md"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## [{category}] — {ts}\n\n{content}\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry)
        # Trim if file exceeds 50KB
        if p.stat().st_size > 50_000:
            text = p.read_text(encoding="utf-8")
            p.write_text(text[-40_000:], encoding="utf-8")
        # Persist to HelixDB for fast semantic retrieval
        self._helix_memory_save(category, content)

    def save_to_skills(self, skill_name: str, description: str) -> None:
        """Appends a learned skill entry to skill.md and HelixDB memory.

        File is capped at 30KB.
        """
        self._ensure_memory_files()
        p = self.memory_dir / "skill.md"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {skill_name} — {ts}\n\n{description}\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry)
        # Trim if file exceeds 30KB
        if p.stat().st_size > 30_000:
            text = p.read_text(encoding="utf-8")
            p.write_text(text[-25_000:], encoding="utf-8")
        self._helix_memory_save("SKILL", f"[{skill_name}] {description}")

    def save_to_journal(self, entry: str) -> None:
        """Appends a timestamped entry to journal.md.

        File is capped at 40KB.
        """
        self._ensure_memory_files()
        p = self.memory_dir / "journal.md"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n### {ts}\n\n{entry}\n")
        # Trim if file exceeds 40KB
        if p.stat().st_size > 40_000:
            text = p.read_text(encoding="utf-8")
            p.write_text(text[-30_000:], encoding="utf-8")

    # ------------------------------------------------------------------
    # HelixDB semantic memory
    # ------------------------------------------------------------------

    def _helix_memory_save(self, category: str, content: str) -> None:
        """Persist memory entry to HelixDB memory store. Fire-and-forget."""
        try:
            from app.core.memory import get_memory_store

            store = get_memory_store()
            tagged = f"[agent:{self.name}] {content}"
            store.save(category="FACT", content=tagged, user_id=f"agent_{self.name}")
        except Exception as exc:
            logger.debug("HelixDB memory save skipped for %s: %s", self.name, exc)

    def _helix_memory_retrieve(self, query: str, top_k: int = 5) -> List[str]:
        """Semantic search against HelixDB memory for this agent's memories."""
        try:
            from app.core.memory import get_memory_store

            store = get_memory_store()
            results = store.retrieve(
                query=f"[agent:{self.name}] {query}",
                top_k=top_k,
                user_id=f"agent_{self.name}",
            )
            cleaned = []
            prefix = f"[agent:{self.name}] "
            for r in results:
                cleaned.append(r[len(prefix) :] if r.startswith(prefix) else r)
            return cleaned
        except Exception as exc:
            logger.debug("HelixDB memory retrieve skipped for %s: %s", self.name, exc)
            return []

    # ------------------------------------------------------------------
    # Enhanced Prompt Builder
    # ------------------------------------------------------------------

    def get_enhanced_prompt(self) -> str:
        """
        Builds a rich system prompt that includes soul, personality, goals,
        skills, and recent memory context.  Used by SwarmManager when
        spawning a WorkerAgent.

        Uses HelixDB semantic search for the memory/skills sections.
        """
        self._ensure_memory_files()

        parts: List[str] = []

        # Header
        parts.append(
            f"You are **{self.name}**, an elite specialist in the RAVEN AI Agency."
        )

        # Soul
        if self.soul:
            parts.append(f"\n## Soul (Immutable Core Purpose)\n{self.soul}")

        # Personality
        if self.personality:
            parts.append(f"\n## Personality\n{self.personality}")

        # Role prompt (legacy — always present)
        parts.append(f"\n## Role & Instructions\n{self.role_prompt}")

        # Goals
        if self.goals:
            goal_lines = "\n".join(f"- {g}" for g in self.goals)
            parts.append(f"\n## Current Goals\n{goal_lines}")

        # Perfectness hint
        if self.perfectness >= 0.8:
            parts.append(
                "\n## Operating Mode\nYou operate in **high-precision** mode. "
                "Verify every claim, double-check calculations, cite sources."
            )
        elif self.perfectness <= 0.2:
            parts.append(
                "\n## Operating Mode\nYou operate in **creative** mode. "
                "Think laterally, brainstorm freely, propose unconventional solutions."
            )

        # Skills context
        skills_text = self.load_skills()
        if skills_text and len(skills_text) > 80:
            snippet = skills_text[-1500:] if len(skills_text) > 1500 else skills_text
            parts.append(f"\n## Learned Skills\n```\n{snippet}\n```")

        # Memory context — prefer HelixDB semantic search, fall back to file tail
        helix_memories = self._helix_memory_retrieve(
            query=f"{self.name} recent tasks and knowledge", top_k=8
        )
        if helix_memories:
            mem_block = "\n".join(f"- {m}" for m in helix_memories)
            parts.append(f"\n## Relevant Memory (semantic)\n{mem_block}")
        else:
            # Fallback: last 2000 chars of memory.md
            memory_text = self.load_memory()
            if memory_text and len(memory_text) > 50:
                snippet = (
                    memory_text[-2000:] if len(memory_text) > 2000 else memory_text
                )
                parts.append(f"\n## Recent Memory\n```\n{snippet}\n```")

        # Execution framing
        parts.append(
            "\n## Execution Protocol\n"
            "You do not talk to the user directly. You are completing a sub-task "
            "for the Manager Agent. Execute your tools, analyse the data, and "
            "provide a comprehensive final report of your findings."
        )

        return "\n".join(parts)
