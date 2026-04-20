from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import time
import logging
import json
import os
from app.settings.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/edge", tags=["edge"])


# DeviceGraph to persist device states
class DeviceGraph:
    def __init__(self):
        self.state_dir = os.path.join(Config.MEMORY_ROOT, "state")
        self.filepath = os.path.join(self.state_dir, "devices.json")
        os.makedirs(self.state_dir, exist_ok=True)
        self.devices = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load devices.json: {e}")
        return {}

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.devices, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save devices.json: {e}")

    def register_node(
        self, node_id: str, capabilities: List[str], location: str, sensors: List[str]
    ):
        self.devices[node_id] = {
            "capabilities": capabilities,
            "location": location,
            "sensors": sensors,
            "last_seen": time.time(),
            "state": self.devices.get(node_id, {}).get("state", {}),
        }
        self._save()

    def update_sensor_state(self, node_id: str, sensor: str, value: Any):
        if node_id not in self.devices:
            self.devices[node_id] = {
                "capabilities": [],
                "location": "unknown",
                "sensors": [],
                "state": {},
            }

        if "state" not in self.devices[node_id]:
            self.devices[node_id]["state"] = {}

        self.devices[node_id]["state"][sensor] = {
            "value": value,
            "timestamp": time.time(),
        }
        self.devices[node_id]["last_seen"] = time.time()
        self._save()

    def get_active_nodes(self, timeout=300):
        now = time.time()
        return {
            k: v
            for k, v in self.devices.items()
            if now - v.get("last_seen", 0) < timeout
        }


device_graph = DeviceGraph()


class EdgeRegisterRequest(BaseModel):
    node_id: str
    capabilities: List[str]  # e.g., ["local_llm", "python", "vision"]
    location: str = "unknown"
    sensors: List[str] = []


class TaskCompleteRequest(BaseModel):
    result: Any
    success: bool


class SensorEventRequest(BaseModel):
    node_id: str
    sensor: str
    value: Any
    is_anomaly: bool = False


@router.post("/register")
async def register_node(req: EdgeRegisterRequest):
    device_graph.register_node(
        node_id=req.node_id,
        capabilities=req.capabilities,
        location=req.location,
        sensors=req.sensors,
    )
    logger.info(
        f"Edge node {req.node_id} registered with capabilities: {req.capabilities}, location: {req.location}"
    )
    return {"status": "ok", "message": f"Registered {req.node_id}"}


@router.get("/nodes")
async def list_nodes():
    return {"nodes": device_graph.get_active_nodes()}


@router.post("/sensor_event")
async def sensor_event(req: SensorEventRequest):
    device_graph.update_sensor_state(req.node_id, req.sensor, req.value)

    if req.is_anomaly:
        logger.warning(
            f"Anomaly detected on {req.node_id} sensor {req.sensor}: {req.value}"
        )
        from app.core.task_ledger import TaskLedger

        ledger = TaskLedger(Config.MEMORY_ROOT)
        ledger.add_task(
            task_id=f"anomaly_{int(time.time())}_{req.node_id}_{req.sensor}",
            task_type="anomaly_response",
            title=f"Anomaly detected on {req.node_id}: {req.sensor}",
            metadata={
                "source": "sensor_event",
                "location": device_graph.devices.get(req.node_id, {}).get(
                    "location", "unknown"
                ),
                "value": req.value,
            },
        )

    return {"status": "ok"}


@router.get("/tasks/{node_id}")
async def get_tasks(node_id: str):
    if node_id in device_graph.devices:
        device_graph.devices[node_id]["last_seen"] = time.time()
        device_graph._save()

    from app.core.task_ledger import TaskLedger

    ledger = TaskLedger(Config.MEMORY_ROOT)
    tasks = ledger.list_tasks(status="queued_for_edge")

    node_caps = device_graph.devices.get(node_id, {}).get("capabilities", [])

    for task in tasks:
        meta = task.get("metadata", {})
        req_cap = meta.get("required_capability")
        target_node = meta.get("target_node")

        # If it's targeted at a specific node, only that node gets it
        if target_node and target_node != node_id:
            continue

        # If it has a required capability, ensure the node has it
        if req_cap and req_cap not in node_caps:
            continue

        # Claim the task
        ledger.update_status(task["task_id"], "in_progress")
        meta["assigned_node"] = node_id
        return {"task": task}

    return {"task": None}


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, req: TaskCompleteRequest):
    from app.core.task_ledger import TaskLedger

    ledger = TaskLedger(Config.MEMORY_ROOT)
    status = "completed" if req.success else "failed"

    ledger.update_status(task_id, status)

    import json
    import os

    res_path = os.path.join(Config.MEMORY_ROOT, f"edge_result_{task_id}.json")
    with open(res_path, "w") as f:
        json.dump({"success": req.success, "result": req.result}, f)

    return {"status": "ok"}
