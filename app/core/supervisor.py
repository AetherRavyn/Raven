"""Hierarchical multi-agent supervisor — routes tasks to the best agent.

Architecture:
    AgentRegistry  — declares each agent's capabilities and specialties
    Supervisor     — receives incoming requests, picks the best agent, delegates
    WorkerPool     — manages concurrent agent execution with backpressure

This replaces the flat agent dispatch with a two-tier hierarchy:
    Supervisor (ConductorAgent)
      ├── PersonalAssistant  — general chat, casual conversation
      ├── HeraldAgent        — communications, messaging, scheduling
      ├── ResearcherAgent    — web research, fact-checking, deep dives
      ├── DeveloperAgent     — code generation, debugging, code review
      ├── FinanceAgent       — financial analysis, budgeting
      ├── HomeGuardianAgent  — home automation, IOT
      ├── SecurityAgent      — security analysis, threat detection
      ├── ArchivistAgent     — data management, organization
      ├── NegotiationAgent   — negotiation, persuasion
      ├── ReviewerAgent      — QA, validation, testing
      ├── NewsAgent          — news aggregation, summarization
      ├── PolymathAgent      — scientific analysis, cross-domain
      ├── ConscienceAgent    — ethical reasoning, moral checks
      └── SysadminAgent      — system administration, devops
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentCapability:
    """Declares what an agent can do."""

    agent_id: str
    agent_name: str
    specialties: list[str]  # ["coding", "research", "finance", ...]
    keywords: list[str]  # trigger words for routing
    priority: int = 0  # higher = preferred for overlapping matches


class AgentRegistry:
    """Registry of all available agents and their capabilities."""

    def __init__(self) -> None:
        self._capabilities: dict[str, AgentCapability] = {}

    def register(self, capability: AgentCapability) -> None:
        self._capabilities[capability.agent_id] = capability
        logger.debug("Supervisor registered: %s (%s)", capability.agent_id, capability.specialties)

    def register_all(self) -> None:
        """Register all built-in agents with their specialties."""
        self.register(
            AgentCapability(
                agent_id="assistant",
                agent_name="PersonalAssistant",
                specialties=["general", "chat", "casual"],
                keywords=["help", "hello", "general"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="herald",
                agent_name="HeraldAgent",
                specialties=["communications", "messaging", "scheduling"],
                keywords=["message", "email", "schedule", "remind", "meeting", "send"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="researcher",
                agent_name="ResearcherAgent",
                specialties=["research", "factcheck", "analysis"],
                keywords=[
                    "research",
                    "find",
                    "search",
                    "investigate",
                    "analyze",
                    "lookup",
                    "what is",
                    "explain",
                ],
            )
        )
        self.register(
            AgentCapability(
                agent_id="developer",
                agent_name="DeveloperAgent",
                specialties=["coding", "development", "debugging"],
                keywords=[
                    "code",
                    "write",
                    "program",
                    "debug",
                    "fix",
                    "implement",
                    "function",
                    "class",
                    "app",
                ],
            )
        )
        self.register(
            AgentCapability(
                agent_id="finance",
                agent_name="FinanceAgent",
                specialties=["finance", "budget", "investing"],
                keywords=["finance", "money", "budget", "invest", "stock", "cost", "price", "buy"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="homeguardian",
                agent_name="HomeGuardianAgent",
                specialties=["home", "iot", "automation"],
                keywords=["home", "iot", "device", "sensor", "light", "thermostat"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="security",
                agent_name="SecurityAgent",
                specialties=["security", "threat", "compliance"],
                keywords=[
                    "security",
                    "threat",
                    "vulnerability",
                    "vulnerabilities",
                    "attack",
                    "protect",
                    "encrypt",
                ],
            )
        )
        self.register(
            AgentCapability(
                agent_id="archivist",
                agent_name="ArchivistAgent",
                specialties=["data", "organization", "storage"],
                keywords=["organize", "file", "data", "archive", "store", "backup"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="reviewer",
                agent_name="ReviewerAgent",
                specialties=["qa", "testing", "validation"],
                keywords=["review", "test", "validate", "verify", "approve", "qa"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="news",
                agent_name="NewsAgent",
                specialties=["news", "current events"],
                keywords=["news", "latest", "headline", "current", "update on"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="polymath",
                agent_name="PolymathAgent",
                specialties=["science", "math", "crossdomain"],
                keywords=["science", "math", "physics", "biology", "chemistry", "theory"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="negotiation",
                agent_name="NegotiationAgent",
                specialties=["negotiation", "persuasion"],
                keywords=["negotiate", "deal", "offer", "bargain", "persuade"],
            )
        )
        self.register(
            AgentCapability(
                agent_id="sysadmin",
                agent_name="SysadminAgent",
                specialties=["devops", "system", "infrastructure"],
                keywords=["server", "deploy", "infra", "docker", "kubernetes", "config"],
            )
        )


class Supervisor:
    """Routes incoming requests to the best agent based on capabilities.

    Two-tier dispatch:
        1. Keyword match — if the request text contains keywords for a
           specialist agent, route there.
        2. Learning-based — if the learning store has a correction for this
           agent on a previous similar request, try the next best.
        3. Default — route to the general assistant.
    """

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or AgentRegistry()
        self._registry.register_all()

    def select_agent(self, text: str, context: dict[str, Any] | None = None) -> str:
        """Select the best agent ID for a given input text.

        Args:
            text: The user's input text.
            context: Optional dict with 'learning_hints' list to skip agents.

        Returns:
            Agent ID string (e.g. "researcher", "developer", "assistant").
        """
        text_lower = text.lower()
        skip_agents: list[str] = list(context.get("learning_hints", []) if context else [])

        # Check each agent's keywords for a match
        best_match: str | None = None
        best_score = 0

        for cap in self._registry._capabilities.values():
            if cap.agent_id in skip_agents:
                continue
            # Score by how many keywords match (word-boundary)
            match_count = sum(
                1 for kw in cap.keywords if re.search(r"\b" + re.escape(kw) + r"\b", text_lower)
            )
            score = match_count * 10 + cap.priority
            if match_count > 0 and score > best_score:
                best_match = cap.agent_id
                best_score = score

        if best_match:
            return best_match

        return "assistant"

    async def delegate(
        self,
        text: str,
        agents: dict[str, Any],
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Route a request to the selected agent and return its response.

        Args:
            text: The user's input text.
            agents: Dict of {agent_id: agent_instance} — all available agents.
            context: Optional routing context.

        Returns:
            dict with 'agent_id', 'response', and 'confidence'.
        """
        agent_id = self.select_agent(text, context)
        agent = agents.get(agent_id)
        if agent is None:
            agent_id = "assistant"
            agent = agents.get("assistant")

        if agent is None:
            return {"agent_id": None, "response": "No available agent.", "confidence": 0.0}

        try:
            result = await agent.run(text, **kwargs)
            return {"agent_id": agent_id, "response": result, "confidence": 1.0}
        except Exception as e:
            logger.error("Supervisor delegation to %s failed: %s", agent_id, e)
            # Fallback to assistant
            fallback = agents.get("assistant")
            if fallback and agent_id != "assistant":
                try:
                    result = await fallback.run(text, **kwargs)
                    return {"agent_id": "assistant", "response": result, "confidence": 0.5}
                except Exception:
                    pass
            return {"agent_id": agent_id, "response": f"Error: {e}", "confidence": 0.0}


# Global singleton
_supervisor: Supervisor | None = None


def get_supervisor() -> Supervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = Supervisor()
    return _supervisor
