"""ESP / IoT device management routes."""

import logging

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from monitoring.src import state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["esps"])


@router.get("/api/esps")
async def list_esps():
    with state._esp_lock:
        return JSONResponse({"esps": list(state.esp_registry.values())})


@router.post("/api/esps")
async def add_esp(esp_id: str = Form(...), esp_type: str = Form("generic"), ip: str = Form(""), location: str = Form("unknown")):
    with state._esp_lock:
        state.esp_registry[esp_id] = {"id": esp_id, "type": esp_type, "ip": ip, "location": location, "status": "online"}
    return JSONResponse({"status": f"ESP {esp_id} registered"})


@router.delete("/api/esps/{esp_id}")
async def remove_esp(esp_id: str):
    with state._esp_lock:
        if esp_id not in state.esp_registry:
            raise HTTPException(404, "ESP not found")
        del state.esp_registry[esp_id]
    return JSONResponse({"status": f"ESP {esp_id} removed"})


@router.post("/api/esps/{esp_id}/actuate")
async def actuate_esp(esp_id: str, command: str = Form(...), value: str = Form("")):
    if state.bus:
        state.bus.publish("actuation_command", {"target": esp_id, "command": command, "value": value})
        return JSONResponse({"status": f"Sent '{command}' to {esp_id}"})
    raise HTTPException(503, "Bus not ready")
