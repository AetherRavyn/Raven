"""Negotiation Protocol — Structured agent debate for disagreement resolution.

When multiple specialist agents are candidates for a task or disagree on
an approach, this protocol runs a structured multi-round debate to reach
consensus or escalate to the operator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Position:
    """An agent's position in a debate."""

    agent_name: str
    stance: str        # The agent's proposed approach
    reasoning: str     # Why they believe this approach
    confidence: float  # 0.0 to 1.0
    round_num: int = 0


@dataclass(slots=True)
class Critique:
    """An agent's critique of another agent's position."""

    critic_name: str
    target_name: str
    critique: str
    agreement_level: float  # 0.0 (strongly disagree) to 1.0 (fully agree)
    round_num: int = 0


@dataclass
class DebateResult:
    """Outcome of a structured debate."""

    topic: str
    rounds_completed: int
    consensus_reached: bool
    winning_position: Position | None = None
    positions: list[Position] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    final_recommendation: str = ""
    escalated: bool = False
    summary: str = ""


class NegotiationProtocol:
    """Manages structured debates between specialist agents.

    Debate structure:
    1. **Round 1 — Propose**: Each agent presents their position
    2. **Round 2 — Critique**: Agents critique each other's positions
    3. **Round 3 — Revise**: Agents revise or defend their positions
    4. **Resolution**: Highest-confidence position wins, or escalate

    Usage:
        protocol = NegotiationProtocol()
        result = protocol.resolve(
            topic="Which deployment strategy to use?",
            positions=[
                Position(agent_name="DevAgent", stance="Blue-green", ...),
                Position(agent_name="SysadminAgent", stance="Canary", ...),
            ],
        )
    """

    def __init__(
        self,
        consensus_threshold: float = 0.7,
        max_rounds: int = 3,
    ) -> None:
        self._consensus_threshold = consensus_threshold
        self._max_rounds = max_rounds

    def resolve(
        self,
        topic: str,
        positions: list[Position],
        critiques: list[Critique] | None = None,
    ) -> DebateResult:
        """Run the full negotiation protocol.

        For now this uses a confidence-weighted scoring system.
        Future: integrate with LLM for actual debate rounds.
        """
        if not positions:
            return DebateResult(
                topic=topic,
                rounds_completed=0,
                consensus_reached=False,
                summary="No positions to debate.",
            )

        if len(positions) == 1:
            return DebateResult(
                topic=topic,
                rounds_completed=0,
                consensus_reached=True,
                winning_position=positions[0],
                positions=positions,
                final_recommendation=positions[0].stance,
                summary=f"Single position from {positions[0].agent_name}: {positions[0].stance}",
            )

        critiques = critiques or []

        # Score each position
        scores = self._score_positions(positions, critiques)

        # Check for consensus
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        best_agent, best_score = sorted_scores[0]
        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

        consensus = (best_score - second_score) >= 0.15 or best_score >= self._consensus_threshold

        # Find winning position
        winner = next(p for p in positions if p.agent_name == best_agent)

        # Determine if escalation is needed
        escalated = not consensus and best_score < 0.5

        # Build summary
        summary_lines = [f"Topic: {topic}"]
        for agent, score in sorted_scores:
            pos = next(p for p in positions if p.agent_name == agent)
            summary_lines.append(f"  {agent}: {pos.stance} (score: {score:.2f})")
        if consensus:
            summary_lines.append(f"Consensus: {winner.agent_name}'s approach wins")
        else:
            summary_lines.append("No consensus — escalating to operator")

        return DebateResult(
            topic=topic,
            rounds_completed=min(self._max_rounds, len(set(p.round_num for p in positions))),
            consensus_reached=consensus,
            winning_position=winner,
            positions=positions,
            critiques=critiques,
            final_recommendation=winner.stance if consensus else "",
            escalated=escalated,
            summary="\n".join(summary_lines),
        )

    def _score_positions(
        self,
        positions: list[Position],
        critiques: list[Critique],
    ) -> dict[str, float]:
        """Score positions based on confidence and peer critiques."""
        scores: dict[str, float] = {}

        for pos in positions:
            base_score = pos.confidence

            # Apply critique adjustments
            pos_critiques = [c for c in critiques if c.target_name == pos.agent_name]
            if pos_critiques:
                avg_agreement = sum(c.agreement_level for c in pos_critiques) / len(pos_critiques)
                # Peer agreement boosts the score
                critique_adjustment = (avg_agreement - 0.5) * 0.3
                base_score += critique_adjustment

            scores[pos.agent_name] = max(0.0, min(1.0, base_score))

        return scores

    def format_debate(self, result: DebateResult) -> str:
        """Format a debate result as readable text."""
        lines: list[str] = [f"## 🗣️ Agent Debate: {result.topic}\n"]

        for pos in result.positions:
            lines.append(f"### {pos.agent_name} (confidence: {pos.confidence:.0%})")
            lines.append(f"**Stance**: {pos.stance}")
            lines.append(f"**Reasoning**: {pos.reasoning}")
            lines.append("")

        if result.critiques:
            lines.append("### Critiques")
            for crit in result.critiques:
                lines.append(
                    f"- {crit.critic_name} → {crit.target_name}: "
                    f"{crit.critique} (agreement: {crit.agreement_level:.0%})"
                )
            lines.append("")

        if result.consensus_reached and result.winning_position:
            lines.append(f"### ✅ Consensus: {result.winning_position.agent_name}")
            lines.append(f"**Approach**: {result.final_recommendation}")
        elif result.escalated:
            lines.append("### ⚠️ No Consensus — Escalated to Operator")
        else:
            lines.append("### 🔄 No Clear Consensus")

        return "\n".join(lines)


class NegotiationAgent:
    """Agent that runs structured debates between specialist agents."""

    name = "NegotiationAgent"
    soul = "I facilitate structured debates between agents to reach consensus."

    def __init__(self):
        self.protocol = NegotiationProtocol()

    def resolve(self, task: str, agent_positions: list[tuple[str, str]], max_rounds: int = 3):
        """Run a negotiation between agents with given positions."""
        positions = [
            Position(agent_name=name, stance=stance, confidence=0.7)
            for name, stance in agent_positions
        ]
        return self.protocol.run_debate(task, positions, max_rounds)
