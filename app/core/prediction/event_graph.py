"""Causal Event Graph — Core of the prediction engine.

Builds a dynamic graph of entities, events, claims, and causal relationships
extracted from real-world signals (news, social, sensors, conversations).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GraphNode:
    """A node in the causal event graph."""
    node_id: str
    node_type: str  # entity, event, claim, signal, scenario
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence: list[str] = field(default_factory=list)  # Source URLs, doc IDs


@dataclass(slots=True)
class GraphEdge:
    """A directed edge representing a causal or relational link."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: str  # causes, influences, contradicts, supports, related_to, precedes
    weight: float = 1.0
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class CausalClaim:
    """A structured claim about causality extracted from sources."""
    claim_id: str
    cause: str
    effect: str
    mechanism: str = ""
    conditions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = ""
    source_url: str = ""
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)


class CausalEventGraph:
    """Maintains a dynamic causal graph of the world.
    
    Nodes: entities, events, claims, signals, scenarios
    Edges: causal (causes, influences), relational (related_to, precedes), epistemic (supports, contradicts)
    
    Supports:
    - Incremental updates from signal ingestion
    - Causal path finding
    - Scenario impact propagation
    - Contradiction detection
    - Confidence calibration
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "prediction" / "event_graph"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._nodes_file = self._dir / "nodes.json"
        self._edges_file = self._dir / "edges.json"
        self._claims_file = self._dir / "claims.jsonl"
        
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._adjacency: dict[str, list[str]] = defaultdict(list)
        self._reverse_adjacency: dict[str, list[str]] = defaultdict(list)
        self._claims: list[CausalClaim] = []
        
        self._load()

    # ── Persistence ────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._nodes_file.exists():
                data = json.loads(self._nodes_file.read_text(encoding="utf-8"))
                self._nodes = {k: GraphNode(**v) for k, v in data.items()}
            if self._edges_file.exists():
                data = json.loads(self._edges_file.read_text(encoding="utf-8"))
                self._edges = {k: GraphEdge(**v) for k, v in data.items()}
                for edge in self._edges.values():
                    self._adjacency[edge.source_id].append(edge.target_id)
                    self._reverse_adjacency[edge.target_id].append(edge.source_id)
            if self._claims_file.exists():
                for line in self._claims_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        self._claims.append(CausalClaim(**json.loads(line)))
        except Exception as e:
            logger.warning("Failed to load event graph: %s", e)

    def _save(self) -> None:
        try:
            self._nodes_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._nodes.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self._edges_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._edges.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            with open(self._claims_file, "a", encoding="utf-8") as f:
                for claim in self._claims:
                    f.write(json.dumps(asdict(claim), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save event graph: %s", e)

    # ── Node Operations ────────────────────────────────────────────

    def upsert_node(self, node: GraphNode) -> str:
        """Add or update a node. Returns node_id."""
        if node.node_id in self._nodes:
            # Merge properties, keep higher confidence
            existing = self._nodes[node.node_id]
            if node.confidence > existing.confidence:
                existing.confidence = node.confidence
            existing.properties.update(node.properties)
            existing.evidence.extend(e for e in node.evidence if e not in existing.evidence)
            existing.timestamp = node.timestamp
        else:
            self._nodes[node.node_id] = node
        self._save()
        return node.node_id

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def find_nodes(self, node_type: str | None = None, label_contains: str = "") -> list[GraphNode]:
        results = list(self._nodes.values())
        if node_type:
            results = [n for n in results if n.node_type == node_type]
        if label_contains:
            lower = label_contains.lower()
            results = [n for n in results if lower in n.label.lower()]
        return results

    # ── Edge Operations ────────────────────────────────────────────

    def add_edge(self, edge: GraphEdge) -> str:
        """Add a directed edge. Returns edge_id."""
        # Check for duplicate
        for existing in self._edges.values():
            if (existing.source_id == edge.source_id and 
                existing.target_id == edge.target_id and
                existing.edge_type == edge.edge_type):
                # Merge: update weight and confidence
                existing.weight = max(existing.weight, edge.weight)
                existing.confidence = max(existing.confidence, edge.confidence)
                existing.evidence.extend(e for e in edge.evidence if e not in existing.evidence)
                self._save()
                return existing.edge_id

        self._edges[edge.edge_id] = edge
        self._adjacency[edge.source_id].append(edge.target_id)
        self._reverse_adjacency[edge.target_id].append(edge.source_id)
        self._save()
        return edge.edge_id

    def get_outgoing(self, node_id: str, edge_type: str | None = None) -> list[GraphEdge]:
        edges = [self._edges[eid] for eid in self._adjacency.get(node_id, []) if eid in self._edges]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    def get_incoming(self, node_id: str, edge_type: str | None = None) -> list[GraphEdge]:
        edges = [self._edges[eid] for eid in self._reverse_adjacency.get(node_id, []) if eid in self._edges]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    # ── Causal Claims ──────────────────────────────────────────────

    def add_claim(self, claim: CausalClaim) -> str:
        """Add a causal claim extracted from sources."""
        self._claims.append(claim)
        
        # Create nodes for cause and effect if they don't exist
        cause_id = f"entity_{hash(claim.cause) % 1000000:06d}"
        effect_id = f"entity_{hash(claim.effect) % 1000000:06d}"
        
        self.upsert_node(GraphNode(
            node_id=cause_id,
            node_type="entity",
            label=claim.cause,
            properties={"extracted_from": claim.source},
            confidence=claim.confidence,
            source=claim.source,
            evidence=[claim.source_url] if claim.source_url else []
        ))
        
        self.upsert_node(GraphNode(
            node_id=effect_id,
            node_type="entity",
            label=claim.effect,
            properties={"extracted_from": claim.source},
            confidence=claim.confidence,
            source=claim.source,
            evidence=[claim.source_url] if claim.source_url else []
        ))
        
        # Add causal edge
        self.add_edge(GraphEdge(
            edge_id=f"causal_{claim.claim_id}",
            source_id=cause_id,
            target_id=effect_id,
            edge_type="causes",
            weight=claim.confidence,
            confidence=claim.confidence,
            evidence=[claim.source_url] if claim.source_url else [],
            properties={"mechanism": claim.mechanism, "conditions": claim.conditions}
        ))
        
        self._save()
        return claim.claim_id

    def get_claims(self, min_confidence: float = 0.0) -> list[CausalClaim]:
        return [c for c in self._claims if c.confidence >= min_confidence]

    # ── Graph Algorithms ───────────────────────────────────────────

    def find_causal_paths(
        self, 
        source_id: str, 
        target_id: str, 
        max_depth: int = 4,
        min_confidence: float = 0.3
    ) -> list[list[GraphEdge]]:
        """Find all causal paths from source to target up to max_depth."""
        paths: list[list[GraphEdge]] = []
        
        def dfs(current: str, path: list[GraphEdge], visited: set[str]) -> None:
            if len(path) >= max_depth:
                return
            if current == target_id:
                paths.append(path.copy())
                return
            if current in visited:
                return
            
            visited.add(current)
            for edge in self.get_outgoing(current, edge_type="causes"):
                if edge.confidence >= min_confidence:
                    path.append(edge)
                    dfs(edge.target_id, path, visited)
                    path.pop()
            visited.remove(current)
        
        dfs(source_id, [], set())
        return paths

    def propagate_impact(
        self, 
        source_id: str, 
        initial_impact: float = 1.0,
        max_depth: int = 3,
        decay: float = 0.7
    ) -> dict[str, float]:
        """Propagate impact through the causal graph. Returns {node_id: impact_score}."""
        impacts: dict[str, float] = {source_id: initial_impact}
        
        for depth in range(max_depth):
            new_impacts: dict[str, float] = {}
            for node_id, impact in impacts.items():
                if impact < 0.1:  # Threshold
                    continue
                for edge in self.get_outgoing(node_id, edge_type="causes"):
                    propagated = impact * edge.weight * edge.confidence * decay
                    if propagated > new_impacts.get(edge.target_id, 0):
                        new_impacts[edge.target_id] = propagated
            impacts.update(new_impacts)
        
        return impacts

    def detect_contradictions(self, min_confidence: float = 0.6) -> list[tuple[GraphEdge, GraphEdge]]:
        """Find contradictory edges (A causes B vs A prevents B, etc.)."""
        contradictions = []
        for edge in self._edges.values():
            if edge.confidence < min_confidence:
                continue
            # Look for contradictory edges
            for other in self.get_outgoing(edge.source_id, edge_type="prevents"):
                if other.target_id == edge.target_id and other.confidence >= min_confidence:
                    contradictions.append((edge, other))
            for other in self.get_incoming(edge.target_id, edge_type="prevents"):
                if other.source_id == edge.source_id and other.confidence >= min_confidence:
                    contradictions.append((edge, other))
        return contradictions

    def get_subgraph(self, node_ids: list[str], depth: int = 1) -> dict[str, Any]:
        """Extract a subgraph around the given nodes."""
        included = set(node_ids)
        frontier = set(node_ids)
        
        for _ in range(depth):
            new_frontier = set()
            for nid in frontier:
                for edge in self.get_outgoing(nid):
                    if edge.target_id not in included:
                        included.add(edge.target_id)
                        new_frontier.add(edge.target_id)
                for edge in self.get_incoming(nid):
                    if edge.source_id not in included:
                        included.add(edge.source_id)
                        new_frontier.add(edge.source_id)
            frontier = new_frontier
        
        nodes = {nid: asdict(self._nodes[nid]) for nid in included if nid in self._nodes}
        edges = [asdict(e) for e in self._edges.values() 
                 if e.source_id in included and e.target_id in included]
        
        return {"nodes": nodes, "edges": edges}

    # ── Statistics ─────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "claims": len(self._claims),
            "node_types": dict(defaultdict(int, {n.node_type: 1 for n in self._nodes.values()})),
            "edge_types": dict(defaultdict(int, {e.edge_type: 1 for e in self._edges.values()})),
        }