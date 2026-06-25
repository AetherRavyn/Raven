"""Autonomous Action Engine — FRIDAY takes action without being asked.

Monitors events, triggers workflows, sends alerts, and executes
pre-approved actions based on learned patterns and rules.

Architecture:
  EventBus → EventClassifier → ActionPlanner → ActionExecutor → BotSignal

The engine runs in the ambient loop and:
  1. Listens for events (sensor readings, calendar changes, anomalies)
  2. Classifies events by urgency and type
  3. Plans appropriate actions (notify, execute workflow, adjust settings)
  4. Executes pre-approved actions or queues for user approval
  5. Reports results via BotSignal

Safety:
  - All actions have risk levels (low/medium/high)
  - Low-risk: auto-execute (send reminder, update memory)
  - Medium-risk: queue for approval (create calendar event, send message)
  - High-risk: always require approval (delete data, modify config)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"        # Auto-execute
    MEDIUM = "medium"  # Queue for approval
    HIGH = "high"      # Always require approval


class ActionType(str, Enum):
    NOTIFY = "notify"          # Send notification to user
    REMIND = "remind"          # Schedule a reminder
    UPDATE_MEMORY = "update_memory"  # Store a fact
    EXECUTE_WORKFLOW = "execute_workflow"  # Run a workflow
    ADJUST_SETTING = "adjust_setting"  # Change a config
    CREATE_EVENT = "create_event"  # Calendar event
    SEND_MESSAGE = "send_message"  # Send message to channel
    MONITOR = "monitor"        # Start monitoring something
    ALERT = "alert"            # Urgent alert


@dataclass(slots=True)
class AutonomousAction:
    """An action the engine plans to take."""
    action_type: ActionType
    risk_level: RiskLevel
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class Event:
    """An event that triggers autonomous action."""
    event_type: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.5  # 0.0 = ignore, 1.0 = critical
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EventClassifier:
    """Classifies events by type and urgency."""

    def classify(self, event: Event) -> tuple[str, float]:
        """Return (event_category, urgency_score)."""
        etype = event.event_type.lower()
        urgency = event.urgency

        if any(w in etype for w in ("anomaly", "intrusion", "security", "breach")):
            return "security", min(urgency + 0.3, 1.0)
        if any(w in etype for w in ("motion", "camera", "door", "window")):
            return "sensor", min(urgency + 0.1, 0.9)
        if any(w in etype for w in ("calendar", "meeting", "appointment")):
            return "schedule", min(urgency + 0.2, 0.8)
        if any(w in etype for w in ("weather", "temperature", "humidity")):
            return "environment", min(urgency + 0.1, 0.7)
        if any(w in etype for w in ("reminder", "deadline", "task")):
            return "task", min(urgency + 0.15, 0.8)
        if any(w in etype for w in ("error", "failure", "crash")):
            return "system", min(urgency + 0.2, 0.9)

        return "general", urgency


class ActionPlanner:
    """Plans appropriate actions based on classified events."""

    def __init__(self) -> None:
        self._rules: list[tuple[str, str, Callable]] = []

    def add_rule(
        self, event_category: str, pattern: str, planner_fn: Callable
    ) -> None:
        """Register a planning rule.

        planner_fn takes (event, category, urgency) and returns
        a list of AutonomousAction or None.
        """
        self._rules.append((event_category, pattern, planner_fn))

    def plan(self, event: Event, category: str, urgency: float) -> list[AutonomousAction]:
        """Plan actions for an event."""
        actions: list[AutonomousAction] = []

        for rule_cat, pattern, planner_fn in self._rules:
            if rule_cat == category or rule_cat == "*":
                if pattern in event.event_type or pattern == "*":
                    try:
                        result = planner_fn(event, category, urgency)
                        if result:
                            actions.extend(result if isinstance(result, list) else [result])
                    except Exception as exc:
                        logger.warning("Action planner rule failed: %s", exc)

        # Default action: log the event
        if not actions and urgency > 0.3:
            actions.append(AutonomousAction(
                action_type=ActionType.NOTIFY,
                risk_level=RiskLevel.LOW,
                description=f"Event: {event.event_type} from {event.source}",
                params={"text": f"[Auto] {event.event_type}: {json.dumps(event.data, default=str)[:200]}"},
                reason=f"Urgency {urgency:.1f} triggered notification",
            ))

        return actions


class ActionExecutor:
    """Executes planned actions based on risk level.

    FRIDAY-style: low-risk actions auto-execute, medium-risk
    can be auto-approved based on learned patterns, high-risk
    always require explicit approval.
    """

    def __init__(self, botsignal: Any = None) -> None:
        self._botsignal = botsignal
        self._pending_approvals: list[AutonomousAction] = []
        self._executed_log: list[dict[str, Any]] = []
        # Auto-approve patterns: actions matching these patterns are auto-approved
        self._auto_approve_patterns: set[str] = {
            "notify", "remind", "update_memory", "monitor",
        }

    async def execute(self, action: AutonomousAction, approval_callback: Any = None) -> bool:
        """Execute an action. Auto-execute low-risk, auto-approve known patterns."""
        if action.risk_level == RiskLevel.HIGH:
            self._pending_approvals.append(action)
            logger.info("HIGH risk action queued for approval: %s", action.description)
            return False

        if action.risk_level == RiskLevel.MEDIUM:
            # Check if this action type is in the auto-approve list
            if action.action_type.value in self._auto_approve_patterns:
                logger.info("Auto-approved MEDIUM risk action: %s", action.description)
            elif approval_callback:
                approved = await approval_callback(action)
                if not approved:
                    logger.info("MEDIUM risk action denied: %s", action.description)
                    return False
            else:
                self._pending_approvals.append(action)
                return False

        # Low risk: auto-execute
        try:
            await self._do_action(action)
            self._executed_log.append({
                "action": action.action_type.value,
                "description": action.description,
                "risk": action.risk_level.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": True,
            })
            return True
        except Exception as exc:
            logger.error("Action execution failed: %s — %s", action.description, exc)
            self._executed_log.append({
                "action": action.action_type.value,
                "description": action.description,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": False,
            })
            return False

    async def _do_action(self, action: AutonomousAction) -> None:
        """Dispatch action to the appropriate handler."""
        if action.action_type == ActionType.NOTIFY:
            text = action.params.get("text", action.description)
            if self._botsignal:
                from app.core.models import ReplyTarget
                target = ReplyTarget(platform="web", chat_id="main")
                await self._botsignal.send_text(target, text)

        elif action.action_type == ActionType.UPDATE_MEMORY:
            from app.core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            facade.remember(
                action.params.get("content", action.description),
                user_id=action.params.get("user_id"),
                category=action.params.get("category", "FACT"),
            )

        elif action.action_type == ActionType.REMIND:
            # Schedule a reminder via the scheduler
            from app.core.proactive import schedule_follow_up
            schedule_follow_up(
                text=action.params.get("text", action.description),
                delay_minutes=action.params.get("delay_minutes", 30),
            )

    def get_pending(self) -> list[AutonomousAction]:
        return list(self._pending_approvals)

    def approve(self, index: int) -> AutonomousAction | None:
        if 0 <= index < len(self._pending_approvals):
            return self._pending_approvals.pop(index)
        return None

    def deny(self, index: int) -> bool:
        if 0 <= index < len(self._pending_approvals):
            self._pending_approvals.pop(index)
            return True
        return False

    def get_log(self) -> list[dict[str, Any]]:
        return list(self._executed_log)


class AutonomousActionEngine:
    """FRIDAY's autonomous action engine.

    Combines event classification, action planning, and execution.
    Runs in the ambient loop to monitor events continuously.
    """

    def __init__(self, botsignal: Any = None) -> None:
        self.classifier = EventClassifier()
        self.planner = ActionPlanner()
        self.executor = ActionExecutor(botsignal)
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Register default action planning rules."""
        # Security events → alert
        self.planner.add_rule("security", "*", lambda e, c, u: [
            AutonomousAction(
                action_type=ActionType.ALERT,
                risk_level=RiskLevel.HIGH,
                description=f"Security alert: {e.event_type}",
                params={"text": f"🚨 Security: {e.event_type} — {json.dumps(e.data, default=str)[:200]}"},
                reason="Security events always alert",
            )
        ])

        # Sensor events → notify if urgent
        self.planner.add_rule("sensor", "motion", lambda e, c, u: [
            AutonomousAction(
                action_type=ActionType.NOTIFY,
                risk_level=RiskLevel.LOW,
                description=f"Motion detected: {e.source}",
                params={"text": f"📷 Motion detected at {e.source}"},
                reason="Sensor alert",
            )
        ] if u > 0.5 else None)

        # Schedule events → remind
        self.planner.add_rule("schedule", "meeting", lambda e, c, u: [
            AutonomousAction(
                action_type=ActionType.REMIND,
                risk_level=RiskLevel.LOW,
                description=f"Upcoming: {e.data.get('title', 'meeting')}",
                params={
                    "text": f"Meeting coming up: {e.data.get('title', 'unknown')}",
                    "delay_minutes": e.data.get("minutes_until", 5),
                },
                reason="Proactive meeting reminder",
            )
        ])

        # Task deadlines → remind
        self.planner.add_rule("task", "deadline", lambda e, c, u: [
            AutonomousAction(
                action_type=ActionType.NOTIFY,
                risk_level=RiskLevel.LOW,
                description=f"Deadline approaching: {e.data.get('task', 'unknown')}",
                params={"text": f"⏰ Deadline: {e.data.get('task', 'task')} — due {e.data.get('due', 'soon')}"},
                reason="Deadline reminder",
            )
        ])

    async def process_event(self, event: Event, approval_callback: Any = None) -> list[bool]:
        """Process an event: classify → plan → execute."""
        category, urgency = self.classifier.classify(event)
        actions = self.planner.plan(event, category, urgency)

        results = []
        for action in actions:
            success = await self.executor.execute(action, approval_callback)
            results.append(success)

        return results

    def get_pending_actions(self) -> list[AutonomousAction]:
        return self.executor.get_pending()

    def get_execution_log(self) -> list[dict[str, Any]]:
        return self.executor.get_log()
