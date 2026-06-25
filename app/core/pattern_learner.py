"""Pattern Learning — Raven learns rules from user behavior patterns.

Instead of just storing facts, Raven discovers patterns:
- "User codes best in the morning" → schedule coding tasks for AM
- "User prefers short responses on mobile" → adapt response length
- "User always checks weather before commute" → auto-notify weather

Patterns are extracted from interaction history and stored
as actionable rules.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Pattern:
    """A learned pattern from user behavior."""
    pattern_type: str  # time_preference, response_style, topic_interest, tool_preference
    description: str
    rule: str  # Human-readable rule
    confidence: float = 0.5
    evidence_count: int = 1
    last_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


class PatternLearner:
    """Discovers patterns from interaction history."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "patterns"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "patterns.jsonl"

    def learn_from_interaction(
        self,
        user_message: str,
        assistant_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[Pattern]:
        """Analyze an interaction and extract patterns."""
        patterns: list[Pattern] = []
        meta = metadata or {}

        # Time-based patterns
        hour = datetime.now(timezone.utc).hour
        if "code" in user_message.lower() or "implement" in user_message.lower():
            patterns.append(Pattern(
                pattern_type="time_preference",
                description=f"User codes at hour {hour}",
                rule=f"User tends to code around {hour}:00 UTC",
                confidence=0.3,
                metadata={"hour": hour, "topic": "coding"},
            ))

        # Response length patterns
        if len(assistant_response) > 500 and "short" in user_message.lower():
            patterns.append(Pattern(
                pattern_type="response_style",
                description="User wants shorter responses",
                rule="Keep responses concise when user asks for brevity",
                confidence=0.6,
                metadata={"trigger": "brevity_request"},
            ))

        # Tool preference patterns
        tool_used = meta.get("tool_used", "")
        if tool_used:
            patterns.append(Pattern(
                pattern_type="tool_preference",
                description=f"User used tool: {tool_used}",
                rule=f"User frequently uses {tool_used} for similar tasks",
                confidence=0.3,
                metadata={"tool": tool_used},
            ))

        # Topic interest patterns
        topics = self._extract_topics(user_message)
        for topic in topics:
            patterns.append(Pattern(
                pattern_type="topic_interest",
                description=f"User interested in: {topic}",
                rule=f"User has discussed {topic}",
                confidence=0.4,
                metadata={"topic": topic},
            ))

        # Save patterns (with aggregation: merge duplicates, grow confidence)
        for pattern in patterns:
            self._aggregate_and_save(pattern)

        return patterns

    def _extract_topics(self, text: str) -> list[str]:
        """Extract topic keywords from text."""
        topics = []
        topic_keywords = {
            "ai": ["ai", "llm", "gpt", "model", "neural", "machine learning"],
            "web": ["web", "html", "css", "frontend", "backend", "api"],
            "devops": ["docker", "kubernetes", "deploy", "ci", "pipeline"],
            "security": ["security", "vulnerability", "encrypt", "auth"],
            "finance": ["stock", "crypto", "investment", "portfolio"],
            "health": ["health", "fitness", "sleep", "nutrition"],
            "home": ["smart home", "iot", "sensor", "camera"],
        }

        lower = text.lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in lower for kw in keywords):
                topics.append(topic)

        return topics[:3]  # Max 3 topics per interaction

    def _aggregate_and_save(self, new_pattern: Pattern) -> None:
        """Merge new pattern with existing similar patterns.

        If a matching pattern exists (same type + same rule), increment
        its evidence_count and boost confidence. Otherwise, save as new.
        """
        import math
        from dataclasses import asdict

        existing = self.get_patterns(limit=1000)
        merged = False
        updated_lines: list[str] = []

        for p in existing:
            if p.pattern_type == new_pattern.pattern_type and p.rule == new_pattern.rule:
                # Aggregate: increment evidence, boost confidence
                p.evidence_count += 1
                p.confidence = min(1.0, 0.5 + 0.1 * math.log2(max(1, p.evidence_count)))
                p.last_seen = new_pattern.last_seen
                p.metadata.update(new_pattern.metadata)
                merged = True
            updated_lines.append(json.dumps(asdict(p), ensure_ascii=False))

        if not merged:
            # New unique pattern — append it
            updated_lines.append(json.dumps(asdict(new_pattern), ensure_ascii=False))

        self._file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    def get_patterns(self, pattern_type: str | None = None, limit: int = 50) -> list[Pattern]:
        """Get stored patterns, optionally filtered by type."""
        if not self._file.exists():
            return []

        patterns: list[Pattern] = []
        for line in self._file.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                p = Pattern(**data)
                if pattern_type is None or p.pattern_type == pattern_type:
                    patterns.append(p)
            except Exception:
                continue

        # Sort by confidence and evidence count
        patterns.sort(key=lambda p: (p.confidence, p.evidence_count), reverse=True)
        return patterns[:limit]

    def get_rules_for_prompt(self) -> str:
        """Build a prompt section from learned patterns.

        Injected into system prompt so Raven applies learned
        behavioral rules automatically. Automatically prunes
        low-confidence and duplicate patterns.
        """
        patterns = self.get_patterns(limit=50)

        # Prune: keep only patterns with confidence > 0.3
        patterns = [p for p in patterns if p.confidence > 0.3]

        # Aggregate: deduplicate by rule text
        seen_rules: set[str] = set()
        unique_patterns = []
        for p in patterns:
            if p.rule not in seen_rules:
                seen_rules.add(p.rule)
                unique_patterns.append(p)

        # Cap at 15 rules to avoid prompt bloat
        unique_patterns = unique_patterns[:15]

        if not unique_patterns:
            return ""

        lines = ["## Learned Behavioral Rules"]
        for p in unique_patterns:
            lines.append(f"- {p.rule}")

        return "\n".join(lines)

    def prune(self, min_confidence: float = 0.3) -> int:
        """Remove low-confidence patterns. Returns count removed."""
        if not self._file.exists():
            return 0

        patterns = self.get_patterns(limit=1000)
        original_count = len(patterns)

        # Filter
        kept = [p for p in patterns if p.confidence >= min_confidence]

        # Rewrite file
        from dataclasses import asdict
        with open(self._file, "w", encoding="utf-8") as f:
            for p in kept:
                f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")

        removed = original_count - len(kept)
        if removed:
            logger.info("Pruned %d low-confidence patterns", removed)
        return removed

    def count(self) -> int:
        if not self._file.exists():
            return 0
        return sum(1 for line in self._file.read_text(encoding="utf-8").strip().splitlines() if line.strip())
