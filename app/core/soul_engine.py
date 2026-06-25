"""Soul Engine — AetherRavyn's Identity Core.

Loads SOUL.md + MEMORY.md + AGENTS.md, parses frontmatter, merges with the
PersonaEngine to produce a unified, dynamic system prompt that reflects
Ravyn's evolving personality, user knowledge, and workspace context.

This replaces the hardcoded system_prompt.txt approach with a living
identity system inspired by Hermes Agent's SOUL.md / OpenClaw's SOUL.md.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class SoulProfile:
    """Parsed representation of SOUL.md frontmatter."""

    name: str = "AetherRavyn"
    aliases: list[str] = field(default_factory=lambda: ["Ravyn", "Raven"])
    creator: str = ""
    version: str = "1.0.0"
    born: str = ""

    # Personality
    base_traits: list[str] = field(default_factory=list)
    humor_style: str = "dry-sarcastic"
    formality: str = "adaptive"
    energy: str = "high"
    verbosity: str = "proportional"

    # Principles
    principles: list[str] = field(default_factory=list)

    # Communication
    greeting_examples: list[str] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)

    # Platform adaptations
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Circadian rhythms
    circadian: dict[str, str] = field(default_factory=dict)

    # Raw body text (the prose section of SOUL.md)
    body: str = ""


@dataclass(slots=True)
class MemoryProfile:
    """Parsed representation of MEMORY.md."""

    raw_text: str = ""
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceInstructions:
    """Parsed representation of AGENTS.md."""

    raw_text: str = ""
    rules: list[str] = field(default_factory=list)


class SoulEngine:
    """Loads and merges SOUL.md, MEMORY.md, AGENTS.md into a dynamic system prompt.

    The Soul Engine is the identity core of AetherRavyn. It reads persona files
    from the project root and produces context-aware system prompts that adapt
    to time-of-day, platform, and user relationship state.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve() if project_root else _PROJECT_ROOT
        self._workspace_dir: Path | None = (
            Path(workspace_dir).resolve() if workspace_dir else None
        )

        self._soul: SoulProfile | None = None
        self._memory: MemoryProfile | None = None
        self._instructions: WorkspaceInstructions | None = None
        self._last_load: float = 0.0
        self._cache_ttl: float = 60.0  # Reload files every 60 seconds max

    # ── File Resolution ─────────────────────────────────────────────

    def _resolve_file(self, filename: str) -> Path | None:
        """Find a file in project root or workspace directory."""
        candidates = [self._project_root / filename]
        if self._workspace_dir:
            candidates.insert(0, self._workspace_dir / filename)
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        return None

    # ── SOUL.md Parsing ─────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        """Parse YAML frontmatter from a markdown file."""
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, text

        end_index: int | None = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_index = idx
                break

        if end_index is None:
            return {}, text

        frontmatter_text = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1:])

        try:
            data = yaml.safe_load(frontmatter_text) or {}
        except Exception as exc:
            logger.warning("Failed to parse SOUL.md frontmatter: %s", exc)
            return {}, body

        if not isinstance(data, dict):
            return {}, body

        return data, body

    def _load_soul(self) -> SoulProfile:
        """Load and parse SOUL.md into a SoulProfile."""
        path = self._resolve_file("SOUL.md")
        if not path:
            logger.info("SOUL.md not found — using default identity")
            return SoulProfile()

        try:
            raw_text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to read SOUL.md: %s", exc)
            return SoulProfile()

        data, body = self._parse_frontmatter(raw_text)
        if not data:
            return SoulProfile(body=body)

        personality = data.get("personality") or {}
        communication = data.get("communication") or {}

        return SoulProfile(
            name=str(data.get("name") or "AetherRavyn"),
            aliases=_to_list(data.get("aliases")),
            creator=str(data.get("creator") or ""),
            version=str(data.get("version") or "1.0.0"),
            born=str(data.get("born") or ""),
            base_traits=_to_list(personality.get("base_traits")),
            humor_style=str(personality.get("humor_style") or "dry-sarcastic"),
            formality=str(personality.get("formality") or "adaptive"),
            energy=str(personality.get("energy") or "high"),
            verbosity=str(personality.get("verbosity") or "proportional"),
            principles=_to_list(data.get("principles")),
            greeting_examples=_to_list(communication.get("greeting_examples")),
            forbidden_phrases=_to_list(communication.get("forbidden_phrases")),
            platforms=data.get("platforms") or {},
            circadian=data.get("circadian") or {},
            body=body.strip(),
        )

    # ── MEMORY.md Parsing ───────────────────────────────────────────

    def _load_memory(self) -> MemoryProfile:
        """Load MEMORY.md for persistent user knowledge."""
        path = self._resolve_file("MEMORY.md")
        if not path:
            return MemoryProfile()

        try:
            raw_text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to read MEMORY.md: %s", exc)
            return MemoryProfile()

        sections = _parse_markdown_sections(raw_text)
        return MemoryProfile(raw_text=raw_text, sections=sections)

    # ── AGENTS.md Parsing ───────────────────────────────────────────

    def _load_instructions(self) -> WorkspaceInstructions:
        """Load AGENTS.md for workspace-level instructions."""
        path = self._resolve_file("AGENTS.md")
        if not path:
            return WorkspaceInstructions()

        try:
            raw_text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to read AGENTS.md: %s", exc)
            return WorkspaceInstructions()

        rules = _extract_rules(raw_text)
        return WorkspaceInstructions(raw_text=raw_text, rules=rules)

    # ── Cache Management ────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Load/reload files if cache has expired."""
        import time as _time

        now = _time.monotonic()
        if now - self._last_load < self._cache_ttl and self._soul is not None:
            return

        self._soul = self._load_soul()
        self._memory = self._load_memory()
        self._instructions = self._load_instructions()
        self._last_load = now
        logger.debug("Soul Engine loaded: %s v%s", self._soul.name, self._soul.version)

    def reload(self) -> None:
        """Force reload all files."""
        self._last_load = 0.0
        self._ensure_loaded()

    # ── Public API ──────────────────────────────────────────────────

    @property
    def soul(self) -> SoulProfile:
        self._ensure_loaded()
        assert self._soul is not None
        return self._soul

    @property
    def memory(self) -> MemoryProfile:
        self._ensure_loaded()
        assert self._memory is not None
        return self._memory

    @property
    def instructions(self) -> WorkspaceInstructions:
        self._ensure_loaded()
        assert self._instructions is not None
        return self._instructions

    def get_name(self) -> str:
        """Return the agent's primary name."""
        return self.soul.name

    def get_identity_block(self) -> str:
        """Return a compact identity block for system prompt injection."""
        soul = self.soul
        lines = [
            f"You are {soul.name}.",
        ]
        if soul.aliases:
            lines.append(f"Also known as: {', '.join(soul.aliases)}.")
        if soul.creator:
            lines.append(f"Created by {soul.creator}.")
        if soul.base_traits:
            lines.append(f"Core traits: {', '.join(soul.base_traits)}.")
        if soul.principles:
            lines.append("")
            lines.append("Principles:")
            for principle in soul.principles:
                lines.append(f"- {principle}")
        return "\n".join(lines)

    def get_communication_block(self, platform: str | None = None) -> str:
        """Return communication style instructions, optionally platform-adapted."""
        soul = self.soul
        lines: list[str] = []

        # Platform-specific overrides
        if platform and platform in soul.platforms:
            plat = soul.platforms[platform]
            style = plat.get("style", soul.formality)
            lines.append(f"Communication style: {style}")
            max_len = plat.get("max_length")
            if max_len:
                lines.append(f"Max response length: {max_len} characters")
            emoji = plat.get("emoji_level", "moderate")
            lines.append(f"Emoji usage: {emoji}")
        else:
            lines.append(f"Humor style: {soul.humor_style}")
            lines.append(f"Formality: {soul.formality}")
            lines.append(f"Verbosity: {soul.verbosity}")

        # Forbidden phrases
        if soul.forbidden_phrases:
            lines.append("")
            lines.append("Never say:")
            for phrase in soul.forbidden_phrases:
                lines.append(f'- "{phrase}"')

        return "\n".join(lines)

    def get_circadian_block(self) -> str:
        """Return time-of-day personality adaptation."""
        soul = self.soul
        if not soul.circadian:
            return ""

        now = datetime.now(timezone.utc)
        hour = now.hour

        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "late_night"

        instruction = soul.circadian.get(period, "")
        if instruction:
            return f"Time-of-day adaptation ({period}): {instruction}"
        return ""

    def get_memory_block(self, max_chars: int = 2000) -> str:
        """Return condensed user knowledge from MEMORY.md."""
        mem = self.memory
        if not mem.raw_text:
            return ""

        # Strip markdown formatting for prompt injection
        text = mem.raw_text
        # Remove the title and frontmatter
        text = re.sub(r"^#\s+.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^>\s+.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^---\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*Last updated:.*$", "", text, flags=re.MULTILINE)
        text = text.strip()

        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"

        return f"Known facts about the user:\n{text}" if text else ""

    def get_instructions_block(self, max_chars: int = 1500) -> str:
        """Return workspace instructions from AGENTS.md."""
        inst = self.instructions
        if not inst.rules:
            return ""

        rules_text = "\n".join(f"- {rule}" for rule in inst.rules[:20])
        if len(rules_text) > max_chars:
            rules_text = rules_text[:max_chars] + "\n...[truncated]"

        return f"Workspace rules:\n{rules_text}"

    def get_voice_context_block(self, *, within_seconds: float = 300.0) -> str:
        """Return a compact voice-state block if the user spoke recently.

        Reads :class:`app.core.voice_context.VoiceContextEngine` via the
        lazy singleton.  When the user spoke within ``within_seconds``
        the persona engine gets a "Recent voice state" block listing
        the mood, ambient noise, and recency.  The import is wrapped
        in try/except so a RAVEN deployment that never wires the voice
        pipeline can still build a system prompt.

        Returns an empty string when the voice context is unknown
        or stale, so the caller can simply concatenate.
        """
        try:
            from app.core.voice_context import get_voice_context
        except Exception:  # noqa: BLE001 - voice module optional
            return ""
        try:
            snap = get_voice_context().snapshot()
        except Exception:  # noqa: BLE001 - defensive
            return ""
        if not snap.is_recent(within_seconds=within_seconds):
            return ""
        lines = [
            "Recent voice state:",
            f"- Last active: {within_seconds:.0f}s ago",
            f"- Mood: {snap.mood}",
            f"- Ambient noise: {snap.ambient_noise_db:.0f} dBFS",
        ]
        if snap.speaker_id:
            lines.append(f"- Speaker: {snap.speaker_id}")
        return "\n".join(lines)

    def build_system_prompt(
        self,
        platform: str | None = None,
        user_id: str | None = None,
        include_memory: bool = True,
        include_instructions: bool = True,
    ) -> str:
        """Build the complete system prompt from all soul files.

        This is the primary method that the orchestrator/bootstrapper should
        call instead of reading system_prompt.txt directly.
        """
        parts: list[str] = []

        # 1. Identity core
        parts.append(self.get_identity_block())

        # 2. Communication style
        comm = self.get_communication_block(platform)
        if comm:
            parts.append(f"\n{comm}")

        # 3. Circadian adaptation
        circadian = self.get_circadian_block()
        if circadian:
            parts.append(f"\n{circadian}")

        # 4. Soul body (prose description from SOUL.md)
        if self.soul.body:
            # Only include first ~500 chars of the body to avoid bloat
            body = self.soul.body[:500]
            parts.append(f"\n{body}")

        # 5. User memory
        if include_memory:
            mem = self.get_memory_block()
            if mem:
                parts.append(f"\n{mem}")

        # 6. Workspace instructions
        if include_instructions:
            inst = self.get_instructions_block()
            if inst:
                parts.append(f"\n{inst}")

        # 7. Voice context — only when the user spoke recently.
        voice = self.get_voice_context_block()
        if voice:
            parts.append(f"\n{voice}")

        return "\n".join(parts)


# ── Helpers ─────────────────────────────────────────────────────────


def _to_list(value: Any) -> list[str]:
    """Convert various types to a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    item = str(value).strip()
    return [item] if item else []


def _parse_markdown_sections(text: str) -> dict[str, str]:
    """Parse markdown into sections keyed by heading."""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            if current_heading and current_lines:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading and current_lines:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def _extract_rules(text: str) -> list[str]:
    """Extract numbered rules from AGENTS.md."""
    rules: list[str] = []
    for line in text.splitlines():
        # Match numbered rules like "1. **Python 3.12+** — All new code..."
        match = re.match(r"^\d+\.\s+\*{0,2}(.+?)(?:\*{0,2}\s*[-—]\s*(.+))?$", line)
        if match:
            title = match.group(1).strip().strip("*")
            desc = match.group(2).strip() if match.group(2) else ""
            rule = f"{title}: {desc}" if desc else title
            rules.append(rule)
        # Match bullet rules like "- **Formatter**: `ruff format`"
        elif re.match(r"^-\s+\*{0,2}\w+", line):
            cleaned = line.lstrip("- ").strip()
            if cleaned:
                rules.append(cleaned)
    return rules


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_SOUL_ENGINE: SoulEngine | None = None


def get_soul_engine(
    project_root: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> SoulEngine:
    """Get or create the global SoulEngine instance."""
    global _GLOBAL_SOUL_ENGINE
    if _GLOBAL_SOUL_ENGINE is None:
        _GLOBAL_SOUL_ENGINE = SoulEngine(
            project_root=project_root,
            workspace_dir=workspace_dir,
        )
    return _GLOBAL_SOUL_ENGINE
