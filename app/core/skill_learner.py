"""Skill Learner — Auto-creates skills from successful interactions.

Monitors the orchestrator's execution traces. When it detects a complex,
multi-step solution that the user approved, it extracts the procedure and
saves it as a reusable SKILL.md + module.yaml in ``skills/learned/``.

This is the core of AetherRavyn's self-evolution loop, inspired by
Hermes Agent's auto-skill creation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class ExecutionTrace:
    """Record of a completed orchestrator turn."""

    interaction_id: str
    user_message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    agent_used: str | None = None
    response: str = ""
    success: bool = True
    user_satisfied: bool = False  # Inferred from feedback signals
    latency_ms: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class SkillDraft:
    """A candidate skill extracted from an execution trace."""

    name: str
    module_id: str
    description: str
    tags: list[str]
    trigger_patterns: list[str]
    procedure_steps: list[str]
    tools_used: list[str]
    agent_used: str | None
    learned_from: str  # Trace description
    confidence: float = 0.75


@dataclass(slots=True)
class SkillInvocation:
    """Record of a skill being invoked."""

    skill_id: str
    success: bool
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    feedback: str = ""


class SkillLearner:
    """Observes execution traces and auto-creates reusable skills.

    The learning loop:
    1. observe() — called after each orchestrator turn with the execution trace
    2. _should_learn() — decides if this trace is skill-worthy
    3. extract() — uses heuristics to extract a reusable skill
    4. save() — writes SKILL.md + module.yaml to skills/learned/
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        min_tool_calls: int = 2,
        min_confidence: float = 0.6,
        max_learned_skills: int = 100,
    ) -> None:
        self._project_root = (
            Path(project_root).resolve() if project_root else _PROJECT_ROOT
        )
        self._learned_dir = self._project_root / "skills" / "learned"
        self._learned_dir.mkdir(parents=True, exist_ok=True)
        self._history_dir = self._project_root / "workspace" / "memory" / "skill_learning"
        self._history_dir.mkdir(parents=True, exist_ok=True)

        self._min_tool_calls = min_tool_calls
        self._min_confidence = min_confidence
        self._max_learned_skills = max_learned_skills

        # In-memory trace buffer for pattern detection
        self._recent_traces: list[ExecutionTrace] = []
        self._max_buffer: int = 50

    # ── Observation ─────────────────────────────────────────────────

    async def observe(self, trace: ExecutionTrace) -> SkillDraft | None:
        """Monitor an execution trace and potentially create a new skill.

        Returns a SkillDraft if a new skill was created, None otherwise.
        """
        self._recent_traces.append(trace)
        if len(self._recent_traces) > self._max_buffer:
            self._recent_traces = self._recent_traces[-self._max_buffer:]

        # Log the trace for history
        self._log_trace(trace)

        # Decide if this is skill-worthy
        if not self._should_learn(trace):
            return None

        # Check if we already have a similar skill
        if self._has_similar_skill(trace):
            logger.debug("Similar skill already exists, skipping creation")
            return None

        # Extract skill
        draft = self.extract(trace)
        if draft and draft.confidence >= self._min_confidence:
            record = await self.save(draft)
            logger.info(
                "Learned new skill: %s (confidence=%.2f)",
                draft.name,
                draft.confidence,
            )
            return draft

        return None

    def _should_learn(self, trace: ExecutionTrace) -> bool:
        """Decide if an execution trace is worth turning into a skill."""
        # Must be successful
        if not trace.success:
            return False

        # Must use enough tools (simple Q&A isn't worth a skill)
        if len(trace.tool_calls) < self._min_tool_calls:
            return False

        # User must have been satisfied (positive feedback signal)
        if not trace.user_satisfied:
            return False

        # Don't exceed max learned skills
        existing_count = sum(1 for _ in self._learned_dir.iterdir() if _.is_dir())
        if existing_count >= self._max_learned_skills:
            logger.warning(
                "Max learned skills (%d) reached, skipping",
                self._max_learned_skills,
            )
            return False

        return True

    def _has_similar_skill(self, trace: ExecutionTrace) -> bool:
        """Check if a similar skill already exists."""
        tools_used = {tc.get("tool", "") for tc in trace.tool_calls}
        keywords = set(trace.user_message.lower().split())

        for skill_dir in self._learned_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest = skill_dir / "module.yaml"
            if not manifest.exists():
                continue
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                skill_tags = set(data.get("tags") or [])
                # If tags overlap significantly, consider it similar
                overlap = keywords & skill_tags
                if len(overlap) >= 3:
                    return True
            except Exception:
                continue

        return False

    # ── Extraction ──────────────────────────────────────────────────

    def extract(self, trace: ExecutionTrace) -> SkillDraft | None:
        """Extract a reusable skill from an execution trace.

        Uses heuristics to build the skill. In the future, this will call
        the LLM to generate a richer skill description.
        """
        tools_used = []
        procedure_steps = []
        for idx, tc in enumerate(trace.tool_calls, 1):
            tool_name = tc.get("tool", "unknown_tool")
            action = tc.get("action", "execute")
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            procedure_steps.append(
                f"Step {idx}: Use {tool_name} ({action})"
            )

        # Generate a slug for the skill name
        words = re.sub(r"[^a-z0-9\s]", "", trace.user_message.lower()).split()
        meaningful_words = [w for w in words if len(w) > 2 and w not in _STOP_WORDS][:4]
        slug = "_".join(meaningful_words) or "learned_skill"

        # Generate tags from the message and tools
        tags = list(set(meaningful_words + [t.replace("_", "-") for t in tools_used[:3]]))

        # Build trigger patterns from the user message
        trigger_patterns = []
        if meaningful_words:
            pattern = ".*".join(meaningful_words[:3])
            trigger_patterns.append(pattern)

        name = slug.replace("_", " ").title()
        module_id = f"skill.learned.{slug}"

        confidence = 0.7
        if trace.user_satisfied:
            confidence += 0.1
        if len(trace.tool_calls) >= 4:
            confidence += 0.05
        if trace.agent_used:
            confidence += 0.05

        return SkillDraft(
            name=name,
            module_id=module_id,
            description=f"Learned procedure for: {trace.user_message[:100]}",
            tags=tags,
            trigger_patterns=trigger_patterns,
            procedure_steps=procedure_steps,
            tools_used=tools_used,
            agent_used=trace.agent_used,
            learned_from=f"{trace.timestamp} — {trace.user_message[:80]}",
            confidence=min(1.0, confidence),
        )

    # ── Persistence ─────────────────────────────────────────────────

    async def save(self, draft: SkillDraft) -> dict[str, Any]:
        """Save a skill draft as SKILL.md + module.yaml in skills/learned/."""
        slug = draft.module_id.replace("skill.learned.", "").replace(".", "_")
        skill_dir = self._learned_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write module.yaml (canonical manifest)
        manifest = {
            "schema_version": "1.0",
            "module_id": draft.module_id,
            "display_name": draft.name,
            "name": draft.name,
            "version": "0.1.0",
            "category": "skill",
            "description": draft.description,
            "tags": draft.tags,
            "capabilities": draft.tools_used,
            "trust_level": "workspace",
            "enabled_by_default": True,
            "stability": "experimental",
            "maturity": "development",
            "origin": "learned",
            "learned_from": draft.learned_from,
            "confidence": draft.confidence,
            "invocation_count": 0,
            "success_rate": 1.0,
            "triggers": [
                {"pattern": p, "confidence": draft.confidence}
                for p in draft.trigger_patterns
            ],
        }
        manifest_path = skill_dir / "module.yaml"
        manifest_path.write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        # Write SKILL.md
        skill_md_lines = [
            f"---",
            f"name: {draft.name}",
            f"module_id: {draft.module_id}",
            f"version: 0.1.0",
            f"category: skill",
            f"description: {draft.description}",
            f"tags: [{', '.join(draft.tags)}]",
            f"origin: learned",
            f"---",
            f"",
            f"# {draft.name}",
            f"",
            f"## Description",
            f"{draft.description}",
            f"",
            f"## Procedure",
        ]
        for step in draft.procedure_steps:
            skill_md_lines.append(f"- {step}")

        skill_md_lines.extend([
            f"",
            f"## Tools Used",
        ])
        for tool in draft.tools_used:
            skill_md_lines.append(f"- `{tool}`")

        if draft.agent_used:
            skill_md_lines.extend([
                f"",
                f"## Recommended Agent",
                f"- {draft.agent_used}",
            ])

        skill_md_lines.extend([
            f"",
            f"## Learning Origin",
            f"- Learned from: {draft.learned_from}",
            f"- Confidence: {draft.confidence:.2f}",
            f"- Auto-generated by AetherRavyn SkillLearner",
        ])

        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text("\n".join(skill_md_lines), encoding="utf-8")

        # Create history.jsonl for tracking invocations
        history_path = skill_dir / "history.jsonl"
        if not history_path.exists():
            history_path.write_text("", encoding="utf-8")

        logger.info("Saved learned skill to %s", skill_dir)
        return {"skill_dir": str(skill_dir), "module_id": draft.module_id}

    # ── Skill Improvement ───────────────────────────────────────────

    async def record_invocation(
        self, skill_id: str, success: bool, feedback: str = ""
    ) -> None:
        """Record a skill invocation outcome for improvement tracking."""
        slug = skill_id.replace("skill.learned.", "").replace(".", "_")
        skill_dir = self._learned_dir / slug
        if not skill_dir.exists():
            logger.warning("Skill directory not found: %s", skill_dir)
            return

        # Append to history
        history_path = skill_dir / "history.jsonl"
        invocation = SkillInvocation(
            skill_id=skill_id,
            success=success,
            feedback=feedback,
        )
        try:
            with history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(invocation)) + "\n")
        except Exception as exc:
            logger.warning("Failed to record invocation: %s", exc)

        # Update manifest stats
        manifest_path = skill_dir / "module.yaml"
        if manifest_path.exists():
            try:
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                count = data.get("invocation_count", 0) + 1
                data["invocation_count"] = count

                # Recalculate success rate from history
                successes = 0
                total = 0
                for line in history_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        total += 1
                        if entry.get("success"):
                            successes += 1
                    except Exception:
                        continue
                if total > 0:
                    data["success_rate"] = round(successes / total, 3)

                data["last_invoked"] = datetime.now(timezone.utc).isoformat()
                manifest_path.write_text(
                    yaml.dump(data, default_flow_style=False, allow_unicode=True),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("Failed to update skill manifest: %s", exc)

    def record_feedback(
        self,
        interaction_id: str,
        satisfied: bool,
        feedback_text: str = "",
    ) -> None:
        """Record user feedback for an interaction.

        If the user was satisfied and the interaction had multiple tool calls,
        this may trigger skill extraction on the next observation cycle.

        Args:
            interaction_id: The session/interaction ID to record feedback for
            satisfied: Whether the user was satisfied with the response
            feedback_text: Optional explicit feedback text
        """
        # Update any recent traces with this feedback
        for trace in self._recent_traces:
            if trace.interaction_id == interaction_id:
                trace.user_satisfied = satisfied
                # If satisfied and meets criteria, try to extract skill now
                if satisfied and self._should_learn(trace):
                    if not self._has_similar_skill(trace):
                        draft = self.extract(trace)
                        if draft and draft.confidence >= self._min_confidence:
                            import asyncio
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    # Schedule as task if loop is running
                                    asyncio.create_task(self.save(draft))
                                else:
                                    loop.run_until_complete(self.save(draft))
                                logger.info(
                                    "Feedback-triggered skill creation: %s",
                                    draft.name,
                                )
                            except Exception as exc:
                                logger.debug("Feedback skill creation error: %s", exc)
                break

        # Log feedback
        feedback_dir = self._history_dir / "feedback"
        feedback_dir.mkdir(parents=True, exist_ok=True)
        feedback_file = feedback_dir / f"{interaction_id}.json"
        try:
            import json
            data = {
                "interaction_id": interaction_id,
                "satisfied": satisfied,
                "feedback_text": feedback_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            feedback_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Feedback logging error: %s", exc)

    # ── Pattern Detection ───────────────────────────────────────────

    def detect_recurring_patterns(self) -> list[dict[str, Any]]:
        """Analyze recent traces to find recurring tool-use patterns."""
        if len(self._recent_traces) < 5:
            return []

        # Count tool combinations
        from collections import Counter

        tool_combos: Counter[tuple[str, ...]] = Counter()
        for trace in self._recent_traces:
            if trace.success and len(trace.tool_calls) >= 2:
                tools = tuple(
                    tc.get("tool", "") for tc in trace.tool_calls if tc.get("tool")
                )
                if tools:
                    tool_combos[tools] += 1

        patterns = []
        for combo, count in tool_combos.most_common(5):
            if count >= 2:
                patterns.append({
                    "tools": list(combo),
                    "frequency": count,
                    "suggestion": f"Tools {', '.join(combo)} are frequently used together. "
                    f"Consider creating a dedicated skill.",
                })

        return patterns

    # ── History ──────────────────────────────────────────────────────

    def _log_trace(self, trace: ExecutionTrace) -> None:
        """Append trace to persistent history file."""
        log_path = self._history_dir / "traces.jsonl"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(trace)) + "\n")
        except Exception as exc:
            logger.debug("Trace logging failed: %s", exc)

    def get_learned_skills_summary(self) -> dict[str, Any]:
        """Return a summary of all learned skills."""
        skills: list[dict[str, Any]] = []
        for skill_dir in sorted(self._learned_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "module.yaml"
            if not manifest_path.exists():
                continue
            try:
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                skills.append({
                    "module_id": data.get("module_id"),
                    "name": data.get("display_name") or data.get("name"),
                    "confidence": data.get("confidence", 0),
                    "invocation_count": data.get("invocation_count", 0),
                    "success_rate": data.get("success_rate", 0),
                    "origin": data.get("origin", "learned"),
                })
            except Exception:
                continue

        return {
            "count": len(skills),
            "skills": skills,
        }


# ── Stop words for slug generation ──────────────────────────────────

_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "have", "has",
    "was", "are", "were", "been", "being", "can", "could", "would",
    "should", "will", "shall", "may", "might", "must", "need", "not",
    "but", "about", "into", "than", "then", "them", "they", "what",
    "when", "where", "which", "while", "who", "whom", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "too", "very",
    "please", "help", "want", "just", "like", "make", "get",
})


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_LEARNER: SkillLearner | None = None


def get_skill_learner(
    project_root: str | Path | None = None,
) -> SkillLearner:
    """Get or create the global SkillLearner instance."""
    global _GLOBAL_LEARNER
    if _GLOBAL_LEARNER is None:
        _GLOBAL_LEARNER = SkillLearner(project_root=project_root)
    return _GLOBAL_LEARNER
