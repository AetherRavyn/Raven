"""Companion AI Connection — protocol for other AIs to connect to Raven.

FRIDAY-style: Tony's other systems (JARVIS, FRIDAY, suit AI) can
collaborate with Raven. This module defines the protocol for:

1. AI Discovery — find available companion AIs
2. AI Handshake — establish secure connection
3. Task Delegation — delegate work to companion AIs
4. Result Integration — merge results from multiple AIs
5. Shared Context — share relevant context between AIs

Like how JARVIS and FRIDAY work together in the MCU, Raven
can collaborate with Claude, GPT, Gemini, or any A2A-compatible AI.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from raven_protocol import AgentCard, Skill, Message, get_registry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompanionAI:
    """A connected companion AI."""
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    endpoint: str = ""  # HTTP endpoint or "in-process"
    auth_token: str = ""
    status: str = "disconnected"  # disconnected, connected, busy
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollaborationTask:
    """A task delegated to a companion AI."""
    task_id: str
    from_ai: str  # "raven"
    to_ai: str  # companion AI name
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


class CompanionManager:
    """Manages connections to companion AIs.

    FRIDAY-style: Raven can collaborate with other AIs to
    solve complex problems. Each companion AI exposes its
    capabilities via Agent Cards, and Raven can delegate
    tasks to the best-suited companion.
    """

    def __init__(self) -> None:
        self._companions: dict[str, CompanionAI] = {}
        self._tasks: dict[str, CollaborationTask] = {}
        self._task_counter = 0
        self._callbacks: list[Callable] = []

    def register_companion(self, companion: CompanionAI) -> None:
        """Register a companion AI."""
        self._companions[companion.name] = companion
        logger.info("Companion AI registered: %s — %s", companion.name, companion.description[:60])

    def disconnect_companion(self, name: str) -> bool:
        """Disconnect a companion AI."""
        if name in self._companions:
            self._companions[name].status = "disconnected"
            return True
        return False

    def get_companion(self, name: str) -> CompanionAI | None:
        return self._companions.get(name)

    def list_companions(self) -> list[CompanionAI]:
        return list(self._companions.values())

    def find_companion_for_task(self, task_description: str) -> CompanionAI | None:
        """Find the best companion AI for a task based on capabilities."""
        best = None
        best_score = 0

        for companion in self._companions.values():
            if companion.status != "connected":
                continue
            score = 0
            for cap in companion.capabilities:
                if cap.lower() in task_description.lower():
                    score += 2
            if score > best_score:
                best_score = score
                best = companion

        return best

    def delegate_task(
        self,
        to_ai: str,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> CollaborationTask:
        """Delegate a task to a companion AI."""
        self._task_counter += 1
        task = CollaborationTask(
            task_id=f"collab_{self._task_counter}",
            from_ai="raven",
            to_ai=to_ai,
            description=description,
            context=context or {},
        )
        self._tasks[task.task_id] = task
        logger.info("Task delegated to %s: %s", to_ai, description[:60])
        return task

    def complete_task(self, task_id: str, result: str) -> None:
        """Mark a collaboration task as completed."""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.status = "completed"
            task.result = result
            task.completed_at = datetime.now(timezone.utc).isoformat()

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a collaboration task as failed."""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.status = "failed"
            task.result = error
            task.completed_at = datetime.now(timezone.utc).isoformat()

    def get_tasks_for(self, ai_name: str) -> list[CollaborationTask]:
        """Get all tasks for a specific companion AI."""
        return [t for t in self._tasks.values() if t.to_ai == ai_name]

    def get_pending_tasks(self) -> list[CollaborationTask]:
        return [t for t in self._tasks.values() if t.status == "pending"]

    def get_completed_tasks(self) -> list[CollaborationTask]:
        return [t for t in self._tasks.values() if t.status == "completed"]

    def on_task_complete(self, callback: Callable) -> None:
        """Register a callback for task completion."""
        self._callbacks.append(callback)

    def get_collaboration_summary(self) -> dict[str, Any]:
        """Get a summary of all collaborations."""
        return {
            "total_companions": len(self._companions),
            "connected_companions": sum(1 for c in self._companions.values() if c.status == "connected"),
            "total_tasks": len(self._tasks),
            "pending_tasks": len(self.get_pending_tasks()),
            "completed_tasks": len(self.get_completed_tasks()),
        }


# Singleton
_companion_manager: CompanionManager | None = None


def get_companion_manager() -> CompanionManager:
    global _companion_manager
    if _companion_manager is None:
        _companion_manager = CompanionManager()
    return _companion_manager
