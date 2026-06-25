"""Auto Prompt Improvement — Raven improves its own prompts from failures.

When an interaction fails or gets negative feedback, Raven analyzes
what went wrong and adjusts its system prompt to avoid the same
mistake in the future.

Flow:
  1. Track interaction outcomes (success/failure + reason)
  2. Analyze failure patterns
  3. Generate prompt adjustments
  4. Apply adjustments to future prompts
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InteractionRecord:
    """Record of a single interaction for analysis."""
    interaction_id: str
    query: str
    response: str
    success: bool
    failure_reason: str = ""
    tool_used: str = ""
    model_used: str = ""
    duration_ms: float = 0.0
    user_feedback: str | None = None  # "good", "bad", or None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class PromptAdjustment:
    """A suggested adjustment to the system prompt."""
    category: str  # e.g. "tone", "detail_level", "tool_usage", "response_format"
    adjustment: str  # e.g. "Be more concise for simple questions"
    reason: str  # Why this adjustment is needed
    confidence: float = 0.7  # How confident we are
    applied: bool = False


class InteractionTracker:
    """Tracks interaction outcomes for pattern analysis."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "interactions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "interactions.jsonl"

    def record(self, interaction: InteractionRecord) -> None:
        """Append an interaction record."""
        data = {
            "id": interaction.interaction_id,
            "query": interaction.query[:200],
            "response": interaction.response[:200],
            "success": interaction.success,
            "failure_reason": interaction.failure_reason,
            "tool_used": interaction.tool_used,
            "model_used": interaction.model_used,
            "duration_ms": interaction.duration_ms,
            "user_feedback": interaction.user_feedback,
            "timestamp": interaction.timestamp,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def get_recent(self, n: int = 100) -> list[InteractionRecord]:
        """Get the last N interaction records."""
        if not self._file.exists():
            return []
        lines = self._file.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines[-n:]:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                records.append(InteractionRecord(
                    interaction_id=d.get("id", ""),
                    query=d.get("query", ""),
                    response=d.get("response", ""),
                    success=d.get("success", True),
                    failure_reason=d.get("failure_reason", ""),
                    tool_used=d.get("tool_used", ""),
                    model_used=d.get("model_used", ""),
                    duration_ms=d.get("duration_ms", 0),
                    user_feedback=d.get("user_feedback"),
                    timestamp=d.get("timestamp", ""),
                ))
            except Exception:
                continue
        return records

    def get_failure_rate(self, window: int = 50) -> float:
        """Get the recent failure rate (0.0 to 1.0)."""
        records = self.get_recent(window)
        if not records:
            return 0.0
        failures = sum(1 for r in records if not r.success)
        return failures / len(records)


class PromptAnalyzer:
    """Analyzes interaction patterns and generates prompt adjustments."""

    def __init__(self) -> None:
        self._tracker = InteractionTracker()

    def analyze(self) -> list[PromptAdjustment]:
        """Analyze recent interactions and suggest prompt adjustments."""
        records = self._tracker.get_recent(200)
        if len(records) < 10:
            return []

        adjustments: list[PromptAdjustment] = []

        # Analyze failure patterns
        failures = [r for r in records if not r.success]
        if failures:
            # Check for timeout pattern
            timeouts = [f for f in failures if "timeout" in f.failure_reason.lower()]
            if len(timeouts) > len(failures) * 0.3:
                adjustments.append(PromptAdjustment(
                    category="tool_usage",
                    adjustment="When tools timeout, suggest alternative approaches instead of retrying the same tool.",
                    reason=f"{len(timeouts)}/{len(failures)} failures were timeouts",
                    confidence=0.8,
                ))

            # Check for tool-not-found pattern
            not_found = [f for f in failures if "not found" in f.failure_reason.lower() or "unknown" in f.failure_reason.lower()]
            if len(not_found) > len(failures) * 0.2:
                adjustments.append(PromptAdjustment(
                    category="tool_usage",
                    adjustment="Before using a tool, verify the tool name is correct. Check available tools first.",
                    reason=f"{len(not_found)}/{len(failures)} failures were tool-not-found",
                    confidence=0.7,
                ))

        # Analyze user feedback patterns
        bad_feedback = [r for r in records if r.user_feedback == "bad"]
        if len(bad_feedback) > 5:
            # Check if responses are too long
            long_responses = [r for r in bad_feedback if len(r.response) > 500]
            if len(long_responses) > len(bad_feedback) * 0.4:
                adjustments.append(PromptAdjustment(
                    category="detail_level",
                    adjustment="Keep responses concise. Use bullet points for lists. Avoid unnecessary preamble.",
                    reason=f"{len(long_responses)}/{len(bad_feedback)} negative feedback on long responses",
                    confidence=0.7,
                ))

        # Analyze response time
        slow_interactions = [r for r in records if r.duration_ms > 10000]
        if len(slow_interactions) > len(records) * 0.2:
            adjustments.append(PromptAdjustment(
                category="efficiency",
                adjustment="Prioritize fast tools. Use cached results when available. Avoid unnecessary API calls.",
                    reason=f"{len(slow_interactions)}/{len(records)} interactions took >10s",
                    confidence=0.6,
                ))

        return adjustments


class PromptImprover:
    """Applies prompt adjustments to improve future responses.

    Maintains a list of active adjustments that are injected
    into the system prompt on every interaction.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "prompt_adjustments"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "adjustments.json"
        self._adjustments: list[PromptAdjustment] = self._load()

    def _load(self) -> list[PromptAdjustment]:
        if not self._file.exists():
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return [PromptAdjustment(**a) for a in data]
        except Exception:
            return []

    def _save(self) -> None:
        data = [
            {
                "category": a.category,
                "adjustment": a.adjustment,
                "reason": a.reason,
                "confidence": a.confidence,
                "applied": a.applied,
            }
            for a in self._adjustments
        ]
        self._file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_adjustment(self, adjustment: PromptAdjustment) -> None:
        """Add a new adjustment (avoid duplicates)."""
        for existing in self._adjustments:
            if existing.category == adjustment.category and existing.adjustment == adjustment.adjustment:
                return  # Already exists
        self._adjustments.append(adjustment)
        self._save()
        logger.info("Prompt adjustment added: [%s] %s", adjustment.category, adjustment.adjustment[:60])

    def remove_adjustment(self, index: int) -> bool:
        """Remove an adjustment by index."""
        if 0 <= index < len(self._adjustments):
            self._adjustments.pop(index)
            self._save()
            return True
        return False

    def get_adjustments_prompt(self) -> str:
        """Build a prompt section with all active adjustments.

        Injected into the system prompt so Raven applies the
        learned improvements automatically.
        """
        active = [a for a in self._adjustments if not a.applied]
        if not active:
            return ""

        lines = ["## Learned Improvements (apply these to every response)"]
        for a in active:
            lines.append(f"- {a.adjustment}")
        return "\n".join(lines)

    def get_all(self) -> list[PromptAdjustment]:
        return list(self._adjustments)

    def clear(self) -> None:
        self._adjustments.clear()
        self._save()
