"""Scenario Engine — Generates and evaluates alternative futures.

Uses the causal event graph to create structured scenarios (baseline, optimistic,
pessimistic, adversarial, black-swan) and runs lightweight simulations.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.prediction.event_graph import CausalEventGraph, GraphNode, GraphEdge

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Scenario:
    """A structured scenario representing a possible future."""
    scenario_id: str
    name: str
    scenario_type: str  # baseline, optimistic, pessimistic, adversarial, black_swan
    description: str
    assumptions: list[str] = field(default_factory=list)
    initial_conditions: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)  # [{time, events, state_changes}]
    probability: float = 0.0
    confidence: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SimulationResult:
    """Result of running a scenario simulation."""
    scenario_id: str
    final_state: dict[str, Any]
    key_outcomes: list[dict[str, Any]]
    trajectory: list[dict[str, Any]]  # Time-series of state
    risk_factors: list[str]
    opportunities: list[str]
    confidence: float
    simulated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class Stakeholder:
    """A stakeholder agent for social simulation."""
    stakeholder_id: str
    name: str
    role: str
    interests: list[str]
    influence: float  # 0-1
    risk_tolerance: float  # 0-1
    relationships: dict[str, float]  # other_id -> affinity (-1 to 1)
    beliefs: dict[str, float]  # claim -> belief strength


class ScenarioEngine:
    """Generates and simulates scenarios using the causal event graph."""

    def __init__(
        self, 
        event_graph: CausalEventGraph,
        workspace_dir: str = "workspace"
    ) -> None:
        self.graph = event_graph
        self._dir = Path(workspace_dir) / "prediction" / "scenarios"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._scenarios_file = self._dir / "scenarios.json"
        self._results_file = self._dir / "results.jsonl"
        self._stakeholders_file = self._dir / "stakeholders.json"
        
        self._scenarios: dict[str, Scenario] = {}
        self._stakeholders: dict[str, Stakeholder] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._scenarios_file.exists():
                data = json.loads(self._scenarios_file.read_text(encoding="utf-8"))
                self._scenarios = {k: Scenario(**v) for k, v in data.items()}
            if self._stakeholders_file.exists():
                data = json.loads(self._stakeholders_file.read_text(encoding="utf-8"))
                self._stakeholders = {k: Stakeholder(**v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Failed to load scenarios: %s", e)

    def _save(self) -> None:
        try:
            self._scenarios_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._scenarios.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self._stakeholders_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._stakeholders.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save scenarios: %s", e)

    # ── Stakeholder Management ────────────────────────────────────

    def add_stakeholder(self, stakeholder: Stakeholder) -> str:
        self._stakeholders[stakeholder.stakeholder_id] = stakeholder
        self._save()
        return stakeholder.stakeholder_id

    def get_stakeholder(self, stakeholder_id: str) -> Stakeholder | None:
        return self._stakeholders.get(stakeholder_id)

    def list_stakeholders(self) -> list[Stakeholder]:
        return list(self._stakeholders.values())

    # ── Scenario Generation ────────────────────────────────────────

    def generate_scenarios(
        self,
        focal_event_id: str,
        time_horizon_days: int = 30,
        num_stakeholders: int = 5
    ) -> list[Scenario]:
        """Generate a set of scenarios around a focal event/node."""
        focal_node = self.graph.get_node(focal_event_id)
        if not focal_node:
            raise ValueError(f"Focal node {focal_event_id} not found")

        scenarios = []
        
        # 1. Baseline - most likely continuation
        scenarios.append(self._create_baseline_scenario(
            focal_node, time_horizon_days
        ))
        
        # 2. Optimistic - positive outcomes amplified
        scenarios.append(self._create_optimistic_scenario(
            focal_node, time_horizon_days
        ))
        
        # 3. Pessimistic - negative outcomes amplified
        scenarios.append(self._create_pessimistic_scenario(
            focal_node, time_horizon_days
        ))
        
        # 4. Adversarial - stakeholder conflict scenario
        if self._stakeholders:
            scenarios.append(self._create_adversarial_scenario(
                focal_node, time_horizon_days
            ))
        
        # 5. Black Swan - low probability, high impact
        scenarios.append(self._create_black_swan_scenario(
            focal_node, time_horizon_days
        ))

        # Save all
        for s in scenarios:
            self._scenarios[s.scenario_id] = s
        self._save()
        
        return scenarios

    def _create_baseline_scenario(
        self, focal: GraphNode, horizon_days: int
    ) -> Scenario:
        # Propagate impact from focal node through causal graph
        impacts = self.graph.propagate_impact(focal.node_id, max_depth=3)
        
        timeline = []
        for day in range(0, horizon_days + 1, max(1, horizon_days // 5)):
            events = []
            for node_id, impact in impacts.items():
                if impact > 0.3:
                    node = self.graph.get_node(node_id)
                    if node:
                        events.append({
                            "node_id": node_id,
                            "label": node.label,
                            "impact": round(impact, 3),
                            "type": node.node_type
                        })
            if events:
                timeline.append({
                    "day": day,
                    "events": sorted(events, key=lambda e: -e["impact"])[:5]
                })
        
        return Scenario(
            scenario_id=f"scenario_{uuid.uuid4().hex[:8]}",
            name=f"Baseline: {focal.label}",
            scenario_type="baseline",
            description=f"Most likely continuation from {focal.label} based on current causal pathways",
            assumptions=[
                "Current causal relationships hold",
                "No major external shocks",
                "Stakeholders act in character"
            ],
            initial_conditions={"focal_event": focal.node_id, "focal_label": focal.label},
            timeline=timeline,
            probability=0.5,
            confidence=0.7
        )

    def _create_optimistic_scenario(
        self, focal: GraphNode, horizon_days: int
    ) -> Scenario:
        # Amplify positive impacts, dampen negative
        impacts = self.graph.propagate_impact(focal.node_id, max_depth=3)
        
        timeline = []
        for day in range(0, horizon_days + 1, max(1, horizon_days // 5)):
            events = []
            for node_id, impact in impacts.items():
                node = self.graph.get_node(node_id)
                if node and impact > 0.2:
                    # Boost positive-sounding outcomes
                    label_lower = node.label.lower()
                    positive_keywords = ["growth", "success", "improvement", "recovery", "gain", "profit", "adoption"]
                    if any(kw in label_lower for kw in positive_keywords):
                        impact *= 1.5
                    events.append({
                        "node_id": node_id,
                        "label": node.label,
                        "impact": round(min(impact, 1.0), 3),
                        "type": node.node_type
                    })
            if events:
                timeline.append({"day": day, "events": sorted(events, key=lambda e: -e["impact"])[:5]})
        
        return Scenario(
            scenario_id=f"scenario_{uuid.uuid4().hex[:8]}",
            name=f"Optimistic: {focal.label}",
            scenario_type="optimistic",
            description=f"Positive outcomes amplified; favorable conditions prevail",
            assumptions=[
                "Positive feedback loops dominate",
                "Stakeholders cooperate",
                "External conditions favorable"
            ],
            initial_conditions={"focal_event": focal.node_id},
            timeline=timeline,
            probability=0.2,
            confidence=0.5
        )

    def _create_pessimistic_scenario(
        self, focal: GraphNode, horizon_days: int
    ) -> Scenario:
        impacts = self.graph.propagate_impact(focal.node_id, max_depth=3)
        
        timeline = []
        for day in range(0, horizon_days + 1, max(1, horizon_days // 5)):
            events = []
            for node_id, impact in impacts.items():
                node = self.graph.get_node(node_id)
                if node and impact > 0.2:
                    label_lower = node.label.lower()
                    negative_keywords = ["decline", "loss", "failure", "crisis", "risk", "threat", "drop"]
                    if any(kw in label_lower for kw in negative_keywords):
                        impact *= 1.5
                    events.append({
                        "node_id": node_id,
                        "label": node.label,
                        "impact": round(min(impact, 1.0), 3),
                        "type": node.node_type
                    })
            if events:
                timeline.append({"day": day, "events": sorted(events, key=lambda e: -e["impact"])[:5]})
        
        return Scenario(
            scenario_id=f"scenario_{uuid.uuid4().hex[:8]}",
            name=f"Pessimistic: {focal.label}",
            scenario_type="pessimistic",
            description=f"Negative outcomes amplified; risks materialize",
            assumptions=[
                "Negative feedback loops dominate",
                "Stakeholders defect/compete",
                "External conditions deteriorate"
            ],
            initial_conditions={"focal_event": focal.node_id},
            timeline=timeline,
            probability=0.2,
            confidence=0.5
        )

    def _create_adversarial_scenario(
        self, focal: GraphNode, horizon_days: int
    ) -> Scenario:
        # Simulate stakeholder conflict
        stakeholders = list(self._stakeholders.values())[:5]
        if not stakeholders:
            return self._create_pessimistic_scenario(focal, horizon_days)
        
        timeline = []
        for day in range(0, horizon_days + 1, max(1, horizon_days // 5)):
            events = []
            for sh in stakeholders:
                # Each stakeholder pushes for their interests
                for interest in sh.interests[:2]:
                    events.append({
                        "node_id": f"stakeholder_{sh.stakeholder_id}",
                        "label": f"{sh.name} advocates for {interest}",
                        "impact": round(sh.influence * 0.5, 3),
                        "type": "stakeholder_action",
                        "stakeholder": sh.name
                    })
            if events:
                timeline.append({"day": day, "events": events})
        
        return Scenario(
            scenario_id=f"scenario_{uuid.uuid4().hex[:8]}",
            name=f"Adversarial: {focal.label}",
            scenario_type="adversarial",
            description=f"Stakeholder conflict around {focal.label}",
            assumptions=[
                "Stakeholders pursue conflicting interests",
                "Zero-sum dynamics dominate",
                "Coordination fails"
            ],
            initial_conditions={"focal_event": focal.node_id},
            timeline=timeline,
            probability=0.15,
            confidence=0.4
        )

    def _create_black_swan_scenario(
        self, focal: GraphNode, horizon_days: int
    ) -> Scenario:
        # Low probability, high impact exogenous shock
        shock_types = [
            ("Regulatory Shock", "Sudden policy/regulation change"),
            ("Market Crash", "Financial market collapse"),
            ("Tech Breakthrough", "Disruptive technology emergence"),
            ("Geopolitical Event", "War, sanctions, alliance shift"),
            ("Natural Disaster", "Pandemic, climate event, infrastructure failure"),
        ]
        
        import random
        shock_name, shock_desc = random.choice(shock_types)
        
        timeline = [{
            "day": random.randint(1, horizon_days // 2),
            "events": [{
                "node_id": f"black_swan_{uuid.uuid4().hex[:6]}",
                "label": shock_name,
                "description": shock_desc,
                "impact": 0.9,
                "type": "exogenous_shock"
            }]
        }]
        
        # Propagate shock through graph
        impacts = self.graph.propagate_impact(focal.node_id, max_depth=2)
        for node_id, impact in impacts.items():
            if impact > 0.2:
                node = self.graph.get_node(node_id)
                if node:
                    timeline.append({
                        "day": horizon_days,
                        "events": [{
                            "node_id": node_id,
                            "label": f"Cascading: {node.label}",
                            "impact": round(impact * 0.8, 3),
                            "type": "cascade_effect"
                        }]
                    })
                    break
        
        return Scenario(
            scenario_id=f"scenario_{uuid.uuid4().hex[:8]}",
            name=f"Black Swan: {shock_name} affecting {focal.label}",
            scenario_type="black_swan",
            description=f"{shock_desc} with cascading effects on {focal.label}",
            assumptions=[
                "Exogenous shock occurs",
                "System has low resilience",
                "Cascading failures propagate"
            ],
            initial_conditions={"focal_event": focal.node_id, "shock": shock_name},
            timeline=timeline,
            probability=0.02,
            confidence=0.3
        )

    # ── Simulation ────────────────────────────────────────────────

    def simulate_scenario(
        self,
        scenario: Scenario,
        steps: int = 10,
        stakeholder_rounds: int = 3
    ) -> SimulationResult:
        """Run a lightweight simulation of a scenario."""
        # Initialize state from scenario
        state = {**scenario.initial_conditions}
        
        # Track key nodes from graph
        key_nodes = {}
        for node in self.graph._nodes.values():
            if node.node_type in ("entity", "event", "claim"):
                key_nodes[node.node_id] = {
                    "label": node.label,
                    "value": 0.5,  # Baseline activation
                    "type": node.node_type
                }
        
        # Apply initial conditions
        focal_id = scenario.initial_conditions.get("focal_event")
        if focal_id and focal_id in key_nodes:
            key_nodes[focal_id]["value"] = 1.0
        
        trajectory = []
        
        for step in range(steps):
            step_state = {}
            
            # Propagate through causal edges
            for node_id, node_data in key_nodes.items():
                current_value = node_data["value"]
                if current_value < 0.1:
                    continue
                
                # Push to downstream
                for edge in self.graph.get_outgoing(node_id, edge_type="causes"):
                    if edge.target_id in key_nodes:
                        push = current_value * edge.weight * edge.confidence * 0.5
                        key_nodes[edge.target_id]["value"] = min(
                            1.0, key_nodes[edge.target_id]["value"] + push
                        )
            
            # Stakeholder dynamics (simplified)
            if self._stakeholders and step % 3 == 0:
                for sh in list(self._stakeholders.values())[:3]:
                    for interest in sh.interests[:1]:
                        # Find matching node
                        for node_id, node_data in key_nodes.items():
                            if interest.lower() in node_data["label"].lower():
                                node_data["value"] = min(1.0, node_data["value"] + sh.influence * 0.1)
            
            # Record trajectory
            active = [(nid, nd["value"]) for nid, nd in key_nodes.items() if nd["value"] > 0.3]
            trajectory.append({
                "step": step,
                "active_nodes": sorted(active, key=lambda x: -x[1])[:10]
            })
        
        # Extract key outcomes
        final_state = {nid: nd["value"] for nid, nd in key_nodes.items() if nd["value"] > 0.3}
        key_outcomes = [
            {"node_id": nid, "label": key_nodes[nid]["label"], "value": val, "probability": val}
            for nid, val in sorted(final_state.items(), key=lambda x: -x[1])[:10]
        ]
        
        # Identify risks and opportunities
        risk_factors = []
        opportunities = []
        for nid, val in final_state.items():
            node = self.graph.get_node(nid)
            if node:
                label_lower = node.label.lower()
                if any(kw in label_lower for kw in ["risk", "threat", "decline", "loss", "failure", "crisis"]):
                    risk_factors.append(f"{node.label} (probability: {val:.2f})")
                if any(kw in label_lower for kw in ["opportunity", "growth", "gain", "success", "adoption", "breakthrough"]):
                    opportunities.append(f"{node.label} (probability: {val:.2f})")
        
        result = SimulationResult(
            scenario_id=scenario.scenario_id,
            final_state=final_state,
            key_outcomes=key_outcomes,
            trajectory=trajectory,
            risk_factors=risk_factors[:5],
            opportunities=opportunities[:5],
            confidence=scenario.confidence * 0.8  # Simulation adds uncertainty
        )
        
        # Save result
        with open(self._results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        
        return result

    def compare_scenarios(self, scenario_ids: list[str]) -> dict[str, Any]:
        """Compare multiple scenarios side by side."""
        scenarios = [self._scenarios[sid] for sid in scenario_ids if sid in self._scenarios]
        if not scenarios:
            return {}
        
        # Run simulations for each
        results = [self.simulate_scenario(s) for s in scenarios]
        
        # Compare outcomes
        all_outcomes = set()
        for r in results:
            for o in r.key_outcomes:
                all_outcomes.add(o["node_id"])
        
        comparison = {}
        for oid in all_outcomes:
            comparison[oid] = {
                "label": self.graph.get_node(oid).label if self.graph.get_node(oid) else oid,
                "values": {r.scenario_id: next((o["value"] for o in r.key_outcomes if o["node_id"] == oid), 0)
                          for r in results}
            }
        
        return {
            "scenarios": [{"id": s.scenario_id, "name": s.name, "type": s.scenario_type, "probability": s.probability} for s in scenarios],
            "outcome_comparison": comparison,
            "risk_comparison": {r.scenario_id: r.risk_factors for r in results},
            "opportunity_comparison": {r.scenario_id: r.opportunities for r in results}
        }

    def get_scenario(self, scenario_id: str) -> Scenario | None:
        return self._scenarios.get(scenario_id)

    def list_scenarios(self) -> list[Scenario]:
        return list(self._scenarios.values())