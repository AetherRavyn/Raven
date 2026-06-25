"""Proactive Opportunity Detection — Identifies actionable patterns and suggests next steps.

Analyzes user behavior, calendar, tasks, and conversation history to detect:
- Upcoming deadlines that need attention
- Recurring tasks that could be automated
- Information gaps that could be filled
- Follow-up actions from previous conversations
- Time-based opportunities (e.g., "you usually check X on Mondays")
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.settings.config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Opportunity:
    """A detected opportunity for proactive action."""

    opportunity_type: str  # deadline, automation, followup, info_gap, pattern
    title: str
    description: str
    confidence: float  # 0.0 to 1.0
    urgency: str  # low, medium, high, critical
    suggested_action: str
    context: dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OpportunityDetector:
    """Detects proactive opportunities from user activity and context."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self._detected: list[Opportunity] = []
        self._last_scan: datetime | None = None

    def detect_all(self) -> list[Opportunity]:
        """Run all opportunity detection checks and return findings."""
        opportunities: list[Opportunity] = []

        # Run each detector
        opportunities.extend(self._detect_deadline_opportunities())
        opportunities.extend(self._detect_followup_opportunities())
        opportunities.extend(self._detect_pattern_opportunities())
        opportunities.extend(self._detect_automation_opportunities())
        opportunities.extend(self._detect_info_gap_opportunities())

        # Sort by urgency and confidence
        urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        opportunities.sort(
            key=lambda o: (urgency_order.get(o.urgency, 4), -o.confidence)
        )

        self._detected = opportunities
        self._last_scan = datetime.now(timezone.utc)
        return opportunities

    def _detect_deadline_opportunities(self) -> list[Opportunity]:
        """Detect upcoming deadlines that need attention."""
        opportunities = []

        # Check task inbox for items with due dates
        try:
            from app.core.task_inbox import TaskInboxStore
            inbox = TaskInboxStore(str(self.workspace_dir))

            now = datetime.now(timezone.utc)
            soon = now + timedelta(days=3)

            # Get all open tasks
            for user_id in self._get_active_users():
                items = inbox.list_items(user_id, kind="task")
                for item in items:
                    due_str = item.get("due_date")
                    if not due_str:
                        continue

                    try:
                        due = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    # Check if deadline is approaching
                    if now < due <= soon:
                        hours_left = (due - now).total_seconds() / 3600
                        urgency = "critical" if hours_left < 24 else "high" if hours_left < 48 else "medium"

                        opportunities.append(Opportunity(
                            opportunity_type="deadline",
                            title=f"Deadline approaching: {item.get('title', 'Unknown')[:50]}",
                            description=f"Due in {hours_left:.1f} hours",
                            confidence=0.9,
                            urgency=urgency,
                            suggested_action=f"Review and complete: {item.get('title', '')[:100]}",
                            context={"task_id": item.get("id"), "due_date": due_str},
                        ))
                    elif due < now:
                        # Overdue
                        opportunities.append(Opportunity(
                            opportunity_type="deadline",
                            title=f"OVERDUE: {item.get('title', 'Unknown')[:50]}",
                            description=f"Was due {due.strftime('%Y-%m-%d')}",
                            confidence=1.0,
                            urgency="critical",
                            suggested_action=f"Complete or reschedule: {item.get('title', '')[:100]}",
                            context={"task_id": item.get("id"), "due_date": due_str},
                        ))
        except Exception as e:
            logger.debug("Deadline detection failed: %s", e)

        return opportunities

    def _detect_followup_opportunities(self) -> list[Opportunity]:
        """Detect conversations that need follow-up."""
        opportunities = []

        try:
            from app.core.session import SessionManager
            session_mgr = SessionManager(str(self.workspace_dir))

            now = datetime.now(timezone.utc)
            followup_window = timedelta(days=2)

            for user_id in self._get_active_users():
                # Get recent sessions
                sessions_dir = Path(self.workspace_dir) / "sessions"
                if not sessions_dir.exists():
                    continue

                for session_file in sessions_dir.glob(f"{user_id}*.jsonl"):
                    try:
                        stat = session_file.stat()
                        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

                        # Only check sessions from last week
                        if (now - mtime) > timedelta(days=7):
                            continue

                        # Read last few messages
                        lines = session_file.read_text(encoding="utf-8").splitlines()
                        if len(lines) < 4:
                            continue

                        # Check last assistant message for follow-up indicators
                        for line in reversed(lines[-10:]):
                            if not line.strip():
                                continue
                            msg = json.loads(line)
                            if msg.get("role") != "assistant":
                                continue

                            content = msg.get("content", "").lower()

                            # Check for follow-up indicators
                            followup_phrases = [
                                "let me know if",
                                "feel free to",
                                "when you get a chance",
                                "you might want to",
                                "consider",
                                "next steps",
                                "follow up",
                                "remind",
                            ]

                            for phrase in followup_phrases:
                                if phrase in content:
                                    # Extract a summary
                                    summary = msg.get("content", "")[:100]
                                    opportunities.append(Opportunity(
                                        opportunity_type="followup",
                                        title=f"Possible follow-up needed",
                                        description=f"From {mtime.strftime('%Y-%m-%d')}: {summary}...",
                                        confidence=0.6,
                                        urgency="low",
                                        suggested_action="Check if user needs follow-up on previous conversation",
                                        context={
                                            "session_file": str(session_file),
                                            "message_time": mtime.isoformat(),
                                            "trigger_phrase": phrase,
                                        },
                                    ))
                                    break
                            break  # Only check last assistant message
                    except Exception as e:
                        logger.debug("Session analysis failed for %s: %s", session_file, e)

        except Exception as e:
            logger.debug("Follow-up detection failed: %s", e)

        return opportunities

    def _detect_pattern_opportunities(self) -> list[Opportunity]:
        """Detect recurring patterns that could be optimized."""
        opportunities = []

        try:
            # Analyze task patterns
            from app.core.task_ledger import TaskLedger
            ledger = TaskLedger(str(self.workspace_dir))

            tasks = ledger.list_tasks(status="done")

            # Group tasks by title pattern
            task_titles = [t.get("title", "").lower() for t in tasks if t.get("title")]
            title_counter = Counter(task_titles)

            # Find recurring tasks (same title 3+ times)
            for title, count in title_counter.items():
                if count >= 3 and len(title) > 5:
                    opportunities.append(Opportunity(
                        opportunity_type="pattern",
                        title=f"Recurring task detected: {title[:50]}",
                        description=f"Appears {count} times in task history",
                        confidence=0.7,
                        urgency="low",
                        suggested_action="Consider automating this recurring task",
                        context={"task_title": title, "occurrences": count},
                    ))

        except Exception as e:
            logger.debug("Pattern detection failed: %s", e)

        return opportunities

    def _detect_automation_opportunities(self) -> list[Opportunity]:
        """Detect tasks that could be automated."""
        opportunities = []

        try:
            # Check for manual tasks that match automation patterns
            from app.core.task_inbox import TaskInboxStore
            inbox = TaskInboxStore(str(self.workspace_dir))

            automation_patterns = [
                ("check", "monitoring"),
                ("remind", "reminder"),
                ("daily", "schedule"),
                ("weekly", "schedule"),
                ("report", "reporting"),
                ("backup", "backup"),
                ("sync", "sync"),
            ]

            for user_id in self._get_active_users():
                items = inbox.list_items(user_id, kind="task")
                for item in items:
                    title = item.get("title", "").lower()
                    for pattern, category in automation_patterns:
                        if pattern in title:
                            opportunities.append(Opportunity(
                                opportunity_type="automation",
                                title=f"Could automate: {item.get('title', '')[:50]}",
                                description=f"Matches '{category}' automation pattern",
                                confidence=0.5,
                                urgency="low",
                                suggested_action=f"Consider creating an automated {category} routine",
                                context={"task_id": item.get("id"), "pattern": pattern},
                            ))
                            break

        except Exception as e:
            logger.debug("Automation detection failed: %s", e)

        return opportunities

    def _detect_info_gap_opportunities(self) -> list[Opportunity]:
        """Detect information gaps that could be filled."""
        opportunities = []

        try:
            # Check for questions that were asked but not answered
            sessions_dir = Path(self.workspace_dir) / "sessions"
            if not sessions_dir.exists():
                return opportunities

            now = datetime.now(timezone.utc)

            for session_file in sessions_dir.glob("*.jsonl"):
                try:
                    lines = session_file.read_text(encoding="utf-8").splitlines()
                    if len(lines) < 2:
                        continue

                    # Look for unanswered questions
                    for i, line in enumerate(lines[:-1]):
                        if not line.strip():
                            continue
                        msg = json.loads(line)
                        if msg.get("role") != "user":
                            continue

                        content = msg.get("content", "")

                        # Check if it's a question
                        if "?" in content or any(
                            content.lower().startswith(prefix)
                            for prefix in ["what", "how", "why", "when", "where", "who", "can you", "could you"]
                        ):
                            # Check if next message is an answer
                            next_line = lines[i + 1] if i + 1 < len(lines) else None
                            if next_line:
                                next_msg = json.loads(next_line)
                                if next_msg.get("role") == "assistant":
                                    response = next_msg.get("content", "")
                                    # Check if response indicates uncertainty
                                    uncertainty_phrases = [
                                        "i'm not sure",
                                        "i don't know",
                                        "i couldn't find",
                                        "unfortunately",
                                        "i don't have access",
                                        "let me know if you",
                                    ]
                                    if any(phrase in response.lower() for phrase in uncertainty_phrases):
                                        opportunities.append(Opportunity(
                                            opportunity_type="info_gap",
                                            title=f"Unanswered question detected",
                                            description=f"Question: {content[:100]}...",
                                            confidence=0.6,
                                            urgency="low",
                                            suggested_action="Research and provide a complete answer",
                                            context={
                                                "question": content[:200],
                                                "partial_response": response[:200],
                                            },
                                        ))
                except Exception as e:
                    logger.debug("Info gap analysis failed for %s: %s", session_file, e)

        except Exception as e:
            logger.debug("Info gap detection failed: %s", e)

        return opportunities

    def _get_active_users(self) -> list[str]:
        """Get list of active user IDs."""
        users = []
        sessions_dir = Path(self.workspace_dir) / "sessions"
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.jsonl"):
                # Extract user ID from filename
                user_id = session_file.stem.split("_")[0]
                if user_id and user_id not in users:
                    users.append(user_id)
        return users

    def format_opportunities(self, opportunities: list[Opportunity] | None = None, max_items: int = 5) -> str:
        """Format opportunities as a readable report."""
        if opportunities is None:
            opportunities = self._detected

        if not opportunities:
            return "✨ No proactive opportunities detected at this time."

        lines = ["## 🎯 Proactive Opportunities\n"]

        urgency_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }

        for i, opp in enumerate(opportunities[:max_items], 1):
            emoji = urgency_emoji.get(opp.urgency, "⚪")
            lines.append(f"### {i}. {emoji} {opp.title}")
            lines.append(f"**Type**: {opp.opportunity_type} | **Confidence**: {opp.confidence:.0%}")
            lines.append(f"{opp.description}")
            lines.append(f"**Suggested Action**: {opp.suggested_action}")
            lines.append("")

        if len(opportunities) > max_items:
            lines.append(f"... and {len(opportunities) - max_items} more opportunities")

        return "\n".join(lines)


# Module singleton
_DETECTOR: OpportunityDetector | None = None


def get_opportunity_detector() -> OpportunityDetector:
    """Get or create the global opportunity detector."""
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = OpportunityDetector()
    return _DETECTOR
