"""Social Simulator — Multi-agent stakeholder simulation for scenario analysis.

Models stakeholder behavior, interactions, and emergent dynamics using lightweight
agent-based modeling. Not thousands of agents - just tens of key stakeholders
with defined interests, influence, and relationships.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StakeholderAgent:
    """A stakeholder in the social simulation."""
    agent_id: str
    name: str
    role: str  # decision_maker, influencer, affected_party, regulator, competitor
    interests: list[str] = field(default_factory=list)  # What they care about
    goals: list[str] = field(default_factory=list)      # What they want to achieve
    influence: float = 0.5          # 0-1: ability to affect outcomes
    resources: float = 0.5          # 0-1: money, authority, information access
    risk_tolerance: float = 0.5     # 0-1: willingness to take risks
    time_horizon: str = "medium"    # short, medium, long
    beliefs: dict[str, float] = field(default_factory=dict)  # claim -> certainty (-1 to 1)
    relationships: dict[str, float] = field(default_factory=dict)  # other_id -> affinity (-1 to 1)
    personality: dict[str, float] = field(default_factory=dict)  # Big Five traits
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Interaction:
    """An interaction between stakeholders."""
    interaction_id: str
    source_id: str
    target_id: str
    interaction_type: str  # negotiate, coerce, cooperate, compete, inform, threaten
    topic: str
    outcome: str = ""  # agreement, disagreement, compromise, deferred
    influence_exchanged: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class SimulationResult:
    """Result of a social simulation run."""
    simulation_id: str
    scenario_context: str
    rounds: int
    final_positions: dict[str, dict[str, Any]]  # agent_id -> {topic: position}
    coalitions: list[list[str]]  # Groups of aligned agents
    conflicts: list[tuple[str, str, str]]  # (agent1, agent2, topic)
    key_decisions: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    metrics: dict[str, float]
    simulated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SocialSimulator:
    """Lightweight agent-based social simulation for scenario analysis.
    
    Simulates 10-50 key stakeholders over 5-20 rounds.
    Focus: coalition formation, conflict dynamics, decision cascades.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "prediction" / "social_sim"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._agents_file = self._dir / "agents.json"
        self._interactions_file = self._dir / "interactions.jsonl"
        self._results_file = self._dir / "results.jsonl"
        
        self._agents: dict[str, StakeholderAgent] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._agents_file.exists():
                data = json.loads(self._agents_file.read_text(encoding="utf-8"))
                self._agents = {k: StakeholderAgent(**v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Failed to load agents: %s", e)

    def _save(self) -> None:
        try:
            self._agents_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._agents.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save agents: %s", e)

    # ── Agent Management ──────────────────────────────────────────

    def add_agent(self, agent: StakeholderAgent) -> str:
        self._agents[agent.agent_id] = agent
        self._save()
        return agent.agent_id

    def get_agent(self, agent_id: str) -> StakeholderAgent | None:
        return self._agents.get(agent_id)

    def list_agents(self, role: str | None = None) -> list[StakeholderAgent]:
        agents = list(self._agents.values())
        if role:
            agents = [a for a in agents if a.role == role]
        return agents

    def create_stakeholder_from_entity(
        self,
        entity_name: str,
        role: str,
        interests: list[str],
        influence: float = 0.5
    ) -> StakeholderAgent:
        """Factory method to create a stakeholder from a world model entity."""
        return StakeholderAgent(
            agent_id=f"agent_{uuid.uuid4().hex[:8]}",
            name=entity_name,
            role=role,
            interests=interests,
            goals=[f"Advance {i}" for i in interests],
            influence=influence,
            resources=influence * 0.8,
            risk_tolerance=random.uniform(0.3, 0.7),
            time_horizon=random.choice(["short", "medium", "long"]),
            personality={
                "openness": random.uniform(0.3, 0.8),
                "conscientiousness": random.uniform(0.3, 0.8),
                "extraversion": random.uniform(0.3, 0.8),
                "agreeableness": random.uniform(0.3, 0.8),
                "neuroticism": random.uniform(0.2, 0.6),
            }
        )

    # ── Simulation ────────────────────────────────────────────────

    def run_simulation(
        self,
        scenario_context: str,
        focal_topic: str,
        agents: list[StakeholderAgent] | None = None,
        rounds: int = 10,
        interaction_probability: float = 0.3
    ) -> SimulationResult:
        """Run a social simulation around a focal topic."""
        if agents is None:
            agents = list(self._agents.values())[:15]  # Cap at 15 for performance
        
        if len(agents) < 2:
            raise ValueError("Need at least 2 agents for simulation")
        
        # Initialize positions on focal topic
        positions = {}
        for agent in agents:
            # Position: -1 (strongly against) to 1 (strongly for)
            # Influenced by interests, beliefs, personality
            base = 0.0
            for interest in agent.interests:
                if interest.lower() in focal_topic.lower():
                    base += 0.3
            for belief_topic, certainty in agent.beliefs.items():
                if belief_topic.lower() in focal_topic.lower():
                    base += certainty * 0.2
            # Add personality influence
            base += (agent.personality.get("openness", 0.5) - 0.5) * 0.2
            base += (agent.personality.get("agreeableness", 0.5) - 0.5) * 0.1
            positions[agent.agent_id] = max(-1.0, min(1.0, base + random.uniform(-0.2, 0.2)))
        
        timeline = []
        interactions_log = []
        coalitions_history = []
        
        for round_num in range(rounds):
            round_interactions = []
            
            # Pairwise interactions
            for i, agent_a in enumerate(agents):
                for agent_b in agents[i+1:]:
                    if random.random() > interaction_probability:
                        continue
                    
                    interaction = self._simulate_interaction(
                        agent_a, agent_b, focal_topic, positions
                    )
                    round_interactions.append(interaction)
                    interactions_log.append(interaction)
            
            # Update positions based on interactions
            for interaction in round_interactions:
                self._update_positions(interaction, positions, agents)
            
            # Detect coalitions (agents with similar positions)
            coalitions = self._detect_coalitions(agents, positions, focal_topic)
            coalitions_history.append(coalitions)
            
            # Record timeline
            timeline.append({
                "round": round_num,
                "positions": positions.copy(),
                "interactions": len(round_interactions),
                "coalitions": [[a.name for a in c] for c in coalitions],
                "avg_position": sum(positions.values()) / len(positions)
            })
        
        # Final analysis
        final_positions = {}
        for agent in agents:
            final_positions[agent.agent_id] = {
                "name": agent.name,
                "role": agent.role,
                "position": positions[agent.agent_id],
                "influence": agent.influence,
                "interests": agent.interests
            }
        
        # Detect conflicts
        conflicts = []
        for agent_a in agents:
            for agent_b in agents:
                if agent_a.agent_id >= agent_b.agent_id:
                    continue
                pos_diff = abs(positions[agent_a.agent_id] - positions[agent_b.agent_id])
                if pos_diff > 0.7:  # Strong disagreement
                    conflicts.append((agent_a.name, agent_b.name, focal_topic))
        
        # Key decisions (coalitions that formed)
        key_decisions = []
        for coalition in coalitions_history[-1]:
            if len(coalition) >= 2:
                avg_pos = sum(positions[a.agent_id] for a in coalition) / len(coalition)
                key_decisions.append({
                    "coalition": [a.name for a in coalition],
                    "position": avg_pos,
                    "combined_influence": sum(a.influence for a in coalition),
                    "topic": focal_topic
                })
        
        # Metrics
        metrics = {
            "polarization": max(positions.values()) - min(positions.values()),
            "consensus": 1.0 - (sum(abs(p - sum(positions.values())/len(positions)) for p in positions.values()) / len(positions)),
            "num_coalitions": len(coalitions_history[-1]),
            "num_conflicts": len(conflicts),
            "total_interactions": len(interactions_log),
            "influence_concentration": max(a.influence for a in agents) / sum(a.influence for a in agents)
        }
        
        result = SimulationResult(
            simulation_id=f"sim_{uuid.uuid4().hex[:8]}",
            scenario_context=scenario_context,
            rounds=rounds,
            final_positions=final_positions,
            coalitions=[[a.name for a in c] for c in coalitions_history[-1]],
            conflicts=conflicts,
            key_decisions=key_decisions,
            timeline=timeline,
            metrics=metrics
        )
        
        # Save
        with open(self._interactions_file, "a", encoding="utf-8") as f:
            for inter in interactions_log:
                f.write(json.dumps(asdict(inter), ensure_ascii=False) + "\n")
        with open(self._results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        
        return result

    def _simulate_interaction(
        self,
        agent_a: StakeholderAgent,
        agent_b: StakeholderAgent,
        topic: str,
        positions: dict[str, float]
    ) -> Interaction:
        """Simulate a single interaction between two agents."""
        pos_a = positions[agent_a.agent_id]
        pos_b = positions[agent_b.agent_id]
        pos_diff = abs(pos_a - pos_b)
        
        # Determine interaction type based on positions and relationship
        affinity = agent_a.relationships.get(agent_b.agent_id, 0.0)
        
        if pos_diff < 0.3 and affinity > 0:
            interaction_type = "cooperate"
        elif pos_diff > 0.7 and affinity < 0:
            interaction_type = "compete"
        elif agent_a.influence > agent_b.influence * 1.5:
            interaction_type = "coerce"
        elif agent_b.influence > agent_a.influence * 1.5:
            interaction_type = "coerce"  # b coerces a
        elif affinity > 0.3:
            interaction_type = "negotiate"
        else:
            interaction_type = "inform"
        
        # Determine outcome
        if interaction_type == "cooperate":
            outcome = "agreement"
            influence_exchanged = 0.1 * affinity
        elif interaction_type == "compete":
            outcome = "disagreement"
            influence_exchanged = -0.05
        elif interaction_type == "coerce":
            # Stronger pulls weaker
            if agent_a.influence > agent_b.influence:
                outcome = "concession"
                influence_exchanged = 0.15
            else:
                outcome = "concession"
                influence_exchanged = -0.15
        elif interaction_type == "negotiate":
            outcome = "compromise" if pos_diff < 0.6 else "disagreement"
            influence_exchanged = 0.05 if outcome == "compromise" else -0.02
        else:  # inform
            outcome = "information_shared"
            influence_exchanged = 0.02
        
        # Update relationship
        if outcome in ("agreement", "compromise"):
            agent_a.relationships[agent_b.agent_id] = min(1.0, affinity + 0.05)
            agent_b.relationships[agent_a.agent_id] = min(1.0, agent_b.relationships.get(agent_a.agent_id, 0.0) + 0.05)
        elif outcome in ("disagreement", "concession"):
            agent_a.relationships[agent_b.agent_id] = max(-1.0, affinity - 0.05)
            agent_b.relationships[agent_a.agent_id] = max(-1.0, agent_b.relationships.get(agent_a.agent_id, 0.0) - 0.05)
        
        return Interaction(
            interaction_id=f"inter_{uuid.uuid4().hex[:8]}",
            source_id=agent_a.agent_id,
            target_id=agent_b.agent_id,
            interaction_type=interaction_type,
            topic=topic,
            outcome=outcome,
            influence_exchanged=influence_exchanged
        )

    def _update_positions(
        self,
        interaction: Interaction,
        positions: dict[str, float],
        agents: list[StakeholderAgent]
    ) -> None:
        """Update agent positions based on interaction outcome."""
        agent_a = next(a for a in agents if a.agent_id == interaction.source_id)
        agent_b = next(a for a in agents if a.agent_id == interaction.target_id)
        
        pos_a = positions[agent_a.agent_id]
        pos_b = positions[agent_b.agent_id]
        
        if interaction.outcome == "agreement":
            # Move toward each other
            mid = (pos_a + pos_b) / 2
            positions[agent_a.agent_id] = pos_a + (mid - pos_a) * 0.3
            positions[agent_b.agent_id] = pos_b + (mid - pos_b) * 0.3
        elif interaction.outcome == "compromise":
            mid = (pos_a + pos_b) / 2
            positions[agent_a.agent_id] = pos_a + (mid - pos_a) * 0.2
            positions[agent_b.agent_id] = pos_b + (mid - pos_b) * 0.2
        elif interaction.outcome == "concession":
            # Weaker moves toward stronger
            if agent_a.influence > agent_b.influence:
                positions[agent_b.agent_id] = pos_b + (pos_a - pos_b) * 0.2
            else:
                positions[agent_a.agent_id] = pos_a + (pos_b - pos_a) * 0.2
        elif interaction.outcome == "disagreement":
            # Polarize slightly
            if pos_a > pos_b:
                positions[agent_a.agent_id] = min(1.0, pos_a + 0.05)
                positions[agent_b.agent_id] = max(-1.0, pos_b - 0.05)
            else:
                positions[agent_a.agent_id] = max(-1.0, pos_a - 0.05)
                positions[agent_b.agent_id] = min(1.0, pos_b + 0.05)

    def _detect_coalitions(
        self,
        agents: list[StakeholderAgent],
        positions: dict[str, float],
        topic: str
    ) -> list[list[StakeholderAgent]]:
        """Detect coalitions of agents with aligned positions."""
        # Group by position similarity
        coalitions = []
        used = set()
        
        for agent in agents:
            if agent.agent_id in used:
                continue
            coalition = [agent]
            used.add(agent.agent_id)
            
            for other in agents:
                if other.agent_id in used:
                    continue
                if abs(positions[agent.agent_id] - positions[other.agent_id]) < 0.3:
                    # Check relationship affinity
                    affinity = agent.relationships.get(other.agent_id, 0.0)
                    if affinity > -0.3:  # Not actively hostile
                        coalition.append(other)
                        used.add(other.agent_id)
            
            if len(coalition) >= 2:
                coalitions.append(coalition)
        
        return coalitions

    # ── Analysis Helpers ──────────────────────────────────────────

    def analyze_power_dynamics(self) -> dict[str, Any]:
        """Analyze power structure among agents."""
        agents = list(self._agents.values())
        if not agents:
            return {}
        
        total_influence = sum(a.influence for a in agents)
        total_resources = sum(a.resources for a in agents)
        
        # Find most influential
        most_influential = max(agents, key=lambda a: a.influence)
        
        # Find potential kingmakers (high influence, moderate position)
        kingmakers = [a for a in agents if a.influence > 0.6 and a.resources > 0.5]
        
        # Find swing voters (moderate influence, flexible)
        swing = [a for a in agents if 0.3 < a.influence < 0.6 and a.personality.get("openness", 0.5) > 0.6]
        
        return {
            "total_agents": len(agents),
            "total_influence": total_influence,
            "total_resources": total_resources,
            "most_influential": {"name": most_influential.name, "influence": most_influential.influence},
            "kingmakers": [{"name": a.name, "influence": a.influence, "resources": a.resources} for a in kingmakers],
            "swing_voters": [{"name": a.name, "influence": a.influence} for a in swing],
            "by_role": {role: len([a for a in agents if a.role == role]) for role in set(a.role for a in agents)}
        }