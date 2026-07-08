"""Prediction Orchestrator — Main entry point for predictive intelligence.

Coordinates world model, event graph, scenario engine, social simulator,
forecasting, and prediction memory to provide unified prediction capabilities.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.prediction.world_model import WorldModel, Entity, TimelineEvent
from app.core.prediction.event_graph import CausalEventGraph, CausalClaim
from app.core.prediction.scenario_engine import ScenarioEngine, Scenario
from app.core.prediction.social_simulator import SocialSimulator, StakeholderAgent
from app.core.prediction.forecasting import ForecastingEngine, TimeSeriesPoint
from app.core.prediction.prediction_memory import PredictionMemory, OutcomeTracker

logger = logging.getLogger(__name__)


class PredictionOrchestrator:
    """Unified predictive intelligence orchestrator.
    
    Provides high-level API for:
    - Causal reasoning and forecasting
    - Scenario generation and simulation
    - Social dynamics modeling
    - Time-series forecasting
    - Prediction tracking and learning
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.workspace_dir = workspace_dir
        
        # Core components
        self.world_model = WorldModel(workspace_dir)
        self.event_graph = CausalEventGraph(workspace_dir)
        self.scenario_engine = ScenarioEngine(self.event_graph, workspace_dir)
        self.social_simulator = SocialSimulator(workspace_dir)
        self.forecasting = ForecastingEngine(workspace_dir)
        self.prediction_memory = PredictionMemory(workspace_dir)
        self.outcome_tracker = OutcomeTracker(workspace_dir)
        
        # Auto-populate stakeholders from world model entities
        self._sync_stakeholders_from_world_model()

    def _sync_stakeholders_from_world_model(self) -> None:
        """Create stakeholder agents from person/organization entities."""
        people = self.world_model.find_entities(entity_type="person")
        orgs = self.world_model.find_entities(entity_type="organization")
        
        for person in people:
            if not self.social_simulator.get_agent(f"agent_{person.entity_id}"):
                agent = self.social_simulator.create_stakeholder_from_entity(
                    entity_name=person.name,
                    role="decision_maker" if person.properties.get("is_decision_maker") else "affected_party",
                    interests=list(person.properties.get("interests", [])),
                    influence=person.properties.get("influence", 0.5)
                )
                agent.agent_id = f"agent_{person.entity_id}"
                self.social_simulator.add_agent(agent)
        
        for org in orgs:
            if not self.social_simulator.get_agent(f"agent_{org.entity_id}"):
                agent = self.social_simulator.create_stakeholder_from_entity(
                    entity_name=org.name,
                    role="decision_maker",
                    interests=list(org.properties.get("interests", [])),
                    influence=org.properties.get("influence", 0.7)
                )
                agent.agent_id = f"agent_{org.entity_id}"
                self.social_simulator.add_agent(agent)

    # ── High-Level Prediction API ─────────────────────────────────

    def predict_future(
        self,
        query: str,
        time_horizon: str = "30 days",
        context: dict[str, Any] | None = None,
        methods: list[str] | None = None
    ) -> dict[str, Any]:
        """Main prediction entry point - routes to appropriate method."""
        
        query_lower = query.lower()
        
        # Determine prediction type from query
        if any(kw in query_lower for kw in ["forecast", "predict", "trend", "will ", "going to"]):
            return self._handle_forecast(query, time_horizon, context)
        elif any(kw in query_lower for kw in ["scenario", "what if", "possible future", "alternative"]):
            return self._handle_scenario(query, time_horizon, context)
        elif any(kw in query_lower for kw in ["causal", "cause", "effect", "impact", "consequence"]):
            return self._handle_causal(query, context)
        elif any(kw in query_lower for kw in ["stakeholder", "reaction", "response", "social", "people will"]):
            return self._handle_social(query, context)
        else:
            # Default: try causal + scenario
            return self._handle_comprehensive(query, time_horizon, context)

    def _handle_forecast(
        self,
        query: str,
        time_horizon: str,
        context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Handle time-series forecasting queries."""
        # Extract entity/series from query
        series_id = self._extract_series_id(query, context)
        
        if series_id and series_id in self.forecasting.list_series():
            horizon = self._parse_horizon(time_horizon)
            result = self.forecasting.forecast(series_id, horizon=horizon)
            
            if result:
                pred_id = self.prediction_memory.record_prediction(
                    prediction_type="forecast",
                    query=query,
                    prediction={
                        "series_id": series_id,
                        "horizon": horizon,
                        "predictions": result.predictions,
                        "confidence_intervals": result.confidence_intervals,
                        "method": result.method
                    },
                    confidence=0.7,
                    reasoning=f"Forecast using {result.method} on series {series_id}",
                    time_horizon=time_horizon,
                    context=context or {},
                    tags=["forecast", series_id]
                )
                
                return {
                    "type": "forecast",
                    "prediction_id": pred_id,
                    "series_id": series_id,
                    "horizon": horizon,
                    "predictions": result.predictions,
                    "confidence_intervals": result.confidence_intervals,
                    "method": result.method,
                    "metrics": result.metrics
                }
        
        # Fallback: create a new series from context or return guidance
        return {
            "type": "forecast",
            "error": "No time series data available for this query",
            "suggestion": "Provide historical data or specify a tracked metric",
            "available_series": self.forecasting.list_series()
        }

    def _handle_scenario(
        self,
        query: str,
        time_horizon: str,
        context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Handle scenario generation queries."""
        focal_id = self._extract_focal_entity(query, context)
        
        if not focal_id:
            # Try to find relevant entity in world model
            entities = self.world_model.find_entities(name_contains=query)
            if entities:
                focal_id = entities[0].entity_id
        
        if focal_id:
            scenarios = self.scenario_engine.generate_scenarios(focal_id)
            results = []
            
            for scenario in scenarios:
                sim_result = self.scenario_engine.simulate_scenario(scenario)
                results.append({
                    "scenario": asdict(scenario),
                    "simulation": asdict(sim_result)
                })
            
            pred_id = self.prediction_memory.record_prediction(
                prediction_type="scenario",
                query=query,
                prediction={
                    "focal_entity": focal_id,
                    "scenarios": results
                },
                confidence=0.6,
                reasoning=f"Generated {len(scenarios)} scenarios for {focal_id}",
                time_horizon=time_horizon,
                context=context or {},
                tags=["scenario", focal_id]
            )
            
            return {
                "type": "scenario",
                "prediction_id": pred_id,
                "focal_entity": focal_id,
                "scenarios": results
            }
        
        return {
            "type": "scenario",
            "error": "Could not identify focal entity for scenario generation",
            "suggestion": "Specify a person, project, or entity to scenario plan around"
        }

    def _handle_causal(
        self,
        query: str,
        context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Handle causal reasoning queries."""
        # Extract cause and effect from query
        cause, effect = self._extract_causal_entities(query)
        
        if cause and effect:
            # Find or create nodes
            cause_nodes = self.event_graph.find_nodes(label_contains=cause)
            effect_nodes = self.event_graph.find_nodes(label_contains=effect)
            
            if cause_nodes and effect_nodes:
                cause_id = cause_nodes[0].node_id
                effect_id = effect_nodes[0].node_id
                
                paths = self.event_graph.find_causal_paths(cause_id, effect_id)
                impacts = self.event_graph.propagate_impact(cause_id)
                
                pred_id = self.prediction_memory.record_prediction(
                    prediction_type="causal",
                    query=query,
                    prediction={
                        "cause": cause,
                        "effect": effect,
                        "causal_paths": len(paths),
                        "path_details": [
                            [{"node": self.event_graph.get_node(e.target_id).label if self.event_graph.get_node(e.target_id) else e.target_id, 
                              "confidence": e.confidence} for e in path]
                            for path in paths[:5]
                        ],
                        "impact_propagation": {
                            k: v for k, v in impacts.items() if v > 0.1
                        }
                    },
                    confidence=0.65,
                    reasoning=f"Found {len(paths)} causal paths from {cause} to {effect}",
                    context=context or {},
                    tags=["causal", cause, effect]
                )
                
                return {
                    "type": "causal",
                    "prediction_id": pred_id,
                    "cause": cause,
                    "effect": effect,
                    "causal_paths": paths,
                    "impact_propagation": impacts
                }
        
        return {
            "type": "causal",
            "error": "Could not identify clear cause-effect pair in query",
            "suggestion": "Specify cause and effect explicitly"
        }

    def _handle_social(
        self,
        query: str,
        context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Handle social dynamics queries."""
        topic = self._extract_topic(query)
        
        if topic:
            agents = self.social_simulator.list_agents()
            if len(agents) >= 2:
                result = self.social_simulator.run_simulation(
                    scenario_context=query,
                    focal_topic=topic,
                    agents=agents[:10],
                    rounds=10
                )
                
                pred_id = self.prediction_memory.record_prediction(
                    prediction_type="social",
                    query=query,
                    prediction={
                        "topic": topic,
                        "final_positions": result.final_positions,
                        "coalitions": result.coalitions,
                        "conflicts": result.conflicts,
                        "key_decisions": result.key_decisions,
                        "metrics": result.metrics
                    },
                    confidence=0.55,
                    reasoning=f"Simulated {len(agents)} stakeholders over {result.rounds} rounds on {topic}",
                    context=context or {},
                    tags=["social", topic]
                )
                
                return {
                    "type": "social",
                    "prediction_id": pred_id,
                    "topic": topic,
                    "result": asdict(result)
                }
        
        return {
            "type": "social",
            "error": "Could not identify topic for social simulation",
            "available_agents": [a.name for a in self.social_simulator.list_agents()]
        }

    def _handle_comprehensive(
        self,
        query: str,
        time_horizon: str,
        context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Comprehensive prediction using multiple methods."""
        results = {}
        
        # Try causal
        causal = self._handle_causal(query, context)
        if "error" not in causal:
            results["causal"] = causal
        
        # Try scenario
        scenario = self._handle_scenario(query, time_horizon, context)
        if "error" not in scenario:
            results["scenario"] = scenario
        
        # Try social
        social = self._handle_social(query, context)
        if "error" not in social:
            results["social"] = social
        
        pred_id = self.prediction_memory.record_prediction(
            prediction_type="comprehensive",
            query=query,
            prediction=results,
            confidence=0.5,
            reasoning="Multi-method comprehensive prediction",
            time_horizon=time_horizon,
            context=context or {},
            tags=["comprehensive"]
        )
        
        return {
            "type": "comprehensive",
            "prediction_id": pred_id,
            "results": results
        }

    # ── Helper Methods ────────────────────────────────────────────

    def _extract_series_id(self, query: str, context: dict[str, Any] | None) -> str | None:
        """Extract time series ID from query or context."""
        if context and "series_id" in context:
            return context["series_id"]
        # Could add NLP extraction here
        return None

    def _extract_focal_entity(self, query: str, context: dict[str, Any] | None) -> str | None:
        """Extract focal entity ID from query or context."""
        if context and "entity_id" in context:
            return context["entity_id"]
        if context and "focal_entity" in context:
            return context["focal_entity"]
        return None

    def _extract_causal_entities(self, query: str) -> tuple[str | None, str | None]:
        """Extract cause and effect from query (simplified)."""
        # Simplified - would use NLP in production
        query_lower = query.lower()
        if "cause" in query_lower and "effect" in query_lower:
            parts = query_lower.split("cause")
            if len(parts) > 1:
                cause_part = parts[1].split("effect")[0].strip()
                effect_part = parts[1].split("effect")[1].strip() if "effect" in parts[1] else ""
                return cause_part, effect_part
        return None, None

    def _extract_topic(self, query: str) -> str | None:
        """Extract topic from social query."""
        query_lower = query.lower()
        for kw in ["about", "on", "regarding", "topic"]:
            if kw in query_lower:
                parts = query_lower.split(kw, 1)
                if len(parts) > 1:
                    return parts[1].strip().rstrip("?.")
        return None

    def _parse_horizon(self, horizon_str: str) -> int:
        """Parse time horizon string to number of steps."""
        horizon_str = horizon_str.lower()
        if "day" in horizon_str:
            try:
                return int(horizon_str.split()[0])
            except (ValueError, IndexError):
                return 7
        elif "week" in horizon_str:
            try:
                return int(horizon_str.split()[0]) * 7
            except (ValueError, IndexError):
                return 30
        elif "month" in horizon_str:
            try:
                return int(horizon_str.split()[0]) * 30
            except (ValueError, IndexError):
                return 30
        return 7

    # ── World Model Integration ──────────────────────────────────

    def add_entity(self, entity: Entity) -> None:
        """Add entity to world model and sync to stakeholders."""
        self.world_model.upsert_entity(entity)
        
        # If person or org, create stakeholder
        if entity.entity_type in ("person", "organization"):
            agent = self.social_simulator.create_stakeholder_from_entity(
                entity_name=entity.name,
                role="decision_maker" if entity.entity_type == "person" else "decision_maker",
                interests=list(entity.properties.get("interests", [])),
                influence=entity.properties.get("influence", 0.5)
            )
            agent.agent_id = f"agent_{entity.entity_id}"
            self.social_simulator.add_agent(agent)

    def add_event(self, event: TimelineEvent) -> None:
        """Add event to world model timeline."""
        self.world_model.add_event(event)
        
        # Also add to event graph as signal
        self.event_graph.upsert_node(
            self.event_graph._nodes.get(event.event_id) or
            type('obj', (object,), {
                'node_id': event.event_id,
                'node_type': 'event',
                'label': event.title,
                'properties': event.metadata,
                'confidence': event.confidence,
                'source': event.source,
                'evidence': []
            })()
        )

    def add_causal_claim(self, claim: CausalClaim) -> None:
        """Add a causal claim to the event graph."""
        self.event_graph.add_claim(claim)

    def add_time_series_point(self, series_id: str, point: TimeSeriesPoint) -> None:
        """Add a point to a time series for forecasting."""
        self.forecasting.append_point(series_id, point)

    # ── Memory & Learning ────────────────────────────────────────

    def record_prediction_outcome(
        self,
        prediction_id: str,
        actual_outcome: str,
        accuracy: float | None = None
    ) -> bool:
        """Record the outcome of a prediction for learning."""
        return self.prediction_memory.record_outcome(
            prediction_id, actual_outcome, accuracy=accuracy
        )

    def record_action_outcome(
        self,
        prediction_id: str,
        action_taken: str,
        expected_outcome: str,
        actual_outcome: str,
        success: bool
    ) -> str:
        """Record outcome of action taken based on prediction."""
        return self.outcome_tracker.record_outcome(
            prediction_id, action_taken, expected_outcome, actual_outcome, success
        )

    def get_performance_report(self) -> dict[str, Any]:
        """Get comprehensive prediction performance report."""
        return self.prediction_memory.generate_performance_report()

    def get_lessons_learned(self, limit: int = 20) -> list[str]:
        """Get key lessons from prediction history."""
        return self.prediction_memory.get_lessons_learned(limit)

    def find_similar_predictions(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find historically similar predictions."""
        preds = self.prediction_memory.find_similar_predictions(query, limit=limit)
        return [
            {
                "prediction_id": p.prediction_id,
                "query": p.query,
                "type": p.prediction_type,
                "confidence": p.confidence,
                "accuracy": p.accuracy,
                "created_at": p.created_at
            }
            for p in preds
        ]

    # ── Status ──────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get overall prediction system status."""
        return {
            "world_model": {
                "entities": len(self.world_model._load_entities()),
                "events": len(self.world_model.get_recent_events(1000)),
                "habits": len(self.world_model.get_habits())
            },
            "event_graph": self.event_graph.stats(),
            "scenarios": len(self.scenario_engine.list_scenarios()),
            "stakeholders": len(self.social_simulator.list_agents()),
            "forecasting": {
                "series": len(self.forecasting.list_series()),
                "calibration": self.forecasting.get_calibration_report().get("overall", {})
            },
            "prediction_memory": {
                "total": len(self.prediction_memory._predictions),
                "calibrated": len(self.prediction_memory.get_calibrated_predictions()),
                "clusters": len(self.prediction_memory._clusters)
            }
        }