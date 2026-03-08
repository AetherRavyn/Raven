"""Camera management routes — CRUD + video streaming + YAML persistence."""

import asyncio
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from monitoring.src import state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cameras"])

_CAMERAS_YAML = Path(__file__).parents[1] / "config" / "cameras.yaml"


def _save_cameras_to_yaml():
    """Write current camera list back to cameras.yaml and refresh settings cache."""
    from monitoring.config.settings import config as settings_config

    try:
        full_cfg = settings_config.get("cameras.yaml").copy()
    except Exception:
        full_cfg = {}

    cam_list = []
    with state._camera_lock:
        for cam in state.camera_registry.values():
            cam_list.append({"id": cam.cam_id, "url": cam.url, "location": cam.location})
    full_cfg["cameras"] = cam_list

    with open(_CAMERAS_YAML, "w") as f:
        yaml.dump(full_cfg, f, default_flow_style=False, sort_keys=False)

    settings_config._cache.pop("cameras.yaml", None)
    logger.info("Saved %d cameras to cameras.yaml", len(cam_list))


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/cameras")
async def list_cameras():
    with state._camera_lock:
        cams = [c.to_dict() for c in state.camera_registry.values()]
    return JSONResponse({"cameras": cams})


@router.post("/api/cameras")
async def add_camera(cam_id: str = Form(...), url: str = Form(...), location: str = Form("unknown")):
    if cam_id in state.camera_registry:
        raise HTTPException(409, f"Camera {cam_id} already exists")

    # Import here to avoid circular (main defines _start_camera)
    from monitoring.main import _start_camera
    _start_camera(cam_id, url, location)
    _save_cameras_to_yaml()

    if state.db:
        try:
            state.db.neo4j.add_camera(cam_id, location=location)
        except Exception:
            pass
    return JSONResponse({"status": f"Camera {cam_id} added & saved", "camera": state.camera_registry[cam_id].to_dict()})


@router.delete("/api/cameras/{cam_id}")
async def remove_camera(cam_id: str):
    if cam_id not in state.camera_registry:
        raise HTTPException(404, f"Camera {cam_id} not found")

    from monitoring.main import _stop_camera
    _stop_camera(cam_id)
    _save_cameras_to_yaml()
    return JSONResponse({"status": f"Camera {cam_id} removed & saved"})


# ── Video Stream ──────────────────────────────────────────────────────────────

@router.get("/video/{cam_id}")
async def video_stream(cam_id: str, request: Request):
    cam = state.camera_registry.get(cam_id)
    if not cam:
        raise HTTPException(404, f"Camera {cam_id} not found")

    async def mjpeg():
        try:
            while not state._shutdown_event.is_set():
                if await request.is_disconnected():
                    break
                with cam.lock:
                    frame = cam.annotated_frame
                if frame:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                await asyncio.sleep(0.04)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")
