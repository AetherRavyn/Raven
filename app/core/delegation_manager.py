"""Cross-Agent Task Delegation — agents delegate sub-tasks to each other.

FRIDAY-style: Agent A can ask Agent B to do a specific part
of its work, then integrate the results.

This creates a hierarchy of specialized agents working together:
- Manager Agent decomposes the task
- Specialist Agents execute sub-tasks
- Each specialist can delegate further if needed
- Results are collected and synthesized

Unlike the current flat swarm (all agents run in parallel),
this enables recursive delegation with shared context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskDelegation:
    """A task delegation from one agent to another."""
    delegation_id: str
    from_agent: str
    to_agent: str
    task_description: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


@dataclass(slots=True)
class SharedWorkingMemory:
    """Shared state between collaborating agents."""
    session_id: str
    entries: dict[str, Any] = field(default_factory=dict)
    participants: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DelegationManager:
    """Manages cross-agent task delegations.

    Enables agents to:
    1. Request help from other agents
    2. Share working memory during collaboration
    3. Track delegation chains
    4. Synthesize results from delegated tasks
    """

    def __init__(self) -> None:
        self._delegations: dict[str, TaskDelegation] = {}
        self._shared_memory: dict[str, SharedWorkingMemory] = {}
        self._delegation_counter = 0

    def create_delegation(
        self,
        from_agent: str,
        to_agent: str,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> TaskDelegation:
        """Create a new task delegation."""
        self._delegation_counter += 1
        delegation = TaskDelegation(
            delegation_id=f"del_{self._delegation_counter}",
            from_agent=from_agent,
            to_agent=to_agent,
            task_description=task_description,
            context=context or {},
        )
        self._delegations[delegation.delegation_id] = delegation
        logger.info("Delegation created: %s → %s: %s", from_agent, to_agent, task_description[:60])
        return delegation

    def execute_delegation(self, delegation_id: str) -> None:
        """Mark a delegation as running."""
        if delegation_id in self._delegations:
            self._delegations[delegation_id].status = "running"

    def complete_delegation(self, delegation_id: str, result: str) -> None:
        """Mark a delegation as completed with result."""
        if delegation_id in self._delegations:
            d = self._delegations[delegation_id]
            d.status = "completed"
            d.result = result
            d.completed_at = datetime.now(timezone.utc).isoformat()

    def fail_delegation(self, delegation_id: str, error: str) -> None:
        """Mark a delegation as failed."""
        if delegation_id in self._delegations:
            d = self._delegations[delegation_id]
            d.status = "failed"
            d.result = error
            d.completed_at = datetime.now(timezone.utc).isoformat()

    def get_pending_for(self, agent_name: str) -> list[TaskDelegation]:
        """Get all pending delegations for a specific agent."""
        return [
            d for d in self._delegations.values()
            if d.to_agent == agent_name and d.status == "pending"
        ]

    def get_delegations_by(self, agent_name: str) -> list[TaskDelegation]:
        """Get all delegations initiated by a specific agent."""
        return [
            d for d in self._delegations.values()
            if d.from_agent == agent_name
        ]

    # ── Shared Working Memory ─────────────────────────────────────

    def create_shared_memory(self, session_id: str, participants: list[str]) -> SharedWorkingMemory:
        """Create shared working memory for a collaboration."""
        memory = SharedWorkingMemory(
            session_id=session_id,
            participants=participants,
        )
        self._shared_memory[session_id] = memory
        return memory

    def write_to_shared(self, session_id: str, key: str, value: Any, agent: str) -> None:
        """Write to shared working memory."""
        if session_id in self._shared_memory:
            memory = self._shared_memory[session_id]
            memory.entries[key] = {
                "value": value,
                "written_by": agent,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def read_from_shared(self, session_id: str, key: str) -> Any | None:
        """Read from shared working memory."""
        if session_id in self._shared_memory:
            entry = self._shared_memory[session_id].entries.get(key)
            if entry:
                return entry.get("value")
        return None

    def get_shared_memory(self, session_id: str) -> dict[str, Any]:
        """Get all entries from shared working memory."""
        if session_id in self._shared_memory:
            return {k: v.get("value") for k, v in self._shared_memory[session_id].entries.items()}
        return {}

    def get_delegation_chain(self, delegation_id: str) -> list[TaskDelegation]:
        """Get the full delegation chain for a task."""
        chain = []
        current_id = delegation_id
        while current_id:
            d = self._delegations.get(current_id)
            if not d:
                break
            chain.append(d)
            # Find the originating delegation (if this was delegated from another)
            for del_id, del_obj in self._delegations.items():
                if del_obj.to_agent == d.from_agent and del_obj.status == "running":
                    current_id = del_id
                    break
            else:
                break
        return list(reversed(chain))


# Singleton
_delegation_manager: DelegationManager | None = None


def get_delegation_manager() -> DelegationManager:
    global _delegation_manager
    if _delegation_manager is None:
        _delegation_manager = DelegationManager()
    return _delegation_manager
