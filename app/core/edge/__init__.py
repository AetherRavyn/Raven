"""Edge/Compute Tier Architecture — PicoClaw/ZeroClaw-inspired distributed compute.

Provides:
- Model tier routing (Tiny → Small → Large → Swarm)
- Edge node protocol for ESP32/Pi Zero/phone workers
- Local/offline modes with sync
- Resource-aware dispatch
- Distributed worker registry
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ComputeTier(Enum):
    """Compute tiers for model routing."""
    TIER_0_RULES = "tier_0_rules"        # Rules, cache, command parsing - instant
    TIER_1_TINY = "tier_1_tiny"          # Tiny local model (1-3B params) - <100ms
    TIER_2_SMALL = "tier_2_small"        # Small local/cheap cloud (7-13B) - <1s
    TIER_3_LARGE = "tier_3_large"        # Large cloud model - <10s
    TIER_4_SWARM = "tier_4_swarm"        # Multi-agent swarm/simulation - <60s


class EdgeNodeType(Enum):
    """Types of edge nodes."""
    PHONE = "phone"              # Mobile companion
    RASPBERRY_PI = "raspberry_pi"  # Pi Zero / Pi 4
    ESP32 = "esp32"              # Microcontroller
    JETSON = "jetson"            # NVIDIA Jetson
    DESKTOP = "desktop"          # Desktop companion
    CLOUD = "cloud"              # Cloud worker


class TaskComplexity(Enum):
    """Task complexity classification."""
    TRIVIAL = "trivial"      # Rules/cache only
    SIMPLE = "simple"        # Tiny model
    MODERATE = "moderate"    # Small model
    COMPLEX = "complex"      # Large model
    DEEP = "deep"            # Swarm/simulation


@dataclass(slots=True)
class EdgeNode:
    """An edge compute node."""
    node_id: str
    node_type: EdgeNodeType
    name: str
    capabilities: list[str] = field(default_factory=list)  # stt, tts, inference, sensors, actuation
    supported_tiers: list[ComputeTier] = field(default_factory=list)
    max_model_size: str = "small"  # tiny, small, medium, large
    memory_mb: int = 512
    compute_score: float = 1.0  # Relative compute power
    status: str = "offline"  # online, offline, busy, degraded
    last_heartbeat: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assigned_tasks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ComputeTask:
    """A task to be executed on an edge node or cloud."""
    task_id: str
    task_type: str  # inference, stt, tts, sensor_process, actuation
    complexity: TaskComplexity
    required_tier: ComputeTier
    input_data: dict[str, Any]
    constraints: dict[str, Any] = field(default_factory=dict)  # latency, privacy, offline_ok
    preferred_node_type: EdgeNodeType | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assigned_node: str | None = None
    status: str = "pending"  # pending, assigned, running, completed, failed
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class ModelRoute:
    """Routing decision for a model request."""
    tier: ComputeTier
    model_name: str
    provider: str
    estimated_latency_ms: int
    estimated_cost_usd: float
    reasoning: str
    fallback_tiers: list[ComputeTier] = field(default_factory=list)


class ModelTierRouter:
    """Routes requests to appropriate compute tier based on complexity, cost, latency."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "edge" / "router"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._config_file = self._dir / "router_config.json"
        self._history_file = self._dir / "routing_history.jsonl"
        
        self._config = self._load_config()
        self._node_registry: dict[str, EdgeNode] = {}
    
    def _load_config(self) -> dict[str, Any]:
        default_config = {
            "tier_models": {
                "tier_0_rules": {"provider": "local", "model": "rules_engine", "cost": 0.0, "latency_ms": 5},
                "tier_1_tiny": {"provider": "ollama", "model": "phi3:mini", "cost": 0.0, "latency_ms": 100},
                "tier_2_small": {"provider": "ollama", "model": "llama3:8b", "cost": 0.0, "latency_ms": 1000},
                "tier_3_large": {"provider": "opencode_zen", "model": "gpt-4o", "cost": 0.01, "latency_ms": 5000},
                "tier_4_swarm": {"provider": "internal", "model": "agent_swarm", "cost": 0.05, "latency_ms": 30000},
            },
            "complexity_keywords": {
                "trivial": ["hello", "hi", "time", "date", "status", "health", "ping"],
                "simple": ["summarize", "define", "what is", "who is", "calculate", "convert"],
                "moderate": ["write", "create", "analyze", "compare", "research", "plan", "code"],
                "complex": ["design", "architect", "optimize", "debug", "refactor", "investigate"],
                "deep": ["simulate", "forecast", "predict", "model", "strategize", "swarm"]
            },
            "routing_rules": [
                {"condition": "privacy_required", "max_tier": "tier_2_small"},
                {"condition": "offline_mode", "max_tier": "tier_1_tiny"},
                {"condition": "latency_critical", "max_tier": "tier_1_tiny"},
                {"condition": "cost_sensitive", "max_tier": "tier_2_small"},
            ]
        }
        
        try:
            if self._config_file.exists():
                return json.loads(self._config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default_config
    
    def _save_config(self) -> None:
        try:
            self._config_file.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save router config: %s", e)
    
    def classify_complexity(self, query: str, context: dict[str, Any] | None = None) -> TaskComplexity:
        """Classify task complexity from query and context."""
        query_lower = query.lower()
        context = context or {}
        
        # Check for explicit complexity hints
        if context.get("force_tier"):
            tier_map = {
                "tier_0_rules": TaskComplexity.TRIVIAL,
                "tier_1_tiny": TaskComplexity.SIMPLE,
                "tier_2_small": TaskComplexity.MODERATE,
                "tier_3_large": TaskComplexity.COMPLEX,
                "tier_4_swarm": TaskComplexity.DEEP,
            }
            return tier_map.get(context["force_tier"], TaskComplexity.MODERATE)
        
        # Keyword-based classification
        scores = {c: 0 for c in TaskComplexity}
        keywords = self._config.get("complexity_keywords", {})
        
        for complexity, words in keywords.items():
            for word in words:
                if word in query_lower:
                    scores[TaskComplexity(complexity)] += 1
        
        # Context modifiers
        if context.get("requires_tools"):
            scores[TaskComplexity.MODERATE] += 1
            scores[TaskComplexity.COMPLEX] += 1
        if context.get("multi_step"):
            scores[TaskComplexity.COMPLEX] += 2
            scores[TaskComplexity.DEEP] += 1
        if context.get("requires_reasoning"):
            scores[TaskComplexity.COMPLEX] += 1
            scores[TaskComplexity.DEEP] += 1
        if len(query) > 500:
            scores[TaskComplexity.MODERATE] += 1
        if len(query) > 2000:
            scores[TaskComplexity.COMPLEX] += 1
        
        # Return highest scoring complexity
        max_complexity = max(scores, key=scores.get)
        if scores[max_complexity] == 0:
            return TaskComplexity.SIMPLE
        return max_complexity
    
    def route(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        available_nodes: list[EdgeNode] | None = None
    ) -> ModelRoute:
        """Determine the best compute tier for a request."""
        context = context or {}
        complexity = self.classify_complexity(query, context)
        
        # Map complexity to preferred tier
        tier_map = {
            TaskComplexity.TRIVIAL: ComputeTier.TIER_0_RULES,
            TaskComplexity.SIMPLE: ComputeTier.TIER_1_TINY,
            TaskComplexity.MODERATE: ComputeTier.TIER_2_SMALL,
            TaskComplexity.COMPLEX: ComputeTier.TIER_3_LARGE,
            TaskComplexity.DEEP: ComputeTier.TIER_4_SWARM,
        }
        preferred_tier = tier_map[complexity]
        
        # Apply routing rules
        max_tier = preferred_tier
        for rule in self._config.get("routing_rules", []):
            condition = rule["condition"]
            if context.get(condition, False):
                rule_max = ComputeTier(rule["max_tier"])
                # Use more restrictive tier
                tier_order = list(ComputeTier)
                if tier_order.index(rule_max) < tier_order.index(max_tier):
                    max_tier = rule_max
        
        # Check available nodes for edge execution
        if available_nodes and max_tier != ComputeTier.TIER_0_RULES:
            for node in available_nodes:
                if node.status == "online" and max_tier in node.supported_tiers:
                    # Can run on edge
                    pass  # Would prefer edge for privacy/latency
        
        # Get model config for tier
        tier_models = self._config.get("tier_models", {})
        model_config = tier_models.get(max_tier.value, tier_models.get("tier_2_small", {}))
        
        # Build fallback chain
        all_tiers = list(ComputeTier)
        current_idx = all_tiers.index(max_tier)
        fallback_tiers = all_tiers[current_idx + 1:] if current_idx + 1 < len(all_tiers) else []
        
        route = ModelRoute(
            tier=max_tier,
            model_name=model_config.get("model", "unknown"),
            provider=model_config.get("provider", "unknown"),
            estimated_latency_ms=model_config.get("latency_ms", 5000),
            estimated_cost_usd=model_config.get("cost", 0.0),
            reasoning=f"Classified as {complexity.value}, routed to {max_tier.value}",
            fallback_tiers=fallback_tiers
        )
        
        # Log routing decision
        self._log_routing(query, context, route)
        
        return route
    
    def _log_routing(self, query: str, context: dict[str, Any], route: ModelRoute) -> None:
        """Log routing decision for analysis."""
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "query": query[:200],
                "context_keys": list(context.keys()),
                "route": asdict(route)
            }
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
    
    def register_node(self, node: EdgeNode) -> None:
        """Register an edge node."""
        self._node_registry[node.node_id] = node
    
    def get_available_nodes(self, tier: ComputeTier | None = None) -> list[EdgeNode]:
        """Get available edge nodes, optionally filtered by tier."""
        nodes = [n for n in self._node_registry.values() if n.status == "online"]
        if tier:
            nodes = [n for n in nodes if tier in n.supported_tiers]
        return nodes
    
    def get_routing_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        return {
            "registered_nodes": len(self._node_registry),
            "online_nodes": len([n for n in self._node_registry.values() if n.status == "online"]),
            "tier_config": self._config.get("tier_models", {}),
        }


class EdgeNodeProtocol:
    """Protocol for edge node communication."""
    
    def __init__(self, node: EdgeNode, server_url: str = "ws://localhost:8090/ws/edge") -> None:
        self.node = node
        self.server_url = server_url
        self.websocket = None
        self.connected = False
        self._handlers: dict[str, callable] = {}
        self._receive_task = None
    
    async def connect(self) -> bool:
        """Connect to central daemon."""
        try:
            import websockets
            self.websocket = await websockets.connect(self.server_url)
            self.connected = True
            
            # Register node
            await self.send({
                "type": "register",
                "payload": asdict(self.node)
            })
            
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.info(f"Edge node {self.node.node_id} connected")
            return True
        except Exception as e:
            logger.error(f"Edge node connection failed: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from daemon."""
        self.connected = False
        if self._receive_task:
            self._receive_task.cancel()
        if self.websocket:
            await self.websocket.close()
    
    async def send(self, message: dict[str, Any]) -> bool:
        """Send message to daemon."""
        if not self.websocket or not self.connected:
            return False
        try:
            await self.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Edge send failed: {e}")
            self.connected = False
            return False
    
    async def _receive_loop(self) -> None:
        """Receive messages from daemon."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type in self._handlers:
                    await self._handlers[msg_type](data.get("payload", {}))
        except Exception as e:
            logger.error(f"Edge receive error: {e}")
        finally:
            self.connected = False
    
    def on(self, event: str, handler: callable) -> None:
        """Register handler for message type."""
        self._handlers[event] = handler
    
    async def send_heartbeat(self) -> None:
        """Send heartbeat to daemon."""
        await self.send({
            "type": "heartbeat",
            "payload": {
                "node_id": self.node.node_id,
                "status": self.node.status,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })
    
    async def send_task_result(self, task_id: str, result: dict[str, Any]) -> None:
        """Send task completion result."""
        await self.send({
            "type": "task_result",
            "payload": {
                "task_id": task_id,
                "node_id": self.node.node_id,
                "result": result,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }
        })


class EdgeTaskDispatcher:
    """Dispatches tasks to edge nodes or cloud based on routing."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.router = ModelTierRouter(workspace_dir)
        self._pending_tasks: dict[str, ComputeTask] = {}
        self._node_protocols: dict[str, EdgeNodeProtocol] = {}
    
    def register_edge_node(self, node: EdgeNode, protocol: EdgeNodeProtocol) -> None:
        """Register an edge node with its protocol."""
        self.router.register_node(node)
        self._node_protocols[node.node_id] = protocol
    
    async def dispatch(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        task_type: str = "inference"
    ) -> ComputeTask:
        """Dispatch a task to the appropriate compute tier."""
        context = context or {}
        
        # Create task
        complexity = self.router.classify_complexity(query, context)
        tier_map = {
            TaskComplexity.TRIVIAL: ComputeTier.TIER_0_RULES,
            TaskComplexity.SIMPLE: ComputeTier.TIER_1_TINY,
            TaskComplexity.MODERATE: ComputeTier.TIER_2_SMALL,
            TaskComplexity.COMPLEX: ComputeTier.TIER_3_LARGE,
            TaskComplexity.DEEP: ComputeTier.TIER_4_SWARM,
        }
        
        task = ComputeTask(
            task_id=f"task_{uuid.uuid4().hex[:12]}",
            task_type=task_type,
            complexity=complexity,
            required_tier=tier_map[complexity],
            input_data={"query": query, "context": context},
            constraints={
                "privacy_required": context.get("privacy_required", False),
                "offline_ok": context.get("offline_ok", True),
                "latency_budget_ms": context.get("latency_budget_ms", 10000),
            }
        )
        
        # Route to determine target
        available_nodes = self.router.get_available_nodes()
        route = self.router.route(query, context, available_nodes)
        
        # Try edge first if suitable
        edge_node = None
        for node in available_nodes:
            if route.tier in node.supported_tiers and node.status == "online":
                edge_node = node
                break
        
        if edge_node and route.tier != ComputeTier.TIER_3_LARGE and route.tier != ComputeTier.TIER_4_SWARM:
            # Dispatch to edge
            task.assigned_node = edge_node.node_id
            task.status = "assigned"
            protocol = self._node_protocols.get(edge_node.node_id)
            if protocol:
                await protocol.send({
                    "type": "task",
                    "payload": asdict(task)
                })
            logger.info(f"Task {task.task_id} dispatched to edge node {edge_node.node_id}")
        else:
            # Dispatch to cloud (handled by runtime)
            task.assigned_node = "cloud"
            task.status = "assigned"
            logger.info(f"Task {task.task_id} dispatched to cloud (tier: {route.tier.value})")
        
        self._pending_tasks[task.task_id] = task
        return task
    
    def get_task_status(self, task_id: str) -> ComputeTask | None:
        return self._pending_tasks.get(task_id)
    
    def complete_task(self, task_id: str, result: dict[str, Any], error: str | None = None) -> None:
        """Mark task as completed."""
        if task_id in self._pending_tasks:
            task = self._pending_tasks[task_id]
            task.status = "completed" if error is None else "failed"
            task.result = result
            task.error = error


# Global instances
_model_router: ModelTierRouter | None = None
_edge_dispatcher: EdgeTaskDispatcher | None = None


def get_model_tier_router() -> ModelTierRouter:
    """Get global model tier router."""
    global _model_router
    if _model_router is None:
        _model_router = ModelTierRouter()
    return _model_router


def get_edge_dispatcher() -> EdgeTaskDispatcher:
    """Get global edge task dispatcher."""
    global _edge_dispatcher
    if _edge_dispatcher is None:
        _edge_dispatcher = EdgeTaskDispatcher()
    return _edge_dispatcher